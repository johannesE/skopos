#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML>=6.0"]
# ///
"""Post generated review comments to a GitHub pull request.

Responsibilities:
- route inline/general/dashboard/reply markdown files to the correct API path
- submit all inline findings as one pull request review
- suppress duplicates via finding_key/root_cause_cluster/headline matching
- validate resolution metadata before auto-closing threads
- upsert a singleton dashboard note
- emit JSONL audit logs for deterministic replay and debugging
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from post.comment_classification import (
    append_review_metadata,
    build_dedupe_signature,
    contains_lgtm_only,
    extract_identifier_candidates,
    has_actionable_severity,
    is_nitpick_comment,
    is_summary_comment,
    new_side_hunk_index,
    normalize_suggestion_range,
    parse_line_number,
    parse_suggestion_blocks,
    range_outside_single_hunk,
    suggestion_duplicates_enclosing_structure,
)
from post.comment_handlers import (
    post_general_comment,
    post_reply_note,
    queue_inline_comment,
    upsert_dashboard_note,
)
from post.comment_model import ReviewComment
from post.discussion_matching import find_matching_discussion
from post.io import (
    BLUE,
    DASHBOARD_MARKER,
    GREEN,
    RED,
    YELLOW,
    PosterError,
    color,
    init_log_file,
    jsonl_append,
)
from github_api import GitHubError
from post.pr_context_loader import load_live_context, load_packaged_context
from post.publisher import submit_review
from post.thread_resolution import resolve_thread_after_reply


def latest_review_dir(review_root: Path, pr_number: str) -> Path | None:
    mr_dir = review_root / pr_number
    if not mr_dir.is_dir():
        return None
    candidates = [path for path in mr_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


class ReviewPoster:
    def __init__(
        self,
        *,
        pr_number: str,
        review_dir: Path,
        dry_run: bool,
        context_path: Path | None = None,
    ) -> None:
        self.pr_number = pr_number
        self.review_dir = review_dir
        # Offline validation against the packaged context never mutates GitHub.
        self.dry_run = dry_run or context_path is not None
        self.pending_inline: list[tuple[str, dict[str, Any]]] = []

        self.total = 0
        self.inline_posted = 0
        self.notes_created = 0
        self.failed = 0
        self.skipped = 0
        self.updated = 0
        self.replied = 0
        self.resolved_threads = 0
        self.resolve_failed = 0
        self.resolve_validation_failed = 0

        self.skipped_log = review_dir / "posting-skipped.jsonl"
        self.posted_log = review_dir / "posting-posted.jsonl"
        self.updated_log = review_dir / "posting-updated.jsonl"
        self.replied_log = review_dir / "posting-replied.jsonl"
        self.resolved_log = review_dir / "posting-resolved.jsonl"
        self.resolve_failed_log = review_dir / "posting-resolve-failed.jsonl"
        self.resolve_validation_failed_log = (
            review_dir / "posting-resolve-validation-failed.jsonl"
        )

        for path in (
            self.skipped_log,
            self.posted_log,
            self.updated_log,
            self.replied_log,
            self.resolved_log,
            self.resolve_failed_log,
            self.resolve_validation_failed_log,
        ):
            init_log_file(path)

        self.seen_signatures: dict[str, str] = {}
        ctx = (
            load_packaged_context(context_path)
            if context_path is not None
            else load_live_context(pr_number)
        )
        self.offline = ctx.offline
        self.slug = ctx.slug
        self.existing_discussions = ctx.existing_discussions
        self.existing_notes = ctx.existing_notes
        self.ai_reviewer_username = ctx.ai_reviewer_username
        self.allowed_resolution_users = ctx.allowed_resolution_users
        self.changed_files = ctx.changed_files
        self.changed_patches = ctx.changed_patches
        self.base_sha = ctx.base_sha
        self.head_sha = ctx.head_sha

        self.comments = [
            ReviewComment.from_path(path) for path in self._find_markdown_files()
        ]
        self.has_dashboard_file = any(
            comment.comment_type == "dashboard" for comment in self.comments
        )

    def _find_markdown_files(self) -> list[Path]:
        files = sorted(
            [
                path
                for path in self.review_dir.iterdir()
                if path.is_file() and path.suffix.lower() in {".md", ".markdown"}
            ]
        )
        if not files:
            raise PosterError(f"No markdown files found in {self.review_dir}")
        return files

    def _own_marker_notes(self, marker: str) -> list[dict[str, Any]]:
        """Marker comments authored by the reviewer identity (only those are editable)."""
        return [
            note
            for note in self.existing_notes
            if not note.get("system")
            and marker in (note.get("body") or "")
            and (
                not self.ai_reviewer_username
                or ((note.get("author") or {}).get("username") or "")
                == self.ai_reviewer_username
            )
        ]

    def discussion_by_id(self, discussion_id: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.existing_discussions
                if str(item.get("id") or "") == str(discussion_id)
            ),
            None,
        )

    def find_note_id_by_marker(self, marker: str) -> str:
        matches = self._own_marker_notes(marker)
        if not matches:
            return ""
        latest = max(matches, key=lambda note: int(note.get("id") or 0))
        return str(latest.get("id") or "")

    def dashboard_note_count(self) -> int:
        return len(self._own_marker_notes(DASHBOARD_MARKER))

    def print_header(self) -> None:
        print("========================================")
        print("Skopos - Pull Request Review Posting")
        print("========================================")
        print(f"PR:           #{self.pr_number}")
        print(f"Review Dir:   {self.review_dir}")
        print(f"Source:       {'packaged context (offline)' if self.offline else 'live GitHub state'}")
        print(f"Reviewer:     {self.ai_reviewer_username or 'unknown'}")
        print(f"Dry-run:      {self.dry_run}")
        print()
        print("Found comment files:")
        for comment in self.comments:
            print(f"  - {comment.filename}")
        print()
        print(color("Existing review context loaded.", GREEN))
        print(f"  BASE_SHA:  {self.base_sha[:12]}...")
        print(f"  HEAD_SHA:  {self.head_sha[:12]}...")
        print()

        dashboard_count = self.dashboard_note_count()
        if dashboard_count > 1:
            print(
                color(
                    f"Warning: Found {dashboard_count} dashboard comments. Script will upsert the latest one.",
                    YELLOW,
                )
            )

    def log_skip(self, filename: str, reason: str, **extra: Any) -> None:
        payload = {"file": filename, "reason": reason}
        payload.update(extra)
        jsonl_append(self.skipped_log, payload)
        self.skipped += 1

    def validate_comment_against_changes(
        self, comment: ReviewComment
    ) -> tuple[str, dict[str, Any]] | None:
        if comment.comment_type != "inline":
            return None
        if not comment.file_path:
            return None
        if comment.file_path not in self.changed_files:
            return (
                "inline_file_not_in_pr",
                {"file_path": comment.file_path or "", "changed": False},
            )

        line_number = parse_line_number(comment.line_number)
        if line_number is None:
            return None
        start_line = parse_line_number(comment.start_line)
        if start_line is not None and start_line > line_number:
            return (
                "start_line_after_line",
                {"file_path": comment.file_path, "start_line": start_line, "line": line_number},
            )

        body, start_line, line_number, range_error = normalize_suggestion_range(
            comment.body, line_number, start_line
        )
        if range_error:
            return (range_error, {"file_path": comment.file_path, "line_number": line_number})
        comment.body = body
        comment.line_number = str(line_number)
        comment.start_line = str(start_line) if start_line is not None else ""

        patch = self.changed_patches.get(comment.file_path) or ""
        if not patch:
            return (
                "inline_patch_unavailable",
                {"file_path": comment.file_path, "line_number": line_number},
            )
        if new_side_hunk_index(patch, line_number) is None:
            return (
                "inline_line_not_in_diff",
                {"file_path": comment.file_path, "line_number": line_number},
            )
        range_start = start_line if start_line is not None else line_number
        if range_outside_single_hunk(patch, range_start, line_number):
            return (
                "inline_range_outside_single_hunk",
                {"file_path": comment.file_path, "start_line": range_start, "line_number": line_number},
            )

        suggestion_blocks = parse_suggestion_blocks(comment.body)
        if suggestion_blocks and suggestion_duplicates_enclosing_structure(
            patch, range_start, suggestion_blocks
        ):
            return (
                "suggestion_duplicates_enclosing_structure",
                {"file_path": comment.file_path, "line_number": line_number},
            )

        identifiers = extract_identifier_candidates(comment.body)
        if not identifiers:
            return None

        patch_lower = patch.lower()
        if any(identifier.lower() in patch_lower for identifier in identifiers):
            return None
        return (
            "inline_identifier_not_in_diff",
            {"file_path": comment.file_path, "identifiers": identifiers},
        )

    def validate_and_resolve_thread(self, comment: ReviewComment, note_id: str) -> None:
        resolve_thread_after_reply(self, comment, note_id)

    def process_all(self) -> None:
        print(color("Processing review files...", BLUE))
        print()
        dashboard_exists = bool(self.find_note_id_by_marker(DASHBOARD_MARKER))

        for comment in self.comments:
            self.total += 1
            print("----------------------------------------")
            print(f"Processing: {comment.filename}")

            if comment.comment_type != "dashboard":
                comment.body = append_review_metadata(
                    comment.body,
                    comment.finding_key,
                    comment.rule_id,
                    comment.root_cause_cluster,
                )

            print(f"  Type: {comment.comment_type}")

            if comment.comment_type not in {"reply", "dashboard"}:
                signature = build_dedupe_signature(
                    comment.file_path,
                    comment.finding_key,
                    comment.root_cause_cluster,
                    comment.body,
                )
                if signature in self.seen_signatures:
                    print(
                        color(
                            f"  Skipped: Duplicate generated finding in this run ({self.seen_signatures[signature]})",
                            YELLOW,
                        )
                    )
                    self.log_skip(
                        comment.filename, "duplicate_in_run", signature=signature
                    )
                    continue
                self.seen_signatures[signature] = comment.filename

                existing_match = find_matching_discussion(
                    self.existing_discussions,
                    file_path=comment.file_path,
                    body=comment.body,
                    finding_key=comment.finding_key,
                    rule_id=comment.rule_id,
                    root_cause_cluster=comment.root_cause_cluster,
                    allowed_users=self.allowed_resolution_users,
                    desired_states={"open"},
                )
                if existing_match:
                    print(
                        color(
                            f"  Skipped: Matching unresolved discussion already exists ({existing_match.discussion_id})",
                            YELLOW,
                        )
                    )
                    self.log_skip(
                        comment.filename,
                        "duplicate_existing_discussion",
                        discussion_id=existing_match.discussion_id,
                        matching_strategy=existing_match.strategy,
                        matching_score=existing_match.score,
                    )
                    continue

                previous_match = find_matching_discussion(
                    self.existing_discussions,
                    file_path=comment.file_path,
                    body=comment.body,
                    finding_key=comment.finding_key,
                    rule_id=comment.rule_id,
                    root_cause_cluster=comment.root_cause_cluster,
                    allowed_users=self.allowed_resolution_users,
                    desired_states={"resolved", "waived", "acknowledged"},
                )
                if previous_match:
                    print(
                        color(
                            f"  Skipped: Matching {previous_match.state} discussion already exists ({previous_match.discussion_id})",
                            YELLOW,
                        )
                    )
                    self.log_skip(
                        comment.filename,
                        f"duplicate_{previous_match.state}_discussion",
                        discussion_id=previous_match.discussion_id,
                        matching_strategy=previous_match.strategy,
                        matching_score=previous_match.score,
                    )
                    continue

            if contains_lgtm_only(comment.body):
                print(
                    color("  Skipped: LGTM/praise-only comments are not posted", YELLOW)
                )
                self.log_skip(comment.filename, "lgtm_only")
                continue

            if is_nitpick_comment(comment.body) and comment.post_nitpick != "true":
                print(
                    color(
                        "  Skipped: Nitpick requires post_nitpick: true with correctness impact",
                        YELLOW,
                    )
                )
                self.log_skip(comment.filename, "nitpick_without_correctness_impact")
                continue

            if comment.certainty == "low" and comment.post_low_certainty != "true":
                print(
                    color(
                        "  Skipped: Low-certainty finding goes to dashboard unless post_low_certainty: true",
                        YELLOW,
                    )
                )
                self.log_skip(comment.filename, "low_certainty_dashboard_only")
                continue

            if (
                is_summary_comment(comment.comment_type, comment.body)
                and not has_actionable_severity(comment.body)
                and (dashboard_exists or self.has_dashboard_file)
            ):
                print(
                    color(
                        "  Skipped: Summary suppressed (dashboard-only run with no critical/major/minor findings)",
                        YELLOW,
                    )
                )
                self.log_skip(comment.filename, "summary_dashboard_only")
                continue

            validation_failure = self.validate_comment_against_changes(comment)
            if validation_failure is not None:
                reason, extra = validation_failure
                print(
                    color(
                        f"  Skipped: Inline comment failed pre-post validation ({reason})",
                        YELLOW,
                    )
                )
                self.log_skip(comment.filename, reason, **extra)
                continue

            if comment.comment_type == "reply":
                self.process_reply(comment)
                continue
            if comment.comment_type == "dashboard":
                dashboard_exists = True
                self.process_dashboard(comment)
                continue
            if comment.comment_type == "inline":
                queue_inline_comment(self, comment)
                continue
            post_general_comment(self, comment)

    def process_reply(self, comment: ReviewComment) -> None:
        post_reply_note(self, comment)

    def process_dashboard(self, comment: ReviewComment) -> None:
        upsert_dashboard_note(self, comment)

    def submit_review(self) -> int:
        return submit_review(self)

    def summary_payload(self) -> dict[str, Any]:
        return {
            "pr_number": self.pr_number,
            "dry_run": self.dry_run,
            "total": self.total,
            "inline_posted": self.inline_posted,
            "comments_created": self.notes_created,
            "updated": self.updated,
            "replied": self.replied,
            "resolved": self.resolved_threads,
            "resolve_invalid": self.resolve_validation_failed,
            "resolve_failed": self.resolve_failed,
            "skipped": self.skipped,
            "failed": self.failed,
        }

    def print_summary(self) -> None:
        print()
        print("========================================")
        print("Posting Summary")
        print("========================================")
        print(f"Total files:     {self.total}")
        print(f"Inline posted:   {color(str(self.inline_posted), GREEN)}")
        print(f"Comments posted: {color(str(self.notes_created), GREEN)}")
        print(f"Updated:         {color(str(self.updated), GREEN)}")
        print(f"Replied:         {color(str(self.replied), GREEN)}")
        print(f"Resolved:        {color(str(self.resolved_threads), GREEN)}")
        print(f"Resolve invalid: {color(str(self.resolve_validation_failed), YELLOW)}")
        print(f"Resolve failed:  {color(str(self.resolve_failed), YELLOW)}")
        print(f"Skipped:         {color(str(self.skipped), YELLOW)}")
        print(f"Failed:          {color(str(self.failed), RED)}")
        print()
        print("Posting logs:")
        print(f"  - {self.posted_log}")
        print(f"  - {self.updated_log}")
        print(f"  - {self.replied_log}")
        print(f"  - {self.resolved_log}")
        print(f"  - {self.resolve_validation_failed_log}")
        print(f"  - {self.resolve_failed_log}")
        print(f"  - {self.skipped_log}")
        print("========================================")

    def exit_code(self) -> int:
        if self.failed > 0:
            return 1
        if self.resolve_failed > 0 or self.resolve_validation_failed > 0:
            return 1
        return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post generated review comments to a GitHub pull request."
    )
    parser.add_argument("pr_number")
    parser.add_argument("review_dir", nargs="?")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and simulate actions without creating or updating anything on GitHub.",
    )
    parser.add_argument(
        "--context",
        type=Path,
        help=(
            "Validate offline against a packaged context.json instead of live GitHub state. "
            "Implies --dry-run and needs no GitHub token."
        ),
    )
    return parser.parse_args(argv)


def resolve_review_dir(args: argparse.Namespace) -> Path:
    if args.review_dir:
        path = Path(args.review_dir)
    else:
        review_root = Path(
            os.environ.get("SKOPOS_REVIEW_DIR_BASE", Path.cwd() / ".skopos/review")
        )
        path = latest_review_dir(review_root, args.pr_number)
        if path is None:
            raise PosterError(
                "review_dir was not provided and no existing run directory was found. "
                "Provide <review_dir> explicitly or set SKOPOS_REVIEW_DIR_BASE and generate comments first."
            )
    if not path.is_dir():
        raise PosterError(f"Review directory not found: {path}")
    return path


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    review_dir = resolve_review_dir(args)
    poster = ReviewPoster(
        pr_number=args.pr_number,
        review_dir=review_dir,
        dry_run=args.dry_run,
        context_path=args.context,
    )
    poster.print_header()
    poster.process_all()
    review_exit = poster.submit_review()
    poster.print_summary()
    (review_dir / "posting-summary.json").write_text(
        json.dumps(poster.summary_payload(), indent=2) + "\n", encoding="utf-8"
    )
    return review_exit or poster.exit_code()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (PosterError, GitHubError) as exc:
        print(color(f"Error: {exc}", RED), file=sys.stderr)
        raise SystemExit(1) from None
