"""
API tests: the SSE stream for /api/analyze and /api/health.
Fake GitHub + scripted fake model, so no network and no Ollama.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from goodfirst.api import create_app
from goodfirst.config import load_settings
from goodfirst.github_client import RepoNotFoundError
from tests.fakes import GOOD_ANSWER, FakeGitHub, FakeLLM, make_snapshot

SETTINGS = load_settings({"OLLAMA_BASE_URL": "http://127.0.0.1:1"})  # nothing listens there
PICKS = {"picks": [{"number": 1, "why_this_one": "Typo fix.", "where_to_start": "Open README.md."}], "confidence": 0.8}


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = [l for l in block.splitlines() if not l.startswith(":")]
        if not lines:
            continue
        name = next(l[7:] for l in lines if l.startswith("event: "))
        data = json.loads(next(l[6:] for l in lines if l.startswith("data: ")))
        events.append((name, data))
    return events


def analyze(github, llm, **body):
    client = TestClient(create_app(SETTINGS, github=github, llm=llm))
    resp = client.post("/api/analyze", json={"repo": "acme/widgets", **body})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    return parse_sse(resp.text)


def test_stream_has_one_event_per_step_then_result():
    events = analyze(FakeGitHub(make_snapshot()), FakeLLM(GOOD_ANSWER, PICKS), question="I know docs. Where do I start?")
    steps = [(d["step"], d["status"]) for n, d in events if n == "step"]
    assert steps == [
        ("fetching", "started"), ("fetching", "done"),
        ("explaining", "started"), ("explaining", "done"),
        ("picking", "started"), ("picking", "done"),
        ("honesty_check", "started"), ("honesty_check", "done"),
    ]
    assert all("seconds" in d for n, d in events if n == "step" and d["status"] == "done")
    name, result = events[-1]
    assert name == "result"
    assert result["repo"]["full_name"] == "acme/widgets"
    assert result["explanation"]["summary"].startswith("Widgets")
    assert result["issues"]["picks"][0]["number"] == 1
    assert {e["section"] for e in result["evidence"]} == {"repo", "issues"}
    assert result["overall_confidence"] == 0.8   # min(0.85 explain, 0.8 issues)
    assert result["model"] == "gemma3:4b"


def test_no_issues_does_not_zero_the_overall_confidence():
    events = analyze(FakeGitHub(make_snapshot(issues=[])), FakeLLM(GOOD_ANSWER))
    result = events[-1][1]
    assert result["issues"]["picks"] == []
    assert result["overall_confidence"] == 0.85  # explanation only


def test_skipped_step_is_reported():
    events = analyze(FakeGitHub(make_snapshot()), FakeLLM(PICKS), steps=["issues"])
    statuses = {d["step"]: d["status"] for n, d in events if n == "step" and d["status"] != "started"}
    assert statuses["explaining"] == "skipped"
    assert events[-1][1]["explanation"] is None


def test_github_error_becomes_error_event():
    events = analyze(FakeGitHub(error=RepoNotFoundError("Couldn't find github.com/acme/widgets.")), FakeLLM())
    assert ("fetching", "failed") in [(d["step"], d["status"]) for n, d in events if n == "step"]
    assert events[-1] == ("error", {"message": "Couldn't find github.com/acme/widgets."})


def test_model_failure_is_partial_not_fatal():
    events = analyze(FakeGitHub(make_snapshot()), FakeLLM("bad", "bad", PICKS))
    failed = [d for n, d in events if n == "step" and d["status"] == "failed"]
    assert failed[0]["step"] == "explaining"
    result = events[-1][1]
    assert "didn't return a usable answer" in result["explain_error"]
    assert result["issues"]["picks"]


def test_bad_request_is_rejected():
    client = TestClient(create_app(SETTINGS, github=FakeGitHub(make_snapshot()), llm=FakeLLM()))
    assert client.post("/api/analyze", json={"repo": ""}).status_code == 422
    assert client.post("/api/analyze", json={"repo": "a/b", "language": "french"}).status_code == 422


def test_health_reports_unreachable_ollama():
    client = TestClient(create_app(SETTINGS, github=FakeGitHub(), llm=FakeLLM()))
    info = client.get("/api/health").json()
    assert info["ok"] is False and info["ollama_reachable"] is False
    assert info["model"] == "gemma3:4b"


def test_cors_allows_the_web_ui():
    client = TestClient(create_app(SETTINGS, github=FakeGitHub(), llm=FakeLLM()))
    resp = client.options(
        "/api/analyze",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
