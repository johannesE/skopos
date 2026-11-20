"""Markdown frontmatter parsing and the ReviewComment model for the posting script.

Depends on PyYAML — the dependency is declared in the entry script's PEP 723
metadata block (``post_review_comments.py``) so ``uv`` resolves it for the whole
module tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from post.comment_classification import infer_comment_type


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return {}, text
    block = "\n".join(lines[1:end_index])
    frontmatter: dict[str, str] = {}

    def normalize_frontmatter_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value).strip()

    try:
        parsed = yaml.safe_load(block) or {}
        if isinstance(parsed, dict):
            frontmatter = {
                str(key).strip(): normalize_frontmatter_value(value)
                for key, value in parsed.items()
            }
    except yaml.YAMLError:
        for line in lines[1:end_index]:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip().rstrip("\r")
    body = "\n".join(lines[end_index + 1 :])
    return frontmatter, body


@dataclass
class ReviewComment:
    path: Path
    filename: str
    comment_type: str
    file_path: str
    line_number: str
    start_line: str
    discussion_id: str
    finding_key: str
    root_cause_cluster: str
    rule_id: str
    resolution_kind: str
    resolution_basis: str
    resolution_evidence: str
    resolver_username: str
    canonical_discussion_id: str
    waiver_type: str
    waiver_reason: str
    post_nitpick: str
    certainty: str
    post_low_certainty: str
    resolve_thread: str
    body: str

    @classmethod
    def from_path(cls, path: Path) -> ReviewComment:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        if not frontmatter:
            return cls(
                path=path,
                filename=path.name,
                comment_type=infer_comment_type(path.name, text),
                file_path="",
                line_number="",
                start_line="",
                discussion_id="",
                finding_key="",
                root_cause_cluster="",
                rule_id="",
                resolution_kind="",
                resolution_basis="",
                resolution_evidence="",
                resolver_username="",
                canonical_discussion_id="",
                waiver_type="",
                waiver_reason="",
                post_nitpick="false",
                certainty="",
                post_low_certainty="false",
                resolve_thread="false",
                body=text,
            )

        return cls(
            path=path,
            filename=path.name,
            comment_type=infer_comment_type(
                path.name,
                body,
                frontmatter.get("type", "general") or "general",
            ),
            file_path=frontmatter.get("file", ""),
            line_number=frontmatter.get("line", ""),
            start_line=frontmatter.get("start_line", ""),
            discussion_id=frontmatter.get("discussion_id", ""),
            finding_key=frontmatter.get("finding_key", ""),
            root_cause_cluster=frontmatter.get("root_cause_cluster", ""),
            rule_id=frontmatter.get("rule_id", ""),
            resolution_kind=frontmatter.get("resolution_kind", ""),
            resolution_basis=frontmatter.get("resolution_basis", ""),
            resolution_evidence=frontmatter.get("resolution_evidence", ""),
            resolver_username=frontmatter.get("resolver_username", ""),
            canonical_discussion_id=frontmatter.get("canonical_discussion_id", ""),
            waiver_type=frontmatter.get("waiver_type", ""),
            waiver_reason=frontmatter.get("waiver_reason", ""),
            post_nitpick=frontmatter.get("post_nitpick", "false") or "false",
            certainty=frontmatter.get("certainty", ""),
            post_low_certainty=frontmatter.get("post_low_certainty", "false")
            or "false",
            resolve_thread=frontmatter.get("resolve_thread", "false") or "false",
            body=body,
        )
