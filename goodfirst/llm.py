"""
The only place GoodFirst talks to the language model.

- The model is ALWAYS a local Ollama model (Gemma by default). No cloud fallback.
- Every call asks for strict JSON. When we pass a JSON schema, Ollama's
  "structured outputs" force the model to produce exactly those keys (plain
  format="json" only guarantees *some* valid JSON). The reply is then validated
  against a pydantic model.
- On a parse/validation failure we retry ONCE, telling the model what was
  wrong. If that also fails we raise LLMOutputError, and the app says honestly
  "the model couldn't produce a usable answer" instead of showing garbage.
- Every call records timings, so we can see where the seconds go on a CPU
  (reading the prompt vs. writing the answer).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from goodfirst.config import Settings

log = logging.getLogger("goodfirst.llm")

T = TypeVar("T", bound=BaseModel)


class LLMUnavailableError(Exception):
    """Ollama isn't running, the model isn't pulled, or the call timed out."""


class LLMOutputError(Exception):
    """The model answered twice, but neither answer was valid JSON of the right shape."""


@dataclass
class CallStats:
    """Timings for one model call. Durations are seconds."""

    wall_s: float = 0.0
    load_s: float = 0.0
    prompt_tokens: int = 0
    prompt_s: float = 0.0
    output_tokens: int = 0
    output_s: float = 0.0
    attempts: int = 1

    def as_dict(self) -> dict:
        def rate(tokens, seconds):
            return round(tokens / seconds, 1) if seconds else None

        return {
            "wall_s": round(self.wall_s, 1),
            "load_s": round(self.load_s, 1),
            "prompt_tokens": self.prompt_tokens,
            "prompt_s": round(self.prompt_s, 1),
            "prompt_tokens_per_s": rate(self.prompt_tokens, self.prompt_s),
            "output_tokens": self.output_tokens,
            "output_s": round(self.output_s, 1),
            "output_tokens_per_s": rate(self.output_tokens, self.output_s),
            "attempts": self.attempts,
        }


@dataclass
class RawReply:
    text: str
    stats: CallStats = field(default_factory=CallStats)


class ChatBackend(Protocol):
    """
    Anything that can turn (system, user) into raw text. Tests pass a fake.
    `json_schema`, when given, is the exact JSON shape the reply must follow.
    """

    def chat(self, system: str, user: str, json_schema: dict | None = None) -> RawReply: ...


# ---------------------------------------------------------------------------
# The real backend: langchain-ollama talking to the local Ollama server.
# ---------------------------------------------------------------------------


class OllamaBackend:
    def __init__(self, settings: Settings):
        # Imported here so tests (which use a fake backend) don't need Ollama at all.
        from langchain_ollama import ChatOllama

        self.settings = settings
        self.model = ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            format="json",                 # Ollama constrains the output to valid JSON
            temperature=settings.temperature,
            num_ctx=settings.num_ctx,
            num_predict=settings.num_predict,
            keep_alive=settings.keep_alive,
            client_kwargs={"timeout": settings.llm_timeout_s},
        )

    def chat(self, system: str, user: str, json_schema: dict | None = None) -> RawReply:
        from langchain_core.messages import HumanMessage, SystemMessage

        start = time.perf_counter()
        try:
            # With a schema, Ollama's "structured outputs" force exactly these keys.
            # Without one we fall back to plain JSON mode.
            msg = self.model.invoke(
                [SystemMessage(content=system), HumanMessage(content=user)],
                format=json_schema or "json",
            )
        except Exception as exc:  # ollama/httpx raise several types; translate them all
            raise LLMUnavailableError(_friendly_ollama_error(exc, self.settings)) from exc
        wall = time.perf_counter() - start

        meta = getattr(msg, "response_metadata", {}) or {}
        ns = 1e9  # Ollama reports nanoseconds
        stats = CallStats(
            wall_s=wall,
            load_s=(meta.get("load_duration") or 0) / ns,
            prompt_tokens=meta.get("prompt_eval_count") or 0,
            prompt_s=(meta.get("prompt_eval_duration") or 0) / ns,
            output_tokens=meta.get("eval_count") or 0,
            output_s=(meta.get("eval_duration") or 0) / ns,
        )
        content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
        return RawReply(text=content, stats=stats)


def _friendly_ollama_error(exc: Exception, settings: Settings) -> str:
    text = str(exc)
    lowered = text.lower()
    if "not found" in lowered and "model" in lowered:
        return f"The model '{settings.ollama_model}' isn't pulled. Run: ollama pull {settings.ollama_model}"
    if "timed out" in lowered or "timeout" in lowered:
        return (
            f"The model took longer than {int(settings.llm_timeout_s)} s. Try again (the second run is "
            "faster), use a smaller model (OLLAMA_MODEL=gemma3:1b), or raise OLLAMA_TIMEOUT_S."
        )
    if "connect" in lowered or "refused" in lowered:
        return "Couldn't reach Ollama. Start the Ollama app (or run `ollama serve`) and try again."
    return f"Ollama error: {text[:300]}"


# ---------------------------------------------------------------------------
# JSON parsing + validation + one retry.
# ---------------------------------------------------------------------------

_FENCED = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_json_object(text: str) -> dict:
    """Parse the model's reply as a JSON object, tolerating ```json fences."""
    match = _FENCED.match(text)
    if match:
        text = match.group(1)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object at the top level")
    return data


def unwrap(data: dict, required: set[str]) -> dict:
    """
    Small models sometimes wrap the answer: {"response": {...the real answer...}}.
    If the required keys are missing and there is exactly one nested object that
    has them, use that object instead.
    """
    if required <= data.keys():
        return data
    nested = [v for v in data.values() if isinstance(v, dict) and required <= v.keys()]
    return nested[0] if len(nested) == 1 else data


def ask_json(
    backend: ChatBackend,
    system: str,
    user: str,
    schema: type[T],
    json_schema: dict | None = None,
) -> tuple[T, CallStats]:
    """
    Ask for JSON matching `schema` (pydantic). `json_schema` is passed to Ollama to
    constrain the output. Retries once with the error explained.
    Returns (validated_object, combined_stats). Raises LLMOutputError after two failures.
    """
    required = {name for name, f in schema.model_fields.items() if f.is_required()}
    total = CallStats(attempts=0)
    prompt = user
    last_error = ""
    for attempt in (1, 2):
        reply = backend.chat(system, prompt, json_schema)
        _add_stats(total, reply.stats)
        total.attempts = attempt
        try:
            obj = schema.model_validate(unwrap(parse_json_object(reply.text), required))
            log.info("LLM ok on attempt %d: %s", attempt, total.as_dict())
            return obj, total
        except (ValueError, ValidationError) as exc:  # JSONDecodeError is a ValueError
            last_error = _short_error(exc)
            log.warning("LLM attempt %d gave unusable output: %s", attempt, last_error)
            # Show what the model actually wrote, so failures can be understood, not guessed at.
            log.warning("Raw reply (first 400 chars): %s", reply.text[:400].replace("\n", " "))
            prompt = (
                f"{user}\n\nYOUR PREVIOUS ANSWER WAS NOT USABLE: {last_error}\n"
                "Reply again with ONLY one JSON object with exactly the keys described above."
            )
    raise LLMOutputError(
        f"The model didn't return a usable answer after 2 tries ({last_error}). "
        "Try again, or check the repo yourself and ask the maintainers."
    )


def _add_stats(total: CallStats, one: CallStats) -> None:
    total.wall_s += one.wall_s
    total.load_s += one.load_s
    total.prompt_tokens += one.prompt_tokens
    total.prompt_s += one.prompt_s
    total.output_tokens += one.output_tokens
    total.output_s += one.output_s


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc']) or 'answer'}: {e['msg']}" for e in exc.errors()[:3]]
        return "; ".join(parts)
    return str(exc)[:200]
