"""File-content fetching/decoding helpers for the packaging script."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from urllib.parse import quote

from github_api import GitHubError, api_get
from package.io import run_bytes


def count_patch_stats(patch: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def decode_repository_file(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    content = payload.get("content")
    if not isinstance(content, str):
        return None
    encoding = payload.get("encoding", "")
    if encoding == "base64":
        raw = base64.b64decode(content)
    else:
        raw = content.encode("utf-8")
    try:
        text = raw.decode("utf-8")
        return {"text": text, "binary": False, "encoding": "utf-8"}
    except UnicodeDecodeError:
        return {
            "text": None,
            "binary": True,
            "encoding": "base64",
            "base64": base64.b64encode(raw).decode("ascii"),
        }


def safe_github_file(slug: str, path: str, ref: str) -> dict[str, Any] | None:
    """Fetch a file at a ref via the contents API (fallback when the object is not local)."""
    encoded = quote(path, safe="/")
    try:
        payload = api_get(f"repos/{slug}/contents/{encoded}?ref={quote(ref, safe='')}")
    except GitHubError:
        return None
    if not isinstance(payload, dict) or payload.get("type") != "file":
        return None
    return decode_repository_file(payload)


def file_at(repo_root: Path, slug: str, path: str, ref: str) -> dict[str, Any] | None:
    """Prefer the local checkout (fetch-depth: 0); fall back to the API."""
    local = safe_git_show(repo_root, f"{ref}:{path}")
    if local is not None:
        return local
    return safe_github_file(slug, path, ref)


def safe_git_show(repo_root: Path, revision_path: str) -> dict[str, Any] | None:
    result = run_bytes(["git", "show", revision_path], cwd=repo_root, check=False)
    if result.returncode != 0:
        return None
    raw = result.stdout
    try:
        return {"text": raw.decode("utf-8"), "binary": False, "encoding": "utf-8"}
    except UnicodeDecodeError:
        return {
            "text": None,
            "binary": True,
            "encoding": "base64",
            "base64": base64.b64encode(raw).decode("ascii"),
        }
