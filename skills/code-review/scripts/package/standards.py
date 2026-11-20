"""Collect repo standards (AGENTS.md / CLAUDE.md files + coding guidelines) for review context.

Always includes the root AGENTS.md / CLAUDE.md / .github/copilot-instructions.md and
docs/coding-guidelines.md, plus the nearest AGENTS.md / CLAUDE.md per changed file (walks up from the file's directory to the
repo root, gathering every AGENTS.md found).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

GUIDANCE_FILENAMES = ("AGENTS.md", "CLAUDE.md")


def collect_standards(repo_root: Path, changed_paths: list[str]) -> dict[str, Any]:
    """Collect repo AGENTS.md files (root + nearest per changed file) and coding guidelines.

    Walks up from each changed file's directory to the repo root, gathering every
    AGENTS.md found, so component/base-specific agent guidance applies to the files
    actually changed. Always includes the root AGENTS.md and docs/coding-guidelines.md.
    """
    root_resolved = repo_root.resolve()
    agents_entries: dict[str, str] = {}

    def harvest_from(directory: Path) -> None:
        current = directory.resolve()
        while True:
            for name in GUIDANCE_FILENAMES:
                candidate = current / name
                if candidate.is_file():
                    rel = str(candidate.relative_to(root_resolved))
                    if rel not in agents_entries:
                        agents_entries[rel] = candidate.read_text(encoding="utf-8")
            if current == root_resolved:
                break
            parent = current.parent
            if parent == current:
                break
            current = parent

    for name in (*GUIDANCE_FILENAMES, ".github/copilot-instructions.md"):
        root_file = repo_root / name
        if root_file.is_file():
            agents_entries[name] = root_file.read_text(encoding="utf-8")

    for path_str in changed_paths:
        if not path_str:
            continue
        harvest_from((repo_root / path_str).parent)

    coding_guidelines_path = repo_root / "docs" / "coding-guidelines.md"
    coding_guidelines = None
    if coding_guidelines_path.is_file():
        coding_guidelines = {
            "path": str(coding_guidelines_path.relative_to(repo_root)),
            "text": coding_guidelines_path.read_text(encoding="utf-8"),
        }

    return {
        "agents_md": [
            {"path": rel, "text": text} for rel, text in sorted(agents_entries.items())
        ],
        "coding_guidelines": coding_guidelines,
    }
