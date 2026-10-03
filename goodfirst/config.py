"""
Central configuration for GoodFirst.

Every tunable value lives here and is read from environment variables
(optionally loaded from a `.env` file in the project root). The rest of the
code imports `get_settings()` instead of reading os.environ directly, so
there is exactly one place to look when you want to know "what can I change?".

Design notes:
- The LLM is ALWAYS a local Ollama model. There is intentionally no setting
  for a hosted API and no cloud fallback.
- Text limits (README / CONTRIBUTING / issue bodies) keep prompts small so a
  ~4B model on a CPU-only, 8GB-RAM laptop can still answer in reasonable time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

# Project root = the folder that contains the `goodfirst/` package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(ValueError):
    """Raised when a setting in .env has an invalid value."""


@dataclass(frozen=True)
class Settings:
    # --- Local model (Ollama) ---
    ollama_base_url: str          # where the Ollama server listens
    ollama_model: str             # e.g. "gemma3:4b" (default) or "gemma3:1b"
    num_ctx: int                  # model context window, in tokens
    temperature: float            # low = more predictable answers
    llm_timeout_s: float          # CPU inference is slow; be patient
    keep_alive: str               # how long Ollama keeps the model in RAM after a call (avoids ~25 s reloads)
    num_predict: int              # hard cap on answer length in tokens (stops runaway output)

    # --- GitHub (read-only) ---
    github_token: str | None      # optional; only raises the rate limit
    github_api_url: str

    # --- Honesty layer ---
    confidence_floor: float       # below this => "low confidence" + ask-the-maintainer box
    no_docs_confidence_cap: float # max confidence when README and CONTRIBUTING are both missing

    # --- Prompt size limits (characters, not tokens) ---
    max_readme_chars: int
    max_contributing_chars: int
    max_issue_body_chars: int
    max_issues: int               # how many good-first-issues to fetch at most

    # --- On-disk cache for GitHub responses ---
    cache_dir: Path
    cache_ttl_s: int              # 0 disables the cache

    # --- HTTP API (FastAPI) ---
    api_port: int
    cors_origins: list[str]       # where the web UI runs


# ---------------------------------------------------------------------------
# Small parsing helpers. They raise ConfigError with a friendly message
# instead of a bare ValueError, so a typo in .env is easy to spot.
# ---------------------------------------------------------------------------

def _get_str(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key, "").strip()
    return value or default


def _get_int(env: Mapping[str, str], key: str, default: int, minimum: int = 0) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a whole number, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}, got {value}")
    return value


def _get_float(
    env: Mapping[str, str], key: str, default: float, lo: float, hi: float
) -> float:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc
    if not lo <= value <= hi:
        raise ConfigError(f"{key} must be between {lo} and {hi}, got {value}")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """
    Build a Settings object.

    `env` is injectable so tests can pass a plain dict. When it is None we
    load `.env` from the project root (without overriding variables that are
    already set in the real environment) and read os.environ.
    """
    if env is None:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        env = os.environ

    cache_dir = Path(_get_str(env, "GOODFIRST_CACHE_DIR", ".cache"))
    if not cache_dir.is_absolute():
        cache_dir = PROJECT_ROOT / cache_dir

    return Settings(
        ollama_base_url=_get_str(env, "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=_get_str(env, "OLLAMA_MODEL", "gemma3:4b"),
        num_ctx=_get_int(env, "OLLAMA_NUM_CTX", 8192, minimum=512),
        temperature=_get_float(env, "OLLAMA_TEMPERATURE", 0.2, 0.0, 2.0),
        llm_timeout_s=float(_get_int(env, "OLLAMA_TIMEOUT_S", 300, minimum=10)),
        keep_alive=_get_str(env, "OLLAMA_KEEP_ALIVE", "30m"),
        num_predict=_get_int(env, "OLLAMA_NUM_PREDICT", 900, minimum=100),
        github_token=env.get("GITHUB_TOKEN", "").strip() or None,
        github_api_url=_get_str(env, "GITHUB_API_URL", "https://api.github.com").rstrip("/"),
        confidence_floor=_get_float(env, "CONFIDENCE_FLOOR", 0.6, 0.0, 1.0),
        no_docs_confidence_cap=_get_float(env, "NO_DOCS_CONFIDENCE_CAP", 0.3, 0.0, 1.0),
        max_readme_chars=_get_int(env, "MAX_README_CHARS", 6000, minimum=200),
        max_contributing_chars=_get_int(env, "MAX_CONTRIBUTING_CHARS", 4000, minimum=200),
        max_issue_body_chars=_get_int(env, "MAX_ISSUE_BODY_CHARS", 600, minimum=50),
        max_issues=_get_int(env, "MAX_ISSUES", 15, minimum=1),
        cache_dir=cache_dir,
        cache_ttl_s=_get_int(env, "CACHE_TTL_S", 3600, minimum=0),
        api_port=_get_int(env, "API_PORT", 8000, minimum=1),
        cors_origins=[
            o.strip().rstrip("/")
            for o in _get_str(env, "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
            if o.strip()
        ],
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor used by the app. Tests should call load_settings(dict)."""
    return load_settings()
