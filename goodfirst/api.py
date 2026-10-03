"""
GoodFirst HTTP API (FastAPI).

    POST /api/analyze   -> Server-Sent Events: one "step" event when each graph node
                           starts and finishes, then one "result" event (or "error").
    POST /api/ci        -> same, for the PR CI Explainer (why did my pull request's checks fail?).
    GET  /api/health    -> is Ollama running, is the model pulled, is a GitHub token set.

Run it:   python -m goodfirst.api        (serves http://127.0.0.1:8000)

Why SSE? On a CPU one analysis takes 1-2 minutes. Streaming every step (with
timings) lets the UI show real progress instead of a frozen spinner, so the
wait feels intentional. The graph itself is synchronous, so it runs in a worker
thread that pushes events into a queue; the HTTP response reads from that
queue and sends a keep-alive comment every few seconds while the model thinks.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import queue
import threading
import time
from typing import Any, Callable, Iterator, Literal

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from goodfirst.ci import build_ci_graph
from goodfirst.config import Settings, get_settings
from goodfirst.github_client import GitHubClient
from goodfirst.graph import ALL_STEPS, build_graph
from goodfirst.llm import ChatBackend, OllamaBackend

log = logging.getLogger("goodfirst.api")

# Graph node -> the step name the UI shows. Fixed order: the graph has fixed nodes.
NODE_ORDER = ["fetch", "explain", "pick_issues", "honesty_check"]
STEP_NAMES = {"fetch": "fetching", "explain": "explaining", "pick_issues": "picking", "honesty_check": "honesty_check"}
KEEPALIVE_S = 10


class AnalyzeRequest(BaseModel):
    repo: str = Field(min_length=1, max_length=300)
    question: str = Field(default="", max_length=500)  # the user's optional question
    language: Literal["english", "hinglish"] = "english"
    steps: list[Literal["explain", "issues"]] = Field(default_factory=lambda: list(ALL_STEPS))


def sse(event: str, data: Any) -> str:
    """Format one Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# Turning graph progress into events
# ---------------------------------------------------------------------------


def _step_detail(node: str, state: dict) -> tuple[str, str]:
    """(status, human-readable detail) for a node that just finished."""
    steps = state.get("steps", list(ALL_STEPS))
    if node == "fetch":
        if state.get("error"):
            return "failed", state["error"]
        s = state["snapshot"]
        docs = [d.path for d in (s.readme, s.contributing) if d]
        return "done", (
            f"Read {' and '.join(docs) or 'no docs'}, listed {len(s.all_paths):,} files, found "
            f"{len(s.issues)} beginner issue{'s' if len(s.issues) != 1 else ''}"
        )
    if node == "explain":
        if "explain" not in steps:
            return "skipped", "Not requested"
        if state.get("explain_error"):
            return "failed", state["explain_error"]
        t = state.get("timings", {}).get("explain", {})
        return "done", f"Read {t.get('prompt_tokens', '?')} tokens, wrote {t.get('output_tokens', '?')}"
    if node == "pick_issues":
        if "issues" not in steps:
            return "skipped", "Not requested"
        if state.get("issues_error"):
            return "failed", state["issues_error"]
        pool = state.get("pool", [])
        if not pool:
            return "done", "No open beginner issues, so the model wasn't asked"
        return "done", f"Ranked {len(state.get('ranked', []))} issues, model chose from the top {len(pool)}"
    if node == "honesty_check":
        removed = flagged = 0
        for part in (state.get("explanation"), state.get("issues")):
            for e in (part or {}).get("evidence", []):
                removed += e["status"] == "removed"
                flagged += e["status"] == "flagged"
        return "done", f"Removed {removed} claim{'s' if removed != 1 else ''}, flagged {flagged}"
    return "done", ""


def build_result(state: dict, settings: Settings, total_s: float) -> dict:
    """The final JSON the UI renders. Plain dicts only (no dataclasses)."""
    s = state["snapshot"]
    explanation = state.get("explanation")
    issues = state.get("issues")
    # The weakest part sets the tone. "No beginner issues exist" is not a low-confidence
    # claim, so an issue section without picks doesn't count towards the overall score.
    parts = [explanation] if explanation else []
    if issues and issues["picks"]:
        parts.append(issues)
    overall = round(min(p["confidence"] for p in parts), 2) if parts else 0.0
    evidence = [dict(e, section="repo") for e in (explanation or {}).get("evidence", [])]
    evidence += [dict(e, section="issues") for e in (issues or {}).get("evidence", [])]
    return {
        "repo": {
            "full_name": s.full_name,
            "html_url": s.html_url,
            "description": s.description,
            "language": s.language,
            "stars": s.stars,
            "license": s.license,
            "archived": s.archived,
            "readme_path": s.readme.path if s.readme else None,
            "contributing_path": s.contributing.path if s.contributing else None,
            "file_count": len(s.all_paths),
            "tree_truncated": s.tree_truncated,
            "labels_used": s.issue_labels_used,
            "issue_count": len(s.issues),
            "notes": s.notes,
        },
        "explanation": explanation,
        "issues": issues,
        "explain_error": state.get("explain_error"),
        "issues_error": state.get("issues_error"),
        "evidence": evidence,
        "overall_confidence": overall,
        "overall_low": overall < settings.confidence_floor,
        "confidence_floor": settings.confidence_floor,
        "timings": state.get("timings", {}),
        "total_s": round(total_s, 1),
        "model": settings.ollama_model,
        "language": state.get("language", "english"),
        "question": state.get("question", "") or None,
    }


def stream_graph(
    graph,
    state: dict[str, Any],
    node_order: list[str],
    step_names: dict[str, str],
    detail: Callable[[str, dict], tuple[str, str]],
    result: Callable[[dict, float], dict],
) -> Iterator[tuple[str, Any]]:
    """
    Run a fixed-node graph and yield (event_name, data) pairs: a "step" event when each
    node starts and finishes (with timings), then one "result" or "error" event.
    Shared by /api/analyze and /api/ci.
    """
    start = last = time.perf_counter()
    yield "step", {"step": step_names[node_order[0]], "status": "started"}
    try:
        for chunk in graph.stream(dict(state), stream_mode="updates"):
            for node, update in chunk.items():
                state.update(update or {})
                now = time.perf_counter()
                status, text = detail(node, state)
                yield "step", {
                    "step": step_names.get(node, node),
                    "status": status,
                    "seconds": round(now - last, 1),
                    "detail": text,
                }
                last = now
                if state.get("error"):
                    break
                nxt = node_order.index(node) + 1
                if nxt < len(node_order):
                    yield "step", {"step": step_names[node_order[nxt]], "status": "started"}
    except Exception as exc:  # never leave the UI hanging on an unexpected bug
        log.exception("graph run crashed")
        yield "error", {"message": f"Something went wrong inside GoodFirst: {exc}"}
        return

    if state.get("error"):
        yield "error", {"message": state["error"]}
        return
    yield "result", result(state, time.perf_counter() - start)


def run_events(graph, request: AnalyzeRequest, settings: Settings) -> Iterator[tuple[str, Any]]:
    state: dict[str, Any] = {
        "repo_input": request.repo,
        "language": request.language,
        "question": request.question,
        "steps": list(request.steps),
    }
    return stream_graph(graph, state, NODE_ORDER, STEP_NAMES, _step_detail, lambda st, t: build_result(st, settings, t))


# ---------------------------------------------------------------------------
# PR CI Explainer
# ---------------------------------------------------------------------------

CI_NODE_ORDER = ["fetch", "explain", "honesty_check"]
CI_STEP_NAMES = {"fetch": "fetching", "explain": "explaining", "honesty_check": "honesty_check"}


class CIRequest(BaseModel):
    pr: str = Field(min_length=1, max_length=300)
    language: Literal["english", "hinglish"] = "english"


def _ci_detail(node: str, state: dict) -> tuple[str, str]:
    if node == "fetch":
        if state.get("error"):
            return "failed", state["error"]
        s = state["snapshot"]
        return "done", (
            f"PR #{s.number}: {s.checks_total} check{'s' if s.checks_total != 1 else ''}, "
            f"{len(s.failed)} failed, {len(s.changed_files)} changed file{'s' if len(s.changed_files) != 1 else ''}"
        )
    if node == "explain":
        if state.get("explain_error"):
            return "failed", state["explain_error"]
        if not state["snapshot"].failed:
            return "skipped", "Nothing failed, so there is nothing to explain"
        t = state.get("timings", {}).get("explain", {})
        return "done", f"Read {t.get('prompt_tokens', '?')} tokens, wrote {t.get('output_tokens', '?')}"
    if node == "honesty_check":
        ev = (state.get("result") or {}).get("evidence", [])
        removed = sum(e["status"] == "removed" for e in ev)
        flagged = sum(e["status"] == "flagged" for e in ev)
        return "done", f"Removed {removed} claim{'s' if removed != 1 else ''}, flagged {flagged}"
    return "done", ""


def build_ci_result(state: dict, settings: Settings, total_s: float) -> dict:
    snap = state["snapshot"]
    checked = state.get("result") or {}
    return {
        "pr": snap.to_dict(),
        **checked,
        "explain_error": state.get("explain_error"),
        "confidence_floor": settings.confidence_floor,
        "timings": state.get("timings", {}),
        "total_s": round(total_s, 1),
        "model": settings.ollama_model,
    }


def run_ci_events(graph, request: CIRequest, settings: Settings) -> Iterator[tuple[str, Any]]:
    state: dict[str, Any] = {"pr_input": request.pr, "language": request.language}
    return stream_graph(graph, state, CI_NODE_ORDER, CI_STEP_NAMES, _ci_detail, lambda st, t: build_ci_result(st, settings, t))


def sse_response(events_iter: Callable[[], Iterator[tuple[str, Any]]]) -> StreamingResponse:
    """Run a blocking event generator in a worker thread and stream it as SSE, with keep-alives."""
    events: queue.Queue = queue.Queue()
    done = object()

    def worker() -> None:
        try:
            for item in events_iter():
                events.put(item)
        finally:
            events.put(done)

    threading.Thread(target=worker, daemon=True).start()

    async def stream():
        while True:
            try:
                item = await asyncio.to_thread(events.get, True, KEEPALIVE_S)
            except queue.Empty:
                yield ": still working\n\n"  # SSE comment; keeps the connection alive
                continue
            if item is done:
                break
            name, data = item
            yield sse(name, data)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# The app
# ---------------------------------------------------------------------------


def _private_network_option() -> dict:
    """
    Lets a deployed UI (e.g. https://goodfirst.vercel.app) talk to this API on 127.0.0.1.
    Chrome asks the API to opt in to requests from a public site to a local address.
    Older Starlette versions don't have the option, so only pass it when it exists.
    """
    if "allow_private_network" in inspect.signature(CORSMiddleware.__init__).parameters:
        return {"allow_private_network": True}
    return {}


def create_app(
    settings: Settings | None = None,
    github: GitHubClient | None = None,
    llm: ChatBackend | None = None,
) -> FastAPI:
    """Build the API. Tests pass a fake GitHub and a fake model."""
    settings = settings or get_settings()
    github = github or GitHubClient(settings)
    llm = llm or OllamaBackend(settings)
    graph = build_graph(github, llm, settings)
    ci_graph = build_ci_graph(github, llm, settings)

    app = FastAPI(title="GoodFirst API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        **_private_network_option(),
    )

    @app.post("/api/analyze")
    async def analyze(request: AnalyzeRequest) -> StreamingResponse:
        return sse_response(lambda: run_events(graph, request, settings))

    @app.post("/api/ci")
    async def ci(request: CIRequest) -> StreamingResponse:
        return sse_response(lambda: run_ci_events(ci_graph, request, settings))

    @app.get("/api/health")
    async def health() -> dict:
        info: dict[str, Any] = {
            "model": settings.ollama_model,
            "ollama_reachable": False,
            "model_available": False,
            "github_token": bool(settings.github_token),
        }
        try:
            async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=3) as client:
                tags = (await client.get("/api/tags")).json()
            info["ollama_reachable"] = True
            wanted = settings.ollama_model if ":" in settings.ollama_model else settings.ollama_model + ":latest"
            info["model_available"] = any(m.get("name") == wanted for m in tags.get("models", []))
        except (httpx.HTTPError, ValueError):
            pass
        info["ok"] = info["ollama_reachable"] and info["model_available"]
        return info

    return app


def main() -> None:
    """`python -m goodfirst.api` starts the server on http://127.0.0.1:8000 (API_PORT to change)."""
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    settings = get_settings()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.api_port)


if __name__ == "__main__":
    main()
