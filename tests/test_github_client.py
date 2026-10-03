"""
Tests for the GitHub layer. No real network: every request goes to a small
fake GitHub implemented with httpx.MockTransport.
"""

from __future__ import annotations

import base64
from dataclasses import replace

import httpx
import pytest

from goodfirst.config import load_settings
from goodfirst.github_client import (
    GitHubAuthError,
    GitHubClient,
    GitHubUnavailableError,
    InvalidRepoError,
    RateLimitError,
    RepoNotFoundError,
    clean_text,
    find_contributing_path,
    parse_repo,
    pick_beginner_labels,
    truncate,
)

API = "https://api.github.com"


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def make_issue(number, title="Fix typo", body="Small fix", pr=False, assignee=None, comments=0, labels=("good first issue",)):
    item = {
        "number": number,
        "title": title,
        "body": body,
        "html_url": f"https://github.com/acme/widgets/issues/{number}",
        "labels": [{"name": n} for n in labels],
        "comments": comments,
        "assignee": assignee,
        "assignees": [assignee] if assignee else [],
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
    }
    if pr:
        item["pull_request"] = {"url": "..."}
    return item


def default_routes() -> dict:
    """A healthy repo with README, .github/CONTRIBUTING.md and good first issues."""
    return {
        "/repos/acme/widgets": {
            "name": "widgets",
            "full_name": "acme/widgets",
            "owner": {"login": "acme"},
            "html_url": "https://github.com/acme/widgets",
            "description": "Tiny widgets",
            "default_branch": "main",
            "language": "Python",
            "topics": ["widgets"],
            "stargazers_count": 42,
            "archived": False,
            "has_issues": True,
            "license": {"spdx_id": "MIT"},
        },
        "/repos/acme/widgets/git/trees/main": {
            "truncated": False,
            "tree": [
                {"path": "src", "type": "tree"},
                {"path": "src/widgets.py", "type": "blob"},
                {"path": "README.md", "type": "blob"},
                {"path": ".github", "type": "tree"},
                {"path": ".github/CONTRIBUTING.md", "type": "blob"},
                {"path": "vendor-lib", "type": "commit"},  # submodule: should be ignored
            ],
        },
        "/repos/acme/widgets/readme": {
            "path": "README.md",
            "encoding": "base64",
            "content": b64("# Widgets\n![badge](https://img.shields.io/x)\n<!-- hidden -->\nInstall with pip."),
        },
        "/repos/acme/widgets/contents/.github/CONTRIBUTING.md": {
            "path": ".github/CONTRIBUTING.md",
            "encoding": "base64",
            "content": b64("Run `pytest` before opening a PR."),
        },
        "/repos/acme/widgets/labels": [{"name": "bug"}, {"name": "good first issue"}, {"name": "help wanted"}],
        "/repos/acme/widgets/issues": [
            make_issue(1, "Fix typo in docs"),
            make_issue(2, "A pull request", pr=True),
            make_issue(3, "Add a test", assignee={"login": "bob"}, comments=4),
        ],
    }


class FakeGitHub:
    """Routes requests by path. A route value can be JSON data, or an httpx.Response for errors."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path not in self.routes:
            return httpx.Response(404, json={"message": "Not Found"})
        value = self.routes[path]
        if callable(value):           # a function that builds the response from the request
            value = value(request)
        if isinstance(value, httpx.Response):
            return value
        return httpx.Response(200, json=value)


@pytest.fixture
def settings(tmp_path):
    # Cache disabled by default so each test sees its own fake responses.
    return load_settings({"GOODFIRST_CACHE_DIR": str(tmp_path / "cache"), "CACHE_TTL_S": "0"})


def make_client(settings, routes):
    fake = FakeGitHub(routes)
    return GitHubClient(settings, http=httpx.Client(transport=httpx.MockTransport(fake))), fake


# ---------------------------------------------------------------- parse_repo


@pytest.mark.parametrize(
    "text",
    [
        "acme/widgets",
        " acme/widgets/ ",
        "https://github.com/acme/widgets",
        "https://github.com/acme/widgets/",
        "github.com/acme/widgets",
        "https://www.github.com/acme/widgets.git",
        "https://github.com/acme/widgets/tree/main/src",
        "https://github.com/acme/widgets/issues/12",
        "git@github.com:acme/widgets.git",
    ],
)
def test_parse_repo_accepts_common_forms(text):
    assert parse_repo(text) == ("acme", "widgets")


@pytest.mark.parametrize(
    "text",
    ["", "acme", "https://gitlab.com/acme/widgets", "https://github.com/acme", "a/b/c", "acme widgets", "../x"],
)
def test_parse_repo_rejects_bad_input(text):
    with pytest.raises(InvalidRepoError):
        parse_repo(text)


# ---------------------------------------------------------------- helpers


def test_clean_text_removes_badges_and_comments():
    out = clean_text("# T\n![b](u)\n<!-- x -->\n<img src='a'>\n\n\n\nBody")
    assert out == "# T\n\nBody"


def test_clean_text_removes_empty_wrappers_left_by_images():
    # Real pattern from firstcontributions/first-contributions: a flag image inside <kbd>,
    # repeated ~80 times. Without this cleanup the model would read 80 lines of '<kbd></kbd>'.
    readme = (
        '#### _Read this in [other languages](docs/translations/Translations.md)._\n'
        + '<kbd><img title="English" alt="English" src="https://x/flag.png" width="22"></kbd>\n' * 80
        + '<p align="center">\n<a href="https://x"><img src="logo.png"></a>\n</p>\n'
        + "# First Contributions\nSome text."
    )
    out = clean_text(readme)
    assert "<kbd>" not in out and "<p" not in out and "<a" not in out
    assert out == (
        "#### _Read this in [other languages](docs/translations/Translations.md)._\n\n"
        "# First Contributions\nSome text."
    )


def test_clean_text_leaves_code_blocks_alone():
    readme = "Example:\n```html\n<div id=\"root\"></div>\n<img src=\"a.png\">\n```\nDone."
    assert clean_text(readme) == readme


def test_truncate_marks_cut_text():
    text, cut = truncate("line one\nline two\nline three", 15)
    assert cut is True
    assert text.startswith("line one")
    assert "truncated by GoodFirst" in text
    assert truncate("short", 100) == ("short", False)


def test_pick_beginner_labels_prefers_exact_match():
    labels = ["easy", "bug", "Good First Issue", "first-timers-only"]
    assert pick_beginner_labels(labels) == ["Good First Issue", "first-timers-only"]
    assert pick_beginner_labels(["bug", "enhancement"]) == []


def test_find_contributing_path():
    assert find_contributing_path(["README.md", "docs/CONTRIBUTING.rst"]) == "docs/CONTRIBUTING.rst"
    assert find_contributing_path(["Contributing.md", ".github/CONTRIBUTING.md"]) == "Contributing.md"
    assert find_contributing_path(["src/contributing.md"]) is None  # not a standard place


# ---------------------------------------------------------------- full snapshot


def test_snapshot_happy_path(settings):
    client, fake = make_client(settings, default_routes())
    snap = client.fetch_snapshot("https://github.com/acme/widgets")

    assert snap.full_name == "acme/widgets"
    assert snap.license == "MIT"
    assert snap.readme.path == "README.md"
    assert "badge" not in snap.readme.text and "hidden" not in snap.readme.text
    assert snap.contributing.path == ".github/CONTRIBUTING.md"
    assert {"path": "src", "type": "dir"} in snap.top_level
    assert "src/widgets.py" in snap.all_paths
    assert "vendor-lib" not in snap.all_paths          # submodule skipped
    assert [i.number for i in snap.issues] == [1, 3]   # PR #2 excluded
    assert snap.issues[1].assigned is True
    assert snap.issue_labels_used == ["good first issue"]
    assert snap.notes == []
    # Read-only: every request was a GET.
    assert all(call.method == "GET" for call in fake.calls)


def test_labels_are_paged_for_big_repos(settings):
    # Like streamlit/streamlit: 'good first issue' is not in the first 100 labels.
    def labels(request):
        page = request.url.params.get("page", "1")
        if page == "1":
            return httpx.Response(200, json=[{"name": f"area:{i}"} for i in range(100)])
        return httpx.Response(200, json=[{"name": "good first issue"}, {"name": "type:bug"}])

    routes = default_routes()
    routes["/repos/acme/widgets/labels"] = labels
    client, fake = make_client(settings, routes)
    snap = client.fetch_snapshot("acme/widgets")
    assert snap.issue_labels_used == ["good first issue"]
    label_calls = [c for c in fake.calls if c.url.path.endswith("/labels")]
    assert len(label_calls) == 2  # stopped after the short last page


def test_standard_label_is_tried_directly_when_discovery_finds_nothing(settings):
    # e.g. a huge repo whose 'good first issue' label sits beyond the label pages we read
    routes = default_routes()
    routes["/repos/acme/widgets/labels"] = [{"name": "bug"}]
    client, fake = make_client(settings, routes)
    snap = client.fetch_snapshot("acme/widgets")
    assert snap.issue_labels_used == ["good first issue"]
    assert [i.number for i in snap.issues] == [1, 3]
    assert not any("no 'good first issue'" in n for n in snap.notes)


def test_issue_request_uses_label_and_open_state(settings):
    client, fake = make_client(settings, default_routes())
    client.fetch_snapshot("acme/widgets")
    issue_call = next(c for c in fake.calls if c.url.path.endswith("/issues"))
    assert issue_call.url.params["labels"] == "good first issue"
    assert issue_call.url.params["state"] == "open"


def test_missing_readme_contributing_and_labels_become_notes(settings):
    routes = default_routes()
    del routes["/repos/acme/widgets/readme"]
    routes["/repos/acme/widgets/git/trees/main"]["tree"] = [{"path": "main.py", "type": "blob"}]
    routes["/repos/acme/widgets/labels"] = [{"name": "bug"}]
    routes["/repos/acme/widgets/issues"] = []  # GitHub returns [] for a label that doesn't exist
    client, _ = make_client(settings, routes)

    snap = client.fetch_snapshot("acme/widgets")
    assert snap.readme is None
    assert snap.contributing is None
    assert snap.issues == []
    assert "No README was found." in snap.notes
    assert "No CONTRIBUTING guide was found." in snap.notes
    assert any("no 'good first issue'" in n for n in snap.notes)


def test_long_issue_body_is_truncated(settings):
    routes = default_routes()
    routes["/repos/acme/widgets/issues"] = [make_issue(7, body="x" * 5000)]
    client, _ = make_client(settings, routes)
    issue = client.fetch_snapshot("acme/widgets").issues[0]
    assert issue.body_truncated is True
    assert len(issue.body) < 700


def test_empty_repo(settings):
    routes = default_routes()
    routes["/repos/acme/widgets/git/trees/main"] = httpx.Response(409, json={"message": "Git Repository is empty."})
    del routes["/repos/acme/widgets/readme"]
    client, _ = make_client(settings, routes)
    snap = client.fetch_snapshot("acme/widgets")
    assert snap.all_paths == []
    assert any("empty" in n for n in snap.notes)


def test_issues_disabled(settings):
    routes = default_routes()
    routes["/repos/acme/widgets"]["has_issues"] = False
    client, fake = make_client(settings, routes)
    snap = client.fetch_snapshot("acme/widgets")
    assert snap.issues == []
    assert "Issues are turned off for this repo." in snap.notes
    assert not any(c.url.path.endswith("/issues") for c in fake.calls)


# ---------------------------------------------------------------- errors


def test_repo_not_found(settings):
    client, _ = make_client(settings, {})
    with pytest.raises(RepoNotFoundError):
        client.fetch_snapshot("acme/nope")


def test_rate_limit_is_reported_with_reset_time(settings):
    routes = {
        "/repos/acme/widgets": httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1900000000"},
            json={"message": "API rate limit exceeded"},
        )
    }
    client, _ = make_client(settings, routes)
    with pytest.raises(RateLimitError) as info:
        client.fetch_snapshot("acme/widgets")
    assert info.value.reset_at is not None
    assert "GITHUB_TOKEN" in str(info.value)  # tip shown when no token is set


def test_forbidden_without_rate_limit_is_not_called_rate_limit(settings):
    routes = {"/repos/acme/widgets": httpx.Response(403, json={"message": "Resource not accessible"})}
    client, _ = make_client(settings, routes)
    with pytest.raises(Exception) as info:
        client.fetch_snapshot("acme/widgets")
    assert not isinstance(info.value, RateLimitError)


def test_bad_token(settings):
    routes = {"/repos/acme/widgets": httpx.Response(401, json={"message": "Bad credentials"})}
    client, _ = make_client(replace(settings, github_token="bad"), routes)
    with pytest.raises(GitHubAuthError):
        client.fetch_snapshot("acme/widgets")


def test_token_is_sent_as_bearer(settings):
    client, fake = make_client(replace(settings, github_token="abc123"), default_routes())
    client.fetch_snapshot("acme/widgets")
    assert fake.calls[0].headers["authorization"] == "Bearer abc123"


def test_network_error(settings):
    def boom(request):
        raise httpx.ConnectError("offline")

    client = GitHubClient(settings, http=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(GitHubUnavailableError):
        client.fetch_snapshot("acme/widgets")


def test_server_error(settings):
    client, _ = make_client(settings, {"/repos/acme/widgets": httpx.Response(502)})
    with pytest.raises(GitHubUnavailableError):
        client.fetch_snapshot("acme/widgets")


# ---------------------------------------------------------------- cache


def test_cache_avoids_repeat_requests(tmp_path):
    cached_settings = load_settings({"GOODFIRST_CACHE_DIR": str(tmp_path / "c"), "CACHE_TTL_S": "3600"})
    client, fake = make_client(cached_settings, default_routes())
    first = client.fetch_snapshot("acme/widgets")
    calls_after_first = len(fake.calls)
    second = client.fetch_snapshot("acme/widgets")
    assert len(fake.calls) == calls_after_first  # nothing new hit the network
    assert first.to_dict() == second.to_dict()


def test_offline_falls_back_to_old_saved_data(tmp_path, monkeypatch):
    s = load_settings({"GOODFIRST_CACHE_DIR": str(tmp_path / "c"), "CACHE_TTL_S": "60"})
    online, _ = make_client(s, default_routes())
    online.fetch_snapshot("acme/widgets")            # saves everything to the cache

    import goodfirst.cache as cache_module
    real_time = cache_module.time.time
    monkeypatch.setattr(cache_module.time, "time", lambda: real_time() + 7 * 86400)  # a week later: all expired

    def offline(request):
        raise httpx.ConnectError("no internet")

    client = GitHubClient(s, http=httpx.Client(transport=httpx.MockTransport(offline)))
    snap = client.fetch_snapshot("acme/widgets")
    assert snap.full_name == "acme/widgets"
    assert [i.number for i in snap.issues] == [1, 3]
    assert any("couldn't be reached" in n and "saved on" in n for n in snap.notes)


def test_offline_without_saved_data_is_a_clear_error(settings):
    def offline(request):
        raise httpx.ConnectError("no internet")

    client = GitHubClient(settings, http=httpx.Client(transport=httpx.MockTransport(offline)))
    with pytest.raises(GitHubUnavailableError) as info:
        client.fetch_snapshot("acme/widgets")
    assert "no saved copy" in str(info.value)
