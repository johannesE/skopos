"""Submit queued inline comments as a single GitHub pull request review.

One review (event ``COMMENT``) produces one notification and keeps the inline
findings grouped. GitHub rejects the whole review if any comment targets a
line outside the diff, so on failure each comment is retried individually and
only the offending ones are counted as failed.
"""

from __future__ import annotations

import json
from typing import Any

from github_api import api_call, error_message
from post.io import BLUE, GREEN, RED, YELLOW, color, jsonl_append
from review_shared import REVIEW_MARKER


def _review_body(count: int) -> str:
    noun = "finding" if count == 1 else "findings"
    return (
        f"{REVIEW_MARKER}\n**Skopos** left {count} inline {noun}. "
        "The dashboard comment on this pull request has the full overview."
    )


def _log_posted(poster: Any, filename: str, comment_id: str, review_id: str = "") -> None:
    poster.inline_posted += 1
    jsonl_append(
        poster.posted_log,
        {"file": filename, "comment_id": comment_id, "review_id": review_id, "type": "inline"},
    )


def submit_review(poster: Any) -> int:
    pending = poster.pending_inline
    if not pending:
        print(color("No inline comments to submit.", YELLOW))
        return 0
    if poster.dry_run:
        print(color(f"Dry-run: would submit one review with {len(pending)} inline comment(s).", YELLOW))
        for filename, _ in pending:
            _log_posted(poster, filename, "dry-run")
        return 0

    print(color(f"Submitting review with {len(pending)} inline comment(s)...", BLUE))
    result = api_call(
        f"repos/{poster.slug}/pulls/{poster.pr_number}/reviews",
        method="POST",
        payload={
            "commit_id": poster.head_sha,
            "event": "COMMENT",
            "body": _review_body(len(pending)),
            "comments": [entry for _, entry in pending],
        },
    )
    if result.returncode == 0:
        review_id = ""
        try:
            review_id = str((json.loads(result.stdout or "{}") or {}).get("id") or "")
        except json.JSONDecodeError:
            pass
        for filename, _ in pending:
            _log_posted(poster, filename, "", review_id)
        print(color(f"Review submitted (ID: {review_id or 'unknown'}).", GREEN))
        return 0

    print(
        color(
            f"Batched review rejected ({error_message(result)}); retrying comments individually...",
            YELLOW,
        )
    )
    failures = 0
    for filename, entry in pending:
        single = api_call(
            f"repos/{poster.slug}/pulls/{poster.pr_number}/comments",
            method="POST",
            payload={**entry, "commit_id": poster.head_sha},
        )
        if single.returncode == 0:
            comment_id = ""
            try:
                comment_id = str((json.loads(single.stdout or "{}") or {}).get("id") or "")
            except json.JSONDecodeError:
                pass
            _log_posted(poster, filename, comment_id)
            print(color(f"  Posted {filename} (ID: {comment_id})", GREEN))
            continue
        failures += 1
        poster.failed += 1
        print(color(f"  Failed {filename}: {error_message(single)}", RED))
        print(
            color(
                f"  Debug: check that {entry['path']} line {entry['line']} is visible in the PR diff",
                YELLOW,
            )
        )
    return 1 if failures else 0
