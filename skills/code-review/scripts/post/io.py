"""Terminal colors, errors, and JSONL audit-log helpers for the posting script."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from review_shared import DASHBOARD_MARKER  # noqa: F401  (re-exported)

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"


class PosterError(RuntimeError):
    pass


def color(text: str, code: str) -> str:
    return f"{code}{text}{NC}"


def jsonl_append(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def init_log_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
