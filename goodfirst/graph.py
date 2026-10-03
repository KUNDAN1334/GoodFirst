"""
The GoodFirst pipeline as a LangGraph graph with FIXED nodes.

    START -> fetch -> explain -> pick_issues -> honesty_check -> END
               |
               +--> END   (GitHub problem: friendly message in state["error"])

Why fixed nodes instead of letting the model pick tools? Small local models
are unreliable at free-form tool calling. Here the code decides what happens
and does all the fetching; the model only reads the fetched text and explains.

Failure handling:
- If fetching fails, nothing else can run: the graph stops with state["error"].
- If ONE model step fails (e.g. invalid JSON twice), the other step still runs.
  The failure is stored in state["explain_error"] / state["issues_error"] and
  the UI shows it next to the part that's missing. Partial, honest results
  beat no results.

`steps` lets callers run only part of the pipeline ("explain", "issues"), which
matters on a CPU where each model call takes 30-90 seconds.

Dependencies (GitHub client, LLM backend, settings) are passed in, so tests
can run the whole graph with a fake GitHub and a fake model.
"""

from __future__ import annotations

import logging
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from goodfirst.config import Settings
from goodfirst.github_client import GitHubClient, GitHubError, RepoSnapshot
from goodfirst.honesty import check_explanation, check_picks
from goodfirst.issues import RankedIssue, candidates, rank_issues
from goodfirst.llm import ChatBackend, LLMOutputError, LLMUnavailableError, ask_json
from goodfirst.prompts import (
    explainer_system_prompt,
    explainer_user_prompt,
    picker_system_prompt,
    picker_user_prompt,
)
from goodfirst.schemas import (
    EXPLAINER_JSON_SCHEMA,
    MAX_PICKS,
    IssuePicks,
    RepoExplanation,
    issue_picks_schema,
)

log = logging.getLogger("goodfirst.graph")

ALL_STEPS = ("explain", "issues")


class GoodFirstState(TypedDict, total=False):
    # inputs
    repo_input: str
    language: str              # "english" or "hinglish"
    question: str              # the user's optional question about the repo
    steps: list[str]           # which model steps to run: "explain", "issues"
    # filled in by the nodes
    snapshot: RepoSnapshot
    draft: RepoExplanation     # the model's explanation, before the honesty check
    ranked: list[RankedIssue]  # all issues, scored by code
    pool: list[RankedIssue]    # the candidates the model was shown
    picks_draft: IssuePicks    # the model's issue picks, before the honesty check
    explanation: dict          # checked explanation for the UI
    issues: dict               # checked issue picks for the UI
    error: str                 # fatal (GitHub) problem; nothing else ran
    explain_error: str         # the explainer step failed; issues may still be fine
    issues_error: str          # the issue picker step failed; explanation may still be fine
    timings: dict[str, Any]


def build_graph(github: GitHubClient, llm: ChatBackend, settings: Settings):
    """Wire the nodes together and return a compiled, runnable graph."""

    def fetch(state: GoodFirstState) -> dict:
        start = time.perf_counter()
        try:
            snapshot = github.fetch_snapshot(state["repo_input"])
        except GitHubError as exc:
            return {"error": str(exc)}
        return {"snapshot": snapshot, "timings": {"github_s": round(time.perf_counter() - start, 1)}}

    def explain(state: GoodFirstState) -> dict:
        if "explain" not in state.get("steps", ALL_STEPS):
            return {}
        language = state.get("language", "english")
        try:
            draft, stats = ask_json(
                llm,
                explainer_system_prompt(language),
                explainer_user_prompt(state["snapshot"], language, state.get("question", "")),
                RepoExplanation,
                json_schema=EXPLAINER_JSON_SCHEMA,
            )
        except (LLMUnavailableError, LLMOutputError) as exc:
            return {"explain_error": str(exc)}
        timings = dict(state.get("timings", {}))
        timings["explain"] = stats.as_dict()
        return {"draft": draft, "timings": timings}

    def pick_issues(state: GoodFirstState) -> dict:
        if "issues" not in state.get("steps", ALL_STEPS):
            return {}
        snapshot = state["snapshot"]
        question = state.get("question", "")
        ranked = rank_issues(snapshot.issues, question)
        pool = candidates(ranked)
        update: dict[str, Any] = {"ranked": ranked, "pool": pool}
        if not pool:
            return update  # no issues: don't spend 30+ seconds asking the model about nothing
        language = state.get("language", "english")
        n_picks = min(MAX_PICKS, len(pool))
        try:
            picks, stats = ask_json(
                llm,
                picker_system_prompt(language, n_picks),
                picker_user_prompt(snapshot, pool, question, language),
                IssuePicks,
                json_schema=issue_picks_schema(n_picks),
            )
        except (LLMUnavailableError, LLMOutputError) as exc:
            update["issues_error"] = str(exc)
            return update
        timings = dict(state.get("timings", {}))
        timings["issues"] = stats.as_dict()
        update.update({"picks_draft": picks, "timings": timings})
        return update

    def honesty_check(state: GoodFirstState) -> dict:
        language = state.get("language", "english")
        update: dict[str, Any] = {}
        if "draft" in state:
            update["explanation"] = check_explanation(
                state["draft"], state["snapshot"], settings, language=language, question=state.get("question", "")
            )
        if "ranked" in state:
            update["issues"] = check_picks(
                state.get("picks_draft"),
                state["snapshot"],
                state["ranked"],
                state.get("pool", []),
                settings,
                language=language,
            )
        return update

    def after_fetch(state: GoodFirstState) -> str:
        return END if state.get("error") else "explain"

    graph = StateGraph(GoodFirstState)
    graph.add_node("fetch", fetch)
    graph.add_node("explain", explain)
    graph.add_node("pick_issues", pick_issues)
    graph.add_node("honesty_check", honesty_check)
    graph.add_edge(START, "fetch")
    graph.add_conditional_edges("fetch", after_fetch, ["explain", END])
    graph.add_edge("explain", "pick_issues")
    graph.add_edge("pick_issues", "honesty_check")
    graph.add_edge("honesty_check", END)
    return graph.compile()


def run(
    repo_input: str,
    language: str = "english",
    question: str = "",
    steps: tuple[str, ...] | list[str] = ALL_STEPS,
    *,
    github: GitHubClient,
    llm: ChatBackend,
    settings: Settings,
) -> GoodFirstState:
    """Convenience wrapper: build the graph and run it once."""
    app = build_graph(github, llm, settings)
    return app.invoke(
        {"repo_input": repo_input, "language": language, "question": question, "steps": list(steps)}
    )
