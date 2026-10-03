"""
PR CI Explainer tests: PR parsing, log trimming, fetching (fake GitHub), the honesty
check, the graph and the /api/ci stream. No network, no Ollama.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from goodfirst.api import create_app
from goodfirst.ci import (
    CIExplanation,
    build_ci_graph,
    check_ci,
    computed_link,
    extract_excerpt,
    fetch_ci,
    parse_pr,
)
from goodfirst.config import load_settings
from goodfirst.github_client import GitHubClient, InvalidRepoError
from tests.fakes import FakeLLM
from tests.test_api import parse_sse
from tests.test_github_client import FakeGitHub as RouteGitHub

LOG = """2026-10-01T10:00:00.0000000Z ##[group]Run pytest
2026-10-01T10:00:01.0000000Z \x1b[32mcollected 12 items\x1b[0m
2026-10-01T10:00:02.0000000Z tests/test_theme.py::test_dark_palette FAILED
2026-10-01T10:00:02.1000000Z ________________________ test_dark_palette ________________________
2026-10-01T10:00:02.2000000Z     def test_dark_palette():
2026-10-01T10:00:02.3000000Z >       assert dark_palette()["background"] == "#000000"
2026-10-01T10:00:02.4000000Z E       KeyError: 'background'
2026-10-01T10:00:02.5000000Z /home/runner/work/widgets/widgets/src/theme.py:14: KeyError
2026-10-01T10:00:03.0000000Z FAILED tests/test_theme.py::test_dark_palette - KeyError: 'background'
2026-10-01T10:00:03.1000000Z ========================= 1 failed, 11 passed in 0.52s =========================
2026-10-01T10:00:03.2000000Z ##[error]Process completed with exit code 1.
"""

SETTINGS = load_settings({"CACHE_TTL_S": "0"})


def ci_routes(log_response=None) -> dict:
    return {
        "/repos/acme/widgets/pulls/7": {
            "head": {"sha": "abc123"},
            "title": "Add dark mode",
            "html_url": "https://github.com/acme/widgets/pull/7",
            "state": "open",
        },
        "/repos/acme/widgets/commits/abc123/check-runs": {
            "check_runs": [
                {"id": 111, "name": "tests (3.11)", "status": "completed", "conclusion": "failure",
                 "app": {"slug": "github-actions"}, "html_url": "https://github.com/acme/widgets/actions/runs/1/job/111"},
                {"id": 222, "name": "lint", "status": "completed", "conclusion": "success", "app": {"slug": "github-actions"}},
            ]
        },
        "/repos/acme/widgets/check-runs/111/annotations": [
            {"path": ".github", "annotation_level": "failure", "message": "Process completed with exit code 1."}
        ],
        "/repos/acme/widgets/actions/jobs/111/logs": log_response or httpx.Response(200, text=LOG),
        "/repos/acme/widgets/pulls/7/files": [{"filename": "src/theme.py"}],
        "/repos/acme/widgets/git/trees/abc123": {
            "tree": [
                {"path": "src", "type": "tree"},
                {"path": "src/theme.py", "type": "blob"},
                {"path": "tests", "type": "tree"},
                {"path": "tests/test_theme.py", "type": "blob"},
            ]
        },
    }


def client_for(routes) -> GitHubClient:
    return GitHubClient(SETTINGS, http=httpx.Client(transport=httpx.MockTransport(RouteGitHub(routes))))


GOOD = {
    "what_failed": "The test step failed.",
    "why": "test_dark_palette expects a 'background' key that dark_palette() doesn't return.",
    "fix_steps": ["Add a 'background' entry to the dict returned in src/theme.py", "Run `pytest` again"],
    "quoted_lines": ["E       KeyError: 'background'"],
    "files": ["src/theme.py"],
    "caused_by_this_pr": "yes",
    "confidence": 0.8,
}


# ------------------------------------------------------------- parsing + log trimming


@pytest.mark.parametrize(
    "text", ["https://github.com/acme/widgets/pull/7", "https://github.com/acme/widgets/pull/7/checks", "acme/widgets#7", "acme/widgets/pull/7"]
)
def test_parse_pr(text):
    assert parse_pr(text) == ("acme", "widgets", 7)


def test_parse_pr_rejects_non_pr_links():
    with pytest.raises(InvalidRepoError):
        parse_pr("https://github.com/acme/widgets")


def test_excerpt_strips_noise_and_keeps_the_error():
    excerpt = extract_excerpt(LOG)
    assert "2026-10-01T" not in excerpt and "\x1b[" not in excerpt
    assert "E       KeyError: 'background'" in excerpt
    assert "Process completed with exit code 1." in excerpt


def test_excerpt_is_capped_and_keeps_the_end():
    big = "\n".join(f"line {i}" for i in range(5000)) + "\nError: the real failure"
    excerpt = extract_excerpt(big, max_chars=500)
    assert len(excerpt) < 600
    assert excerpt.rstrip().endswith("Error: the real failure")


# ------------------------------------------------------------- fetching


def test_fetch_ci_collects_failed_checks_logs_and_changed_files():
    snap = fetch_ci(client_for(ci_routes()), "https://github.com/acme/widgets/pull/7")
    assert snap.title == "Add dark mode" and snap.checks_total == 2
    assert [c.name for c in snap.failed] == ["tests (3.11)"]
    check = snap.failed[0]
    assert check.log_status == "ok" and "KeyError" in check.log_excerpt
    assert check.annotations == ["Process completed with exit code 1."]
    assert snap.changed_files == ["src/theme.py"]
    assert computed_link(snap) == ["src/theme.py"]  # the error mentions a file this PR changed


def test_logs_needing_a_token_fall_back_to_annotations():
    routes = ci_routes(log_response=httpx.Response(403, json={"message": "Must have admin rights"}))
    snap = fetch_ci(client_for(routes), "acme/widgets#7")
    assert snap.failed[0].log_status == "needs_token"
    assert snap.failed[0].log_excerpt is None
    assert any("GITHUB_TOKEN" in n for n in snap.notes)


def test_no_failed_checks():
    routes = ci_routes()
    routes["/repos/acme/widgets/commits/abc123/check-runs"]["check_runs"][0]["conclusion"] = "success"
    snap = fetch_ci(client_for(routes), "acme/widgets#7")
    assert snap.failed == [] and any("No failed checks" in n for n in snap.notes)


# ------------------------------------------------------------- honesty


def snap():
    return fetch_ci(client_for(ci_routes()), "acme/widgets#7")


def test_good_explanation_passes():
    out = check_ci(CIExplanation.model_validate(GOOD), snap(), SETTINGS)
    e = out["explanation"]
    assert e["quoted_lines"] == [{"text": "E       KeyError: 'background'", "verified": True}]
    assert e["files"] == [{"path": "src/theme.py", "in_pr": True}]
    assert out["low_confidence"] is False and out["ask_comment"] is None
    assert not any(ev["status"] == "removed" for ev in out["evidence"])


def test_invented_quote_and_file_are_removed_and_confidence_capped():
    bad = {**GOOD, "quoted_lines": ["ImportError: cannot import name 'dark'"], "files": ["src/colors/dark.py"]}
    out = check_ci(CIExplanation.model_validate(bad), snap(), SETTINGS)
    assert out["explanation"]["quoted_lines"] == [] and out["explanation"]["files"] == []
    removed = [ev for ev in out["evidence"] if ev["status"] == "removed"]
    assert {ev["reason"] for ev in removed} == {"This line isn't in the log", "File does not exist in the repo"}
    assert out["confidence"] == 0.4 and out["low_confidence"] is True
    assert "tests (3.11)" in out["ask_comment"]


def test_model_saying_not_my_change_is_flagged_when_error_mentions_changed_file():
    out = check_ci(CIExplanation.model_validate({**GOOD, "caused_by_this_pr": "no"}), snap(), SETTINGS)
    assert any("which this PR changes" in w for w in out["warnings"])
    assert any(ev["claim"].startswith("Caused by this PR") and ev["status"] == "flagged" for ev in out["evidence"])


def test_fix_command_not_in_log_is_flagged():
    steps = {**GOOD, "fix_steps": ["Run `make test-all`"]}
    out = check_ci(CIExplanation.model_validate(steps), snap(), SETTINGS)
    assert out["explanation"]["fix_steps"] == [{"text": "Run `make test-all`", "verified": False}]


# ------------------------------------------------------------- graph + API


def test_graph_happy_path():
    llm = FakeLLM(GOOD)
    state = build_ci_graph(client_for(ci_routes()), llm, SETTINGS).invoke({"pr_input": "acme/widgets#7"})
    assert state["result"]["explanation"]["what_failed"] == "The test step failed."
    assert "KeyError" in llm.prompts[0][1] and "src/theme.py" in llm.prompts[0][1]


def test_graph_does_not_ask_model_without_any_log_or_annotations():
    routes = ci_routes(log_response=httpx.Response(403, json={"message": "no"}))
    routes["/repos/acme/widgets/check-runs/111/annotations"] = []
    llm = FakeLLM()
    state = build_ci_graph(client_for(routes), llm, SETTINGS).invoke({"pr_input": "acme/widgets#7"})
    assert llm.prompts == []
    assert "wasn't asked to guess" in state["explain_error"]
    assert state["result"]["ask_comment"]


def test_api_ci_stream():
    app = create_app(SETTINGS, github=client_for(ci_routes()), llm=FakeLLM(GOOD))
    resp = TestClient(app).post("/api/ci", json={"pr": "https://github.com/acme/widgets/pull/7"})
    events = parse_sse(resp.text)
    steps = [(d["step"], d["status"]) for n, d in events if n == "step"]
    assert steps == [("fetching", "started"), ("fetching", "done"), ("explaining", "started"), ("explaining", "done"),
                     ("honesty_check", "started"), ("honesty_check", "done")]
    name, result = events[-1]
    assert name == "result" and result["pr"]["number"] == 7
    assert result["linked_files"] == ["src/theme.py"]
    assert json.dumps(result)  # fully JSON-serialisable


def test_api_ci_bad_link_is_an_error_event():
    app = create_app(SETTINGS, github=client_for(ci_routes()), llm=FakeLLM())
    events = parse_sse(TestClient(app).post("/api/ci", json={"pr": "not a pr"}).text)
    assert events[-1][0] == "error" and "pull request link" in events[-1][1]["message"]


def test_invented_file_lowers_confidence():
    extra = {**GOOD, "files": ["src/theme.py", "src/colors/dark.py"]}
    out = check_ci(CIExplanation.model_validate(extra), snap(), SETTINGS)
    assert out["confidence"] == 0.7  # 0.8 minus 10% for one invented file; a real quote keeps it uncapped
    assert any("invented" in w for w in out["warnings"])
