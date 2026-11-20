"""Review-state derivation helpers for the packaging script.

Builds derived indexes (finding index, duplicate candidates, thread timeline,
dashboard notes) consumed by the downstream review/dedupe logic. Pure functions
over discussion/note payloads — no GitHub API calls here.
"""

from __future__ import annotations

from typing import Any

from package.io import DASHBOARD_MARKER, SEVERITY_TOKENS
from review_shared import (
    extract_issue_headline,
    extract_review_metadata,
    normalize_text,
    token_fingerprint,
)


def summarize_notes(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dashboards = []
    for note in notes:
        body = note.get("body") or ""
        if DASHBOARD_MARKER in body:
            dashboards.append(
                {
                    "note_id": note.get("id"),
                    "author": (note.get("author") or {}).get("username"),
                    "created_at": note.get("created_at"),
                    "updated_at": note.get("updated_at"),
                }
            )
    return dashboards


def build_finding_index(discussions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for discussion in discussions:
        notes = discussion.get("notes") or []
        if not notes:
            continue
        first = notes[0]
        body = first.get("body") or ""
        metadata = extract_review_metadata(body)
        position = first.get("position") or {}
        finding = {
            "discussion_id": discussion.get("id"),
            "note_id": first.get("id"),
            "resolved": bool(discussion.get("resolved") or first.get("resolved")),
            "resolved_by": (
                (discussion.get("resolved_by") or {}).get("username")
                or (first.get("resolved_by") or {}).get("username")
            ),
            "resolved_at": discussion.get("resolved_at") or first.get("resolved_at"),
            "author": (first.get("author") or {}).get("username"),
            "created_at": first.get("created_at"),
            "updated_at": first.get("updated_at"),
            "latest_author": (
                (notes[-1].get("author") or {}).get("username") if notes else None
            ),
            "note_count": len(notes),
            "file": position.get("new_path") or position.get("old_path") or "",
            "line": position.get("new_line") or position.get("old_line"),
            "headline": extract_issue_headline(body),
            "finding_key": metadata.get("finding_key"),
            "rule_id": metadata.get("rule_id"),
            "root_cause_cluster": metadata.get("root_cause_cluster"),
            "severity": next(
                (token for token in SEVERITY_TOKENS if token in body), None
            ),
            "resolvable": bool(first.get("resolvable")),
            "actionable": any(token in body for token in SEVERITY_TOKENS),
        }
        findings.append(finding)
    return findings


def build_duplicate_candidates(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actionable = [finding for finding in findings if finding.get("actionable")]
    duplicate_groups: list[dict[str, Any]] = []
    seen_group_keys: set[tuple[str, ...]] = set()

    def add_group(match_basis: str, items: list[dict[str, Any]]) -> None:
        if len(items) < 2:
            return
        ordered = sorted(
            items,
            key=lambda item: (
                item.get("resolved"),
                item.get("created_at") or "",
                item.get("discussion_id") or "",
            ),
        )
        canonical = ordered[0]
        group_ids = tuple(item.get("discussion_id") or "" for item in ordered)
        if group_ids in seen_group_keys:
            return
        seen_group_keys.add(group_ids)
        duplicate_groups.append(
            {
                "match_basis": match_basis,
                "canonical_discussion_id": canonical.get("discussion_id"),
                "duplicate_discussion_ids": [
                    item.get("discussion_id") for item in ordered[1:]
                ],
                "file": canonical.get("file"),
                "headline": canonical.get("headline"),
            }
        )

    for key_name in ("finding_key", "root_cause_cluster"):
        buckets: dict[str, list[dict[str, Any]]] = {}
        for finding in actionable:
            key = finding.get(key_name)
            if key:
                buckets.setdefault(str(key), []).append(finding)
        for key, items in buckets.items():
            add_group(f"{key_name}:{key}", items)

    exact_buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for finding in actionable:
        file_path = finding.get("file") or ""
        headline = finding.get("headline") or ""
        if file_path and headline:
            exact_buckets.setdefault((file_path, headline), []).append(finding)
    for (file_path, headline), items in exact_buckets.items():
        add_group(f"headline_exact:{file_path}:{headline[:80]}", items)

    by_file: dict[str, list[dict[str, Any]]] = {}
    for finding in actionable:
        file_path = finding.get("file") or ""
        if file_path:
            by_file.setdefault(file_path, []).append(finding)
    for file_path, items in by_file.items():
        fingerprints = [token_fingerprint(item.get("headline") or "") for item in items]
        for i, left in enumerate(items):
            left_tokens = fingerprints[i]
            if not left_tokens:
                continue
            cluster = [left]
            for offset, right in enumerate(items[i + 1 :], start=i + 1):
                right_tokens = fingerprints[offset]
                if not right_tokens:
                    continue
                overlap = len(left_tokens & right_tokens)
                union = len(left_tokens | right_tokens)
                similarity = overlap / union if union else 0
                if similarity >= 0.75:
                    cluster.append(right)
            add_group(f"headline_similarity:{file_path}", cluster)

    return duplicate_groups


def build_thread_timeline(discussions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for discussion in discussions:
        discussion_id = discussion.get("id")
        notes = discussion.get("notes") or []
        for note in notes:
            events.append(
                {
                    "discussion_id": discussion_id,
                    "note_id": note.get("id"),
                    "author": (note.get("author") or {}).get("username"),
                    "created_at": note.get("created_at"),
                    "resolved": bool(note.get("resolved")),
                    "system": bool(note.get("system")),
                    "kind": "note",
                    "body_excerpt": normalize_text((note.get("body") or "")[:240]),
                }
            )
        if discussion.get("resolved"):
            events.append(
                {
                    "discussion_id": discussion_id,
                    "note_id": None,
                    "author": (discussion.get("resolved_by") or {}).get("username"),
                    "created_at": discussion.get("resolved_at"),
                    "resolved": True,
                    "system": False,
                    "kind": "discussion_resolved",
                    "body_excerpt": "discussion resolved",
                }
            )
    events.sort(
        key=lambda event: (
            event.get("created_at") or "",
            event.get("discussion_id") or "",
        )
    )
    return events
