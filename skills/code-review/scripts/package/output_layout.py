"""Output layout helpers for review context packages.

Defines the OutputLayout dataclass and a factory that creates the run directory
structure (root + raw subdir) for a given source kind and identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class OutputLayout:
    root: Path
    raw_dir: Path
    context_path: Path
    manifest_path: Path


def make_output_layout(
    base_output: Path, source_kind: str, identifier: str
) -> OutputLayout:
    prefix = "local" if source_kind == "local" else "pr"
    run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    root = base_output / source_kind / identifier / run_id
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return OutputLayout(
        root=root,
        raw_dir=raw_dir,
        context_path=root / "context.json",
        manifest_path=root / "manifest.json",
    )
