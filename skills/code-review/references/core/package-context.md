---
name: code-review.reference.package-context
description: Package-first review context commands and schema reference.
---

# Package Context Reference

`scripts/package_review_context.py` (under `$SKOPOS_SKILL_DIR`) freezes review input into JSON. In CI the entrypoint has already run it; the package is attached to your prompt.

## Commands

```bash
# GitHub pull request (needs an authenticated gh)
uv run "$SKOPOS_SKILL_DIR/scripts/package_review_context.py" pr <pr_number>

# Local committed branch delta only (no GitHub access needed)
uv run "$SKOPOS_SKILL_DIR/scripts/package_review_context.py" local --base-ref main

# Local committed branch delta plus PR review-thread state
uv run "$SKOPOS_SKILL_DIR/scripts/package_review_context.py" local --base-ref main --pr <pr_number> --include-discussions

# Local committed branch delta, auto-enriched with the open PR for this branch
uv run "$SKOPOS_SKILL_DIR/scripts/package_review_context.py" local --base-ref main --auto-enrich
```

## Local mode rules

- Uses `git merge-base <base-ref> HEAD`.
- Includes committed branch changes only.
- Excludes unstaged, staged-but-uncommitted, and untracked files.
- `--pr --include-discussions` is an explicit opt-in for lifecycle replay.
- `--auto-enrich` picks the most recently updated open PR whose head is the current branch.

## Output structure

The packager writes:

- `context.json` - primary agent input
- `manifest.json` - summary and file locations
- `raw/*.json` - raw GitHub API payloads for debugging

## Canonical JSON sections

```json
{
  "schema_version": "review-context/v1",
  "source": {},
  "meta": {},
  "warnings": [],
  "project": {},
  "standards": {},
  "pr": {},
  "issue": {},
  "changes": {},
  "review_state": {},
  "derived": {}
}
```

Key sections:

- `source` - package origin, timestamps, PR or local mode
- `meta` - provenance hash and package metadata
- `warnings` - degraded-mode warnings (see below)
- `standards` - embedded `AGENTS.md` / `CLAUDE.md` files (root + nearest per changed file), `.github/copilot-instructions.md`, and `docs/coding-guidelines.md`; the authoritative reference for the code-standards and project-conventions checks
- `pr` - title, description, branches, author, assignees, reviewers
- `issue` - the linked issue (closing reference or `#N` mention) with extracted requirements
- `changes.base_sha` / `changes.head_sha` - merge base and head of the PR
- `changes.files[]` - path, status, patch, additions/deletions, base/head contents
- `review_state.bot_login` - the reviewer identity; only threads it opened may be resolved
- `review_state.participants` - users whose replies count as waivers/acknowledgements
- `review_state.discussions[]` - review threads (`kind: review_thread`, resolvable) and plain PR comments (`kind: issue_comment`, not resolvable). `id` is the value to use as `discussion_id`.
- `review_state.notes` - plain PR conversation comments (including any existing dashboard)
- `derived.finding_index` - normalized finding list
- `derived.duplicate_candidates` - likely duplicate thread groups
- `derived.thread_timeline` - chronological discussion events

Warnings:

- `OFFLINE_REPLAY_LIMITED` - no PR discussion state is included, so duplicate suppression and lifecycle replay must stay conservative.
- `CHANGES_TRUNCATED` - GitHub returned fewer files than the PR reports (very large PRs).
- `PATCH_UNAVAILABLE` - no patch for some files (binary or too large); inline comments cannot target them.
- `ISSUE_CONTEXT_UNAVAILABLE` - a referenced issue could not be fetched.

## Agent usage

- Treat `context.json` as the source of truth. It already contains every patch and file body you need.
- Do not try to fetch live GitHub state; in CI you have no GitHub credentials.
- If `warnings` contains `OFFLINE_REPLAY_LIMITED`, avoid thread-resolution claims that require missing discussion history.
- Explore the JSON with targeted `jq` queries, never by dumping whole files.
