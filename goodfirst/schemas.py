"""
The JSON shapes we ask the model for, validated with pydantic.

Small models get the *meaning* right more often than the exact *format*:
they write confidence as "85%" or 85, return a file as a plain string instead
of {"path": ..., "why": ...}, or add extra list items. The validators below
quietly repair those harmless format slips. Anything they can't repair
(missing summary, not JSON at all) fails validation, and the LLM layer retries
once and then gives up honestly.

Repairing format is NOT the honesty check. The honesty check (honesty.py) runs
afterwards and decides whether the *content* can be trusted.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Upper limits keep answers short: every output token costs ~0.1 s on a CPU.
MAX_SETUP_STEPS = 8
MAX_FILES = 6
MAX_QUESTIONS = 4
MAX_UNSURE = 4


def _as_confidence(value: Any) -> float:
    """Accept 0.8, "0.8", "80%", 80 -> 0.8. Clamp to [0, 1]."""
    if isinstance(value, str):
        text = value.strip()
        match = re.search(r"\d+(\.\d+)?", text)
        if not match:
            raise ValueError(f"confidence is not a number: {value!r}")
        number = float(match.group())
        if text.endswith("%"):
            number /= 100
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        raise ValueError(f"confidence is not a number: {value!r}")
    if number > 1:          # the model meant a percentage
        number /= 100
    return max(0.0, min(1.0, number))


def _text_list(value: Any, limit: int) -> list[str]:
    """A list of non-empty strings. Dict items like {"step": "..."} are flattened."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item = next((v for v in item.values() if isinstance(v, str) and v.strip()), "")
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out[:limit]


# The JSON schema we hand to Ollama ("structured outputs"). Ollama turns it into a
# grammar, so the model *cannot* produce different keys or wrap the answer in
# another object. Plain format="json" only guarantees *some* valid JSON, and on a
# real run Gemma 3 4B returned JSON without "summary"/"confidence".
# Kept deliberately simple (no $ref, no length limits) so every Ollama version
# can compile it; list lengths are trimmed by the validators below instead.
EXPLAINER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "answer_found_in_docs": {"type": "boolean"},
        "summary": {"type": "string"},
        "setup_steps": {"type": "array", "items": {"type": "string"}},
        "important_files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "why": {"type": "string"}},
                "required": ["path", "why"],
            },
        },
        "questions_for_maintainers": {"type": "array", "items": {"type": "string"}},
        "unsure_about": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": [
        "answer",
        "answer_found_in_docs",
        "summary",
        "setup_steps",
        "important_files",
        "questions_for_maintainers",
        "unsure_about",
        "confidence",
    ],
}


ISSUE_PICKS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "why_this_one": {"type": "string"},
                    "where_to_start": {"type": "string"},
                },
                "required": ["number", "why_this_one", "where_to_start"],
            },
        },
        "confidence": {"type": "number"},
    },
    "required": ["picks", "confidence"],
}

MAX_PICKS = 3


def issue_picks_schema(n_picks: int) -> dict:
    """
    The picker schema with an exact number of picks. On real runs Gemma 3 4B
    returned only ONE pick when the count was just a prompt instruction, so we
    let Ollama's grammar enforce it (minItems/maxItems on the array).
    """
    import copy

    schema = copy.deepcopy(ISSUE_PICKS_JSON_SCHEMA)
    schema["properties"]["picks"]["minItems"] = n_picks
    schema["properties"]["picks"]["maxItems"] = n_picks
    return schema


class IssuePick(BaseModel):
    number: int
    why_this_one: str = ""
    where_to_start: str = ""

    @field_validator("number", mode="before")
    @classmethod
    def _number(cls, v):
        # "#123", "123", 123.0 -> 123
        if isinstance(v, str):
            match = re.search(r"\d+", v)
            if not match:
                raise ValueError(f"issue number is not a number: {v!r}")
            return int(match.group())
        if isinstance(v, float) and v.is_integer():
            return int(v)
        return v

    @field_validator("why_this_one", "where_to_start", mode="before")
    @classmethod
    def _text(cls, v):
        return v.strip() if isinstance(v, str) else ("" if v is None else str(v))


class IssuePicks(BaseModel):
    """What the Issue Picker node must return."""

    picks: list[IssuePick]
    confidence: float

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v):
        return _as_confidence(v)

    @field_validator("picks", mode="before")
    @classmethod
    def _picks(cls, v):
        if isinstance(v, dict):
            v = [v]
        return (v or [])[: MAX_PICKS + 2]  # a little slack; the honesty check trims to 3


class ImportantFile(BaseModel):
    path: str
    why: str = ""


class RepoExplanation(BaseModel):
    """What the Repo Explainer node must return."""

    # Answer to the user's question ("" when they didn't ask one), and whether the
    # model found that answer in the README/CONTRIBUTING rather than guessing.
    answer: str = ""
    answer_found_in_docs: bool = False
    summary: str = Field(min_length=1)
    setup_steps: list[str] = Field(default_factory=list)
    important_files: list[ImportantFile] = Field(default_factory=list)
    questions_for_maintainers: list[str] = Field(default_factory=list)
    unsure_about: list[str] = Field(default_factory=list)
    confidence: float

    @field_validator("answer", mode="before")
    @classmethod
    def _answer(cls, v):
        if isinstance(v, list):
            v = " ".join(str(x) for x in v)
        return v.strip() if isinstance(v, str) else ""

    @field_validator("answer_found_in_docs", mode="before")
    @classmethod
    def _found(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in ("true", "yes", "1")
        return bool(v)

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, v):
        if isinstance(v, list):  # some models return a list of sentences
            v = " ".join(str(x) for x in v)
        return v.strip() if isinstance(v, str) else v

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v):
        return _as_confidence(v)

    @field_validator("setup_steps", mode="before")
    @classmethod
    def _steps(cls, v):
        return _text_list(v, MAX_SETUP_STEPS)

    @field_validator("questions_for_maintainers", mode="before")
    @classmethod
    def _questions(cls, v):
        return _text_list(v, MAX_QUESTIONS)

    @field_validator("unsure_about", mode="before")
    @classmethod
    def _unsure(cls, v):
        return _text_list(v, MAX_UNSURE)

    @field_validator("important_files", mode="before")
    @classmethod
    def _files(cls, v):
        if v is None:
            return []
        if isinstance(v, (str, dict)):
            v = [v]
        out = []
        for item in v:
            if isinstance(item, str) and item.strip():
                out.append({"path": item.strip(), "why": ""})
            elif isinstance(item, dict):
                path = item.get("path") or item.get("file") or item.get("name")
                if isinstance(path, str) and path.strip():
                    why = item.get("why") or item.get("reason") or item.get("description") or ""
                    out.append({"path": path.strip(), "why": str(why).strip()})
        return out[:MAX_FILES]
