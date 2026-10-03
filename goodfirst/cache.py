"""
A tiny on-disk cache for GitHub API responses.

Why: unauthenticated GitHub access allows only 60 requests per hour, and one
GoodFirst analysis makes about 5. Caching means re-running the same repo (very
common while demoing or tweaking prompts) costs zero requests.

Each entry is one JSON file named after a hash of the request URL. We store
the HTTP status too, so "this file does not exist (404)" is cached as well.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class DiskCache:
    def __init__(self, directory: Path, ttl_s: int):
        self.directory = Path(directory)
        self.ttl_s = ttl_s

    @property
    def enabled(self) -> bool:
        return self.ttl_s > 0

    def _file_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.directory / f"{digest}.json"

    def get(self, key: str) -> tuple[int, Any] | None:
        """Return (status, data) if a fresh entry exists, else None."""
        entry = self._read(key)
        if entry is None or time.time() - entry.get("saved_at", 0) > self.ttl_s:
            return None
        return entry["status"], entry["data"]

    def get_stale(self, key: str) -> tuple[int, Any, float] | None:
        """
        Return (status, data, saved_at) even if the entry is older than the TTL.
        Used only when GitHub can't be reached: old data clearly labelled as old
        is more useful than nothing (and lets the demo work offline).
        """
        entry = self._read(key)
        if entry is None:
            return None
        return entry["status"], entry["data"], float(entry.get("saved_at", 0))

    def _read(self, key: str) -> dict | None:
        if not self.enabled:
            return None
        try:
            return json.loads(self._file_for(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # missing or corrupted file = cache miss

    def set(self, key: str, status: int, data: Any) -> None:
        if not self.enabled:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            entry = {"saved_at": time.time(), "key": key, "status": status, "data": data}
            self._file_for(key).write_text(json.dumps(entry), encoding="utf-8")
        except OSError:
            pass  # a cache that can't write is just a slower app, never a crash
