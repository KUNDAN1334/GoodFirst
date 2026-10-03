"""
Phase 2 tests: schema repair, JSON retry, the honesty check, and the full
LangGraph pipeline. The model is always a scripted fake; no Ollama needed.
"""

from __future__ import annotations

import pytest

from goodfirst.config import load_settings
from goodfirst.github_client import RepoNotFoundError
from goodfirst.graph import run
from goodfirst.honesty import check_explanation, commands_in, resolve_path
from goodfirst.llm import LLMOutputError, ask_json, parse_json_object
from goodfirst.prompts import explainer_system_prompt, explainer_user_prompt, files_for_prompt
from goodfirst.schemas import RepoExplanation
from tests.fakes import GOOD_ANSWER, FakeGitHub, FakeLLM, make_snapshot

SETTINGS = load_settings({})


def explanation(**changes) -> RepoExplanation:
    return RepoExplanation.model_validate({**GOOD_ANSWER, **changes})


# ------------------------------------------------------------- schema repair


def test_schema_repairs_common_format_slips():
    expl = RepoExplanation.model_validate(
        {
            "summary": ["Line one.", "Line two."],
            "setup_steps": "Run `pytest`",
            "important_files": ["README.md", {"file": "setup.py", "reason": "packaging"}],
            "questions_for_maintainers": [{"q": "Where do I start?"}, ""],
            "confidence": "85%",
        }
    )
    assert expl.summary == "Line one. Line two."
    assert expl.setup_steps == ["Run `pytest`"]
    assert [f.path for f in expl.important_files] == ["README.md", "setup.py"]
    assert expl.important_files[1].why == "packaging"
    assert expl.questions_for_maintainers == ["Where do I start?"]
    assert expl.confidence == 0.85


@pytest.mark.parametrize("raw,expected", [(0.7, 0.7), (70, 0.7), ("0.7", 0.7), ("70%", 0.7), (-1, 0.0), (1.0, 1.0)])
def test_confidence_coercion(raw, expected):
    assert explanation(confidence=raw).confidence == pytest.approx(expected)


def test_missing_summary_is_rejected():
    with pytest.raises(Exception):
        RepoExplanation.model_validate({"confidence": 0.5})


def test_parse_json_tolerates_code_fences():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json_object("[1, 2]")


# ------------------------------------------------------------- retry once, then fail honestly


def test_ask_json_retries_once_then_succeeds():
    llm = FakeLLM("this is not json", GOOD_ANSWER)
    obj, stats = ask_json(llm, "sys", "user", RepoExplanation)
    assert obj.summary.startswith("Widgets")
    assert stats.attempts == 2
    assert stats.prompt_tokens == 2000  # both attempts are counted
    assert "NOT USABLE" in llm.prompts[1][1]  # the retry tells the model what went wrong


def test_ask_json_gives_up_after_two_failures():
    llm = FakeLLM("nope", '{"confidence": 0.9}')  # second one is JSON but has no summary
    with pytest.raises(LLMOutputError) as info:
        ask_json(llm, "sys", "user", RepoExplanation)
    assert "2 tries" in str(info.value)
    assert len(llm.prompts) == 2


def test_wrapped_answer_is_unwrapped():
    llm = FakeLLM({"response": GOOD_ANSWER})
    obj, stats = ask_json(llm, "sys", "user", RepoExplanation)
    assert obj.confidence == 0.85
    assert stats.attempts == 1


def test_failed_attempt_logs_raw_reply(caplog):
    llm = FakeLLM('{"answer": "Yeh project beginners ke liye hai"}', GOOD_ANSWER)
    with caplog.at_level("WARNING", logger="goodfirst.llm"):
        ask_json(llm, "sys", "user", RepoExplanation)
    assert "Yeh project beginners" in caplog.text


def test_json_schema_matches_pydantic_model():
    from goodfirst.schemas import EXPLAINER_JSON_SCHEMA

    assert set(EXPLAINER_JSON_SCHEMA["properties"]) == set(RepoExplanation.model_fields)
    assert set(EXPLAINER_JSON_SCHEMA["required"]) == set(RepoExplanation.model_fields)


def test_graph_sends_schema_to_model():
    from goodfirst.schemas import EXPLAINER_JSON_SCHEMA

    llm = FakeLLM(GOOD_ANSWER)
    run("acme/widgets", steps=["explain"], github=FakeGitHub(make_snapshot()), llm=llm, settings=SETTINGS)
    assert llm.schemas == [EXPLAINER_JSON_SCHEMA]


# ------------------------------------------------------------- honesty check: files


def test_honesty_drops_files_that_do_not_exist():
    expl = explanation(
        important_files=[
            {"path": "src/widgets.py", "why": "main code"},
            {"path": "src/magic_engine.py", "why": "invented"},
            {"path": "docs/ARCHITECTURE.md", "why": "invented"},
        ]
    )
    out = check_explanation(expl, make_snapshot(), SETTINGS)
    assert [f["path"] for f in out["important_files"]] == ["src/widgets.py"]
    assert any("Removed 2 files" in w and "src/magic_engine.py" in w for w in out["warnings"])
    # Two invented files cost 20% confidence.
    assert out["confidence"] == pytest.approx(0.65)
    assert out["model_confidence"] == 0.85


def test_honesty_accepts_harmless_path_variations():
    expl = explanation(
        important_files=[
            {"path": "./README.md", "why": ""},
            {"path": "readme.md", "why": "duplicate, different case"},
            {"path": "`widgets.py`", "why": "bare file name, unique in repo"},
            {"path": "src/", "why": "folder"},
        ]
    )
    out = check_explanation(expl, make_snapshot(), SETTINGS)
    assert [f["path"] for f in out["important_files"]] == ["README.md", "src/widgets.py", "src/"]
    assert out["important_files"][2]["url"] == "https://github.com/acme/widgets/tree/main/src"
    assert out["important_files"][0]["url"] == "https://github.com/acme/widgets/blob/main/README.md"
    assert out["warnings"] == []


def test_resolve_path_rejects_ambiguous_bare_names():
    paths = ["a/utils.py", "b/utils.py"]
    assert resolve_path("utils.py", paths) is None
    assert resolve_path("a/utils.py", paths) == "a/utils.py"


# ------------------------------------------------------------- honesty check: setup + confidence


def test_no_docs_removes_steps_caps_confidence_and_offers_question():
    snap = make_snapshot(readme=None, contributing=None)
    out = check_explanation(explanation(confidence=0.9), snap, SETTINGS)
    assert out["setup_steps"] == []
    assert out["confidence"] == 0.3
    assert out["low_confidence"] is True
    assert "acme/widgets" in out["ask_maintainer"]
    assert "how to set up the project locally" in out["ask_maintainer"]
    joined = " ".join(out["warnings"])
    assert "Removed 2 setup steps" in joined
    assert "Confidence capped at 30%" in joined


def test_readme_without_setup_section_also_removes_steps():
    snap = make_snapshot(readme="# Widgets\nA library that draws widgets.", contributing=None)
    out = check_explanation(explanation(), snap, SETTINGS)
    assert out["setup_steps"] == []
    assert any("Removed 2 setup steps" in w for w in out["warnings"])
    # README exists, so no 30% cap; the model's 0.85 stands.
    assert out["confidence"] == 0.85


def test_setup_commands_not_in_docs_are_flagged_not_hidden():
    expl = explanation(setup_steps=["Install with `pip install -e .`", "Start the server with `npm run dev`"])
    out = check_explanation(expl, make_snapshot(), SETTINGS)
    assert [s["verified"] for s in out["setup_steps"]] == [True, False]
    assert any("1 setup step contains a command" in w for w in out["warnings"])


def test_commands_in():
    assert commands_in("Run `pip install -e .` then `pytest`") == ["pip install -e .", "pytest"]
    assert commands_in("$ npm install") == ["npm install"]
    assert commands_in("Read the README first") == []
    # Real Gemma output: closing backtick missing.
    assert commands_in('Commit with `git commit -m "Add your-name"') == ['git commit -m "Add your-name"']


def test_unclosed_backtick_command_is_still_verified():
    expl = explanation(setup_steps=["Run tests with `pytest --fast-mode"])
    out = check_explanation(expl, make_snapshot(), SETTINGS)
    assert out["setup_steps"][0]["verified"] is False


def test_hinglish_requested_but_english_answer_is_flagged():
    english = check_explanation(explanation(), make_snapshot(), SETTINGS, language="hinglish")
    assert "You asked for Hinglish, but the model answered in English." in english["warnings"]

    hinglish = explanation(
        summary="Yeh ek chhota Python library hai jo widgets draw karti hai.",
        questions_for_maintainers=["Pehla contribution ke liye kaunsa part best hai?"],
    )
    out = check_explanation(hinglish, make_snapshot(), SETTINGS, language="hinglish")
    assert out["warnings"] == []
    # English mode never complains about language.
    assert check_explanation(explanation(), make_snapshot(), SETTINGS)["warnings"] == []


def test_hinglish_reminder_is_at_end_of_user_prompt():
    user = explainer_user_prompt(make_snapshot(), "hinglish")
    assert user.rstrip().endswith("Now return the JSON object.")
    assert "HINGLISH" in user[-600:]


def test_low_confidence_from_model_triggers_question():
    out = check_explanation(explanation(confidence=0.4), make_snapshot(), SETTINGS)
    assert out["low_confidence"] is True
    assert out["ask_maintainer"].startswith("Hi maintainers!")


def test_good_answer_passes_untouched():
    out = check_explanation(explanation(), make_snapshot(), SETTINGS)
    assert out["warnings"] == []
    assert out["low_confidence"] is False
    assert out["ask_maintainer"] is None
    assert all(s["verified"] for s in out["setup_steps"])


def test_confidence_floor_is_configurable():
    strict = load_settings({"CONFIDENCE_FLOOR": "0.9"})
    assert check_explanation(explanation(confidence=0.85), make_snapshot(), strict)["low_confidence"] is True


# ------------------------------------------------------------- prompts


def test_prompt_contains_docs_and_marks_missing_ones():
    text = explainer_user_prompt(make_snapshot(contributing=None))
    assert "Installation" in text
    assert "CONTRIBUTING GUIDE: NOT FOUND" in text
    assert "- src/" in text and "- src/widgets.py" in text


def test_hinglish_prompt():
    assert "Hinglish" in explainer_system_prompt("hinglish")
    assert "Hinglish" not in explainer_system_prompt("english")


def test_files_for_prompt_marks_folders_and_limits_size():
    paths = [f"pkg/mod{i}.py" for i in range(50)] + ["pkg/sub/x.py", "pkg", "pkg/sub"]
    snap = make_snapshot(top_level=[{"path": "pkg", "type": "dir"}], all_paths=paths)
    shown = files_for_prompt(snap)
    assert shown[0] == "pkg/"
    assert len(shown) == 6  # the folder + 5 entries inside it
    assert "pkg/sub/" not in shown[1:]  # files come before folders


# ------------------------------------------------------------- the whole graph


def test_graph_happy_path():
    llm = FakeLLM(GOOD_ANSWER)
    state = run("acme/widgets", "english", steps=["explain"], github=FakeGitHub(make_snapshot()), llm=llm, settings=SETTINGS)
    assert "error" not in state
    assert state["explanation"]["summary"].startswith("Widgets")
    assert state["timings"]["explain"]["attempts"] == 1
    assert "github_s" in state["timings"]


def test_graph_runs_honesty_check_on_model_output():
    bad = {**GOOD_ANSWER, "important_files": [{"path": "src/imaginary.py", "why": "x"}]}
    state = run("acme/widgets", steps=["explain"], github=FakeGitHub(make_snapshot()), llm=FakeLLM(bad), settings=SETTINGS)
    assert state["explanation"]["important_files"] == []
    assert any("src/imaginary.py" in w for w in state["explanation"]["warnings"])


def test_graph_stops_on_github_error_without_calling_model():
    llm = FakeLLM()
    state = run(
        "acme/nope",
        github=FakeGitHub(error=RepoNotFoundError("Couldn't find github.com/acme/nope.")),
        llm=llm,
        settings=SETTINGS,
    )
    assert state["error"].startswith("Couldn't find")
    assert "explanation" not in state
    assert llm.prompts == []


def test_graph_reports_model_failure_honestly():
    state = run("acme/widgets", steps=["explain"], github=FakeGitHub(make_snapshot()), llm=FakeLLM("x", "y"), settings=SETTINGS)
    assert "didn't return a usable answer" in state["explain_error"]
    assert "error" not in state  # not fatal: other steps could still run
    assert "explanation" not in state


def test_graph_passes_language_to_prompt():
    llm = FakeLLM(GOOD_ANSWER)
    run("acme/widgets", "hinglish", steps=["explain"], github=FakeGitHub(make_snapshot()), llm=llm, settings=SETTINGS)
    assert "Hinglish" in llm.prompts[0][0]


# ------------------------------------------------------------- evidence rows (for the UI + eval)


def test_evidence_records_sources_and_removals():
    expl = explanation(
        setup_steps=["Install with `pip install -e .`", "Run `npm run dev`", "Read the docs first"],
        important_files=[{"path": "src/widgets.py", "why": ""}, {"path": "src/ghost.py", "why": ""}],
    )
    ev = check_explanation(expl, make_snapshot(), SETTINGS)["evidence"]
    by_claim = {e["claim"]: e for e in ev}
    assert by_claim["Important file: src/widgets.py"]["status"] == "verified"
    assert by_claim["Important file: src/ghost.py"]["status"] == "removed"
    assert by_claim["Important file: src/ghost.py"]["reason"] == "File does not exist in the repo"
    assert by_claim["Setup step: Install with `pip install -e .`"]["status"] == "verified"
    assert by_claim["Setup step: Install with `pip install -e .`"]["source"] == "README.md"
    assert by_claim["Setup step: Run `npm run dev`"]["status"] == "flagged"
    assert by_claim["Setup step: Read the docs first"]["status"] == "unchecked"
    assert ev[0]["claim"].startswith("Summary:")


def test_evidence_shows_removed_setup_steps_without_docs():
    ev = check_explanation(explanation(), make_snapshot(readme=None, contributing=None), SETTINGS)["evidence"]
    removed = [e for e in ev if e["status"] == "removed"]
    assert len(removed) == 2
    assert all("guess" in e["reason"] for e in removed)


# ------------------------------------------------------------- the user's question


Q = "How do I run the tests?"


def test_answer_found_in_docs_and_checkable_is_verified():
    expl = explanation(answer="Run `pytest` after installing with `pip install -e .`.", answer_found_in_docs=True)
    out = check_explanation(expl, make_snapshot(), SETTINGS, question=Q)
    assert out["question"] == Q and out["answer_found"] is True
    row = next(e for e in out["evidence"] if e["claim"].startswith("Answer to"))
    assert row["status"] == "verified"
    assert out["ask_maintainer"] is None


def test_answer_not_in_docs_asks_maintainers_with_the_users_question():
    expl = explanation(answer="The docs don't say how to run the tests; ask the maintainers.", answer_found_in_docs=False)
    out = check_explanation(expl, make_snapshot(), SETTINGS, question=Q)
    assert out["answer_found"] is False
    assert out["ask_reason"] == "answer_not_found"
    assert '"How do I run the tests?"' in out["ask_maintainer"]
    assert any("don't clearly answer your question" in w for w in out["warnings"])


def test_answer_with_invented_file_or_command_is_flagged():
    expl = explanation(answer="Edit tests/conftest.py and run `make test-all`.", answer_found_in_docs=True)
    out = check_explanation(expl, make_snapshot(), SETTINGS, question=Q)
    assert out["answer_found"] is False                      # a failed check overrides the model's claim
    assert any("tests/conftest.py" in f for f in out["answer_flags"])
    assert any("make test-all" in f for f in out["answer_flags"])
    row = next(e for e in out["evidence"] if e["claim"].startswith("Answer to"))
    assert row["status"] == "flagged"
    assert out["ask_reason"] == "answer_not_found"


def test_empty_answer_to_a_question_counts_as_removed():
    out = check_explanation(explanation(answer="", answer_found_in_docs=True), make_snapshot(), SETTINGS, question=Q)
    row = next(e for e in out["evidence"] if e["claim"].startswith("Answer to"))
    assert row["status"] == "removed" and out["answer_found"] is False


def test_no_question_means_no_answer_section():
    out = check_explanation(explanation(answer="stray text", answer_found_in_docs=True), make_snapshot(), SETTINGS)
    assert out["question"] is None and out["answer"] is None and out["answer_found"] is None
    assert not any(e["claim"].startswith("Answer to") for e in out["evidence"])


def test_question_is_in_the_prompt_near_the_end():
    user = explainer_user_prompt(make_snapshot(), "english", Q)
    assert f"THE BEGINNER'S QUESTION: {Q}" in user[-400:]
    assert "(none; assume a complete beginner)" in explainer_user_prompt(make_snapshot())


def test_graph_passes_question_to_model_and_honesty_check():
    llm = FakeLLM({**GOOD_ANSWER, "answer": "Run `pytest`.", "answer_found_in_docs": True})
    state = run("acme/widgets", question=Q, steps=["explain"], github=FakeGitHub(make_snapshot()), llm=llm, settings=SETTINGS)
    assert Q in llm.prompts[0][1]
    assert state["explanation"]["answer"] == "Run `pytest`."
    assert state["explanation"]["answer_found"] is True
