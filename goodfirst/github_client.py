"""
GitHub layer for GoodFirst (READ-ONLY).

Everything the model later "knows" about a repo comes from here. The model
never fetches anything itself; this module does all the fetching and returns
one plain `RepoSnapshot` object.

Only GET requests are ever made. There is no code path that writes to GitHub.

Requests per analysis (uncached), roughly:
  1. GET /repos/{owner}/{repo}                      -> metadata
  2. GET /repos/{owner}/{repo}/git/trees/{branch}   -> every file path (one call)
  3. GET /repos/{owner}/{repo}/readme               -> README
  4. GET /repos/{owner}/{repo}/contents/{path}      -> CONTRIBUTING (only if the tree has one)
  5. GET /repos/{owner}/{repo}/labels               -> find the "good first issue"-style labels
  6. GET /repos/{owner}/{repo}/issues?labels=...    -> 1-2 calls, one per matching label
"""

from __future__ import annotations

import base64
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from goodfirst.cache import DiskCache
from goodfirst.config import Settings

# ---------------------------------------------------------------------------
# Errors. Each has a beginner-friendly message the UI can show as-is.
# ---------------------------------------------------------------------------


class GitHubError(Exception):
    """Base class for problems talking to GitHub."""


class InvalidRepoError(GitHubError):
    """The text the user typed doesn't look like a GitHub repo."""


class RepoNotFoundError(GitHubError):
    """404 on the repo itself: wrong name, or a private repo."""


class RateLimitError(GitHubError):
    """GitHub says we've made too many requests."""

    def __init__(self, message: str, reset_at: datetime | None = None):
        super().__init__(message)
        self.reset_at = reset_at


class GitHubAuthError(GitHubError):
    """The GITHUB_TOKEN in .env was rejected."""


class GitHubUnavailableError(GitHubError):
    """Network problem or GitHub server error."""


# ---------------------------------------------------------------------------
# Data we hand to the rest of the app.
# ---------------------------------------------------------------------------


@dataclass
class TextDoc:
    """A text file we fetched (README or CONTRIBUTING), already cleaned and truncated."""

    path: str
    text: str
    truncated: bool
    original_chars: int


@dataclass
class Issue:
    number: int
    title: str
    body: str                 # cleaned + truncated
    body_truncated: bool
    url: str
    labels: list[str]
    comments: int
    assigned: bool
    created_at: str
    updated_at: str


@dataclass
class RepoSnapshot:
    owner: str
    repo: str
    full_name: str
    html_url: str
    description: str
    default_branch: str
    language: str | None
    topics: list[str]
    stars: int
    archived: bool
    license: str | None
    readme: TextDoc | None
    contributing: TextDoc | None
    top_level: list[dict]          # [{"path": "src", "type": "dir"}, ...]
    all_paths: list[str]           # every file AND folder path in the repo (for the honesty check)
    tree_truncated: bool           # GitHub cuts off very large trees
    issues: list[Issue]
    issue_labels_used: list[str]
    notes: list[str] = field(default_factory=list)  # human-readable "what we couldn't find"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Parsing what the user typed.
# ---------------------------------------------------------------------------

# GitHub names: letters, digits, '-', '_', '.'
_NAME = r"[A-Za-z0-9_.-]+"
_OWNER_REPO = re.compile(rf"^({_NAME})/({_NAME})$")


def parse_repo(text: str) -> tuple[str, str]:
    """
    Accepts any of:
        owner/repo
        https://github.com/owner/repo
        github.com/owner/repo/tree/main/src     (extra path is ignored)
        https://github.com/owner/repo.git
        git@github.com:owner/repo.git
    Returns (owner, repo) or raises InvalidRepoError.
    """
    raw = (text or "").strip()
    if not raw:
        raise InvalidRepoError("Please enter a GitHub repo, like `owner/repo`.")

    if raw.startswith("git@github.com:"):
        raw = raw[len("git@github.com:"):]
    elif "github.com" in raw:
        if "://" not in raw:
            raw = "https://" + raw
        parsed = urlparse(raw)
        if parsed.hostname not in ("github.com", "www.github.com"):
            raise InvalidRepoError(f"That doesn't look like a github.com link: {text!r}")
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise InvalidRepoError("The link needs both an owner and a repo name, like github.com/owner/repo.")
        raw = f"{parts[0]}/{parts[1]}"
    elif "://" in raw:
        raise InvalidRepoError(f"Only github.com repos are supported, got {text!r}")

    raw = raw.strip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]

    match = _OWNER_REPO.match(raw)
    if not match:
        raise InvalidRepoError(f"Couldn't read {text!r} as a repo. Try the form `owner/repo`.")
    owner, repo = match.groups()
    if repo in (".", "..") or owner in (".", ".."):
        raise InvalidRepoError(f"Couldn't read {text!r} as a repo.")
    return owner, repo


# ---------------------------------------------------------------------------
# Text cleaning: small models have small context windows, so we remove things
# that cost tokens but carry no meaning for a beginner (badges, HTML comments)
# and then cut to a maximum length.
# ---------------------------------------------------------------------------

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")              # ![alt](url)
_HTML_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_EMPTY_LINK = re.compile(r"\[\s*\]\([^)]*\)")                # [](url) left after removing an image
_EMPTY_TAG = re.compile(r"<(\w+)\b[^>]*>\s*</\1\s*>", re.IGNORECASE)  # <kbd></kbd>, <a href=..></a>
_TAGS_ONLY_LINE = re.compile(r"^\s*(</?\w+\b[^>]*>\s*)+$")   # e.g. '<p align="center">' on its own
_FENCE = re.compile(r"^\s*(```|~~~)")
_MANY_BLANKS = re.compile(r"\n{3,}")


def _clean_line(line: str) -> str | None:
    """Clean one line of prose. Returns None if nothing meaningful is left."""
    line = _MD_IMAGE.sub("", line)
    line = _HTML_IMG.sub("", line)
    line = _EMPTY_LINK.sub("", line)
    # Removing an image often leaves an empty wrapper like <a ...></a> or <kbd></kbd>,
    # and removing that can leave another empty wrapper, so repeat a few times.
    for _ in range(4):
        new = _EMPTY_TAG.sub("", line)
        if new == line:
            break
        line = new
    if line.strip() and _TAGS_ONLY_LINE.match(line):
        return None  # pure layout markup, no words for a reader
    if line.strip() == "" and line != "":
        return ""   # keep paragraph breaks, drop trailing spaces
    return line.rstrip()


def clean_text(text: str) -> str:
    """
    Remove things that cost tokens but carry no meaning (badges, images,
    empty HTML wrappers, comments). Lines inside ``` code blocks are left
    untouched, so example code in a README is never altered.
    """
    text = _HTML_COMMENT.sub("", text.replace("\r\n", "\n"))
    out: list[str] = []
    in_code = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_code = not in_code
            out.append(line.rstrip())
            continue
        if in_code:
            out.append(line.rstrip())
            continue
        cleaned = _clean_line(line)
        if cleaned is not None:
            out.append(cleaned)
    return _MANY_BLANKS.sub("\n\n", "\n".join(out)).strip()


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Cut to max_chars, preferring a line break, and say clearly that we cut."""
    if len(text) <= max_chars:
        return text, False
    cut = text[:max_chars]
    last_newline = cut.rfind("\n")
    if last_newline > max_chars * 0.6:   # don't throw away too much just to end on a line
        cut = cut[:last_newline]
    return cut.rstrip() + "\n[... truncated by GoodFirst ...]", True


# ---------------------------------------------------------------------------
# Which labels count as "good first issue"?
# ---------------------------------------------------------------------------

# Ordered by how strongly they signal "made for newcomers".
_BEGINNER_LABEL_PATTERNS = [
    re.compile(r"^good[\s_-]*first[\s_-]*(issue|bug|pr|contribution)s?$", re.I),
    re.compile(r"good[\s_-]*first", re.I),
    re.compile(r"first[\s_-]*timers?", re.I),
    re.compile(r"beginner|newcomer|starter|easy[\s_-]*(fix|pick)?|low[\s_-]*hanging", re.I),
]


STANDARD_LABEL = "good first issue"  # GitHub's default label name


def pick_beginner_labels(label_names: list[str], limit: int = 2) -> list[str]:
    """Return up to `limit` labels that look beginner-friendly, best match first."""
    chosen: list[str] = []
    for pattern in _BEGINNER_LABEL_PATTERNS:
        for name in label_names:
            if name not in chosen and pattern.search(name):
                chosen.append(name)
                if len(chosen) == limit:
                    return chosen
    return chosen


# Common places for contribution docs, in order of preference.
_CONTRIBUTING_NAMES = re.compile(r"^contributing(\.(md|markdown|rst|txt))?$", re.I)
_CONTRIBUTING_DIRS = ["", ".github/", "docs/", "doc/"]


def find_contributing_path(all_paths: list[str]) -> str | None:
    by_lower = {p.lower(): p for p in all_paths}
    for folder in _CONTRIBUTING_DIRS:
        for path_lower, original in by_lower.items():
            if not path_lower.startswith(folder):
                continue
            rest = path_lower[len(folder):]
            if "/" not in rest and _CONTRIBUTING_NAMES.match(rest):
                return original
    return None


# ---------------------------------------------------------------------------
# The client.
# ---------------------------------------------------------------------------


class GitHubClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GoodFirst (local beginner helper)",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        # `http` is injectable so tests can pass a client with a mocked transport.
        self.http = http or httpx.Client(timeout=30.0, follow_redirects=True)
        self.http.headers.update(headers)
        self.cache = DiskCache(settings.cache_dir / "github", settings.cache_ttl_s)
        # Set when GitHub couldn't be reached and saved (older) data was used instead.
        # Holds the oldest save time used, as a Unix timestamp.
        self.offline_since: float | None = None

    # -- low level ----------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> tuple[int, Any]:
        """
        GET one API path. Returns (status, json). 404/409/410 are returned (not
        raised) because "this file doesn't exist" is normal. Rate limits, bad
        tokens and network errors are raised as friendly GitHubError subclasses.
        """
        url = f"{self.settings.github_api_url}{path}"
        cache_key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            resp = self.http.get(url, params=params)
        except httpx.TransportError as exc:  # includes timeouts
            # Offline? Fall back to an older saved copy, and remember that we did.
            stale = self.cache.get_stale(cache_key)
            if stale is not None:
                status, data, saved_at = stale
                self.offline_since = min(self.offline_since or saved_at, saved_at)
                return status, data
            if isinstance(exc, httpx.TimeoutException):
                raise GitHubUnavailableError(
                    "GitHub took too long to answer. Check your internet and try again."
                ) from exc
            raise GitHubUnavailableError(
                "Couldn't reach GitHub, and there is no saved copy of this repo yet. "
                "Check your internet connection."
            ) from exc

        status = resp.status_code
        if status in (403, 429) and self._is_rate_limited(resp):
            raise self._rate_limit_error(resp)
        if status == 401:
            raise GitHubAuthError(
                "GitHub rejected your GITHUB_TOKEN. Fix or remove it in .env (GoodFirst works without one)."
            )
        if status >= 500:
            raise GitHubUnavailableError(f"GitHub had a server problem (HTTP {status}). Try again in a minute.")
        if status in (404, 409, 410):
            self.cache.set(cache_key, status, None)
            return status, None
        if status != 200:
            raise GitHubError(f"Unexpected answer from GitHub (HTTP {status}) for {path}.")

        data = resp.json()
        self.cache.set(cache_key, status, data)
        return status, data

    @staticmethod
    def _is_rate_limited(resp: httpx.Response) -> bool:
        if resp.headers.get("x-ratelimit-remaining") == "0":
            return True
        if "retry-after" in resp.headers:
            return True  # secondary rate limit
        try:
            return "rate limit" in str(resp.json().get("message", "")).lower()
        except ValueError:
            return False

    def _rate_limit_error(self, resp: httpx.Response) -> RateLimitError:
        reset_at = None
        reset = resp.headers.get("x-ratelimit-reset")
        if reset and reset.isdigit():
            reset_at = datetime.fromtimestamp(int(reset))  # local time
        when = f" It resets at {reset_at:%H:%M}." if reset_at else ""
        hint = (
            ""
            if self.settings.github_token
            else " Adding a GITHUB_TOKEN to .env raises the limit from 60 to 5000 requests per hour."
        )
        return RateLimitError(f"GitHub's rate limit was reached.{when}{hint}", reset_at)

    def _repo_path(self, owner: str, repo: str) -> str:
        return f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"

    # -- individual fetches -------------------------------------------------

    def fetch_meta(self, owner: str, repo: str) -> dict:
        status, data = self._get(self._repo_path(owner, repo))
        if status != 200:
            raise RepoNotFoundError(
                f"Couldn't find github.com/{owner}/{repo}. Check the spelling; private repos aren't supported."
            )
        return data

    def fetch_tree(self, owner: str, repo: str, branch: str) -> tuple[list[dict], list[str], bool]:
        """
        One call that lists every path in the repo (GitHub's recursive tree).
        Returns (top_level_entries, all_paths, truncated).
        An empty repo answers 409, which we treat as "no files".
        """
        status, data = self._get(
            f"{self._repo_path(owner, repo)}/git/trees/{quote(branch, safe='')}",
            params={"recursive": "1"},
        )
        if status != 200 or not data:
            return [], [], False
        all_paths: list[str] = []
        top_level: list[dict] = []
        for entry in data.get("tree", []):
            path = entry.get("path", "")
            kind = "dir" if entry.get("type") == "tree" else "file"
            if not path or entry.get("type") == "commit":  # skip git submodules
                continue
            all_paths.append(path)
            if "/" not in path:
                top_level.append({"path": path, "type": kind})
        # Folders first, then files, alphabetical: easier for humans and models to scan.
        top_level.sort(key=lambda e: (e["type"] != "dir", e["path"].lower()))
        return top_level, all_paths, bool(data.get("truncated"))

    def fetch_readme(self, owner: str, repo: str) -> TextDoc | None:
        status, data = self._get(f"{self._repo_path(owner, repo)}/readme")
        if status != 200 or not data:
            return None
        return self._to_doc(data, self.settings.max_readme_chars)

    def fetch_file(self, owner: str, repo: str, path: str, branch: str, max_chars: int) -> TextDoc | None:
        status, data = self._get(
            f"{self._repo_path(owner, repo)}/contents/{quote(path)}", params={"ref": branch}
        )
        if status != 200 or not isinstance(data, dict):
            return None  # 404, or it was a folder (GitHub returns a list for folders)
        return self._to_doc(data, max_chars)

    def _to_doc(self, data: dict, max_chars: int) -> TextDoc | None:
        if data.get("encoding") != "base64" or data.get("content") is None:
            return None  # e.g. file too large for the contents API
        raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        cleaned = clean_text(raw)
        text, was_cut = truncate(cleaned, max_chars)
        return TextDoc(path=data.get("path", ""), text=text, truncated=was_cut, original_chars=len(raw))

    def fetch_labels(self, owner: str, repo: str, max_pages: int = 5) -> list[str]:
        """
        All label names, 100 per page. Big projects have well over 100 labels
        (Streamlit does), so we page through, stopping early once the classic
        "good first issue" label has turned up.
        """
        names: list[str] = []
        for page in range(1, max_pages + 1):
            status, data = self._get(
                f"{self._repo_path(owner, repo)}/labels", params={"per_page": "100", "page": str(page)}
            )
            if status != 200 or not data:
                break
            names.extend(label.get("name", "") for label in data if label.get("name"))
            if len(data) < 100:
                break  # that was the last page
            if any(_BEGINNER_LABEL_PATTERNS[0].match(n) for n in names):
                break  # found the best possible label already
        return names

    def fetch_issues_with_label(self, owner: str, repo: str, label: str) -> list[Issue] | None:
        """Open issues with one label. Returns None if the repo has issues turned off."""
        status, data = self._get(
            f"{self._repo_path(owner, repo)}/issues",
            params={
                "state": "open",
                "labels": label,
                "sort": "updated",
                "direction": "desc",
                # Pull requests also come back from this endpoint and get filtered out, so ask for extra.
                "per_page": str(min(100, self.settings.max_issues * 2)),
            },
        )
        if status != 200:
            return None
        issues = []
        for item in data or []:
            if "pull_request" in item:   # the /issues endpoint also returns PRs; we only want issues
                continue
            body, cut = truncate(clean_text(item.get("body") or ""), self.settings.max_issue_body_chars)
            issues.append(
                Issue(
                    number=item["number"],
                    title=item.get("title", "").strip(),
                    body=body,
                    body_truncated=cut,
                    url=item.get("html_url", ""),
                    labels=[lbl.get("name", "") for lbl in item.get("labels", []) if isinstance(lbl, dict)],
                    comments=int(item.get("comments", 0)),
                    assigned=bool(item.get("assignee") or item.get("assignees")),
                    created_at=item.get("created_at", ""),
                    updated_at=item.get("updated_at", ""),
                )
            )
        return issues

    # -- everything at once ---------------------------------------------------

    def fetch_snapshot(self, repo_input: str) -> RepoSnapshot:
        """
        Fetch everything GoodFirst needs about one repo.
        Raises on fatal problems (bad input, repo not found, rate limit, offline).
        Missing optional pieces (README, CONTRIBUTING, issues) become `notes` instead.
        """
        owner, repo = parse_repo(repo_input)
        self.offline_since = None
        meta = self.fetch_meta(owner, repo)
        # GitHub may redirect renamed repos; use the canonical name it returns.
        owner = meta.get("owner", {}).get("login", owner)
        repo = meta.get("name", repo)
        branch = meta.get("default_branch") or "main"
        notes: list[str] = []

        top_level, all_paths, tree_truncated = self.fetch_tree(owner, repo, branch)
        if not all_paths:
            notes.append("This repository has no files yet (it's empty).")
        if tree_truncated:
            notes.append("This repo is very large, so GitHub only listed part of its files.")

        readme = self.fetch_readme(owner, repo)
        if readme is None:
            notes.append("No README was found.")

        contributing = None
        contributing_path = find_contributing_path(all_paths)
        if contributing_path:
            contributing = self.fetch_file(
                owner, repo, contributing_path, branch, self.settings.max_contributing_chars
            )
        if contributing is None:
            notes.append("No CONTRIBUTING guide was found.")

        issues: list[Issue] = []
        labels_used: list[str] = []
        if not meta.get("has_issues", True):
            notes.append("Issues are turned off for this repo.")
        else:
            labels_used = pick_beginner_labels(self.fetch_labels(owner, repo))
            seen: set[int] = set()
            for label in labels_used:
                for issue in self.fetch_issues_with_label(owner, repo, label) or []:
                    if issue.number not in seen:
                        seen.add(issue.number)
                        issues.append(issue)
            if not labels_used:
                # Label discovery can miss the label on very big repos (we read at most
                # 500 labels). One direct request for the standard label settles it.
                direct = self.fetch_issues_with_label(owner, repo, STANDARD_LABEL) or []
                if direct:
                    labels_used = [STANDARD_LABEL]
                    issues.extend(direct)
                else:
                    notes.append("This repo has no 'good first issue' style label.")
            issues = issues[: self.settings.max_issues]
            if labels_used and not issues:
                notes.append(f"No open issues labelled {', '.join(repr(l) for l in labels_used)} right now.")

        if meta.get("archived"):
            notes.append("This repo is archived (read-only), so it can't accept contributions.")
        if self.offline_since:
            saved = datetime.fromtimestamp(self.offline_since)
            notes.append(
                f"GitHub couldn't be reached, so GoodFirst used data saved on {saved:%d %b at %H:%M}. "
                "Issues may have changed since then."
            )

        license_info = meta.get("license") or {}
        return RepoSnapshot(
            owner=owner,
            repo=repo,
            full_name=meta.get("full_name", f"{owner}/{repo}"),
            html_url=meta.get("html_url", f"https://github.com/{owner}/{repo}"),
            description=(meta.get("description") or "").strip(),
            default_branch=branch,
            language=meta.get("language"),
            topics=list(meta.get("topics") or []),
            stars=int(meta.get("stargazers_count", 0)),
            archived=bool(meta.get("archived")),
            license=license_info.get("spdx_id") or license_info.get("name"),
            readme=readme,
            contributing=contributing,
            top_level=top_level,
            all_paths=all_paths,
            tree_truncated=tree_truncated,
            issues=issues,
            issue_labels_used=labels_used,
            notes=notes,
        )
