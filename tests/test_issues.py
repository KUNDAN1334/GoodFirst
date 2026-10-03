"""
Phase 3 tests: deterministic ranking, the issue-picker honesty check, and the
full graph with both model steps. The model is always a scripted fake.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from goodfirst.config import load_settings
from goodfirst.github_client import Issue
from goodfirst.graph import run
from goodfirst.honesty import check_picks, file_mentions
from goodfirst.issues import candidates, rank_issues, skill_terms
from goodfirst.prompts import picker_user_prompt
from goodfirst.schemas import IssuePicks, issue_picks_schema
from tests.fakes import GOOD_ANSWER, FakeGitHub, FakeLLM, make_snapshot

SETTINGS = load_settings({})
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def issue(number, title="Fix something", body="x" * 200, comments=0, assigned=False,
          labels=("good first issue",), updated="2026-09-20T00:00:00Z") -> Issue:
    return Issue(number, title, body, False, f"https://github.com/acme/widgets/issues/{number}",
                 list(labels), comments, assigned, "2026-01-01T00:00:00Z", updated)


ISSUES = [
    issue(10, "Add CSS dark mode to the settings page", body="The settings page in `src/settings.html` needs dark-mode styles. " * 4),
    issue(11, "Fix typo in README", body="'recieve' should be 'receive' in README.md, line 12. " * 3, comments=1),
    issue(12, "Refactor the plugin loader", body="x", comments=25),
    issue(13, "Add a test for draw()", body="We have no test for draw() in src/draw.py. Please add a pytest test. " * 3, assigned=True),
    issue(14, "Improve error message", body="When the config is missing we crash with a KeyError. " * 3, updated="2024-01-01T00:00:00Z"),
]


def snapshot_with(issues):
    return make_snapshot(issues=issues)


# ------------------------------------------------------------- ranking (pure code, no model)


def test_skill_terms_understand_casual_input():
    terms = skill_terms("I know Python, a little HTML/CSS and docs")
    assert set(terms) == {"python", "html", "css", "documentation"}
    assert skill_terms("") == {}
    # Ordinary question words are not skills.
    assert skill_terms("How do I contribute to my first issue?") == {}
    assert set(skill_terms("mujhe javascript aata hai, kaha se start karu?")) == {"javascript"}


def test_ranking_prefers_unassigned_clear_quiet_issues():
    ranked = rank_issues(ISSUES, question="", now=NOW)
    order = [r.issue.number for r in ranked]
    assert order.index(10) < order.index(12)   # 25 comments + 1-char body sinks #12
    assert order[-1] == 13 or order.index(13) > order.index(10)  # assigned issue ranks low
    top = ranked[0]
    assert "Nobody is assigned yet" in top.reasons


def test_ranking_uses_skills_named_in_the_question():
    css_first = rank_issues(ISSUES, question="I know some CSS, what can I do?", now=NOW)
    docs_first = rank_issues(ISSUES, question="I am good at writing docs", now=NOW)
    assert css_first[0].issue.number == 10
    assert docs_first[0].issue.number == 11
    assert any(r.startswith("Matches your question: documentation") for r in docs_first[0].reasons)


def test_stale_issue_is_marked():
    ranked = {r.issue.number: r for r in rank_issues(ISSUES, now=NOW)}
    assert "No activity for over a year" in ranked[14].reasons
    assert "Active recently" in ranked[10].reasons


def test_candidates_skip_assigned_when_possible():
    pool = candidates(rank_issues(ISSUES, now=NOW))
    assert 13 not in [r.issue.number for r in pool]
    # If almost everything is assigned, assigned issues are allowed back in.
    mostly_taken = [issue(1, assigned=True), issue(2, assigned=True), issue(3)]
    assert len(candidates(rank_issues(mostly_taken, now=NOW))) == 3


# ------------------------------------------------------------- schema


def test_issue_picks_schema_repairs_numbers():
    picks = IssuePicks.model_validate(
        {"picks": [{"number": "#11", "why_this_one": " Easy ", "where_to_start": None}], "confidence": "70%"}
    )
    assert picks.picks[0].number == 11
    assert picks.picks[0].why_this_one == "Easy"
    assert picks.picks[0].where_to_start == ""
    assert picks.confidence == 0.7


# ------------------------------------------------------------- honesty check for picks


def picks(*items, confidence=0.8):
    return IssuePicks.model_validate(
        {"picks": [{"number": n, "why_this_one": w, "where_to_start": s} for n, w, s in items], "confidence": confidence}
    )


def check(p, issues=ISSUES, question=""):
    snap = snapshot_with(issues)
    ranked = rank_issues(issues, question, now=NOW)
    return check_picks(p, snap, ranked, candidates(ranked), SETTINGS)


def test_invented_issue_numbers_are_removed_and_refilled():
    out = check(picks((11, "typo", "Open README.md"), (999, "invented", "x"), (10, "css", "Open `src/settings.html`")))
    numbers = [p["number"] for p in out["picks"]]
    assert 999 not in numbers
    assert numbers[:2] == [11, 10]
    assert len(numbers) == 3                       # topped up from the ranking
    assert out["picks"][2]["source"] == "ranking"
    joined = " ".join(out["warnings"])
    assert "#999" in joined
    assert "Added 1 issue from GoodFirst's own ranking" in joined
    assert out["confidence"] == pytest.approx(0.7)  # 0.8 - 0.1 for one invented number


def test_titles_and_links_come_from_github_not_the_model():
    out = check(picks((11, "why", "where")))
    first = out["picks"][0]
    assert first["title"] == "Fix typo in README"
    assert first["url"].endswith("/issues/11")
    assert first["facts"]  # deterministic reasons are attached


def test_unverified_file_in_where_to_start_is_flagged():
    out = check(picks((11, "why", "Edit docs/guide/intro.md and README.md")))
    entry = out["picks"][0]
    assert entry["unverified_files"] == ["docs/guide/intro.md"]   # README.md exists in the repo
    assert any("docs/guide/intro.md" in w for w in out["warnings"])


def test_file_mentioned_by_the_issue_itself_is_fine():
    # src/settings.html isn't in the fake repo's file list, but issue #10 itself mentions it.
    out = check(picks((10, "css", "Start in src/settings.html")))
    assert out["picks"][0]["unverified_files"] == []


def test_file_mentions():
    assert file_mentions("Open `src/app.py`, then README.md (e.g. line 3) and v1.2") == ["src/app.py", "README.md"]


def test_no_issues_skips_model_and_offers_question():
    out = check(None, issues=[])
    assert out["picks"] == []
    assert out["low_confidence"] is True
    assert "first-time contributor" in out["ask_maintainer"]


def test_model_failure_falls_back_to_ranking_with_clear_warning():
    out = check(None)
    assert len(out["picks"]) == 3
    assert all(p["source"] == "ranking" for p in out["picks"])
    assert "only from GoodFirst's own ranking" in " ".join(out["warnings"])
    assert out["low_confidence"] is True


def test_low_confidence_picks_offer_issue_comment():
    out = check(picks((11, "why", "where"), (10, "w", "s"), (14, "w", "s"), confidence=0.3), question="I know docs")
    assert out["low_confidence"] is True
    assert "#11" in out["ask_maintainer"]


def test_good_picks_pass_without_warnings():
    out = check(picks((11, "w", "Fix the typo in README.md"), (10, "w", "s"), (14, "w", "s")))
    assert out["warnings"] == []
    assert out["low_confidence"] is False
    assert out["ask_maintainer"] is None


def test_top_up_skips_poor_issues():
    poor_pool = [issue(1, body="Clear description of a small change. " * 5), issue(2, body="x", comments=30)]
    out = check(picks((1, "w", "s")), issues=poor_pool)
    # #2 (1-char description, 30 comments) is not added just to reach 3 picks.
    assert [p["number"] for p in out["picks"]] == [1]
    assert not any("Added" in w for w in out["warnings"])


def test_only_three_picks_kept():
    out = check(picks((10, "", ""), (11, "", ""), (14, "", ""), (12, "", "")))
    assert [p["number"] for p in out["picks"]] == [10, 11, 14]


# ------------------------------------------------------------- prompt


def test_picker_prompt_contains_candidates_and_question():
    ranked = rank_issues(ISSUES, "I know css", now=NOW)
    text = picker_user_prompt(snapshot_with(ISSUES), candidates(ranked), "I know css", "english")
    assert "THE BEGINNER'S QUESTION: I know css" in text
    assert "#10: Add CSS dark mode" in text
    assert "#13" not in text  # assigned issue isn't offered


# ------------------------------------------------------------- full graph


PICKS_ANSWER = {
    "picks": [{"number": 1, "why_this_one": "It's a typo fix.", "where_to_start": "Open README.md."}],
    "confidence": 0.8,
}


def test_graph_runs_both_steps():
    llm = FakeLLM(GOOD_ANSWER, PICKS_ANSWER)
    state = run("acme/widgets", question="I know docs", github=FakeGitHub(make_snapshot()), llm=llm, settings=SETTINGS)
    assert state["explanation"]["summary"].startswith("Widgets")
    assert state["issues"]["picks"][0]["number"] == 1
    # the fake repo has 1 issue, so exactly 1 pick is enforced by the schema
    assert llm.schemas[1] == issue_picks_schema(1)
    assert llm.schemas[1]["properties"]["picks"]["minItems"] == 1
    assert "issues" in state["timings"]


def test_graph_issues_only_skips_explainer():
    llm = FakeLLM(PICKS_ANSWER)
    state = run("acme/widgets", steps=["issues"], github=FakeGitHub(make_snapshot()), llm=llm, settings=SETTINGS)
    assert "explanation" not in state
    assert state["issues"]["picks"][0]["number"] == 1
    assert len(llm.prompts) == 1


def test_graph_explainer_failure_does_not_lose_issues():
    llm = FakeLLM("bad", "bad again", PICKS_ANSWER)
    state = run("acme/widgets", github=FakeGitHub(make_snapshot()), llm=llm, settings=SETTINGS)
    assert "explain_error" in state
    assert state["issues"]["picks"][0]["number"] == 1


def test_graph_no_issues_makes_no_model_call():
    llm = FakeLLM()
    state = run("acme/widgets", steps=["issues"], github=FakeGitHub(make_snapshot(issues=[])), llm=llm, settings=SETTINGS)
    assert llm.prompts == []
    assert state["issues"]["picks"] == []
    assert state["issues"]["ask_maintainer"]


def test_picker_schema_enforces_pick_count():
    schema = issue_picks_schema(3)
    assert schema["properties"]["picks"]["minItems"] == 3
    assert schema["properties"]["picks"]["maxItems"] == 3
    assert "minItems" not in issue_picks_schema.__globals__["ISSUE_PICKS_JSON_SCHEMA"]["properties"]["picks"]


def test_picker_prompt_states_exact_count():
    from goodfirst.prompts import picker_system_prompt

    assert "EXACTLY 2 different issues" in picker_system_prompt("english", 2)


def test_pick_evidence():
    out = check(picks((11, "w", "Edit docs/guide/intro.md"), (999, "w", "s"), (10, "w", "s")))
    statuses = {e["claim"].split(":")[0]: (e["status"], e["by"]) for e in out["evidence"]}
    assert statuses["Issue #999"] == ("removed", "model")
    assert statuses["Issue #11"] == ("verified", "model")
    assert ("flagged", "model") in statuses.values()       # the made-up docs/guide/intro.md
    assert ("verified", "goodfirst") in statuses.values()  # the ranking top-up
