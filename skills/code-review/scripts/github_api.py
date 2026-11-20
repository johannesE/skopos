"""GitHub access via the `gh` CLI, plus normalization into the review "discussion" shape.

The review lifecycle logic (matching, dedupe, waivers, resolution gate) operates on
a provider-neutral discussion shape:

    discussion = {
        "id": str,                 # reply target (root review comment id, or "ic-<id>")
        "kind": "review_thread" | "issue_comment",
        "thread_node_id": str,     # GraphQL id used to resolve review threads
        "resolved": bool,
        "outdated": bool,
        "resolved_by": {"username": str} | None,
        "notes": [note, ...],      # first note is the thread root
    }
    note = {
        "id": str, "body": str, "author": {"username": str},
        "created_at": str, "updated_at": str, "system": False,
        "resolvable": bool, "resolved": bool,
        "position": {"new_path": str, "new_line": int | None},
    }

Logins are normalized with ``norm_login`` so REST (``bot[bot]``) and GraphQL
(``bot``) forms compare equal.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from review_shared import norm_login, parse_multi_json


class GitHubError(RuntimeError):
    pass


def run_gh(
    args: list[str], *, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args], input=stdin, text=True, capture_output=True
    )


def error_message(result: subprocess.CompletedProcess[str]) -> str:
    for text in (result.stdout, result.stderr):
        text = (text or "").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(payload, dict):
            message = payload.get("message") or ""
            errors = payload.get("errors")
            if errors:
                message = f"{message} {json.dumps(errors)}".strip()
            if message:
                return message
    return "unknown error"


def repo_slug() -> str:
    slug = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY") or ""
    if slug:
        return slug
    result = run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    if result.returncode != 0 or not result.stdout.strip():
        raise GitHubError(
            "Could not determine the repository. Set GH_REPO=owner/name or run inside a GitHub checkout."
        )
    return result.stdout.strip()


def api_call(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Raw REST call. Caller inspects returncode; use api_get for read-only JSON."""
    args = ["api", path, "--method", method, "-H", "Accept: application/vnd.github+json"]
    stdin = None
    if payload is not None:
        args.extend(["--input", "-"])
        stdin = json.dumps(payload)
    return run_gh(args, stdin=stdin)


def api_get(path: str, *, paginate: bool = False) -> Any:
    args = ["api", path, "-H", "Accept: application/vnd.github+json"]
    if paginate:
        args.insert(1, "--paginate")
    result = run_gh(args)
    if result.returncode != 0:
        raise GitHubError(f"GET {path} failed: {error_message(result)}")
    if paginate:
        return parse_multi_json(result.stdout)
    return json.loads(result.stdout or "null")


def graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    result = run_gh(
        ["api", "graphql", "--input", "-"],
        stdin=json.dumps({"query": query, "variables": variables}),
    )
    payload: Any = None
    try:
        payload = json.loads(result.stdout or "null")
    except json.JSONDecodeError:
        pass
    if result.returncode != 0 or not isinstance(payload, dict) or payload.get("errors"):
        detail = (
            json.dumps(payload.get("errors"))
            if isinstance(payload, dict) and payload.get("errors")
            else error_message(result)
        )
        raise GitHubError(f"GraphQL request failed: {detail}")
    return payload.get("data") or {}


# --------------------------------------------------------------------------- reads

REVIEW_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 50, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id isResolved isOutdated path line originalLine
          resolvedBy { login }
          comments(first: 100) {
            nodes { databaseId body createdAt updatedAt author { login } }
          }
        }
      }
    }
  }
}
"""

CLOSING_ISSUES_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 5) { nodes { number } }
    }
  }
}
"""

RESOLVE_THREAD_MUTATION = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) { thread { id isResolved } }
}
"""


def _owner_name(slug: str) -> tuple[str, str]:
    owner, _, name = slug.partition("/")
    return owner, name


def fetch_pr(slug: str, number: int | str) -> dict[str, Any]:
    return api_get(f"repos/{slug}/pulls/{number}")


def fetch_pr_files(slug: str, number: int | str) -> list[dict[str, Any]]:
    return api_get(f"repos/{slug}/pulls/{number}/files?per_page=100", paginate=True)


def fetch_pr_commits(slug: str, number: int | str) -> list[dict[str, Any]]:
    return api_get(f"repos/{slug}/pulls/{number}/commits?per_page=100", paginate=True)


def fetch_pr_reviews(slug: str, number: int | str) -> list[dict[str, Any]]:
    return api_get(f"repos/{slug}/pulls/{number}/reviews?per_page=100", paginate=True)


def fetch_issue_comments(slug: str, number: int | str) -> list[dict[str, Any]]:
    return api_get(f"repos/{slug}/issues/{number}/comments?per_page=100", paginate=True)


def fetch_review_threads(slug: str, number: int | str) -> list[dict[str, Any]]:
    owner, name = _owner_name(slug)
    threads: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        data = graphql(
            REVIEW_THREADS_QUERY,
            {"owner": owner, "name": name, "number": int(number), "cursor": cursor},
        )
        connection = (
            ((data.get("repository") or {}).get("pullRequest") or {}).get("reviewThreads")
            or {}
        )
        threads.extend(connection.get("nodes") or [])
        page = connection.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return threads
        cursor = page.get("endCursor")


def fetch_closing_issue_numbers(slug: str, number: int | str) -> list[int]:
    owner, name = _owner_name(slug)
    try:
        data = graphql(
            CLOSING_ISSUES_QUERY, {"owner": owner, "name": name, "number": int(number)}
        )
    except GitHubError:
        return []
    nodes = (
        (((data.get("repository") or {}).get("pullRequest") or {}).get("closingIssuesReferences") or {}).get("nodes")
        or []
    )
    return [int(node["number"]) for node in nodes if node and node.get("number")]


def list_open_prs_for_branch(branch: str) -> list[dict[str, Any]]:
    result = run_gh(
        [
            "pr", "list", "--head", branch, "--state", "open",
            "--json", "number,headRefName,updatedAt",
        ]
    )
    if result.returncode != 0:
        raise GitHubError(f"gh pr list failed: {error_message(result)}")
    parsed = json.loads(result.stdout or "[]")
    return parsed if isinstance(parsed, list) else []


# ---------------------------------------------------------------- normalization


def _user(login: str | None) -> dict[str, str]:
    return {"username": norm_login(login)}


def normalize_review_thread(thread: dict[str, Any]) -> dict[str, Any] | None:
    comments = ((thread.get("comments") or {}).get("nodes")) or []
    comments = [c for c in comments if c and c.get("databaseId")]
    if not comments:
        return None
    resolved = bool(thread.get("isResolved"))
    position = {
        "new_path": thread.get("path") or "",
        "new_line": thread.get("line") or thread.get("originalLine"),
    }
    notes = [
        {
            "id": str(comment["databaseId"]),
            "body": comment.get("body") or "",
            "author": _user((comment.get("author") or {}).get("login")),
            "created_at": comment.get("createdAt"),
            "updated_at": comment.get("updatedAt"),
            "system": False,
            "resolvable": True,
            "resolved": resolved,
            "position": position,
        }
        for comment in comments
    ]
    resolved_by = (thread.get("resolvedBy") or {}).get("login")
    return {
        "id": notes[0]["id"],
        "kind": "review_thread",
        "thread_node_id": thread.get("id") or "",
        "resolved": resolved,
        "outdated": bool(thread.get("isOutdated")),
        "resolved_by": _user(resolved_by) if resolved_by else None,
        "resolved_at": None,
        "notes": notes,
    }


def normalize_issue_comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(comment.get("id") or ""),
        "body": comment.get("body") or "",
        "author": _user((comment.get("user") or {}).get("login")),
        "created_at": comment.get("created_at"),
        "updated_at": comment.get("updated_at"),
        "system": False,
        "resolvable": False,
        "resolved": False,
        "position": {},
        "web_url": comment.get("html_url"),
    }


def issue_comment_discussion(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"ic-{note['id']}",
        "kind": "issue_comment",
        "thread_node_id": "",
        "resolved": False,
        "outdated": False,
        "resolved_by": None,
        "resolved_at": None,
        "notes": [note],
    }


def build_review_state(
    threads: list[dict[str, Any]], issue_comments: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (discussions, notes). Notes are the PR conversation comments."""
    notes = [normalize_issue_comment(comment) for comment in issue_comments]
    discussions = [d for d in (normalize_review_thread(t) for t in threads) if d]
    discussions.extend(issue_comment_discussion(note) for note in notes)
    return discussions, notes


def pr_participants(
    pr: dict[str, Any], reviews: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    author = norm_login((pr.get("user") or {}).get("login"))
    assignees = [norm_login((u or {}).get("login")) for u in pr.get("assignees") or []]
    reviewers = {
        norm_login((u or {}).get("login")) for u in pr.get("requested_reviewers") or []
    }
    reviewers.update(
        norm_login((review.get("user") or {}).get("login")) for review in reviews or []
    )
    reviewers.discard("")
    allowed = sorted({user for user in [author, *assignees, *reviewers] if user})
    return {
        "author": author,
        "assignees": [a for a in assignees if a],
        "reviewers": sorted(reviewers),
        "allowed_resolution_users": allowed,
    }


def pr_summary(pr: dict[str, Any], reviews: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    participants = pr_participants(pr, reviews)
    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "description": pr.get("body"),
        "state": pr.get("state"),
        "web_url": pr.get("html_url"),
        "source_branch": (pr.get("head") or {}).get("ref"),
        "target_branch": (pr.get("base") or {}).get("ref"),
        "author": participants["author"],
        "assignees": participants["assignees"],
        "reviewers": participants["reviewers"],
        "draft": bool(pr.get("draft")),
        "created_at": pr.get("created_at"),
        "updated_at": pr.get("updated_at"),
    }


def file_status(entry: dict[str, Any]) -> str:
    return {
        "added": "added",
        "removed": "deleted",
        "modified": "modified",
        "renamed": "renamed",
        "copied": "copied",
        "changed": "modified",
        "unchanged": "modified",
    }.get(entry.get("status") or "", entry.get("status") or "modified")


def bot_login_from_env() -> str:
    """Identity the review posts as. Set by the action; falls back to the gh user locally."""
    explicit = norm_login(os.environ.get("SKOPOS_BOT_LOGIN"))
    if explicit:
        return explicit
    result = run_gh(["api", "user", "-q", ".login"])
    if result.returncode == 0:
        return norm_login(result.stdout.strip())
    return ""


def resolve_review_thread(thread_node_id: str) -> tuple[bool, str]:
    try:
        data = graphql(RESOLVE_THREAD_MUTATION, {"threadId": thread_node_id})
    except GitHubError as exc:
        return False, str(exc)
    thread = ((data.get("resolveReviewThread") or {}).get("thread")) or {}
    if thread.get("isResolved"):
        return True, ""
    return False, "thread not reported as resolved"
