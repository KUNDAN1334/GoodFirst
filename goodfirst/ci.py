"""
PR CI Explainer: "my pull request's checks are red, what broke?"

Same design as the rest of GoodFirst:
  fetch_ci (code, read-only GitHub)  ->  explain_ci (local model, strict JSON)  ->  ci_honesty (plain Python)

What we fetch for one pull request (all GET requests):
  GET /repos/{o}/{r}/pulls/{n}                       -> title, head commit
  GET /repos/{o}/{r}/commits/{sha}/check-runs        -> which checks failed
  GET /repos/{o}/{r}/check-runs/{id}/annotations     -> structured error messages (public, no token needed)
  GET /repos/{o}/{r}/actions/jobs/{id}/logs          -> raw log text (some repos need a GITHUB_TOKEN for this)
  GET /repos/{o}/{r}/pulls/{n}/files                 -> files the PR changes
  GET /repos/{o}/{r}/git/trees/{sha}?recursive=1     -> every file at the PR's commit (for the honesty check)

A CI log can be tens of thousands of lines, far too much for a small model, so code
cuts it down to the part around the last error before the model sees anything.

The honesty check then makes sure that:
  - every log line the model quotes really is in the log,
  - every file it names exists (or appears in the log),
  - commands in its fix steps are flagged if they appear nowhere in the log,
  - "was it my change?" is cross-checked with a fact we compute ourselves:
    does the error mention a file that this PR changed?
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, TypedDict

from pydantic import BaseModel, Field, field_validator
from langgraph.graph import END, START, StateGraph

from goodfirst.config import Settings
from goodfirst.github_client import GitHubClient, GitHubError, InvalidRepoError
from goodfirst.honesty import (
    INVENTED_FILE_PENALTY,
    MAX_INVENTED_PENALTY,
    _squash,
    commands_in,
    looks_like_hinglish,
    resolve_path,
)
from goodfirst.llm import ChatBackend, LLMOutputError, LLMUnavailableError, ask_json
from goodfirst.prompts import LANGUAGE_REMINDERS, LANGUAGE_RULES
from goodfirst.schemas import _as_confidence, _text_list

MAX_EXCERPT_CHARS = 3500
MAX_FAILED_CHECKS = 3
FAILED_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}


class PullNotFoundError(GitHubError):
    """404 on the pull request."""


# ---------------------------------------------------------------------------
# Parsing the PR link
# ---------------------------------------------------------------------------

_PR_URL = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)")
_PR_SHORT = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:#|/pull/)(\d+)$")


def parse_pr(text: str) -> tuple[str, str, int]:
    """Accepts https://github.com/owner/repo/pull/123, owner/repo#123 or owner/repo/pull/123."""
    raw = (text or "").strip().rstrip("/")
    match = _PR_URL.search(raw) or _PR_SHORT.match(raw)
    if not match:
        raise InvalidRepoError("Paste a pull request link, like https://github.com/owner/repo/pull/123.")
    owner, repo, number = match.groups()
    return owner, repo, int(number)


# ---------------------------------------------------------------------------
# Cutting a CI log down to what matters
# ---------------------------------------------------------------------------

_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z ?")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_ERROR_LINE = re.compile(
    r"##\[error\]|\berror\b|\bERROR\b|\bFAILED\b|\bFAIL\b|Traceback|Exception|AssertionError|"
    r"npm ERR!|\bfailed\b|exit code [1-9]|Process completed with exit code",
    re.IGNORECASE,
)


def clean_log(raw: str) -> list[str]:
    """Strip GitHub's timestamps and terminal colour codes; drop empty lines."""
    lines = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        line = _ANSI.sub("", _TIMESTAMP.sub("", line)).rstrip()
        if line.strip():
            lines.append(line)
    return lines


def extract_excerpt(raw: str, max_chars: int = MAX_EXCERPT_CHARS, before: int = 40, after: int = 8) -> str:
    """
    The part of the log around the LAST error (the one that usually stopped the job),
    plus any '##[error]' lines from elsewhere. If nothing looks like an error, the tail.
    Long excerpts keep their END, because that's where the failure is.
    """
    lines = clean_log(raw)
    if not lines:
        return ""
    hits = [i for i, line in enumerate(lines) if _ERROR_LINE.search(line)]
    # Ignore the generic final line if there's a more specific error before it.
    specific = [i for i in hits if "Process completed with exit code" not in lines[i]]
    anchor = (specific or hits or [len(lines) - 1])[-1]
    window = lines[max(0, anchor - before): anchor + after + 1]
    extra = [l for i, l in enumerate(lines) if "##[error]" in l and not (anchor - before <= i <= anchor + after)]
    text = "\n".join(extra[-5:] + (["..."] if extra else []) + window)
    if len(text) > max_chars:
        text = "[... earlier lines cut by GoodFirst ...]\n" + text[-max_chars:]
    return text


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class FailedCheck:
    name: str
    conclusion: str
    url: str
    check_id: int
    is_actions: bool
    annotations: list[str] = field(default_factory=list)
    log_excerpt: str | None = None
    log_status: str = "not_fetched"  # "ok", "needs_token", "missing", "not_actions", "not_fetched"


@dataclass
class CISnapshot:
    owner: str
    repo: str
    number: int
    title: str
    url: str
    head_sha: str
    state: str
    checks_total: int
    checks_pending: int
    failed: list[FailedCheck]
    changed_files: list[str]
    all_paths: list[str]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("all_paths")
        return d


def fetch_ci(github: GitHubClient, pr_input: str) -> CISnapshot:
    owner, repo, number = parse_pr(pr_input)
    base = github._repo_path(owner, repo)

    status, pull = github._get(f"{base}/pulls/{number}")
    if status != 200:
        raise PullNotFoundError(f"Couldn't find pull request #{number} in {owner}/{repo}. Check the link.")
    sha = pull["head"]["sha"]
    notes: list[str] = []

    _, runs = github._get(f"{base}/commits/{sha}/check-runs", params={"per_page": "100"})
    runs = (runs or {}).get("check_runs", [])
    pending = sum(1 for r in runs if r.get("status") != "completed")
    failed_runs = [r for r in runs if r.get("conclusion") in FAILED_CONCLUSIONS]

    failed: list[FailedCheck] = []
    for run in failed_runs[:MAX_FAILED_CHECKS]:
        is_actions = (run.get("app") or {}).get("slug") == "github-actions"
        check = FailedCheck(
            name=run.get("name", "unnamed check"),
            conclusion=run.get("conclusion", ""),
            url=run.get("html_url", ""),
            check_id=int(run["id"]),
            is_actions=is_actions,
        )
        _, annotations = github._get(f"{base}/check-runs/{check.check_id}/annotations", params={"per_page": "50"})
        for a in annotations or []:
            if a.get("annotation_level") in ("failure", "warning"):
                where = f"{a.get('path')}:{a.get('start_line')} " if a.get("path") and a.get("path") != ".github" else ""
                check.annotations.append(f"{where}{(a.get('message') or '').strip()}"[:400])
        check.annotations = check.annotations[:10]
        if is_actions:
            # For GitHub Actions, the check run id is the job id. Some repos only serve logs to signed-in users.
            log_status, log_text = github._get(f"{base}/actions/jobs/{check.check_id}/logs", as_text=True, soft=(403, 404, 410))
            if log_status == 200 and log_text:
                check.log_excerpt = extract_excerpt(log_text)
                check.log_status = "ok"
            else:
                check.log_status = "needs_token" if log_status == 403 else "missing"
        else:
            check.log_status = "not_actions"
        failed.append(check)

    _, files = github._get(f"{base}/pulls/{number}/files", params={"per_page": "100"})
    changed = [f.get("filename", "") for f in files or [] if f.get("filename")]
    _, all_paths, _ = github.fetch_tree(owner, repo, sha)

    if not runs:
        notes.append("This pull request has no checks yet.")
    elif not failed_runs:
        notes.append("No failed checks." + (f" {pending} still running." if pending else ""))
    if len(failed_runs) > MAX_FAILED_CHECKS:
        notes.append(f"{len(failed_runs)} checks failed; GoodFirst looked at the first {MAX_FAILED_CHECKS}.")
    if any(c.log_status == "needs_token" for c in failed):
        notes.append("GitHub only shares these logs with signed-in users. Add a GITHUB_TOKEN to .env to read them.")
    if github.offline_since:
        notes.append("GitHub couldn't be reached, so GoodFirst used saved data. The checks may have changed since.")

    return CISnapshot(
        owner=owner,
        repo=repo,
        number=number,
        title=pull.get("title", ""),
        url=pull.get("html_url", f"https://github.com/{owner}/{repo}/pull/{number}"),
        head_sha=sha,
        state="merged" if pull.get("merged") else pull.get("state", ""),
        checks_total=len(runs),
        checks_pending=pending,
        failed=failed,
        changed_files=changed,
        all_paths=all_paths,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# What the model returns
# ---------------------------------------------------------------------------

CI_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "what_failed": {"type": "string"},
        "why": {"type": "string"},
        "fix_steps": {"type": "array", "items": {"type": "string"}},
        "quoted_lines": {"type": "array", "items": {"type": "string"}},
        "files": {"type": "array", "items": {"type": "string"}},
        "caused_by_this_pr": {"type": "string", "enum": ["yes", "no", "unsure"]},
        "confidence": {"type": "number"},
    },
    "required": ["what_failed", "why", "fix_steps", "quoted_lines", "files", "caused_by_this_pr", "confidence"],
}


class CIExplanation(BaseModel):
    what_failed: str = Field(min_length=1)
    why: str = ""
    fix_steps: list[str] = Field(default_factory=list)
    quoted_lines: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    caused_by_this_pr: str = "unsure"
    confidence: float

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        return _as_confidence(v)

    @field_validator("fix_steps", "files", mode="before")
    @classmethod
    def _lists(cls, v):
        return _text_list(v, 6)

    @field_validator("quoted_lines", mode="before")
    @classmethod
    def _quotes(cls, v):
        return _text_list(v, 4)

    @field_validator("caused_by_this_pr", mode="before")
    @classmethod
    def _cause(cls, v):
        v = str(v or "").strip().lower()
        return v if v in ("yes", "no", "unsure") else "unsure"


CI_SYSTEM = """You help a beginner understand why a check failed on their GitHub pull request.

You get the failing check's name, part of its log and its error annotations, and the list of files the pull request changed.
Use ONLY that text. Never invent errors, files, commands or causes. If the log doesn't make the cause clear, say so and lower your confidence.

{language_rule}

Return ONLY one JSON object:
{{
  "what_failed": "one short sentence: which step failed, in plain words",
  "why": "2-3 short sentences: the most likely reason, based on the log",
  "fix_steps": ["a concrete step to fix it"],
  "quoted_lines": ["an EXACT line copied from the log that shows the error"],
  "files": ["a file path mentioned in the log"],
  "caused_by_this_pr": "yes | no | unsure",
  "confidence": 0.0
}}

Rules:
- Be brief. Every word takes time to write on this computer.
- quoted_lines: 1 to 3 lines copied character for character from the log. Never rephrase them.
- files: only paths that appear in the log or in the changed files list.
- fix_steps: 1 to 4 steps. Copy commands exactly as they appear in the log.
- caused_by_this_pr: "yes" only if the error points at one of the changed files or something the change obviously affects.
- confidence: 0 to 1. Use 0.5 or less if the log is cut off or the cause is a guess."""


def ci_system_prompt(language: str) -> str:
    return CI_SYSTEM.format(language_rule=LANGUAGE_RULES.get(language, LANGUAGE_RULES["english"]))


def ci_user_prompt(snap: CISnapshot, language: str = "english") -> str:
    check = snap.failed[0]
    lines = [
        f"REPOSITORY: {snap.owner}/{snap.repo}",
        f"PULL REQUEST #{snap.number}: {snap.title}",
        "FILES CHANGED BY THIS PULL REQUEST:",
        *[f"- {f}" for f in snap.changed_files[:40]],
        "",
        f"FAILED CHECK: {check.name} ({check.conclusion})",
    ]
    if len(snap.failed) > 1:
        lines.append("OTHER FAILED CHECKS: " + ", ".join(c.name for c in snap.failed[1:]))
    if check.annotations:
        lines += ["", "ERROR ANNOTATIONS:", *[f"- {a}" for a in check.annotations]]
    if check.log_excerpt:
        lines += ["", "LOG (the part around the error):", "<<<", check.log_excerpt, ">>>"]
    reminder = LANGUAGE_REMINDERS.get(language, LANGUAGE_REMINDERS["english"])
    return "\n".join(lines) + f"\n\n{reminder}\nNow return the JSON object."


# ---------------------------------------------------------------------------
# Honesty check
# ---------------------------------------------------------------------------

NO_EVIDENCE_CAP = 0.4


def _ev(claim, source, status, reason=None, by="model"):
    return {"claim": claim, "source": source, "status": status, "by": by, "reason": reason}


def help_comment(snap: CISnapshot) -> str:
    names = ", ".join(f'"{c.name}"' for c in snap.failed) or "the checks"
    return (
        f"Hi! The {names} check on this pull request is failing and I'm not sure why. "
        f"Could someone point me to what it needs, or how to run it locally? Thank you!"
    )


def computed_link(snap: CISnapshot) -> list[str]:
    """
    Our own fact, independent of the model: which files changed by this PR appear in the
    failing check's log or annotations? A plain substring test, so absolute CI paths like
    /home/runner/work/repo/repo/src/app.py still count for src/app.py.
    """
    if not snap.failed:
        return []
    check = snap.failed[0]
    text = "\n".join([check.log_excerpt or "", *check.annotations])
    return sorted({f for f in snap.changed_files if f and f in text})


def check_ci(expl: CIExplanation | None, snap: CISnapshot, settings: Settings, language: str = "english") -> dict:
    warnings: list[str] = []
    evidence: list[dict] = []
    linked = computed_link(snap)

    if not snap.failed:
        return {"explanation": None, "linked_files": [], "warnings": [], "evidence": [], "confidence": None,
                "low_confidence": False, "ask_comment": None}

    check = snap.failed[0]
    source_text = "\n".join([check.log_excerpt or "", *check.annotations])
    source_sq = _squash(source_text)
    log_label = f"Log of \"{check.name}\""

    if expl is None:
        return {"explanation": None, "linked_files": linked, "warnings": warnings, "evidence": evidence,
                "confidence": 0.0, "low_confidence": True, "ask_comment": help_comment(snap)}

    # 1. Quoted log lines must really be in the log.
    quotes = []
    for q in expl.quoted_lines:
        clean = q.strip().strip("`")
        if clean and _squash(clean) in source_sq:
            quotes.append({"text": clean, "verified": True})
            evidence.append(_ev(f"Log line: {clean}", log_label, "verified"))
        else:
            evidence.append(_ev(f"Log line: {clean}", log_label, "removed", "This line isn't in the log"))
    dropped_quotes = len(expl.quoted_lines) - len(quotes)
    if dropped_quotes:
        warnings.append(f"Removed {dropped_quotes} quoted log line(s) that don't appear in the log.")

    # 2. Files must exist at the PR's commit or appear in the log.
    files = []
    for f in expl.files:
        real = resolve_path(f, snap.all_paths)
        if real:
            files.append({"path": real, "in_pr": real in snap.changed_files})
            evidence.append(_ev(f"File: {real}", "File tree at the PR's commit", "verified"))
        elif _squash(f) in source_sq:
            files.append({"path": f, "in_pr": False})
            evidence.append(_ev(f"File: {f}", log_label, "verified", "Mentioned in the log"))
        else:
            evidence.append(_ev(f"File: {f}", "File tree at the PR's commit", "removed", "File does not exist in the repo"))
    if len(files) < len(expl.files):
        warnings.append(f"Removed {len(expl.files) - len(files)} file(s) that aren't in the repo or the log.")

    # 3. Fix steps: commands are flagged if they appear nowhere in the log.
    steps = []
    for step in expl.fix_steps:
        cmds = commands_in(step)
        ok = all(_squash(c) in source_sq for c in cmds)
        steps.append({"text": step, "verified": ok})
        evidence.append(
            _ev(f"Fix: {step}", log_label, "unchecked" if not cmds else ("verified" if ok else "flagged"),
                None if (not cmds or ok) else "Command isn't in the log; double-check it")
        )

    # 4. "Was it my change?" against our own computed fact.
    cause = expl.caused_by_this_pr
    if cause == "no" and linked:
        warnings.append(
            f"Gemma said this PR didn't cause it, but the error mentions {', '.join(linked)}, which this PR changes."
        )
        cause_status = "flagged"
    elif cause == "yes" and not linked:
        cause_status = "unchecked"
    else:
        cause_status = "verified" if (cause == "yes" and linked) else "unchecked"
    evidence.append(_ev(f"Caused by this PR: {cause}", "Changed files vs. files in the error", cause_status,
                        None if cause_status != "flagged" else "Contradicts the files in the error"))

    evidence.insert(0, _ev(f"What failed: {expl.what_failed} {expl.why}".strip(), log_label, "unchecked"))

    if language == "hinglish" and not looks_like_hinglish([expl.what_failed, expl.why]):
        warnings.append("You asked for Hinglish, but the model answered in English.")

    confidence = expl.confidence
    # Same rule as the repo explainer: every invented line or file costs 10%, up to 30%.
    invented = sum(1 for ev in evidence if ev["status"] == "removed")
    if invented:
        penalty = min(MAX_INVENTED_PENALTY, INVENTED_FILE_PENALTY * invented)
        confidence = max(0.0, confidence - penalty)
        warnings.append(f"Lowered confidence by {round(penalty * 100)}% because the model invented log lines or files.")
    if not quotes:
        if confidence > NO_EVIDENCE_CAP:
            confidence = NO_EVIDENCE_CAP
        warnings.append(f"No line from the log backs this explanation, so confidence is capped at {round(NO_EVIDENCE_CAP * 100)}%.")
    if check.log_status != "ok":
        warnings.append("GoodFirst couldn't read the full log, only GitHub's error annotations.")
    confidence = round(confidence, 2)
    low = confidence < settings.confidence_floor

    return {
        "explanation": {
            "what_failed": expl.what_failed,
            "why": expl.why,
            "fix_steps": steps,
            "quoted_lines": quotes,
            "files": files,
            "caused_by_this_pr": cause,
            "model_confidence": round(expl.confidence, 2),
        },
        "linked_files": linked,
        "warnings": warnings,
        "evidence": evidence,
        "confidence": confidence,
        "low_confidence": low,
        "ask_comment": help_comment(snap) if low else None,
    }


# ---------------------------------------------------------------------------
# The graph: fetch_ci -> explain_ci -> ci_honesty
# ---------------------------------------------------------------------------


class CIState(TypedDict, total=False):
    pr_input: str
    language: str
    snapshot: CISnapshot
    draft: CIExplanation
    result: dict
    error: str
    explain_error: str
    timings: dict[str, Any]


def build_ci_graph(github: GitHubClient, llm: ChatBackend, settings: Settings):
    import time

    def fetch(state: CIState) -> dict:
        start = time.perf_counter()
        try:
            snap = fetch_ci(github, state["pr_input"])
        except GitHubError as exc:
            return {"error": str(exc)}
        return {"snapshot": snap, "timings": {"github_s": round(time.perf_counter() - start, 1)}}

    def explain(state: CIState) -> dict:
        snap = state["snapshot"]
        if not snap.failed:
            return {}
        check = snap.failed[0]
        if not check.log_excerpt and not check.annotations:
            return {"explain_error": "GoodFirst couldn't read this check's log or error messages, so Gemma wasn't asked to guess."}
        language = state.get("language", "english")
        try:
            draft, stats = ask_json(llm, ci_system_prompt(language), ci_user_prompt(snap, language), CIExplanation,
                                    json_schema=CI_JSON_SCHEMA)
        except (LLMUnavailableError, LLMOutputError) as exc:
            return {"explain_error": str(exc)}
        timings = dict(state.get("timings", {}))
        timings["explain"] = stats.as_dict()
        return {"draft": draft, "timings": timings}

    def honesty(state: CIState) -> dict:
        return {"result": check_ci(state.get("draft"), state["snapshot"], settings, state.get("language", "english"))}

    g = StateGraph(CIState)
    g.add_node("fetch", fetch)
    g.add_node("explain", explain)
    g.add_node("honesty_check", honesty)
    g.add_edge(START, "fetch")
    g.add_conditional_edges("fetch", lambda s: END if s.get("error") else "explain", ["explain", END])
    g.add_edge("explain", "honesty_check")
    g.add_edge("honesty_check", END)
    return g.compile()
