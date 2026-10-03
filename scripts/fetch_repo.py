"""
Try the GitHub layer on a real repo, without any AI involved.

    python scripts\\fetch_repo.py firstcontributions/first-contributions
    python scripts\\fetch_repo.py https://github.com/owner/repo --json

Prints what GoodFirst would hand to the model: metadata, README/CONTRIBUTING
(after cleaning + truncation), top-level files, good-first-issues and notes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goodfirst.config import get_settings  # noqa: E402
from goodfirst.github_client import GitHubClient, GitHubError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a repo snapshot from GitHub (read-only).")
    parser.add_argument("repo", help="owner/repo or a github.com URL")
    parser.add_argument("--json", action="store_true", help="print the full snapshot as JSON")
    args = parser.parse_args()

    settings = get_settings()
    client = GitHubClient(settings)
    start = time.perf_counter()
    try:
        snap = client.fetch_snapshot(args.repo)
    except GitHubError as exc:
        print(f"[FAIL] {exc}")
        return 1
    elapsed = time.perf_counter() - start

    if args.json:
        print(json.dumps(snap.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print(f"{snap.full_name}  ({snap.stars} stars, {snap.language or 'unknown language'}, license: {snap.license})")
    print(f"  {snap.description or '(no description)'}")
    print(f"  fetched in {elapsed:.1f} s  |  token: {'yes' if settings.github_token else 'no'}")
    print()
    for label, doc in (("README", snap.readme), ("CONTRIBUTING", snap.contributing)):
        if doc:
            cut = f", cut from {doc.original_chars}" if doc.truncated else ""
            print(f"{label:13}: {doc.path} ({len(doc.text)} chars{cut})")
        else:
            print(f"{label:13}: not found")
    print(f"{'Files':13}: {len(snap.all_paths)} paths{' (partial list)' if snap.tree_truncated else ''}")
    print("Top level    : " + ", ".join(e["path"] + ("/" if e["type"] == "dir" else "") for e in snap.top_level[:30]))
    print()
    print(f"Good first issues (labels: {snap.issue_labels_used or 'none'}): {len(snap.issues)}")
    for issue in snap.issues:
        flags = []
        if issue.assigned:
            flags.append("assigned")
        flags.append(f"{issue.comments} comments")
        print(f"  #{issue.number:<6} {issue.title[:70]}  [{', '.join(flags)}]")
    if snap.notes:
        print("\nNotes:")
        for note in snap.notes:
            print(f"  - {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
