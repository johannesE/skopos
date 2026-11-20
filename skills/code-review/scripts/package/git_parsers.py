"""Git output parsers for review packaging.

Parses `git diff --name-status` output into structured file lists and
`git log --format` output into structured commit lists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from package.io import run_text


def parse_name_status(output: str) -> list[dict[str, str]]:
    files = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status_token = parts[0]
        status_code = status_token[0]
        if status_code in {"R", "C"} and len(parts) >= 3:
            old_path, new_path = parts[1], parts[2]
        else:
            old_path = parts[1] if len(parts) >= 2 else ""
            new_path = parts[1] if len(parts) >= 2 else ""
        status = {
            "A": "added",
            "M": "modified",
            "D": "deleted",
            "R": "renamed",
            "C": "copied",
        }.get(status_code, status_token)
        files.append(
            {
                "status": status,
                "status_token": status_token,
                "old_path": old_path,
                "path": new_path,
            }
        )
    return files


def git_commit_list(repo_root: Path, merge_base: str) -> list[dict[str, Any]]:
    output = run_text(
        [
            "git",
            "log",
            "--reverse",
            "--format=%H%x1f%an%x1f%ae%x1f%aI%x1f%s%x1f%b%x1e",
            f"{merge_base}..HEAD",
        ],
        cwd=repo_root,
    )
    commits = []
    for chunk in output.split("\x1e"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split("\x1f", 5)
        while len(parts) < 6:
            parts.append("")
        sha, author_name, author_email, authored_at, subject, body = parts
        commits.append(
            {
                "sha": sha,
                "author_name": author_name,
                "author_email": author_email,
                "created_at": authored_at,
                "title": subject,
                "message": f"{subject}\n\n{body}".strip(),
                "body": body.strip(),
            }
        )
    return commits
