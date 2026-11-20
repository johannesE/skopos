"""IO, subprocess, and git-metadata helpers for the packaging script."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from review_shared import DASHBOARD_MARKER  # noqa: F401  (re-exported)


SEVERITY_TOKENS = (
    "_⚠️ Potential issue_",
    "_🛑 Critical issue_",
    "_💡 Suggestion_",
    "_🧹 Nitpick_",
)


class PackagingError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def run_text(args: list[str], *, cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise PackagingError(message)
    return result.stdout


def run_bytes(
    args: list[str], *, cwd: Path | None = None, check: bool = False
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(args, cwd=cwd, capture_output=True)
    if check and result.returncode != 0:
        message = (
            result.stderr.decode("utf-8", errors="replace").strip()
            or result.stdout.decode("utf-8", errors="replace").strip()
            or "command failed"
        )
        raise PackagingError(message)
    return result


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def provenance_hash(payload: Any) -> str:
    normalized = json.dumps(
        payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def git_root() -> Path:
    return Path(run_text(["git", "rev-parse", "--show-toplevel"]).strip())


def git_branch_name(repo_root: Path) -> str:
    return run_text(["git", "branch", "--show-current"], cwd=repo_root).strip()


def git_remote_url(repo_root: Path) -> str:
    return run_text(
        ["git", "remote", "get-url", "origin"], cwd=repo_root, check=False
    ).strip()
