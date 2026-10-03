"""
Deterministic ranking of good-first-issues, BEFORE the model sees them.

Why rank in code first?
- A small model reading 15 issues is slow (every token costs time on a CPU)
  and easily distracted. Code can cheaply apply the boring, objective rules.
- The rules are explainable: each issue gets human-readable reasons
  ("Nobody is assigned yet", "Only 1 comment") that the UI shows next to it.
  Those reasons come from GitHub data, never from the model.

The model then only chooses among the top few candidates and explains *why*
and *where to start* for this particular person.

Scoring (higher is better):
  unassigned +3, assigned -4
  comments: 0-2 +2, 3-5 +1, 6-10 0, more than 10 -2 (long debates are hard to join)
  description: under 40 chars -2, 40-149 +1, 150+ +2 (clear issues are easier)
  each skill named in the user's question that appears in the issue +2 (max +6)
  updated in the last 120 days +1, no activity for over a year -1
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from goodfirst.github_client import Issue

CANDIDATES_FOR_MODEL = 6
# When the model gives fewer than 3 valid picks, GoodFirst only tops up with
# issues scoring at least this much. Fewer picks beat a bad recommendation.
MIN_TOP_UP_SCORE = 2

# What someone might type -> the words to look for in issue text.
_SKILL_EXPANSIONS = {
    "python": ["python", ".py", "pip", "pytest"],
    "javascript": ["javascript", "js", ".js", "node", "npm"],
    "typescript": ["typescript", ".ts", ".tsx"],
    "html": ["html", "template"],
    "css": ["css", "style", "styling", "scss"],
    "react": ["react", "jsx", "component"],
    "documentation": ["documentation", "docs", "doc", "readme", "typo", "spelling", "translation"],
    "testing": ["test", "tests", "testing", "pytest", "jest", "unit test"],
    "git": ["git", "github"],
    "java": ["java"],
    "go": ["golang", ".go"],  # not the bare word "go": it's everywhere in English text
    "rust": ["rust", "cargo"],
    "c++": ["c++", "cpp"],
    "sql": ["sql", "database", "query"],
    "design": ["design", "ui", "ux", "icon", "logo"],
}
_ALIASES = {
    "py": "python", "js": "javascript", "ts": "typescript", "docs": "documentation",
    "doc": "documentation", "writing": "documentation", "english": "documentation",
    "test": "testing", "tests": "testing", "reactjs": "react", "golang": "go",
    "cpp": "c++", "ui": "design", "ux": "design",
}
_STOPWORDS = {
    "i", "know", "a", "an", "the", "and", "or", "little", "bit", "basic", "basics", "some",
    "with", "of", "in", "to", "can", "am", "learning", "learn", "beginner", "only", "also",
    "bas", "thoda", "aur", "mujhe", "aata", "hai", "hoon", "main",
    "how", "what", "where", "which", "who", "why", "do", "does", "start", "should", "is", "are",
    "this", "that", "it", "my", "me", "for", "on", "repo", "project", "work", "want", "would", "like",
    "kaise", "kya", "kahan", "kaha", "karu", "karun", "se", "ko", "ka", "ki", "ke", "mein", "yeh",
}


def skill_terms(text: str) -> dict[str, list[str]]:
    """
    Pick KNOWN skills out of free text, e.g. the user's question
    "I know Python and a little CSS, where do I start?" -> {python: [...], css: [...]}.
    Only skills in _SKILL_EXPANSIONS count; ordinary words of a question
    ("contribute", "first", "issue") would otherwise match almost every issue.
    """
    terms: dict[str, list[str]] = {}
    lowered = (text or "").lower()
    for word in re.findall(r"[a-z0-9+#]+", lowered):
        if word in _STOPWORDS:
            continue
        canonical = _ALIASES.get(word, word)
        if canonical in _SKILL_EXPANSIONS:
            terms[canonical] = _SKILL_EXPANSIONS[canonical]
    # Multi-character skills the word splitter can't see, like "html/css" or "c++".
    for canonical in ("c++",):
        if canonical in lowered:
            terms[canonical] = _SKILL_EXPANSIONS[canonical]
    return terms


def _mentions(haystack: str, needle: str) -> bool:
    needle = needle.strip()
    if needle.startswith("."):
        return needle in haystack
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


@dataclass
class RankedIssue:
    issue: Issue
    score: int
    reasons: list[str] = field(default_factory=list)
    skill_matches: list[str] = field(default_factory=list)


def _days_since(timestamp: str, now: datetime) -> float | None:
    try:
        then = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return (now - then).total_seconds() / 86400


def rank_issues(issues: list[Issue], question: str = "", now: datetime | None = None) -> list[RankedIssue]:
    """Score every issue and return them best-first, each with its reasons."""
    now = now or datetime.now(timezone.utc)
    terms = skill_terms(question)
    ranked: list[RankedIssue] = []

    for issue in issues:
        score = 0
        reasons: list[str] = []

        if issue.assigned:
            score -= 4
            reasons.append("Already assigned to someone")
        else:
            score += 3
            reasons.append("Nobody is assigned yet")

        if issue.comments == 0:
            score += 2
            reasons.append("No comments yet")
        elif issue.comments <= 2:
            score += 2
            reasons.append(f"Only {issue.comments} comment{'s' if issue.comments > 1 else ''}")
        elif issue.comments <= 5:
            score += 1
            reasons.append(f"{issue.comments} comments")
        elif issue.comments > 10:
            score -= 2
            reasons.append(f"{issue.comments} comments (long discussion)")
        else:
            reasons.append(f"{issue.comments} comments")

        body_len = len(issue.body.strip())
        if body_len < 40:
            score -= 2
            reasons.append("Very short description")
        elif body_len < 150:
            score += 1
        else:
            score += 2
            reasons.append("Clear, detailed description")

        haystack = " ".join([issue.title, issue.body, " ".join(issue.labels)]).lower()
        matches = [skill for skill, words in terms.items() if any(_mentions(haystack, w) for w in words)]
        if matches:
            score += min(6, 2 * len(matches))
            reasons.append("Matches your question: " + ", ".join(matches))

        age = _days_since(issue.updated_at, now)
        if age is not None:
            if age <= 120:
                score += 1
                reasons.append("Active recently")
            elif age > 365:
                score -= 1
                reasons.append("No activity for over a year")

        ranked.append(RankedIssue(issue, score, reasons, matches))

    # Best score first; ties go to fewer comments, then newer issues.
    ranked.sort(key=lambda r: (-r.score, r.issue.comments, -r.issue.number))
    return ranked


def candidates(ranked: list[RankedIssue], limit: int = CANDIDATES_FOR_MODEL) -> list[RankedIssue]:
    """The issues the model gets to choose from. Assigned ones only if nothing else is left."""
    free = [r for r in ranked if not r.issue.assigned]
    pool = free if len(free) >= min(3, len(ranked)) else ranked
    return pool[:limit]
