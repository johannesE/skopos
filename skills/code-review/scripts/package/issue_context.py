"""Linked-issue context for review packaging.

Finds the issue a pull request addresses (GitHub "closing" references first,
then a `#N` mention in the title/body) and extracts its requirements /
acceptance criteria. Unreachable issues are tolerated: the review proceeds
without issue context.
"""

from __future__ import annotations

import re
from typing import Any

from github_api import (
    GitHubError,
    api_get,
    fetch_closing_issue_numbers,
    fetch_issue_comments,
    norm_login,
)


def infer_issue_number(*texts: str, exclude: int | None = None) -> int | None:
    for text in texts:
        for match in re.finditer(r"(?<![\w/])#(\d+)\b", text or ""):
            number = int(match.group(1))
            if number != exclude:
                return number
    return None


def resolve_issue_number(
    slug: str, pr_number: int, title: str, body: str
) -> int | None:
    closing = fetch_closing_issue_numbers(slug, pr_number)
    if closing:
        return closing[0]
    return infer_issue_number(title, body, exclude=pr_number)


def extract_issue_requirements(description: str) -> list[str]:
    requirements: list[str] = []
    lines = description.splitlines()
    capture = False
    headings = {
        "acceptance criteria",
        "requirements",
        "scope",
        "deliverables",
        "objective",
    }
    for line in lines:
        stripped = line.strip()
        lowered = stripped.lstrip("#").strip().lower()
        if stripped.startswith("#"):
            capture = lowered in headings
            continue
        bullet_match = re.match(r"^[-*]\s+(?:\[[ xX]\]\s+)?(.+)$", stripped)
        numbered_match = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if capture and bullet_match:
            requirements.append(bullet_match.group(1).strip())
        elif capture and numbered_match:
            requirements.append(numbered_match.group(1).strip())
    if requirements:
        return requirements

    fallback: list[str] = []
    for line in lines:
        stripped = line.strip()
        bullet_match = re.match(r"^[-*]\s+\[[ xX]\]\s+(.+)$", stripped)
        if bullet_match:
            fallback.append(bullet_match.group(1).strip())
    return fallback


def issue_payload(slug: str, issue_number: int | None) -> dict[str, Any] | None:
    if issue_number is None:
        return None
    try:
        issue = api_get(f"repos/{slug}/issues/{issue_number}")
        if not isinstance(issue, dict) or issue.get("pull_request"):
            # `#N` pointed at another pull request, not an issue.
            return None
        comments = fetch_issue_comments(slug, issue_number)
    except GitHubError:
        return None
    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "description": issue.get("body"),
        "state": issue.get("state"),
        "web_url": issue.get("html_url"),
        "author": norm_login((issue.get("user") or {}).get("login")),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "requirements": extract_issue_requirements(issue.get("body") or ""),
        "notes": [
            {
                "author": norm_login((c.get("user") or {}).get("login")),
                "created_at": c.get("created_at"),
                "body": c.get("body"),
            }
            for c in comments
        ],
    }
