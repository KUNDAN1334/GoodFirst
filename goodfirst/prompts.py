"""
Prompts for the local model, and the code that packs a RepoSnapshot into a
compact text block the model can read.

Guidelines that work well with small (~4B) models:
- One job per prompt, stated first.
- Say exactly which JSON keys to return, with a tiny example of the shape.
- Ground the model: "use ONLY the text below", "choose paths ONLY from this list".
- Give it an explicit, respectable way out ("unsure_about", low confidence),
  so it doesn't have to invent things to look helpful.
"""

from __future__ import annotations

from goodfirst.github_client import RepoSnapshot

LANGUAGE_RULES = {
    "english": "Write every text value in simple, friendly English for a beginner.",
    "hinglish": (
        "Write every text value in Hinglish: casual Hindi written in English letters, mixed with "
        "English, the way Indian college students chat (e.g. 'Yeh project ek tool hai jo...'). "
        "Keep file names, commands and technical terms exactly in English."
    ),
}


EXPLAINER_SYSTEM = """You help a complete beginner understand a GitHub repository before their first open-source contribution.

Use ONLY the repository information given by the user. Never use outside knowledge about this project. Never invent files, commands, URLs or steps.
Being honest matters more than sounding confident. If something is not in the text, say so in "unsure_about" and lower your confidence.

{language_rule}

The beginner may ask ONE question about the repo. If they did, answering it is your most important job,
and the rest of your answer should help with that question (for example, pick files related to it).

Return ONLY one JSON object with exactly these keys:
{{
  "answer": "2-4 short sentences answering the beginner's question, or \"\" if they asked none",
  "answer_found_in_docs": true,
  "summary": "2-3 short sentences: what this project does and who it is for",
  "setup_steps": ["one short step from README/CONTRIBUTING, with its command in backticks"],
  "important_files": [{{"path": "exact path from the FILES list", "why": "one short reason"}}],
  "questions_for_maintainers": ["a polite question the beginner could ask the maintainers"],
  "unsure_about": ["something you could not find in the text"],
  "confidence": 0.0
}}

Rules:
- Be brief. Every word takes time to write on this computer.
- answer: use ONLY the README, CONTRIBUTING and file list. If they don't contain the answer, say so plainly (for example "The docs don't say how to ...; ask the maintainers") and set answer_found_in_docs to false. Never guess. With no question, return "" and false.
- setup_steps: at most 5, each under 20 words. ONLY steps written in the README or CONTRIBUTING; copy commands exactly. If none are written, return [].
- important_files: 2 to 5 entries, each "path" copied exactly from the FILES list.
- questions_for_maintainers: 1 to 3. unsure_about: 0 to 3.
- confidence: a number from 0 to 1. Use 0.8 or more only if the README clearly explains the project and its setup. Use 0.5 or less if the docs are short, missing or unclear."""


def explainer_system_prompt(language: str) -> str:
    rule = LANGUAGE_RULES.get(language, LANGUAGE_RULES["english"])
    return EXPLAINER_SYSTEM.format(language_rule=rule)


def files_for_prompt(snapshot: RepoSnapshot, limit: int = 60) -> list[str]:
    """
    A short, representative list of paths: everything at the top level, then a
    few entries inside each top-level folder. Directories get a trailing '/'.
    The full list is far too long for a small model (Streamlit has 10,000+ paths).
    """
    folders = folder_paths(snapshot.all_paths)
    shown = [e["path"] + ("/" if e["type"] == "dir" else "") for e in snapshot.top_level]
    per_folder = 5
    for top in sorted(e["path"] for e in snapshot.top_level if e["type"] == "dir"):
        children = [p for p in snapshot.all_paths if p.startswith(top + "/") and p.count("/") == 1]
        # Files before folders, then alphabetical: a file name tells a beginner more.
        children.sort(key=lambda p: (p in folders, p.lower()))
        shown.extend(c + ("/" if c in folders else "") for c in children[:per_folder])
    return shown[:limit]


def folder_paths(all_paths: list[str]) -> set[str]:
    """Every path that has something inside it, i.e. is a folder."""
    folders: set[str] = set()
    for path in all_paths:
        parts = path.split("/")
        for i in range(1, len(parts)):
            folders.add("/".join(parts[:i]))
    return folders


def repo_context(snapshot: RepoSnapshot) -> str:
    """The repository facts block shared by the explainer (and later the issue picker)."""
    lines = [
        f"REPOSITORY: {snapshot.full_name}",
        f"DESCRIPTION: {snapshot.description or '(none)'}",
        f"MAIN LANGUAGE: {snapshot.language or 'unknown'}",
    ]
    if snapshot.topics:
        lines.append(f"TOPICS: {', '.join(snapshot.topics[:10])}")
    if snapshot.archived:
        lines.append("NOTE: this repository is ARCHIVED (read-only).")
    lines.append("")
    lines.append("FILES (partial list; folders end with /):")
    lines.extend(f"- {p}" for p in files_for_prompt(snapshot))
    lines.append("")
    if snapshot.readme:
        cut = " (shortened)" if snapshot.readme.truncated else ""
        lines += [f"README ({snapshot.readme.path}){cut}:", "<<<", snapshot.readme.text, ">>>", ""]
    else:
        lines += ["README: NOT FOUND", ""]
    if snapshot.contributing:
        cut = " (shortened)" if snapshot.contributing.truncated else ""
        lines += [f"CONTRIBUTING ({snapshot.contributing.path}){cut}:", "<<<", snapshot.contributing.text, ">>>", ""]
    else:
        lines += ["CONTRIBUTING GUIDE: NOT FOUND", ""]
    return "\n".join(lines)


PICKER_SYSTEM = """You help a complete beginner choose their FIRST open-source issue.

You get a short list of REAL open issues (already filtered by code) and, sometimes, a question from the beginner
that tells you what they know or want to work on.
Choose the best issues for this beginner. Use ONLY the issue text given. Never invent issue numbers, file names or details.

{language_rule}

Return ONLY one JSON object with {n_picks} picks:
{{
  "picks": [
    {{"number": <issue number>, "why_this_one": "...", "where_to_start": "..."}},
    {{"number": <another issue number>, "why_this_one": "...", "where_to_start": "..."}},
    {{"number": <another issue number>, "why_this_one": "...", "where_to_start": "..."}}
  ],
  "confidence": 0.0
}}

Rules:
- Be brief. Every word takes time to write on this computer.
- picks: EXACTLY {n_picks} different issues, best first. Each "number" must be one of the given issue numbers.
- why_this_one: ONE short sentence. If the beginner asked something, connect the issue to their question.
- where_to_start: ONE or TWO short sentences: the first concrete thing to look at. Mention a file only if the issue text mentions it. If the issue text doesn't say, tell them to comment on the issue and ask.
- confidence: 0 to 1, how sure you are these suit this beginner. Lower it if the descriptions are vague."""


def picker_system_prompt(language: str, n_picks: int = 3) -> str:
    rule = LANGUAGE_RULES.get(language, LANGUAGE_RULES["english"])
    return PICKER_SYSTEM.format(language_rule=rule, n_picks=n_picks)


def question_line(question: str) -> str:
    q = question.strip()
    return f"THE BEGINNER'S QUESTION: {q}" if q else "THE BEGINNER'S QUESTION: (none; assume a complete beginner)"


def picker_user_prompt(snapshot: RepoSnapshot, ranked_candidates: list, question: str, language: str = "english") -> str:
    """`ranked_candidates` is a list of goodfirst.issues.RankedIssue (best first)."""
    lines = [
        f"REPOSITORY: {snapshot.full_name} ({snapshot.language or 'unknown language'})",
        f"DESCRIPTION: {snapshot.description or '(none)'}",
        "",
        question_line(question),
        "",
        "ISSUES:",
    ]
    for r in ranked_candidates:
        i = r.issue
        lines += [
            f"#{i.number}: {i.title}",
            f"  labels: {', '.join(i.labels) or 'none'} | comments: {i.comments} | assigned: {'yes' if i.assigned else 'no'}",
            "  description: <<<" + (i.body.strip() or "(empty)") + ">>>",
            "",
        ]
    reminder = LANGUAGE_REMINDERS.get(language, LANGUAGE_REMINDERS["english"])
    return "\n".join(lines) + f"\n{reminder}\nNow return the JSON object."


# Repeated at the END of the user prompt: small models follow the most recent
# instruction best, and on a real run Gemma 3 4B ignored a Hinglish rule that
# appeared only in the system prompt.
LANGUAGE_REMINDERS = {
    "english": "LANGUAGE: write all text values in simple English.",
    "hinglish": (
        # The example is deliberately about NO particular project: an earlier example happened
        # to describe first-contributions, and Gemma copied it word-for-word into its summary.
        "LANGUAGE: write all text values in HINGLISH, not in pure English. Only copy the STYLE of "
        "this example, never its words: \"Pehle yeh file kholo, phir test run karo. Agar error aaye "
        "toh tension mat lo.\" Keep commands and file names in English."
    ),
}


def explainer_user_prompt(snapshot: RepoSnapshot, language: str = "english", question: str = "") -> str:
    reminder = LANGUAGE_REMINDERS.get(language, LANGUAGE_REMINDERS["english"])
    # The question goes near the END, right before the instructions, where a small model attends most.
    return repo_context(snapshot) + f"\n{question_line(question)}\n{reminder}\nNow return the JSON object."
