#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Package review context for pull-request and local-branch review workflows.

Outputs agent-readable JSON bundles with stable top-level sections:
source, meta, warnings, project, pr, issue, changes, review_state, and derived.
Uses the GitHub API (via `gh`) for PR mode and git merge-base deltas for local mode.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from github_api import (
    GitHubError,
    bot_login_from_env,
    build_review_state,
    fetch_issue_comments,
    fetch_pr,
    fetch_pr_commits,
    fetch_pr_files,
    fetch_pr_reviews,
    fetch_review_threads,
    file_status,
    list_open_prs_for_branch,
    pr_participants,
    pr_summary,
    repo_slug,
)
from package.file_contents import count_patch_stats, file_at, safe_git_show
from package.git_parsers import git_commit_list, parse_name_status
from package.io import (
    PackagingError,
    git_branch_name,
    git_remote_url,
    git_root,
    provenance_hash,
    run_text,
    utc_now,
    write_json,
)
from package.issue_context import issue_payload, resolve_issue_number
from package.output_layout import OutputLayout, make_output_layout
from package.review_state import (
    build_duplicate_candidates,
    build_finding_index,
    build_thread_timeline,
    summarize_notes,
)
from package.standards import collect_standards


def merge_base_sha(repo_root: Path, base_sha: str, head_sha: str) -> str:
    """GitHub diffs PRs against the merge base (three-dot), not the base branch tip."""
    result = run_text(
        ["git", "merge-base", base_sha, head_sha], cwd=repo_root, check=False
    ).strip()
    return result or base_sha


def derived_section(
    discussions: list[dict[str, Any]], issue: dict[str, Any] | None
) -> dict[str, Any]:
    finding_index = build_finding_index(discussions)
    return {
        "issue_requirements": (issue or {}).get("requirements", []),
        "finding_index": finding_index,
        "duplicate_candidates": build_duplicate_candidates(finding_index),
        "thread_timeline": build_thread_timeline(discussions),
    }


def build_pr_package(
    args: argparse.Namespace, layout: OutputLayout, repo_root: Path
) -> dict[str, Any]:
    slug = repo_slug()
    number = int(args.pr_number)
    pr = fetch_pr(slug, number)
    files = fetch_pr_files(slug, number)
    commits = fetch_pr_commits(slug, number)
    reviews = fetch_pr_reviews(slug, number)
    threads = fetch_review_threads(slug, number)
    issue_comments = fetch_issue_comments(slug, number)
    discussions, notes = build_review_state(threads, issue_comments)

    head_sha = (pr.get("head") or {}).get("sha") or ""
    start_sha = (pr.get("base") or {}).get("sha") or ""
    base_sha = merge_base_sha(repo_root, start_sha, head_sha) if start_sha else ""

    issue_number = args.issue_number or resolve_issue_number(
        slug, number, pr.get("title") or "", pr.get("body") or ""
    )
    issue = issue_payload(slug, issue_number)

    file_entries = []
    for change in files:
        path = change.get("filename") or ""
        old_path = change.get("previous_filename") or path
        status = file_status(change)
        patch = change.get("patch") or ""
        additions, deletions = count_patch_stats(patch)
        head_content = None
        base_content = None
        if args.include_file_contents:
            if status != "deleted" and path and head_sha:
                head_content = file_at(repo_root, slug, path, head_sha)
            if status != "added" and old_path and base_sha:
                base_content = file_at(repo_root, slug, old_path, base_sha)
        file_entries.append(
            {
                "path": path,
                "old_path": old_path,
                "status": status,
                "renamed": status == "renamed",
                "new_file": status == "added",
                "deleted_file": status == "deleted",
                "additions": additions,
                "deletions": deletions,
                "patch": patch,
                "patch_missing": bool(not patch and status != "deleted"),
                "head_content": head_content,
                "base_content": base_content,
            }
        )

    warnings: list[dict[str, Any]] = []
    if issue_number is not None and issue is None:
        warnings.append(
            {
                "code": "ISSUE_CONTEXT_UNAVAILABLE",
                "message": (
                    f"Referenced issue #{issue_number} could not be fetched "
                    "(not found, inaccessible, or a pull request); reviewing without issue context."
                ),
            }
        )
    changed_files = int(pr.get("changed_files") or 0)
    if changed_files > len(file_entries):
        warnings.append(
            {
                "code": "CHANGES_TRUNCATED",
                "message": (
                    f"Fetched {len(file_entries)} files but the pull request reports"
                    f" {changed_files} changed files."
                ),
            }
        )
    missing_patches = [entry["path"] for entry in file_entries if entry["patch_missing"]]
    if missing_patches:
        warnings.append(
            {
                "code": "PATCH_UNAVAILABLE",
                "message": (
                    "GitHub returned no patch (binary or too large) for: "
                    + ", ".join(missing_patches[:20])
                    + ". Inline comments cannot target these files."
                ),
            }
        )

    standards = collect_standards(
        repo_root,
        sorted({entry["path"] for entry in file_entries if entry.get("path")}),
    )
    context = {
        "schema_version": "review-context/v1",
        "source": {
            "kind": "github_pr",
            "pr_number": number,
            "issue_number": issue_number,
            "repo_root": str(repo_root),
            "generated_at": utc_now(),
            "generated_by": "package_review_context.py",
        },
        "meta": {"compact_bundle": False, "bundle_references": []},
        "warnings": warnings,
        "project": {
            "full_name": slug,
            "default_branch": ((pr.get("base") or {}).get("repo") or {}).get(
                "default_branch"
            ),
            "web_url": ((pr.get("base") or {}).get("repo") or {}).get("html_url"),
            "remote_url": git_remote_url(repo_root),
        },
        "standards": standards,
        "pr": pr_summary(pr, reviews),
        "issue": issue,
        "changes": {
            "base_sha": base_sha,
            "start_sha": start_sha,
            "head_sha": head_sha,
            "commit_count": len(commits),
            "commits": [
                {
                    "sha": item.get("sha"),
                    "title": ((item.get("commit") or {}).get("message") or "").split("\n", 1)[0],
                    "message": (item.get("commit") or {}).get("message"),
                    "author_name": ((item.get("commit") or {}).get("author") or {}).get("name"),
                    "created_at": ((item.get("commit") or {}).get("author") or {}).get("date"),
                }
                for item in commits
            ],
            "files": file_entries,
        },
        "review_state": {
            "bot_login": bot_login_from_env(),
            "participants": pr_participants(pr, reviews),
            "discussions": discussions,
            "notes": notes,
            "dashboard_notes": summarize_notes(notes),
        },
        "derived": derived_section(discussions, issue),
    }

    write_json(layout.raw_dir / "pr.json", pr)
    write_json(layout.raw_dir / "files.json", files)
    write_json(layout.raw_dir / "review_threads.json", threads)
    write_json(layout.raw_dir / "issue_comments.json", issue_comments)
    write_json(layout.raw_dir / "reviews.json", reviews)
    write_json(layout.raw_dir / "commits.json", commits)
    if issue is not None:
        write_json(layout.raw_dir / "issue.json", issue)
    return context


def build_local_package(
    args: argparse.Namespace, layout: OutputLayout, repo_root: Path
) -> dict[str, Any]:
    base_ref = args.base_ref
    merge_base = run_text(
        ["git", "merge-base", base_ref, "HEAD"], cwd=repo_root
    ).strip()
    head_sha = run_text(["git", "rev-parse", "HEAD"], cwd=repo_root).strip()
    branch = git_branch_name(repo_root)
    remote_url = git_remote_url(repo_root)
    name_status = parse_name_status(
        run_text(
            ["git", "diff", "--name-status", "-M", f"{merge_base}", "HEAD"],
            cwd=repo_root,
        )
    )
    commits = git_commit_list(repo_root, merge_base)
    warnings: list[str] = []

    pr_number = args.pr
    include_discussions = args.include_discussions

    if args.auto_enrich and not pr_number:
        candidates = list_open_prs_for_branch(branch)
        if candidates:
            latest = max(candidates, key=lambda item: item.get("updatedAt") or "")
            pr_number = int(latest["number"])
            include_discussions = True
            warnings.append(f"AUTO_ENRICHED_WITH_PR: #{pr_number}")

    if include_discussions and not pr_number:
        raise PackagingError("--include-discussions requires --pr in local mode.")

    pr = None
    reviews: list[dict[str, Any]] = []
    discussions: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    participants: dict[str, Any] = {
        "author": None,
        "assignees": [],
        "reviewers": [],
        "allowed_resolution_users": [],
    }
    slug = ""
    if pr_number:
        slug = repo_slug()
        pr = fetch_pr(slug, pr_number)
        pr_branch = (pr.get("head") or {}).get("ref") or ""
        if pr_branch and pr_branch != branch:
            raise PackagingError(
                f"Local branch '{branch}' does not match PR #{pr_number} head branch '{pr_branch}'."
            )
        reviews = fetch_pr_reviews(slug, pr_number)
        participants = pr_participants(pr, reviews)
        if include_discussions:
            discussions, notes = build_review_state(
                fetch_review_threads(slug, pr_number),
                fetch_issue_comments(slug, pr_number),
            )

    issue = issue_payload(slug or repo_slug(), args.issue_number) if args.issue_number else None

    if not discussions:
        warnings.append(
            "OFFLINE_REPLAY_LIMITED: No PR discussion state included; lifecycle and duplicate replay are limited."
        )

    file_entries = []
    for item in name_status:
        path = item["path"]
        old_path = item["old_path"]
        status = item["status"]
        diff_targets = [target for target in dict.fromkeys([old_path, path]) if target]
        patch = run_text(
            ["git", "diff", "--unified=3", merge_base, "HEAD", "--", *diff_targets],
            cwd=repo_root,
        )
        additions, deletions = count_patch_stats(patch)
        head_content = None
        base_content = None
        if args.include_file_contents:
            if status != "deleted" and path:
                head_content = safe_git_show(repo_root, f"HEAD:{path}")
            if status != "added" and old_path:
                base_content = safe_git_show(repo_root, f"{merge_base}:{old_path}")
        file_entries.append(
            {
                "path": path,
                "old_path": old_path,
                "status": status,
                "status_token": item["status_token"],
                "patch": patch,
                "additions": additions,
                "deletions": deletions,
                "head_content": head_content,
                "base_content": base_content,
            }
        )

    standards = collect_standards(
        repo_root,
        sorted({entry["path"] for entry in file_entries if entry.get("path")}),
    )
    context = {
        "schema_version": "review-context/v1",
        "source": {
            "kind": "local_branch",
            "issue_number": args.issue_number,
            "pr_number": pr_number,
            "repo_root": str(repo_root),
            "generated_at": utc_now(),
            "generated_by": "package_review_context.py",
        },
        "meta": {"compact_bundle": False, "bundle_references": []},
        "warnings": warnings,
        "project": {"remote_url": remote_url, "branch": branch, "full_name": slug or None},
        "standards": standards,
        "pr": pr_summary(pr, reviews) if pr else None,
        "issue": issue,
        "changes": {
            "base_ref": base_ref,
            "base_sha": merge_base,
            "merge_base": merge_base,
            "head_sha": head_sha,
            "commit_range": f"{merge_base}..{head_sha}",
            "commit_count": len(commits),
            "commits": commits,
            "files": file_entries,
        },
        "review_state": {
            "bot_login": bot_login_from_env() if pr_number else "",
            "participants": participants,
            "discussions": discussions,
            "notes": notes,
            "dashboard_notes": summarize_notes(notes),
        },
        "derived": derived_section(discussions, issue),
    }

    write_json(
        layout.raw_dir / "git-context.json",
        {
            "branch": branch,
            "base_ref": base_ref,
            "merge_base": merge_base,
            "head_sha": head_sha,
            "remote_url": remote_url,
        },
    )
    write_json(layout.raw_dir / "commits.json", commits)
    write_json(layout.raw_dir / "changes.json", file_entries)
    if pr is not None:
        write_json(layout.raw_dir / "pr.json", pr)
    if discussions:
        write_json(layout.raw_dir / "discussions.json", discussions)
    if issue is not None:
        write_json(layout.raw_dir / "issue.json", issue)
    return context


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package pull-request or local-branch review context into agent-readable JSON."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    common_parent = argparse.ArgumentParser(add_help=False)
    common_parent.add_argument(
        "--output-dir",
        default=".skopos/review-context",
        help="Base output directory for generated review packages.",
    )
    common_parent.add_argument(
        "--include-file-contents",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include base/head file contents inline in context.json (default: true).",
    )

    pr_parser = subparsers.add_parser(
        "pr", parents=[common_parent], help="Package a GitHub pull request."
    )
    pr_parser.add_argument("pr_number", help="Pull request number.")
    pr_parser.add_argument(
        "--issue-number", type=int, help="Explicit linked issue number override."
    )

    local_parser = subparsers.add_parser(
        "local", parents=[common_parent], help="Package committed branch changes only."
    )
    local_parser.add_argument(
        "--base-ref",
        default="main",
        help="Base ref used for merge-base calculation (default: main).",
    )
    local_parser.add_argument(
        "--issue-number", type=int, help="Optional linked issue number."
    )
    local_parser.add_argument(
        "--pr", type=int, help="Optional PR number to enrich local packages with PR metadata."
    )
    local_parser.add_argument(
        "--auto-enrich",
        action="store_true",
        help="Auto-detect an open PR for the current branch and include its discussion state.",
    )
    local_parser.add_argument(
        "--include-discussions",
        action="store_true",
        help="Include PR review threads/comments in local mode (requires --pr and matching branch).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo_root = git_root()
    output_base = Path(args.output_dir)

    if args.command == "pr":
        layout = make_output_layout(output_base, "pr", str(args.pr_number))
        context = build_pr_package(args, layout, repo_root)
    else:
        branch = git_branch_name(repo_root)
        safe_branch = re.sub(r"[^A-Za-z0-9._-]+", "-", branch or "detached")
        layout = make_output_layout(output_base, "local", safe_branch)
        context = build_local_package(args, layout, repo_root)

    context.setdefault("meta", {})
    context["meta"]["provenance_hash"] = provenance_hash(context)

    manifest = {
        "schema_version": context["schema_version"],
        "generated_at": context["source"]["generated_at"],
        "source": context["source"],
        "meta": context.get("meta", {}),
        "root": str(layout.root),
        "context_json": str(layout.context_path),
        "raw_dir": str(layout.raw_dir),
        "summary": {
            "file_count": len(context["changes"]["files"]),
            "changed_lines": sum(
                int(f.get("additions") or 0) + int(f.get("deletions") or 0)
                for f in context["changes"]["files"]
            ),
            "commit_count": context["changes"]["commit_count"],
            "issue_number": context["source"].get("issue_number"),
            "duplicate_candidates": len(context["derived"]["duplicate_candidates"]),
            "warning_count": len(context.get("warnings", [])),
        },
        "agent_notes": [
            "Use context.json as the primary input for review, optimization, and evaluation.",
            "Treat raw/*.json as optional debugging artifacts.",
            "Do not refetch live GitHub state; the package is the source of truth.",
            "Use context.standards (AGENTS.md / CLAUDE.md + coding guidelines) for project conventions.",
        ],
    }

    write_json(layout.context_path, context)
    write_json(layout.manifest_path, manifest)
    print(
        json.dumps(
            {
                "context_json": str(layout.context_path),
                "manifest_json": str(layout.manifest_path),
                "changed_lines": manifest["summary"]["changed_lines"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (PackagingError, GitHubError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
