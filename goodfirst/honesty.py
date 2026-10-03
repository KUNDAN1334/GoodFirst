"""
The honesty layer: plain, deterministic Python that checks the model's answer
against what we actually fetched from GitHub. No AI here, so its decisions are
predictable, testable and easy to explain.

Principle: a wrong, confident answer is worse than "I'm not sure, ask the maintainer."

What it does to a Repo Explainer answer:
  1. Drops any "important file" that doesn't exist in the repo's file list.
  2. Removes setup steps if the repo has no CONTRIBUTING guide and no setup
     instructions in the README (they could only be guesses), and warns.
  3. Flags setup commands that don't appear word-for-word in the docs.
  4. Caps confidence when README and CONTRIBUTING are both missing, and lowers
     it when the model named files that don't exist.
  5. Marks the answer "low confidence" below CONFIDENCE_FLOOR and builds a
     polite, ready-to-copy question for the maintainers.

What it does to an Issue Picker answer (check_picks):
  1. Drops any issue number that isn't in the fetched good-first-issue list.
  2. Takes titles, links, labels and comment counts from GitHub data, never from the model.
  3. Flags files named in "where to start" that neither exist in the repo nor
     appear in the issue text.
  4. Tops up to 3 picks from the deterministic ranking (clearly labelled) if
     the model returned fewer valid picks, or failed entirely.
  5. Same confidence rules: penalty for invented numbers, low-confidence question.

Every change is recorded as a human-readable warning for the UI.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from goodfirst.config import Settings
from goodfirst.github_client import RepoSnapshot
from goodfirst.prompts import folder_paths
from goodfirst.issues import MIN_TOP_UP_SCORE
from goodfirst.schemas import MAX_PICKS, RepoExplanation

# Lower confidence by this much for each invented file, up to the maximum.
INVENTED_FILE_PENALTY = 0.1
MAX_INVENTED_PENALTY = 0.3

_SETUP_WORDS = re.compile(
    r"\b(install(ation|ing)?|set ?up|getting started|quick ?start|prerequisites|requirements|"
    r"development|build(ing)?|run(ning)? (the )?(tests?|locally|project))\b",
    re.IGNORECASE,
)
_COMMAND_START = re.compile(
    r"^(\$\s*)?(pip3?|python3?|py|npm|npx|yarn|pnpm|git|cd|make|cargo|go|docker|docker-compose|"
    r"poetry|uv|pipx|bundle|gem|mvn|gradle|\./\S+|dotnet|composer|flutter|deno|bun)\b"
)
_INLINE_CODE = re.compile(r"`([^`]+)`")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_path(raw: str) -> str:
    """Undo the usual ways a model decorates a path: `x`, "./x", "/x", "x/"."""
    path = raw.strip().strip("`'\"").strip()
    while path.startswith("./"):
        path = path[2:]
    return path.strip("/")


def has_setup_docs(snapshot: RepoSnapshot) -> bool:
    """True if we fetched any text that could contain setup instructions."""
    if snapshot.contributing is not None:
        return True
    return bool(snapshot.readme and _SETUP_WORDS.search(snapshot.readme.text))


def commands_in(step: str) -> list[str]:
    """
    Commands mentioned in a setup step: `inline code`, or the whole step if it is a
    bare command. An unclosed backtick (seen on a real run: `git commit -m "..." with
    no closing `) counts as code up to the end of the step, so it still gets checked.
    """
    found = [c.strip() for c in _INLINE_CODE.findall(step) if c.strip()]
    if step.count("`") % 2 == 1:
        tail = step[step.rindex("`") + 1:].strip()
        if tail:
            found.append(tail)
    if not found and _COMMAND_START.match(step.strip()):
        found = [step.strip()]
    return [c[1:].strip() if c.startswith("$") else c for c in found]


# Very common Hindi words in Roman script. If none of them appear, the answer
# is almost certainly plain English. A heuristic, so it only produces a warning.
_HINDI_WORDS = {
    # ("main" is left out on purpose: it is also the git branch name.)
    "hai", "hain", "ka", "ki", "ke", "ko", "se", "mein", "aur", "yeh", "ye", "woh", "kya",
    "kaise", "karo", "karna", "karein", "kar", "nahi", "nahin", "aap", "aapko", "apna", "apne", "hota",
    "hoti", "sakte", "sakta", "liye", "bhi", "toh", "jo", "par", "pehla", "pehle", "ek",
}


def looks_like_hinglish(texts: list[str]) -> bool:
    words = re.findall(r"[a-z]+", " ".join(texts).lower())
    hits = sum(1 for w in words if w in _HINDI_WORDS)
    return hits >= 3


def resolve_path(raw: str, all_paths: list[str]) -> str | None:
    """
    Map the model's path to a real path in the repo, or None if it doesn't exist.
    Accepts exact matches, case differences ("readme.md" -> "README.md") and a bare
    file name that matches exactly ONE file ("widgets.py" -> "src/widgets.py").
    """
    path = normalize_path(raw)
    if not path:
        return None
    if path in all_paths:
        return path
    lower = path.lower()
    by_lower = [p for p in all_paths if p.lower() == lower]
    if len(by_lower) == 1:
        return by_lower[0]
    if "/" not in path:
        same_name = [p for p in all_paths if p.rsplit("/", 1)[-1].lower() == lower]
        if len(same_name) == 1:
            return same_name[0]
    return None


def github_url(snapshot: RepoSnapshot, path: str, is_folder: bool) -> str:
    kind = "tree" if is_folder else "blob"
    return f"{snapshot.html_url}/{kind}/{quote(snapshot.default_branch, safe='')}/{quote(path)}"


def maintainer_question(
    snapshot: RepoSnapshot,
    setup_docs: bool,
    extra_points: list[str] | None = None,
    user_question: str = "",
) -> str:
    """
    A polite question the beginner can paste into a GitHub issue or discussion.
    Built from facts (what is missing), not by the model, and always in English
    because that's what most maintainers read.
    """
    points: list[str] = []
    if snapshot.readme is None:
        points.append("what the project does and who it is for")
    if not setup_docs:
        points.append("how to set up the project locally to run and test it")
    if snapshot.contributing is None:
        points.append("whether there are contribution guidelines I should follow")
    points.extend(extra_points or [])
    if not points:
        points.append("which part of the project is a good starting point for a newcomer")

    read = []
    if snapshot.readme:
        read.append("the README")
    if snapshot.contributing:
        read.append("the contributing guide")
    read_text = " and ".join(read) if read else "the repository files"

    if len(points) == 1:
        unsure = points[0]
    else:
        unsure = ", ".join(points[:-1]) + " and " + points[-1]
    if user_question.strip():
        # The user's own question, quoted as they wrote it, is the heart of the message.
        q = user_question.strip().rstrip("?") + "?"
        return (
            f"Hi maintainers! I'm new to open source and would love to make my first contribution to "
            f"{snapshot.full_name}. I've read {read_text}, but I couldn't find an answer to this: "
            f"\"{q}\" Could you point me in the right direction? Thank you for your time!"
        )
    return (
        f"Hi maintainers! I'm new to open source and would love to make my first contribution to "
        f"{snapshot.full_name}. I've read {read_text}, but I'm not sure about {unsure}. "
        f"Could you point me in the right direction? Thank you for your time!"
    )


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# File names worth checking in "where to start": something.ext with a code/docs extension.
_FILE_EXTS = (
    "py|js|jsx|ts|tsx|md|rst|txt|json|yml|yaml|toml|cfg|ini|html|css|scss|vue|svelte|"
    "rs|go|java|kt|rb|php|c|h|cpp|hpp|cs|sh|ps1|sql|lock|xml|gradle|swift|dart"
)
_FILE_MENTION = re.compile(rf"(?<![\w/.-])([\w-]+(?:/[\w.-]+)*\.(?:{_FILE_EXTS}))(?![\w])")


def file_mentions(text: str) -> list[str]:
    """File names mentioned in free text, e.g. 'open src/app.py and README.md'."""
    found: list[str] = []
    for m in _FILE_MENTION.finditer(text):
        name = m.group(1)
        if name not in found:
            found.append(name)
    return found


def issue_question(snapshot: RepoSnapshot, issue) -> str:
    """Polite, ready-to-copy comment for the top issue (English, built from facts)."""
    return (
        f"Hi! I'm new to open source and would like to work on this issue (#{issue.number}: "
        f"\"{issue.title}\") as my first contribution. Is it still available, and could you "
        f"point me to where in the code I should start? Thank you!"
    )


def no_issues_question(snapshot: RepoSnapshot) -> str:
    return (
        f"Hi maintainers! I'm new to open source and would love to make my first contribution to "
        f"{snapshot.full_name}. I couldn't find any open issues marked as good for newcomers. "
        f"Is there a small task you'd recommend for a first-time contributor? Thank you!"
    )


def check_picks(
    picks,                      # schemas.IssuePicks | None (None = the model was not asked)
    snapshot: RepoSnapshot,
    ranked: list,               # list[issues.RankedIssue], best first
    pool: list,                 # the candidates the model was shown
    settings: Settings,
    language: str = "english",
) -> dict:
    """
    Check the Issue Picker's answer against the issues we actually fetched.
    Titles, links, labels and comment counts always come from GitHub data,
    never from the model, so they can't be made up.
    """
    warnings: list[str] = []
    by_number = {r.issue.number: r for r in ranked}

    # No issues at all: nothing for the model to pick, and we say so plainly.
    if not ranked:
        return {
            "picks": [],
            "confidence": 0.0,
            "model_confidence": None,
            "low_confidence": True,
            "ask_maintainer": no_issues_question(snapshot),
            "warnings": [],
            "evidence": [],
            "message": "This repo has no open issues labelled for beginners right now.",
        }

    kept: list[dict] = []
    invented: list[int] = []
    evidence: list[dict] = []
    for pick in (picks.picks if picks else []):
        if pick.number not in by_number:
            invented.append(pick.number)
            evidence.append(_ev(f"Issue #{pick.number}", "Open good-first issues on GitHub", "removed",
                                reason="Not in this repo's open good-first-issue list"))
            continue
        if any(k["number"] == pick.number for k in kept) or len(kept) == MAX_PICKS:
            continue
        r = by_number[pick.number]
        # Files named in "where to start" must exist in the repo or be mentioned by the issue itself.
        issue_text = f"{r.issue.title} {r.issue.body}"
        unverified = [
            f for f in file_mentions(pick.where_to_start)
            if f not in issue_text and resolve_path(f, snapshot.all_paths) is None
        ]
        kept.append(_pick_entry(r, pick.why_this_one, pick.where_to_start, "model", unverified))
        evidence.append(_ev(f"Issue #{r.issue.number}: {r.issue.title}", f"Issue #{r.issue.number} on GitHub", "verified"))
        for f in unverified:
            evidence.append(_ev(f"Start at {f} (issue #{r.issue.number})", "File tree + issue text", "flagged",
                                reason="File isn't in the repo or the issue text"))

    if invented:
        warnings.append(
            f"Removed {_plural(len(invented), 'issue')} the model suggested that isn't in this repo's "
            f"open good-first-issue list: {', '.join('#' + str(n) for n in invented)}."
        )
    unverified_total = sum(len(k["unverified_files"]) for k in kept)
    if unverified_total:
        names = ", ".join(f for k in kept for f in k["unverified_files"])
        warnings.append(
            f"The 'where to start' advice mentions {_plural(unverified_total, 'file')} that doesn't exist in "
            f"the repo and isn't in the issue text: {names}. Check the issue before trusting that part."
        )

    # Top up from our own ranking if the model returned fewer valid picks than it should have.
    wanted = min(MAX_PICKS, len(pool))
    added = 0
    for r in pool:
        if len(kept) >= wanted:
            break
        if any(k["number"] == r.issue.number for k in kept) or r.score < MIN_TOP_UP_SCORE:
            continue
        kept.append(
            _pick_entry(
                r,
                "Picked by GoodFirst's ranking (not by the AI): " + "; ".join(r.reasons) + ".",
                "Read the issue and its comments, then comment to ask if you can take it.",
                "ranking",
                [],
            )
        )
        evidence.append(_ev(f"Issue #{r.issue.number}: {r.issue.title}", "GoodFirst ranking (GitHub data)",
                            "verified", by="goodfirst", reason="Added by GoodFirst, not chosen by the model"))
        added += 1
    if added and picks is None:
        warnings.append("The model couldn't pick issues this time, so these come only from GoodFirst's own ranking.")
    elif added:
        warnings.append(
            f"Added {_plural(added, 'issue')} from GoodFirst's own ranking because the model gave "
            f"fewer than {wanted} valid picks."
        )

    if language == "hinglish" and picks and picks.picks:
        model_text = [p.why_this_one for p in picks.picks] + [p.where_to_start for p in picks.picks]
        if not looks_like_hinglish(model_text):
            warnings.append("You asked for Hinglish, but the model answered in English.")

    model_conf = picks.confidence if picks else 0.0
    confidence = model_conf
    if invented:
        penalty = min(MAX_INVENTED_PENALTY, INVENTED_FILE_PENALTY * len(invented))
        confidence = max(0.0, confidence - penalty)
        warnings.append(f"Lowered confidence by {round(penalty * 100)}% because the model invented issue numbers.")
    confidence = round(confidence, 2)
    low = confidence < settings.confidence_floor

    return {
        "picks": kept,
        "confidence": confidence,
        "model_confidence": round(model_conf, 2) if picks else None,
        "low_confidence": low,
        "ask_maintainer": issue_question(snapshot, by_number[kept[0]["number"]].issue) if low and kept else None,
        "warnings": warnings,
        "evidence": evidence,
        "message": None,
    }


def _pick_entry(ranked_issue, why: str, where: str, source: str, unverified: list[str]) -> dict:
    i = ranked_issue.issue
    return {
        "number": i.number,
        "title": i.title,
        "url": i.url,
        "labels": i.labels,
        "comments": i.comments,
        "assigned": i.assigned,
        "why_this_one": why,
        "where_to_start": where,
        "facts": ranked_issue.reasons,       # from GitHub data, not from the model
        "source": source,                    # "model" or "ranking"
        "unverified_files": unverified,
    }


# ---------------------------------------------------------------------------
# The check itself
# ---------------------------------------------------------------------------


def _ev(claim: str, source: str, status: str, by: str = "model", reason: str | None = None) -> dict:
    """
    One evidence row for the UI's Evidence panel and the eval script.
    status: "verified"  - checked against fetched data and it holds
            "unchecked" - written by the model from the docs; nothing concrete to check
            "flagged"   - kept, but part of it couldn't be verified (see reason)
            "removed"   - dropped by the honesty check (see reason)
    by:     "model" for model claims, "goodfirst" for things GoodFirst added itself
    """
    return {"claim": claim, "source": source, "status": status, "by": by, "reason": reason}


def check_explanation(
    expl: RepoExplanation,
    snapshot: RepoSnapshot,
    settings: Settings,
    language: str = "english",
    question: str = "",
) -> dict:
    """
    Return the cleaned explanation as a plain dict for the UI, including
    `warnings`, `evidence`, `low_confidence` and (when low) `ask_maintainer`.
    """
    warnings: list[str] = []
    evidence: list[dict] = []
    doc_names = [d.path for d in (snapshot.readme, snapshot.contributing) if d is not None]

    # 0. Say so when the model ignored the language the user asked for.
    if language == "hinglish" and not looks_like_hinglish([expl.summary, *expl.questions_for_maintainers]):
        warnings.append("You asked for Hinglish, but the model answered in English.")
    confidence = expl.confidence
    folders = folder_paths(snapshot.all_paths)

    # The user's question comes first: was it answered from the docs, and does the answer hold up?
    question = question.strip()
    answer = expl.answer if question else ""
    answer_found = False
    answer_flags: list[str] = []
    if question:
        docs_text = _squash(" ".join(d.text for d in (snapshot.readme, snapshot.contributing) if d is not None))
        files = file_mentions(answer)
        missing_files = [f for f in files if resolve_path(f, snapshot.all_paths) is None]
        cmds = [c for c in _INLINE_CODE.findall(answer) if c.strip() and c not in files]
        missing_cmds = [c for c in cmds if _squash(c) not in docs_text and resolve_path(c, snapshot.all_paths) is None]
        if missing_files:
            answer_flags.append(f"Mentions {', '.join(missing_files)}, which doesn't exist in the repo")
        if missing_cmds:
            answer_flags.append(f"Mentions {', '.join(missing_cmds)}, which isn't written in the docs")
        answer_found = bool(answer) and expl.answer_found_in_docs and not answer_flags
        if not answer:
            status, reason = "removed", "Gemma gave no answer"
        elif answer_flags:
            status, reason = "flagged", "; ".join(answer_flags)
        elif not expl.answer_found_in_docs:
            status, reason = "unchecked", "Gemma says the docs don't answer this"
        elif files or cmds:
            status, reason = "verified", None
        else:
            status, reason = "unchecked", "Based on the docs; nothing concrete to check"
        evidence.append(
            _ev(f"Answer to \"{question}\": {answer or '(none)'}",
                " + ".join(doc_names) if doc_names else "No docs found", status, reason=reason)
        )
        if answer_flags:
            warnings.append("Part of the answer to your question couldn't be verified: " + "; ".join(answer_flags) + ".")
        if not answer_found:
            warnings.append(
                "The docs don't clearly answer your question, so the message for the maintainers asks it for you."
            )

    evidence.append(
        _ev(
            "Summary: " + expl.summary,
            " + ".join(doc_names) if doc_names else "Repo description and file names only",
            "unchecked",
            reason=None if doc_names else "No README or CONTRIBUTING to base this on",
        )
    )

    # 1. Important files must exist in the fetched file list.
    kept_files: list[dict] = []
    invented: list[str] = []
    seen: set[str] = set()
    for item in expl.important_files:
        real = resolve_path(item.path, snapshot.all_paths)
        if real is None:
            invented.append(item.path)
            evidence.append(_ev(f"Important file: {item.path}", "File tree", "removed",
                                reason="File does not exist in the repo"))
            continue
        if real in seen:
            continue
        seen.add(real)
        shown = real + ("/" if real in folders else "")
        kept_files.append({"path": shown, "why": item.why, "url": github_url(snapshot, real, real in folders)})
        evidence.append(_ev(f"Important file: {shown}", "File tree", "verified"))
    if invented:
        msg = (
            f"Removed {_plural(len(invented), 'file')} that the model mentioned but that "
            f"doesn't exist in this repo: {', '.join(invented)}."
        )
        if snapshot.tree_truncated:
            msg += " (This repo is very large, so GitHub only listed part of its files.)"
        warnings.append(msg)
        penalty = min(MAX_INVENTED_PENALTY, INVENTED_FILE_PENALTY * len(invented))
        confidence = max(0.0, confidence - penalty)
        warnings.append(f"Lowered confidence by {round(penalty * 100)}% because the model invented file names.")

    # 2 + 3. Setup steps only when there are docs to take them from.
    setup_docs = has_setup_docs(snapshot)
    steps: list[dict] = []
    if not setup_docs:
        for step in expl.setup_steps:
            evidence.append(_ev(f"Setup step: {step}", "No setup docs found", "removed",
                                reason="No CONTRIBUTING guide or setup section, so this would be a guess"))
        if expl.setup_steps:
            warnings.append(
                f"Removed {_plural(len(expl.setup_steps), 'setup step')}: this repo has no CONTRIBUTING guide "
                "and no setup instructions in its README, so the steps would only be guesses."
            )
        warnings.append("No setup instructions were found. Ask the maintainers how to run the project locally.")
    else:
        docs_by_name = {
            d.path: _squash(d.text) for d in (snapshot.readme, snapshot.contributing) if d is not None
        }
        all_docs = " ".join(docs_by_name.values())
        unverified = 0
        for step in expl.setup_steps:
            cmds = commands_in(step)
            ok = all(_squash(c) in all_docs for c in cmds)
            steps.append({"text": step, "verified": ok})
            if not cmds:
                evidence.append(_ev(f"Setup step: {step}", " + ".join(doc_names), "unchecked",
                                    reason="Paraphrased from the docs; no command to check"))
            elif ok:
                found_in = [name for name, text in docs_by_name.items() if all(_squash(c) in text for c in cmds)]
                evidence.append(_ev(f"Setup step: {step}", " + ".join(found_in or doc_names), "verified"))
            else:
                unverified += 1
                evidence.append(_ev(f"Setup step: {step}", " + ".join(doc_names), "flagged",
                                    reason="Command not found word-for-word in the docs"))
        if unverified:
            verb = "contains" if unverified == 1 else "contain"
            warnings.append(
                f"{_plural(unverified, 'setup step')} {verb} a command that isn't written word-for-word in "
                "the README/CONTRIBUTING. Double-check before running it."
            )

    # 4. No docs at all => the model is mostly guessing from file names.
    if snapshot.readme is None and snapshot.contributing is None:
        cap = settings.no_docs_confidence_cap
        if confidence > cap:
            confidence = cap
            warnings.append(
                f"Confidence capped at {round(cap * 100)}% because this repo has no README and no CONTRIBUTING guide."
            )

    # 5. Low confidence => offer a ready-made question for the maintainers.
    confidence = round(confidence, 2)
    low = confidence < settings.confidence_floor

    if question and not answer_found:
        ask, ask_reason = maintainer_question(snapshot, setup_docs, user_question=question), "answer_not_found"
    elif low:
        ask, ask_reason = maintainer_question(snapshot, setup_docs), "low_confidence"
    else:
        ask, ask_reason = None, None

    return {
        "question": question or None,
        "answer": answer or None,
        "answer_found": answer_found if question else None,
        "answer_flags": answer_flags,
        "summary": expl.summary,
        "setup_steps": steps,
        "important_files": kept_files,
        "questions_for_maintainers": expl.questions_for_maintainers,
        "unsure_about": expl.unsure_about,
        "confidence": confidence,
        "model_confidence": round(expl.confidence, 2),
        "low_confidence": low,
        "ask_maintainer": ask,
        "ask_reason": ask_reason,
        "warnings": warnings,
        "evidence": evidence,
    }
