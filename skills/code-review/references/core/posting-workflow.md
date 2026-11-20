---
name: code-review.reference.posting-workflow
description: Python posting executor commands, options, and expected behavior.
---

# Posting Workflow Reference

Only the Python executor changes GitHub state.

## Who posts

- **In CI (Skopos GitHub Action):** you only **validate**. Run the executor offline against the packaged context; it needs no token and never touches GitHub. After you finish, the entrypoint runs the executor again against live PR state and posts.
- **Locally (developer running the skill by hand):** the same executor can post directly with an authenticated `gh`.

## Commands

```bash
# CI: offline validation against the package (implies --dry-run)
skopos-post <pr_number> "$SKOPOS_REVIEW_DIR" --context <path/to/context.json>

# Local: validate against live PR state without posting
uv run "$SKOPOS_SKILL_DIR/scripts/post_review_comments.py" <pr_number> <review_dir> --dry-run

# Local: post (inline findings as one review, plus dashboard, replies, resolutions)
uv run "$SKOPOS_SKILL_DIR/scripts/post_review_comments.py" <pr_number> <review_dir>

# Reuse the latest review directory for a PR (under $SKOPOS_REVIEW_DIR_BASE)
uv run "$SKOPOS_SKILL_DIR/scripts/post_review_comments.py" <pr_number>
```

## Options

- `--dry-run` - validate every posting decision, including inline diff checks, without changing GitHub
- `--context <context.json>` - validate offline against a packaged context instead of live state (implies `--dry-run`)

## Deterministic behavior

The executor is responsible for:

- loading existing review threads and PR comments
- suppressing duplicate generated findings
- suppressing comments when a matching unresolved thread already exists, and logging the matching strategy used
- checking every inline comment against the diff: the file must be in the PR, and `line` (and `start_line`) must be on the new side of one diff hunk; otherwise the comment is skipped (`inline_line_not_in_diff`, `inline_range_outside_single_hunk`)
- converting legacy `suggestion:-N+M` offsets into a GitHub `start_line`..`line` range
- submitting all inline findings as **one** pull request review (event `COMMENT`); if GitHub rejects the batch, retrying each comment individually
- replying to existing threads when `type: reply` is used
- validating `resolve_thread: true` before resolving (ownership, resolution metadata, `fixed_by_code` must touch changed lines), then resolving the review thread
- rejecting reply comments that read like resolutions but omit `resolve_thread: true`
- upserting the singleton dashboard comment (marker `<!-- skopos:review-dashboard -->`)
- writing JSONL audit logs and `posting-summary.json` in the review directory

## Reading a dry run

A healthy dry run tells you:

- whether the dashboard would be created or updated
- which inline comments would be submitted, and which were skipped and why
- which threads would receive replies and which would be resolved
- whether any resolution requests are invalid

Fix every skipped inline finding before you finish. Re-anchor it to a line inside the diff, or move it to the dashboard. Then dry-run again. `posting-skipped.jsonl` lists the reasons.
