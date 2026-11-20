"""Thread resolution logic for the posting script.

Validates a ``resolve_thread: true`` request (resolution metadata, allowed users,
thread ownership) and resolves the GitHub review thread via GraphQL.
"""

from __future__ import annotations

from typing import Any

from github_api import resolve_review_thread
from post.discussion_matching import validate_resolution_request
from post.io import GREEN, YELLOW, color, jsonl_append


def resolve_thread_after_reply(poster: Any, comment: Any, reply_id: str) -> None:
    valid, error = validate_resolution_request(
        poster.existing_discussions,
        poster.allowed_resolution_users,
        discussion_id=comment.discussion_id,
        resolution_kind=comment.resolution_kind,
        resolution_basis=comment.resolution_basis,
        resolution_evidence=comment.resolution_evidence,
        resolver_username=comment.resolver_username,
        canonical_discussion_id=comment.canonical_discussion_id,
        waiver_type=comment.waiver_type,
        waiver_reason=comment.waiver_reason,
        ai_reviewer_username=poster.ai_reviewer_username,
        changed_files=poster.changed_files,
        changed_patches=poster.changed_patches,
    )
    if not valid:
        prefix = (
            "Dry-run: resolve validation failed"
            if poster.dry_run
            else "Reply succeeded but resolve validation failed"
        )
        print(color(f"  {prefix} for discussion {comment.discussion_id}: {error}", YELLOW))
        poster.resolve_validation_failed += 1
        jsonl_append(
            poster.resolve_validation_failed_log,
            {
                "file": comment.filename,
                "discussion_id": comment.discussion_id,
                "comment_id": reply_id,
                "error": error,
                "resolution_kind": comment.resolution_kind,
            },
        )
        return

    if poster.dry_run:
        print(color(f"  Dry-run: would resolve discussion ({comment.discussion_id})", GREEN))
        poster.resolved_threads += 1
        jsonl_append(
            poster.resolved_log,
            {"file": comment.filename, "discussion_id": comment.discussion_id, "comment_id": reply_id},
        )
        return

    discussion = poster.discussion_by_id(comment.discussion_id) or {}
    if discussion.get("resolved"):
        ok, error_message = True, ""
    else:
        ok, error_message = resolve_review_thread(discussion.get("thread_node_id") or "")
    if ok:
        print(color(f"  Resolved: Discussion ({comment.discussion_id})", GREEN))
        poster.resolved_threads += 1
        jsonl_append(
            poster.resolved_log,
            {"file": comment.filename, "discussion_id": comment.discussion_id, "comment_id": reply_id},
        )
        return

    print(
        color(
            f"  Reply succeeded but resolve failed for discussion {comment.discussion_id}: {error_message}",
            YELLOW,
        )
    )
    poster.resolve_failed += 1
    jsonl_append(
        poster.resolve_failed_log,
        {
            "file": comment.filename,
            "discussion_id": comment.discussion_id,
            "comment_id": reply_id,
            "error": error_message,
        },
    )
