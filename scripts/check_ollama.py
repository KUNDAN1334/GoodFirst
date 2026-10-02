"""
Ollama health check for GoodFirst.

Run from the project root:   python scripts\\check_ollama.py

It checks, in order:
  1. Is the Ollama server running?
  2. Is the configured model (OLLAMA_MODEL) pulled?
  3. How long does one short answer take? (first call includes loading the model into RAM)
  4. Does the model return valid JSON when asked to? (GoodFirst relies on this)

Only the local Ollama server is contacted. Exit code 0 = all good, 1 = a problem was found.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

# Let `python scripts\check_ollama.py` import the goodfirst package from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goodfirst.config import ConfigError, get_settings  # noqa: E402


def normalize_model_name(name: str) -> str:
    """Ollama treats 'gemma3' and 'gemma3:latest' as the same model."""
    return name if ":" in name else f"{name}:latest"


def model_is_available(tags_response: dict, model: str) -> bool:
    """True if `model` appears in the JSON returned by GET /api/tags."""
    wanted = normalize_model_name(model)
    for entry in tags_response.get("models", []):
        if normalize_model_name(entry.get("name", "")) == wanted:
            return True
    return False


def ns_to_s(nanoseconds: int | None) -> float:
    """Ollama reports durations in nanoseconds."""
    return (nanoseconds or 0) / 1e9


def generate(client: httpx.Client, settings, prompt: str, json_mode: bool) -> tuple[dict, float]:
    """One non-streaming call to /api/generate. Returns (response_json, wall_seconds)."""
    body = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": settings.num_ctx, "temperature": settings.temperature},
    }
    if json_mode:
        body["format"] = "json"
    start = time.perf_counter()
    resp = client.post("/api/generate", json=body)
    elapsed = time.perf_counter() - start
    resp.raise_for_status()
    return resp.json(), elapsed


def main() -> int:
    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"[FAIL] Problem in your .env file: {exc}")
        return 1

    print(f"Ollama URL : {settings.ollama_base_url}")
    print(f"Model      : {settings.ollama_model}")
    print(f"num_ctx    : {settings.num_ctx}")
    print()

    client = httpx.Client(base_url=settings.ollama_base_url, timeout=settings.llm_timeout_s)

    # 1. Is the server up?
    try:
        version = client.get("/api/version", timeout=5).json().get("version", "?")
        print(f"[ OK ] Ollama is running (version {version})")
    except httpx.HTTPError:
        print("[FAIL] Could not reach Ollama.")
        print("       Start the Ollama app from the Start menu (or run `ollama serve`), then retry.")
        return 1

    # 2. Is the model pulled?
    tags = client.get("/api/tags", timeout=10).json()
    if not model_is_available(tags, settings.ollama_model):
        names = ", ".join(m.get("name", "?") for m in tags.get("models", [])) or "(none)"
        print(f"[FAIL] Model '{settings.ollama_model}' is not pulled yet.")
        print(f"       Run:  ollama pull {settings.ollama_model}")
        print(f"       Models you have: {names}")
        return 1
    print(f"[ OK ] Model '{settings.ollama_model}' is available")

    # 3. Timing of one short plain-text answer.
    print("\nAsking one short question (first call loads the model, can take a while on CPU)...")
    try:
        data, wall = generate(
            client, settings, "In one sentence, what is open source?", json_mode=False
        )
    except httpx.HTTPError as exc:
        print(f"[FAIL] Generation failed: {exc}")
        return 1

    answer = data.get("response", "").strip()
    load_s = ns_to_s(data.get("load_duration"))
    eval_s = ns_to_s(data.get("eval_duration"))
    tokens = data.get("eval_count", 0)
    tps = tokens / eval_s if eval_s else 0.0
    print(f"[ OK ] Answer: {answer[:200]}")
    print(f"       Total time      : {wall:.1f} s")
    print(f"       Model load time : {load_s:.1f} s")
    print(f"       Output speed    : {tps:.1f} tokens/s ({tokens} tokens)")

    # 4. JSON mode, which every GoodFirst node depends on.
    print("\nChecking JSON mode...")
    try:
        data, wall = generate(
            client,
            settings,
            'Reply with JSON only, shaped like {"ok": true, "word": "<one word about GitHub>"}',
            json_mode=True,
        )
        parsed = json.loads(data.get("response", ""))
        print(f"[ OK ] Valid JSON in {wall:.1f} s: {parsed}")
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        print(f"[WARN] JSON mode did not return valid JSON: {exc}")
        print("       GoodFirst retries once and then fails honestly, but a 4B model is more reliable than 1B.")
        return 1

    print("\nAll checks passed. Rough guide: a full GoodFirst answer is several hundred tokens,")
    print(f"so expect about {max(1, round(400 / tps)) if tps else '?'} s per answer at this speed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
