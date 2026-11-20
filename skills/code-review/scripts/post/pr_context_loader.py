"""Load pull-request state (threads, comments, SHAs, changed files) for posting.

Two sources:
- ``load_live_context``: fresh state from the GitHub API (used for the real post).
- ``load_packaged_context``: the packaged ``context.json`` (offline validation;
  needs no GitHub token, so the review agent can dry-run without credentials).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from github_api import (
    bot_login_from_env,
    build_review_state,
    fetch_issue_comments,
    fetch_pr,
    fetch_pr_files,
    fetch_pr_reviews,
    fetch_review_threads,
    pr_participants,
    repo_slug,
)
from post.io import PosterError
from review_shared import norm_login


@dataclass
class PRContext:
    slug: str = ""
    existing_discussions: list[dict[str, Any]] = field(default_factory=list)
    existing_notes: list[dict[str, Any]] = field(default_factory=list)
    ai_reviewer_username: str = ""
    allowed_resolution_users: set[str] = field(default_factory=set)
    changed_files: set[str] = field(default_factory=set)
    changed_patches: dict[str, str] = field(default_factory=dict)
    base_sha: str = ""
    head_sha: str = ""
    offline: bool = False


def load_live_context(pr_number: str) -> PRContext:
    slug = repo_slug()
    pr = fetch_pr(slug, pr_number)
    head_sha = (pr.get("head") or {}).get("sha") or ""
    if not head_sha:
        raise PosterError("Could not read the pull request head SHA. Check the PR number and token permissions.")
    discussions, notes = build_review_state(
        fetch_review_threads(slug, pr_number), fetch_issue_comments(slug, pr_number)
    )
    participants = pr_participants(pr, fetch_pr_reviews(slug, pr_number))
    files = fetch_pr_files(slug, pr_number)
    patches = {
        item.get("filename") or "": item.get("patch") or ""
        for item in files
        if item.get("filename")
    }
    return PRContext(
        slug=slug,
        existing_discussions=discussions,
        existing_notes=notes,
        ai_reviewer_username=bot_login_from_env(),
        allowed_resolution_users=set(participants["allowed_resolution_users"]),
        changed_files=set(patches),
        changed_patches=patches,
        base_sha=(pr.get("base") or {}).get("sha") or "",
        head_sha=head_sha,
    )


def load_packaged_context(context_path: Path) -> PRContext:
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PosterError(f"Could not read packaged context {context_path}: {exc}") from exc
    state = context.get("review_state") or {}
    changes = context.get("changes") or {}
    files = changes.get("files") or []
    patches = {
        entry.get("path") or "": entry.get("patch") or ""
        for entry in files
        if entry.get("path")
    }
    participants = state.get("participants") or {}
    return PRContext(
        slug=((context.get("project") or {}).get("full_name")) or "",
        existing_discussions=state.get("discussions") or [],
        existing_notes=state.get("notes") or [],
        ai_reviewer_username=norm_login(state.get("bot_login")),
        allowed_resolution_users=set(participants.get("allowed_resolution_users") or []),
        changed_files=set(patches),
        changed_patches=patches,
        base_sha=changes.get("base_sha") or "",
        head_sha=changes.get("head_sha") or "",
        offline=True,
    )
