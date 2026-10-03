"""
Run GoodFirst from the command line with your local Ollama model:
fetch -> explain -> pick_issues -> honesty_check.

    python scripts\\explain_repo.py owner/repo --question "I know Python. How do I run the tests?"
    python scripts\\explain_repo.py owner/repo --lang hinglish
    python scripts\\explain_repo.py owner/repo --only issues     # skip the explainer (faster)
    python scripts\\explain_repo.py owner/repo --only explain    # skip the issue picker
    python scripts\\explain_repo.py owner/repo --json            # full result as JSON
    python scripts\\explain_repo.py owner/repo --show-prompt     # print what the model reads, then exit
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goodfirst.config import get_settings  # noqa: E402
from goodfirst.github_client import GitHubClient, GitHubError  # noqa: E402
from goodfirst.graph import ALL_STEPS, run  # noqa: E402
from goodfirst.issues import candidates, rank_issues  # noqa: E402
from goodfirst.llm import OllamaBackend  # noqa: E402
from goodfirst.prompts import (  # noqa: E402
    explainer_system_prompt,
    explainer_user_prompt,
    picker_system_prompt,
    picker_user_prompt,
)


def pct(x: float) -> str:
    return f"{round(x * 100)}%"


def timing_line(name: str, t: dict | None) -> str:
    if not t:
        return f"  {name}: skipped"
    return (
        f"  {name}: {t['wall_s']} s (load {t['load_s']} s, read {t['prompt_tokens']} tokens in {t['prompt_s']} s, "
        f"wrote {t['output_tokens']} tokens in {t['output_s']} s, attempts {t['attempts']})"
    )


def print_explanation(result: dict) -> None:
    badge = "LOW CONFIDENCE" if result["low_confidence"] else "ok"
    print(f"--- About this repo ---   confidence {pct(result['confidence'])} [{badge}]")
    if result["confidence"] != result["model_confidence"]:
        print(f"   (the model said {pct(result['model_confidence'])}; the honesty check adjusted it)")
    if result.get("question"):
        found = "found in the docs" if result["answer_found"] else "NOT clearly in the docs"
        print(f"\nYour question: {result['question']}")
        print(f"Answer ({found}): {result['answer'] or '(none)'}")
        for flag in result.get("answer_flags", []):
            print(f"  ! {flag}")
    print(f"\n{result['summary']}\n")
    print("Setup steps:")
    for i, step in enumerate(result["setup_steps"], 1):
        flag = "" if step["verified"] else "   <-- not found word-for-word in the docs, double-check"
        print(f"  {i}. {step['text']}{flag}")
    if not result["setup_steps"]:
        print("  (none)")
    print("\nImportant files:")
    for f in result["important_files"]:
        print(f"  - {f['path']}: {f['why']}")
    if not result["important_files"]:
        print("  (none)")
    print("\nQuestions to ask the maintainers:")
    for q in result["questions_for_maintainers"]:
        print(f"  - {q}")
    if result["unsure_about"]:
        print("\nThe model wasn't sure about:")
        for u in result["unsure_about"]:
            print(f"  - {u}")
    for w in result["warnings"]:
        print(f"  ! {w}")
    if result["ask_maintainer"]:
        print("\nReady-to-copy question for the maintainers:\n  " + result["ask_maintainer"])


def print_issues(result: dict) -> None:
    badge = "LOW CONFIDENCE" if result["low_confidence"] else "ok"
    print(f"--- Good first issues for you ---   confidence {pct(result['confidence'])} [{badge}]")
    if result["message"]:
        print(f"\n{result['message']}")
    for n, p in enumerate(result["picks"], 1):
        by = "AI pick" if p["source"] == "model" else "GoodFirst ranking"
        print(f"\n{n}. #{p['number']} {p['title']}   [{by}]")
        print(f"   {p['url']}")
        print(f"   Facts: {'; '.join(p['facts'])}")
        print(f"   Why this one: {p['why_this_one']}")
        print(f"   Where to start: {p['where_to_start']}")
    if result["warnings"]:
        print()
    for w in result["warnings"]:
        print(f"  ! {w}")
    if result["ask_maintainer"]:
        print("\nReady-to-copy comment:\n  " + result["ask_maintainer"])


def main() -> int:
    parser = argparse.ArgumentParser(description="GoodFirst: help a beginner with a GitHub repo, using a local model.")
    parser.add_argument("repo", help="owner/repo or a github.com URL")
    parser.add_argument("--lang", choices=["english", "hinglish"], default="english")
    parser.add_argument("--question", default="", help="your question about the repo (optional)")
    parser.add_argument("--only", choices=list(ALL_STEPS), help="run just one model step")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("--show-prompt", action="store_true", help="print the prompts and exit (no model call)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log each model attempt")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(name)s: %(message)s")
    steps = [args.only] if args.only else list(ALL_STEPS)

    settings = get_settings()
    github = GitHubClient(settings)

    if args.show_prompt:
        try:
            snap = github.fetch_snapshot(args.repo)
        except GitHubError as exc:
            print(f"[FAIL] {exc}")
            return 1
        if "explain" in steps:
            s, u = explainer_system_prompt(args.lang), explainer_user_prompt(snap, args.lang, args.question)
            print("=== EXPLAINER SYSTEM ===\n" + s + "\n\n=== EXPLAINER USER ===\n" + u)
            print(f"[~{(len(s) + len(u)) // 4} tokens]\n")
        if "issues" in steps:
            pool = candidates(rank_issues(snap.issues, args.question))
            if pool:
                s, u = picker_system_prompt(args.lang, min(3, len(pool))), picker_user_prompt(snap, pool, args.question, args.lang)
                print("=== PICKER SYSTEM ===\n" + s + "\n\n=== PICKER USER ===\n" + u)
                print(f"[~{(len(s) + len(u)) // 4} tokens]")
            else:
                print("=== PICKER === (no open good-first issues, so the model would not be called)")
        return 0

    print(f"Model: {settings.ollama_model} (local, via Ollama). On a CPU this takes about a minute per step...\n")
    start = time.perf_counter()
    state = run(args.repo, args.lang, args.question, steps, github=github, llm=OllamaBackend(settings), settings=settings)
    total = time.perf_counter() - start

    if state.get("error"):
        print(f"[FAIL] {state['error']}")
        return 1

    if args.json:
        out = {k: state.get(k) for k in ("explanation", "issues", "explain_error", "issues_error", "timings")}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    print(f"== {state['snapshot'].full_name} ==\n")
    if state.get("explain_error"):
        print(f"--- About this repo ---\n[FAIL] {state['explain_error']}\n")
    elif "explanation" in state:
        print_explanation(state["explanation"])
        print()
    if state.get("issues_error"):
        print(f"[note] The issue picker model step failed: {state['issues_error']}")
    if "issues" in state:
        print_issues(state["issues"])

    t = state.get("timings", {})
    print(f"\nTime: {total:.0f} s total | GitHub {t.get('github_s', '?')} s")
    print(timing_line("explain", t.get("explain")))
    print(timing_line("issues ", t.get("issues")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
