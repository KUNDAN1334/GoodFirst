"""
Explain why a pull request's checks failed, with your local model.

    python scripts\\explain_ci.py https://github.com/owner/repo/pull/123
    python scripts\\explain_ci.py owner/repo#123 --lang hinglish
    python scripts\\explain_ci.py owner/repo#123 --show-prompt   # see the trimmed log the model reads
    python scripts\\explain_ci.py owner/repo#123 --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goodfirst.ci import build_ci_graph, ci_system_prompt, ci_user_prompt, fetch_ci  # noqa: E402
from goodfirst.config import get_settings  # noqa: E402
from goodfirst.github_client import GitHubClient, GitHubError  # noqa: E402
from goodfirst.llm import OllamaBackend  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain a failing pull request check, using a local model.")
    parser.add_argument("pr", help="pull request link, or owner/repo#123")
    parser.add_argument("--lang", choices=["english", "hinglish"], default="english")
    parser.add_argument("--show-prompt", action="store_true", help="print what the model would read, then exit")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(name)s: %(message)s")

    settings = get_settings()
    github = GitHubClient(settings)

    if args.show_prompt:
        try:
            snap = fetch_ci(github, args.pr)
        except GitHubError as exc:
            print(f"[FAIL] {exc}")
            return 1
        if not snap.failed:
            print("No failed checks. Notes: " + " ".join(snap.notes))
            return 0
        print("=== SYSTEM ===\n" + ci_system_prompt(args.lang) + "\n\n=== USER ===\n" + ci_user_prompt(snap, args.lang))
        return 0

    print(f"Model: {settings.ollama_model} (local). Reading the PR's checks...\n")
    state = build_ci_graph(github, OllamaBackend(settings), settings).invoke({"pr_input": args.pr, "language": args.lang})
    if state.get("error"):
        print(f"[FAIL] {state['error']}")
        return 1
    snap, result = state["snapshot"], state.get("result") or {}
    if args.json:
        print(json.dumps({"pr": snap.to_dict(), **result, "explain_error": state.get("explain_error"),
                          "timings": state.get("timings")}, indent=2, ensure_ascii=False))
        return 0

    print(f"== PR #{snap.number}: {snap.title} ({snap.owner}/{snap.repo}) ==")
    print(f"{snap.checks_total} checks, {len(snap.failed)} failed, {snap.checks_pending} still running")
    for c in snap.failed:
        print(f"  x {c.name} ({c.conclusion})  log: {c.log_status}  {c.url}")
    for n in snap.notes:
        print(f"  note: {n}")
    if state.get("explain_error"):
        print(f"\n[!] {state['explain_error']}")
    e = result.get("explanation")
    if e:
        print(f"\nWhat failed: {e['what_failed']}\nWhy: {e['why']}")
        print("\nFix:")
        for i, s in enumerate(e["fix_steps"], 1):
            print(f"  {i}. {s['text']}" + ("" if s["verified"] else "   <-- command not in the log, double-check"))
        if e["quoted_lines"]:
            print("\nFrom the log:")
            for q in e["quoted_lines"]:
                print(f"  > {q['text']}")
        print(f"\nCaused by this PR? Gemma says: {e['caused_by_this_pr']}")
    if result.get("linked_files"):
        print(f"Fact: the error mentions {', '.join(result['linked_files'])}, which this PR changes.")
    for w in result.get("warnings", []):
        print(f"  ! {w}")
    if result.get("confidence") is not None:
        print(f"\nConfidence: {round(result['confidence'] * 100)}%")
    if result.get("ask_comment"):
        print("\nReady-to-copy comment for the PR:\n  " + result["ask_comment"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
