"""
GoodFirst mini eval: run the full pipeline on a list of repos with your LOCAL model
and write a markdown table of what actually happened.

    python scripts\\eval.py                       # repos from eval\\repos.txt
    python scripts\\eval.py --question "I know Python. Where should I start?"   # the question asked for every repo
    python scripts\\eval.py --fresh               # ignore earlier results and start over

Outputs (rewritten after every repo, so an interrupted run keeps what it finished):
    eval/results.json   raw numbers per repo
    eval/results.md     the table for the blog post

Resuming: repos already in results.json are skipped, so if GitHub's rate limit
stops you halfway, wait (or add GITHUB_TOKEN to .env) and run the same command again.

Every number comes from a real run. Nothing is estimated or filled in: a repo that
failed is reported as failed, with the reason.

What the columns mean:
  Claims    things the model asserted that the honesty check could examine:
            the summary, each setup step, each important file, each issue pick
  Verified  checked against GitHub data and it held (a file exists, a command is
            written in the docs, an issue number is real)
  Flagged   kept, but part of it couldn't be verified (e.g. a command not in the docs)
  Removed   dropped by the honesty check (e.g. a file that doesn't exist)
  Answer    whether the question was answered from the docs (else GoodFirst asks the maintainers)
  The summary and paraphrased steps are "unchecked" (nothing concrete to verify),
  so Claims >= Verified + Flagged + Removed.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from goodfirst.config import get_settings  # noqa: E402
from goodfirst.github_client import GitHubClient, RateLimitError  # noqa: E402
from goodfirst.graph import build_graph  # noqa: E402
from goodfirst.llm import OllamaBackend  # noqa: E402

EVAL_DIR = ROOT / "eval"
DEFAULT_QUESTION = "I know Python and can write clear English. How do I set this up and where should I start?"


def load_repos(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [l.split("#", 1)[0].strip() for l in lines if l.split("#", 1)[0].strip()]


def count(evidence: list[dict], **match) -> int:
    return sum(1 for e in evidence if all(e.get(k) == v for k, v in match.items()))


def evaluate_one(graph, github: GitHubClient, repo: str, question: str, language: str) -> dict:
    start = time.perf_counter()
    try:
        state = graph.invoke({"repo_input": repo, "language": language, "question": question, "steps": ["explain", "issues"]})
    except RateLimitError:
        raise  # stop the whole run; resuming later is better than recording junk
    except Exception as exc:  # record, don't hide
        return {"repo": repo, "ok": False, "error": f"{type(exc).__name__}: {exc}", "runtime_s": round(time.perf_counter() - start, 1)}
    runtime = round(time.perf_counter() - start, 1)

    if state.get("error"):
        if "rate limit" in state["error"].lower():
            raise RateLimitError(state["error"])
        return {"repo": repo, "ok": False, "error": state["error"], "runtime_s": runtime}

    explanation = state.get("explanation") or {}
    issues = state.get("issues") or {}
    evidence = list(explanation.get("evidence", [])) + list(issues.get("evidence", []))
    model_ev = [e for e in evidence if e["by"] == "model"]
    timings = state.get("timings", {})
    snap = state["snapshot"]

    parts = []
    if explanation:
        parts.append(explanation["confidence"])
    if issues and issues.get("picks"):
        parts.append(issues["confidence"])

    return {
        "repo": snap.full_name,
        "ok": True,
        "claims": len(model_ev),
        "verified": count(model_ev, status="verified"),
        "unchecked": count(model_ev, status="unchecked"),
        "flagged": count(model_ev, status="flagged"),
        "removed": count(model_ev, status="removed"),
        "picks_from_ranking": count(evidence, by="goodfirst"),
        "explain_confidence": explanation.get("confidence"),
        "explain_model_confidence": explanation.get("model_confidence"),
        "issues_confidence": issues.get("confidence") if issues.get("picks") else None,
        "overall_confidence": round(min(parts), 2) if parts else None,
        "low_confidence": bool(parts) and min(parts) < get_settings().confidence_floor,
        "beginner_issues_found": len(snap.issues),
        "answer_found": explanation.get("answer_found"),
        "has_readme": snap.readme is not None,
        "has_contributing": snap.contributing is not None,
        "explain_error": state.get("explain_error"),
        "issues_error": state.get("issues_error"),
        "warnings": explanation.get("warnings", []) + issues.get("warnings", []),
        "removed_claims": [f"{e['claim']} ({e['reason']})" for e in model_ev if e["status"] == "removed"],
        "flagged_claims": [f"{e['claim']} ({e['reason']})" for e in model_ev if e["status"] == "flagged"],
        "runtime_s": runtime,
        "model_s": round(sum(t.get("wall_s", 0) for k, t in timings.items() if isinstance(t, dict)), 1),
        "attempts": {k: t.get("attempts") for k, t in timings.items() if isinstance(t, dict)},
    }


def answered(value) -> str:
    return "n/a" if value is None else ("yes" if value else "no, asked maintainers")


def pct(x) -> str:
    return "n/a" if x is None else f"{round(x * 100)}%"


def write_markdown(results: list[dict], meta: dict, path: Path) -> None:
    ok = [r for r in results if r["ok"]]
    lines = [
        "# GoodFirst mini eval",
        "",
        f"- Model: `{meta['model']}` via Ollama, running locally (num_ctx {meta['num_ctx']})",
        f"- Machine: {meta['machine']}",
        f"- Run: {meta['started']} to {meta['updated']}",
        f"- Question asked: \"{meta['question']}\", language: {meta['language']}",
        f"- Repos: {len(results)} attempted, {len(ok)} completed",
        "",
        "| Repo | Claims | Verified | Flagged | Removed | Question answered from docs | Confidence (repo / issues) | Beginner issues | Runtime |",
        "|---|---:|---:|---:|---:|---|---|---:|---:|",
    ]
    for r in results:
        if not r["ok"]:
            lines.append(f"| {r['repo']} | failed: {r['error'][:80]} | | | | | | | {r['runtime_s']:.0f} s |")
            continue
        conf = f"{pct(r['explain_confidence'])} / {pct(r['issues_confidence'])}"
        errs = []
        if r["explain_error"]:
            errs.append("explainer failed")
        if r["issues_error"]:
            errs.append("picker failed")
        note = f" ({', '.join(errs)})" if errs else ""
        lines.append(
            f"| {r['repo']}{note} | {r['claims']} | {r['verified']} | {r['flagged']} | {r['removed']} | "
            f"{answered(r.get('answer_found'))} | {conf} | {r['beginner_issues_found']} | {r['runtime_s']:.0f} s |"
        )
    if ok:
        claims = sum(r["claims"] for r in ok)
        removed = sum(r["removed"] for r in ok)
        flagged = sum(r["flagged"] for r in ok)
        verified = sum(r["verified"] for r in ok)
        runtimes = sorted(r["runtime_s"] for r in ok)
        median = runtimes[len(runtimes) // 2] if len(runtimes) % 2 else (runtimes[len(runtimes) // 2 - 1] + runtimes[len(runtimes) // 2]) / 2
        lines += [
            f"| **Total** | **{claims}** | **{verified}** | **{flagged}** | **{removed}** | "
            f"{sum(1 for r in ok if r.get('answer_found'))} of {len(ok)} | | | median {median:.0f} s |",
            "",
            f"The honesty check removed {removed} of {claims} claims "
            f"({round(100 * removed / claims) if claims else 0}%) and flagged {flagged} more "
            f"({round(100 * flagged / claims) if claims else 0}%).",
            f"{sum(1 for r in ok if r['low_confidence'])} of {len(ok)} repos ended below the "
            f"{pct(meta['floor'])} confidence line and got a ready-to-copy question for the maintainers.",
        ]
    removed_examples = [(r["repo"], c) for r in ok for c in r["removed_claims"]]
    if removed_examples:
        lines += ["", "## What the honesty check removed", ""]
        lines += [f"- `{repo}`: {claim}" for repo, claim in removed_examples]
    flagged_examples = [(r["repo"], c) for r in ok for c in r["flagged_claims"]]
    if flagged_examples:
        lines += ["", "## What it flagged", ""]
        lines += [f"- `{repo}`: {claim}" for repo, claim in flagged_examples]
    lines += [
        "",
        "## How to read this",
        "",
        "- **Claims**: things the model asserted that could be examined: the summary, each setup step, "
        "each important file, each issue pick.",
        "- **Verified**: checked against GitHub data and it held. **Flagged**: kept but not fully verifiable "
        "(e.g. a command not written in the docs). **Removed**: dropped (e.g. a file that doesn't exist, "
        "an issue number that isn't open).",
        "- The summary and paraphrased steps have nothing concrete to check, so they count as claims but "
        "not as verified, flagged or removed.",
        "- **Question answered from docs**: Gemma said the README/CONTRIBUTING answer the question "
        "and nothing in its answer failed a check. Otherwise GoodFirst writes a message asking the maintainers.",
        "- Confidence is after the honesty check. Runtime includes GitHub fetching (cached after the first run) "
        "and both model calls on CPU.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run GoodFirst on a list of repos and write a results table.")
    parser.add_argument("--repos", default=str(EVAL_DIR / "repos.txt"))
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="the question to ask about each repo")
    parser.add_argument("--lang", choices=["english", "hinglish"], default="english")
    parser.add_argument("--fresh", action="store_true", help="ignore earlier results")
    args = parser.parse_args()

    settings = get_settings()
    EVAL_DIR.mkdir(exist_ok=True)
    json_path, md_path = EVAL_DIR / "results.json", EVAL_DIR / "results.md"
    repos = load_repos(Path(args.repos))

    saved = {} if args.fresh or not json_path.exists() else json.loads(json_path.read_text(encoding="utf-8"))
    results: list[dict] = saved.get("results", [])
    meta = saved.get("meta") or {
        "model": settings.ollama_model,
        "num_ctx": settings.num_ctx,
        "machine": f"{platform.system()} {platform.release()}, {platform.processor() or platform.machine()}",
        "started": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "question": args.question,
        "language": args.lang,
        "floor": settings.confidence_floor,
    }
    # Resume: keep finished repos, retry failed ones (a failure may have been a network blip).
    results = [r for r in results if r["ok"]]
    done = {r["input"] for r in results}

    if not settings.github_token:
        print("Note: no GITHUB_TOKEN set. 10 repos need ~80 GitHub requests and the limit is 60/hour;")
        print("      if you hit it, just run this command again later and it will resume.\n")

    github = GitHubClient(settings)
    graph = build_graph(github, OllamaBackend(settings), settings)
    todo = [r for r in repos if r not in done]
    print(f"Model {settings.ollama_model}. {len(done)} repos already done, {len(todo)} to go.\n")

    for i, repo in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {repo} ...", flush=True)
        try:
            row = evaluate_one(graph, github, repo, args.question, args.lang)
        except RateLimitError as exc:
            print(f"\nStopped: {exc}\nRun the same command again later to resume.")
            break
        row["input"] = repo
        results.append(row)
        if row["ok"]:
            print(
                f"    {row['claims']} claims, {row['removed']} removed, {row['flagged']} flagged, "
                f"answered from docs: {answered(row.get('answer_found'))}, "
                f"confidence {pct(row['overall_confidence'])}, {row['runtime_s']:.0f} s"
            )
        else:
            print(f"    failed: {row['error']}")
        meta["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        json_path.write_text(json.dumps({"meta": meta, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
        write_markdown(results, meta, md_path)

    if results:
        meta.setdefault("updated", datetime.now().strftime("%Y-%m-%d %H:%M"))
        write_markdown(results, meta, md_path)
        print(f"\nWrote {md_path.relative_to(ROOT)} and {json_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
