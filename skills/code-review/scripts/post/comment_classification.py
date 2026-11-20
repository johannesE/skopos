"""Comment classification, dedupe, and patch-validation helpers for the posting script.

Pure functions over markdown bodies and patch text — no GitHub API calls here.
"""

from __future__ import annotations

import re
from typing import Any

from post.io import DASHBOARD_MARKER
from review_shared import (
    REVIEW_METADATA_PREFIX,
    extract_issue_headline,
    normalize_text,
    token_fingerprint,
)


WEAK_RESOLUTION_RE = re.compile(
    r"^(done|fixed|resolved|ok|okay|thanks|thx|lgtm|sg|looks good|approved|👍|✅|🙏|will do)\W*$",
    re.IGNORECASE,
)
WAIVER_SIGNAL_RE = re.compile(
    r"\b(by design|intentional|false positive|duplicate|already addressed|no change needed|won.t fix|will not fix|expected behavior)\b",
    re.IGNORECASE,
)
ACTIONABLE_TABLE_RE = re.compile(
    r"(?:Critical|Major|Minor)[ ]+Issues[ ]*\([1-9][0-9]*\)",
    re.IGNORECASE,
)
LGTM_ONLY_RE = re.compile(
    r"^(lgtm|looks\s+good(?:\s+to\s+me)?|seems\s+good(?:\s+to\s+me)?|approved|\+1)$",
    re.IGNORECASE,
)
RESOLUTION_REPLY_RE = re.compile(
    r"(?:status update:\s*resolved|no longer valid|no longer applies|this issue is fixed|this looks fixed now|closing this duplicate|tracked in the canonical discussion)",
    re.IGNORECASE,
)
CODE_SPAN_RE = re.compile(r"`([^`\n]{2,})`")
IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_./:-]{2,}")


def contains_lgtm_only(body: str) -> bool:
    normalized = normalize_text(body)
    normalized = re.sub(r"^[^a-z0-9+]+", "", normalized)
    normalized = re.sub(r"[^a-z0-9+]+$", "", normalized)
    return bool(LGTM_ONLY_RE.fullmatch(normalized))


def is_nitpick_comment(body: str) -> bool:
    return "_🧹 Nitpick_" in body


def is_summary_comment(comment_type: str, body: str) -> bool:
    return comment_type == "general" and "Actionable comments posted:" in body


def has_actionable_severity(body: str) -> bool:
    return any(
        token in body
        for token in ("_🛑 Critical issue_", "_⚠️ Potential issue_", "_💡 Suggestion_")
    ) or bool(ACTIONABLE_TABLE_RE.search(body))


def looks_like_resolution_reply(body: str) -> bool:
    return bool(RESOLUTION_REPLY_RE.search(normalize_text(body)))


def strip_legacy_dashboard_summary(body: str) -> str:
    patterns = [
        re.compile(
            r"\n?<details(?:\s+open)?>\s*\n<summary>📊 Summary</summary>.*?</details>\s*\n?",
            re.S,
        ),
        re.compile(r"\n?## Summary\s*\n.*?(?=\n## |\n### |\Z)", re.S),
    ]
    stripped = body
    for pattern in patterns:
        stripped = pattern.sub("\n", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip()
    return stripped + "\n"


def infer_comment_type(
    filename: str, body: str, declared_type: str | None = None
) -> str:
    declared = (declared_type or "").strip() or "general"
    if DASHBOARD_MARKER in body:
        return "dashboard"
    if filename.startswith("00-dashboard"):
        return "dashboard"
    return declared


def build_dedupe_signature(
    file_path: str, finding_key: str, root_cause_cluster: str, body: str
) -> str:
    if finding_key:
        return f"finding_key:{finding_key}"
    if root_cause_cluster:
        return f"root:{root_cause_cluster}"
    tokens = sorted(token_fingerprint(extract_issue_headline(body)))
    return f"fallback:{file_path}:{' '.join(tokens)}"


def append_review_metadata(
    body: str, finding_key: str, rule_id: str, root_cause_cluster: str
) -> str:
    if REVIEW_METADATA_PREFIX in body:
        return body
    parts = []
    if finding_key:
        parts.append(f"finding_key={finding_key}")
    if rule_id:
        parts.append(f"rule_id={rule_id}")
    if root_cause_cluster:
        parts.append(f"root_cause_cluster={root_cause_cluster}")
    if not parts:
        return body
    return f"{body}\n\n{REVIEW_METADATA_PREFIX}{' '.join(parts)} -->"


def normalize_for_match(text: str) -> str:
    return normalize_text(text)


def headline_for_match(text: str) -> str:
    headline = extract_issue_headline(text)
    return normalize_for_match(headline)


def parse_patch_hunk_ranges(patch: str) -> list[tuple[range, range]]:
    ranges: list[tuple[range, range]] = []
    for line in (patch or "").splitlines():
        match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if not match:
            continue
        old_start = int(match.group(1))
        old_len = int(match.group(2) or "1")
        new_start = int(match.group(3))
        new_len = int(match.group(4) or "1")
        ranges.append(
            (
                range(old_start, old_start + old_len),
                range(new_start, new_start + new_len),
            )
        )
    return ranges


def line_touched_by_patch(patch: str, line_number: int | None) -> bool:
    if line_number is None:
        return False
    for old_range, new_range in parse_patch_hunk_ranges(patch):
        if line_number in old_range or line_number in new_range:
            return True
    return False


def new_side_hunk_index(patch: str, line_number: int | None) -> int | None:
    """Index of the hunk whose new-file (RIGHT side) range contains the line.

    GitHub only accepts review comments on lines visible in the diff; for
    RIGHT-side comments that is the hunk's new-file range (added + context).
    """
    if line_number is None:
        return None
    for index, (_, new_range) in enumerate(parse_patch_hunk_ranges(patch)):
        if line_number in new_range:
            return index
    return None


SUGGESTION_OPEN_RE = re.compile(r"^```suggestion(?::-?(\d+)\+(\d+))?[ \t]*$")
BLOCK_OPENER_KEYWORDS = (
    "for",
    "while",
    "if",
    "elif",
    "with",
    "def",
    "class",
    "try",
    "except",
    "finally",
    "match",
    "case",
    "async",
)


def parse_suggestion_blocks(body: str) -> list[dict[str, Any]]:
    """Extract fenced suggestion blocks.

    Returns ``{"before": int, "after": int, "content_lines": [str]}`` entries.
    GitHub suggestions replace exactly the commented range (``start_line``..``line``);
    ``before``/``after`` are only non-zero when a block uses the legacy
    ``suggestion:-N+M`` offset syntax, which ``normalize_suggestion_range``
    converts into a GitHub range.
    """
    blocks: list[dict[str, Any]] = []
    lines = (body or "").splitlines()
    index = 0
    while index < len(lines):
        match = SUGGESTION_OPEN_RE.match(lines[index])
        if not match:
            index += 1
            continue
        before = int(match.group(1)) if match.group(1) else 0
        after = int(match.group(2)) if match.group(2) else 0
        content: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip() != "```":
            content.append(lines[index])
            index += 1
        index += 1
        blocks.append({"before": before, "after": after, "content_lines": content})
    return blocks


def normalize_suggestion_range(
    body: str, line_number: int, start_line: int | None
) -> tuple[str, int | None, int, str | None]:
    """Convert ``suggestion:-N+M`` offsets into a GitHub ``start_line``..``line`` range.

    Returns ``(body, start_line, line, error)``. A GitHub comment covers one
    range, so all suggestion blocks in a comment must agree on it.
    """
    blocks = parse_suggestion_blocks(body)
    offsets = {(int(b["before"]), int(b["after"])) for b in blocks}
    offsets.discard((0, 0))
    if not offsets:
        return body, start_line, line_number, None
    if len(offsets) > 1 or len(blocks) > 1:
        return body, start_line, line_number, "multiple_suggestion_ranges"
    if start_line is not None:
        return body, start_line, line_number, "suggestion_offsets_with_start_line"
    before, after = offsets.pop()
    new_start = line_number - before
    new_end = line_number + after
    rewritten = re.sub(
        r"^```suggestion:-?\d+\+\d+[ \t]*$", "```suggestion", body, flags=re.M
    )
    return rewritten, (new_start if new_start != new_end else None), new_end, None


def is_block_opener(line: str) -> bool:
    stripped = (line or "").split("#", 1)[0].strip()
    if not stripped.endswith(":"):
        return False
    tokens = stripped.split()
    return bool(tokens) and tokens[0].rstrip(":") in BLOCK_OPENER_KEYWORDS


def build_new_side_line_map(patch: str) -> dict[int, str]:
    """Map new-file line numbers to content for every line visible in the patch."""
    line_map: dict[int, str] = {}
    new_line: int | None = None
    for line in (patch or "").splitlines():
        if line.startswith("@@"):
            header = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            new_line = int(header.group(1)) if header else None
            continue
        if new_line is None or line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            line_map[new_line] = line[1:]
            new_line += 1
        elif line.startswith("-"):
            continue
        elif line.startswith("\\"):
            continue
        else:
            line_map[new_line] = line[1:] if line.startswith(" ") else line
            new_line += 1
    return line_map


def range_outside_single_hunk(patch: str, start: int, end: int) -> bool:
    """True unless every line in start..end is on the RIGHT side of one hunk."""
    if start < 1 or end < start:
        return True
    first = new_side_hunk_index(patch, start)
    if first is None:
        return True
    return any(new_side_hunk_index(patch, n) != first for n in range(start, end + 1))


def suggestion_duplicates_enclosing_structure(
    patch: str, start_line: int, blocks: list[dict[str, Any]]
) -> bool:
    """Detect bodies that re-declare a block header enclosing the replaced range.

    A suggestion whose body repeats a ``for``/``if``/``with``/... header that
    already exists just above the replaced range would nest that block when
    applied (each iteration re-running the loop). This is the "applied
    suggestion corrupts the code" failure class.
    """
    line_map = build_new_side_line_map(patch)
    for block in blocks:
        content_lines = [str(line) for line in block.get("content_lines", [])]
        for offset in range(1, 4):
            above = line_map.get(start_line - offset)
            if not above or not is_block_opener(above):
                continue
            for content_line in content_lines:
                if content_line.strip() and content_line.strip() == above.strip():
                    return True
    return False


def parse_line_number(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_identifier_candidates(body: str) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    for span in CODE_SPAN_RE.findall(body or ""):
        for token in IDENTIFIER_TOKEN_RE.findall(span):
            normalized = token.lower()
            if normalized in {"true", "false", "none", "null", "line", "file"}:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(token)
    return candidates
