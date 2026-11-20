"""Discussion classification, matching, and resolution-validation logic for the posting script.

Handles dedupe against existing unresolved/resolved/waived/acknowledged discussions,
canonical-thread selection, and the validation gate that decides whether a
``resolve_thread: true`` request is allowed to auto-close a thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from post.comment_classification import (
    WAIVER_SIGNAL_RE,
    WEAK_RESOLUTION_RE,
    headline_for_match,
    line_touched_by_patch,
)
from review_shared import extract_review_metadata, normalize_text, token_fingerprint


@dataclass
class DiscussionMatch:
    discussion_id: str
    strategy: str
    score: int
    state: str


def classify_discussion_state(
    discussion: dict[str, Any], allowed_users: set[str] | None = None
) -> str:
    notes = discussion.get("notes") or []
    if not notes:
        return "open"
    first = notes[0]
    if discussion.get("resolved") or first.get("resolved"):
        return "resolved"
    allowed_users = allowed_users or set()
    state = "open"
    for note in notes[1:]:
        author = (note.get("author") or {}).get("username") or ""
        body = normalize_text(note.get("body") or "")
        if not body or author not in allowed_users:
            continue
        if WAIVER_SIGNAL_RE.search(body):
            return "waived"
        state = "acknowledged"
    return state


def find_matching_discussion(
    discussions: list[dict[str, Any]],
    *,
    file_path: str,
    body: str,
    finding_key: str,
    rule_id: str,
    root_cause_cluster: str,
    allowed_users: set[str] | None = None,
    desired_states: set[str] | None = None,
) -> DiscussionMatch | None:
    target_headline = headline_for_match(body)
    target_tokens = token_fingerprint(target_headline)
    best: DiscussionMatch | None = None
    sorted_discussions = sorted(
        discussions,
        key=lambda discussion: (
            ((discussion.get("notes") or [{}])[0].get("created_at") or ""),
            discussion.get("id") or "",
        ),
    )
    for discussion in sorted_discussions:
        notes = discussion.get("notes") or []
        if not notes:
            continue
        first = notes[0]
        state = classify_discussion_state(discussion, allowed_users)
        if desired_states is not None and state not in desired_states:
            continue
        first_body = first.get("body") or ""
        first_meta = extract_review_metadata(first_body)
        position = first.get("position") or {}
        existing_file = position.get("new_path") or position.get("old_path") or ""
        existing_headline = headline_for_match(first_body)
        existing_tokens = token_fingerprint(existing_headline)
        score = 0
        strategy = "none"
        if finding_key and finding_key == first_meta.get("finding_key"):
            score = 100
            strategy = "finding_key_exact"
        elif root_cause_cluster and root_cause_cluster == first_meta.get(
            "root_cause_cluster"
        ):
            score = 90
            strategy = "root_cause_cluster_exact"
        elif (
            rule_id
            and rule_id == first_meta.get("rule_id")
            and file_path
            and file_path == existing_file
            and target_headline
            and target_headline == existing_headline
        ):
            score = 80
            strategy = "rule_id_plus_headline"
        elif (
            file_path
            and file_path == existing_file
            and target_headline
            and target_headline == existing_headline
        ):
            score = 70
            strategy = "headline_exact"
        elif (
            file_path
            and file_path == existing_file
            and target_tokens
            and existing_tokens
        ):
            overlap = len(target_tokens & existing_tokens)
            union = len(target_tokens | existing_tokens)
            similarity = overlap / union if union else 0
            if overlap >= 3 and similarity >= 0.85:
                score = 60
                strategy = "headline_similarity"
        if score and (best is None or score > best.score):
            best = DiscussionMatch(
                discussion_id=discussion.get("id") or "",
                strategy=strategy,
                score=score,
                state=state,
            )
    return best


def validate_resolution_request(
    discussions: list[dict[str, Any]],
    allowed_users: set[str],
    *,
    discussion_id: str,
    resolution_kind: str,
    resolution_basis: str,
    resolution_evidence: str,
    resolver_username: str,
    canonical_discussion_id: str,
    waiver_type: str,
    waiver_reason: str,
    ai_reviewer_username: str = "",
    changed_files: set[str] | None = None,
    changed_patches: dict[str, str] | None = None,
) -> tuple[bool, str | None]:
    valid_kinds = {"fixed_by_code", "waived_by_human", "duplicate_of_canonical"}
    resolution_basis = normalize_text(resolution_basis)
    resolution_evidence = normalize_text(resolution_evidence)
    waiver_reason = normalize_text(waiver_reason)

    if resolution_kind not in valid_kinds:
        return (
            False,
            "resolve_thread requires resolution_kind=fixed_by_code|waived_by_human|duplicate_of_canonical",
        )
    if len(resolution_basis) < 8:
        return False, "resolve_thread requires a concrete resolution_basis"
    if len(resolution_evidence) < 12:
        return False, "resolve_thread requires concrete resolution_evidence"
    if WEAK_RESOLUTION_RE.fullmatch(resolution_basis) or WEAK_RESOLUTION_RE.fullmatch(
        resolution_evidence
    ):
        return False, "resolution_basis/evidence is too weak"

    discussion = next(
        (item for item in discussions if (item.get("id") or "") == discussion_id), None
    )
    if discussion is None:
        return False, "target discussion_id not found in existing discussions"
    if discussion.get("kind") == "issue_comment":
        return (
            False,
            "only review threads can be resolved on GitHub; this discussion is a plain PR comment",
        )

    first_note_author = ((discussion.get("notes") or [{}])[0].get("author") or {}).get(
        "username"
    ) or ""
    if not ai_reviewer_username:
        return False, "ai_reviewer identity unavailable; cannot verify thread ownership"
    if first_note_author != ai_reviewer_username:
        return (
            False,
            f"resolve_thread is only allowed on threads opened by {ai_reviewer_username}; "
            f"this thread was opened by {first_note_author or 'unknown'}",
        )

    if resolution_kind == "fixed_by_code":
        first_note = (discussion.get("notes") or [{}])[0]
        position = first_note.get("position") or {}
        target_file = position.get("new_path") or position.get("old_path") or ""
        target_line = position.get("new_line") or position.get("old_line")
        if (
            changed_files is not None
            and target_file
            and target_file not in changed_files
        ):
            return (
                False,
                "fixed_by_code requires the affected file to be part of the current PR changes",
            )
        if changed_patches is not None and target_file:
            patch = changed_patches.get(target_file) or ""
            if patch and not line_touched_by_patch(patch, target_line):
                return (
                    False,
                    "fixed_by_code requires the affected line to be within changed hunks, not just file membership",
                )
        return True, None

    if resolution_kind == "duplicate_of_canonical":
        if not canonical_discussion_id:
            return False, "duplicate_of_canonical requires canonical_discussion_id"
        if canonical_discussion_id == discussion_id:
            return False, "canonical_discussion_id must differ from discussion_id"
        canonical = next(
            (
                item
                for item in discussions
                if (item.get("id") or "") == canonical_discussion_id
            ),
            None,
        )
        if canonical is None:
            return False, "canonical_discussion_id not found in existing discussions"
        canonical_first_note = (canonical.get("notes") or [{}])[0]
        if canonical.get("resolved") or canonical_first_note.get("resolved"):
            return (
                False,
                "canonical_discussion_id must point to an unresolved discussion",
            )
        return True, None

    if not resolver_username:
        return False, "waived_by_human requires resolver_username"
    if resolver_username not in allowed_users:
        return (
            False,
            "resolver_username must match the PR author, an assignee, or a reviewer",
        )
    if not waiver_type and not waiver_reason:
        return False, "waived_by_human requires waiver_type or waiver_reason"

    for note in discussion.get("notes") or []:
        author = (note.get("author") or {}).get("username") or ""
        body = normalize_text(note.get("body") or "")
        if author != resolver_username:
            continue
        if WEAK_RESOLUTION_RE.fullmatch(body):
            continue
        if WAIVER_SIGNAL_RE.search(body):
            return True, None
        if waiver_reason and waiver_reason.lower() in body.lower():
            return True, None
        if resolution_evidence and resolution_evidence.lower() in body.lower():
            return True, None
    return (
        False,
        "no valid human waiver comment found for resolver_username in the target discussion",
    )
