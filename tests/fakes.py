"""Shared test doubles: a hand-built RepoSnapshot and a scripted fake model."""

from __future__ import annotations

import json

from goodfirst.github_client import Issue, RepoSnapshot, TextDoc
from goodfirst.llm import CallStats, RawReply

README = """# Widgets
Widgets is a tiny Python library for drawing widgets.

## Installation
Run `pip install -e .` and then `pytest` to check everything works.
"""

CONTRIBUTING = "Fork the repo, create a branch, and run `pytest` before opening a PR."


def make_snapshot(readme: str | None = README, contributing: str | None = CONTRIBUTING, **overrides) -> RepoSnapshot:
    all_paths = ["README.md", "CONTRIBUTING.md", "setup.py", "src", "src/widgets.py", "src/draw.py", "tests", "tests/test_widgets.py"]
    values = dict(
        owner="acme",
        repo="widgets",
        full_name="acme/widgets",
        html_url="https://github.com/acme/widgets",
        description="Tiny widgets",
        default_branch="main",
        language="Python",
        topics=["widgets"],
        stars=42,
        archived=False,
        license="MIT",
        readme=TextDoc("README.md", readme, False, len(readme)) if readme is not None else None,
        contributing=TextDoc("CONTRIBUTING.md", contributing, False, len(contributing)) if contributing is not None else None,
        top_level=[
            {"path": "src", "type": "dir"},
            {"path": "tests", "type": "dir"},
            {"path": "CONTRIBUTING.md", "type": "file"},
            {"path": "README.md", "type": "file"},
            {"path": "setup.py", "type": "file"},
        ],
        all_paths=all_paths,
        tree_truncated=False,
        issues=[
            Issue(1, "Fix typo in docs", "The word 'widgte' in README.md is misspelled.", False,
                  "https://github.com/acme/widgets/issues/1", ["good first issue"], 0, False, "", ""),
        ],
        issue_labels_used=["good first issue"],
        notes=[],
    )
    values.update(overrides)
    return RepoSnapshot(**values)


class FakeLLM:
    """Returns pre-scripted replies in order and records every prompt it received."""

    def __init__(self, *replies):
        self.replies = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        self.prompts: list[tuple[str, str]] = []
        self.schemas: list[dict | None] = []

    def chat(self, system: str, user: str, json_schema: dict | None = None) -> RawReply:
        self.prompts.append((system, user))
        self.schemas.append(json_schema)
        if not self.replies:
            raise AssertionError("FakeLLM was called more times than scripted")
        stats = CallStats(wall_s=1.0, prompt_tokens=1000, prompt_s=0.5, output_tokens=100, output_s=0.5)
        return RawReply(self.replies.pop(0), stats)


class FakeGitHub:
    """Stands in for GitHubClient in graph tests."""

    def __init__(self, snapshot=None, error: Exception | None = None):
        self.snapshot = snapshot
        self.error = error
        self.calls = 0

    def fetch_snapshot(self, repo_input: str):
        self.calls += 1
        if self.error:
            raise self.error
        return self.snapshot


GOOD_ANSWER = {
    "summary": "Widgets is a small Python library for drawing widgets.",
    "setup_steps": ["Install it with `pip install -e .`", "Run the tests with `pytest`"],
    "important_files": [
        {"path": "src/widgets.py", "why": "Main code"},
        {"path": "README.md", "why": "Start here"},
    ],
    "questions_for_maintainers": ["Which part of the code is best for a first contribution?"],
    "unsure_about": [],
    "confidence": 0.85,
}
