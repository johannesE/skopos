"""Comment processing handlers for the posting script.

Each handler takes a ``poster`` (ReviewPoster-like) + ``comment`` and performs
the full processing cycle: dry-run simulation, API call, response parsing,
JSONL logging, and error handling.

Handlers:
- queue_inline_comment: add an inline comment to the pending review (submitted once, at the end)
- post_general_comment: POST a PR conversation comment
- post_reply_note: reply to an existing review thread (or PR comment)
- upsert_dashboard_note: PATCH (update) or POST (create) the singleton dashboard comment
"""

from __future__ import annotations

import json
from typing import Any

from github_api import api_call, error_message
from post.comment_classification import (
    looks_like_resolution_reply,
    parse_line_number,
    strip_legacy_dashboard_summary,
)
from post.discussion_matching import find_matching_discussion
from post.io import DASHBOARD_MARKER, GREEN, RED, color, jsonl_append


def _created_id(result: Any) -> str:
    if result.returncode != 0:
        return ""
    try:
        payload = json.loads(result.stdout or "null")
    except json.JSONDecodeError:
        return ""
    return str(payload.get("id") or "") if isinstance(payload, dict) else ""


def queue_inline_comment(poster: Any, comment: Any) -> None:
    """Queue an inline comment; publisher.submit_review posts all of them as one review."""
    if not comment.file_path:
        print(color("  Error: Inline comment missing 'file' field", RED))
        poster.failed += 1
        return
    line_number = parse_line_number(comment.line_number)
    if line_number is None:
        print(color("  Error: Inline comment missing or invalid 'line' field", RED))
        poster.failed += 1
        return
    start_line = parse_line_number(comment.start_line)
    print(f"  File: {comment.file_path}")
    print(f"  Lines: {start_line}-{line_number}" if start_line else f"  Line: {line_number}")

    entry: dict[str, Any] = {
        "path": comment.file_path,
        "line": line_number,
        "side": "RIGHT",
        "body": comment.body,
    }
    if start_line is not None and start_line < line_number:
        entry["start_line"] = start_line
        entry["start_side"] = "RIGHT"
    poster.pending_inline.append((comment.filename, entry))
    print(color("  Queued for review submission", GREEN))


def post_general_comment(poster: Any, comment: Any) -> None:
    if poster.dry_run:
        print(color("  Dry-run: would post PR comment", GREEN))
        poster.notes_created += 1
        jsonl_append(
            poster.posted_log,
            {"file": comment.filename, "comment_id": "dry-run", "type": "general"},
        )
        return
    result = api_call(
        f"repos/{poster.slug}/issues/{poster.pr_number}/comments",
        method="POST",
        payload={"body": comment.body},
    )
    created = _created_id(result)
    if created:
        print(color(f"  Success: PR comment created (ID: {created})", GREEN))
        poster.notes_created += 1
        jsonl_append(
            poster.posted_log,
            {"file": comment.filename, "comment_id": created, "type": "general"},
        )
        return
    print(color(f"  Failed: {error_message(result)}", RED))
    poster.failed += 1


def post_reply_note(poster: Any, comment: Any) -> None:
    """Reply to an existing review thread (or, for plain PR comments, quote-reply)."""
    if not comment.discussion_id:
        auto_match = find_matching_discussion(
            poster.existing_discussions,
            file_path=comment.file_path,
            body=comment.body,
            finding_key=comment.finding_key,
            rule_id=comment.rule_id,
            root_cause_cluster=comment.root_cause_cluster,
            allowed_users=poster.allowed_resolution_users,
            desired_states={"open"},
        )
        if auto_match and auto_match.score >= 80:
            comment.discussion_id = auto_match.discussion_id
            print(
                color(
                    f"  Auto-selected canonical discussion {comment.discussion_id} via {auto_match.strategy}",
                    GREEN,
                )
            )
        else:
            print(
                color(
                    "  Error: reply comment missing 'discussion_id' and no canonical discussion match was found",
                    RED,
                )
            )
            poster.failed += 1
            return
    discussion = poster.discussion_by_id(comment.discussion_id)
    if discussion is None:
        print(color(f"  Error: discussion {comment.discussion_id} not found on this PR", RED))
        poster.failed += 1
        return
    print(f"  Discussion ID: {comment.discussion_id}")
    if comment.resolve_thread == "true":
        print("  Resolve Thread: true")
    elif looks_like_resolution_reply(comment.body):
        print(
            color(
                "  Error: reply reads like a resolution but is missing resolve_thread: true and resolution metadata",
                RED,
            )
        )
        poster.failed += 1
        return

    if poster.dry_run:
        print(color(f"  Dry-run: would reply to discussion ({comment.discussion_id})", GREEN))
        poster.replied += 1
        jsonl_append(
            poster.replied_log,
            {"file": comment.filename, "discussion_id": comment.discussion_id, "comment_id": "dry-run"},
        )
        if comment.resolve_thread == "true":
            poster.validate_and_resolve_thread(comment, "dry-run")
        return

    if discussion.get("kind") == "issue_comment":
        root = (discussion.get("notes") or [{}])[0]
        quoted = "\n".join(
            f"> {line}" for line in (root.get("body") or "").strip().splitlines()[:3]
        )
        result = api_call(
            f"repos/{poster.slug}/issues/{poster.pr_number}/comments",
            method="POST",
            payload={"body": f"{quoted}\n\n{comment.body}"},
        )
    else:
        result = api_call(
            f"repos/{poster.slug}/pulls/{poster.pr_number}/comments/{comment.discussion_id}/replies",
            method="POST",
            payload={"body": comment.body},
        )
    reply_id = _created_id(result)
    if reply_id:
        print(color(f"  Replied: Discussion ({comment.discussion_id}) comment ID {reply_id}", GREEN))
        poster.replied += 1
        jsonl_append(
            poster.replied_log,
            {"file": comment.filename, "discussion_id": comment.discussion_id, "comment_id": reply_id},
        )
        if comment.resolve_thread == "true":
            poster.validate_and_resolve_thread(comment, reply_id)
        return
    print(
        color(
            f"  Failed reply to discussion {comment.discussion_id}: {error_message(result)}",
            RED,
        )
    )
    poster.failed += 1


def upsert_dashboard_note(poster: Any, comment: Any) -> None:
    """PATCH (update) or POST (create) the singleton dashboard comment."""
    body = (
        comment.body
        if DASHBOARD_MARKER in comment.body
        else f"{DASHBOARD_MARKER}\n\n{comment.body}"
    )
    body = strip_legacy_dashboard_summary(body)
    existing_id = poster.find_note_id_by_marker(DASHBOARD_MARKER)
    if poster.dry_run:
        if existing_id:
            print(color(f"  Dry-run: would update dashboard comment (ID: {existing_id})", GREEN))
            poster.updated += 1
            jsonl_append(
                poster.updated_log,
                {"file": comment.filename, "comment_id": existing_id, "dry_run": True},
            )
        else:
            print(color("  Dry-run: would create dashboard comment", GREEN))
            poster.notes_created += 1
            jsonl_append(
                poster.posted_log,
                {"file": comment.filename, "comment_id": "dry-run", "type": "dashboard"},
            )
        return

    if existing_id:
        result = api_call(
            f"repos/{poster.slug}/issues/comments/{existing_id}",
            method="PATCH",
            payload={"body": body},
        )
        updated_id = _created_id(result)
        if updated_id:
            print(color(f"  Updated: Dashboard comment (ID: {updated_id})", GREEN))
            poster.updated += 1
            jsonl_append(poster.updated_log, {"file": comment.filename, "comment_id": updated_id})
            return
        print(color(f"  Failed dashboard update: {error_message(result)}", RED))
        poster.failed += 1
        return

    print("  Dashboard comment not found; creating it")
    result = api_call(
        f"repos/{poster.slug}/issues/{poster.pr_number}/comments",
        method="POST",
        payload={"body": body},
    )
    created_id = _created_id(result)
    if created_id:
        print(color(f"  Success: Dashboard comment created (ID: {created_id})", GREEN))
        poster.notes_created += 1
        jsonl_append(
            poster.posted_log,
            {"file": comment.filename, "comment_id": created_id, "type": "dashboard"},
        )
        return
    print(color(f"  Failed dashboard create: {error_message(result)}", RED))
    poster.failed += 1
