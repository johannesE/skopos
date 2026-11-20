from __future__ import annotations

from conftest import PATCH
from post.discussion_matching import classify_discussion_state, validate_resolution_request


def discussion(author="skopos", kind="review_thread", replies=(), line=6):
    notes = [
        {
            "id": "101",
            "body": "**`div` crashes on zero**",
            "author": {"username": author},
            "position": {"new_path": "calc.py", "new_line": line},
        }
    ]
    for index, (who, body) in enumerate(replies):
        notes.append({"id": str(200 + index), "body": body, "author": {"username": who}})
    return {"id": "101", "kind": kind, "resolved": False, "notes": notes}


def validate(discussions, **overrides):
    params = dict(
        discussion_id="101",
        resolution_kind="fixed_by_code",
        resolution_basis="div now guards zero divisors",
        resolution_evidence="line 6 returns 0 when b is falsy",
        resolver_username="",
        canonical_discussion_id="",
        waiver_type="",
        waiver_reason="",
        ai_reviewer_username="skopos",
        changed_files={"calc.py"},
        changed_patches={"calc.py": PATCH},
    )
    params.update(overrides)
    return validate_resolution_request(discussions, {"author"}, **params)


def test_bot_can_resolve_its_own_thread():
    assert validate([discussion()]) == (True, None)


def test_human_threads_are_not_resolved():
    ok, error = validate([discussion(author="octocat")])
    assert not ok and "only allowed on threads opened by skopos" in error


def test_plain_pr_comments_cannot_be_resolved():
    ok, error = validate([discussion(kind="issue_comment")])
    assert not ok and "only review threads" in error


def test_fixed_by_code_requires_changed_line():
    ok, error = validate([discussion(line=15)])
    assert not ok and "within changed hunks" in error


def test_waiver_from_participant_is_recognized():
    d = discussion(replies=[("author", "This is intentional, by design for legacy clients")])
    assert classify_discussion_state(d, {"author"}) == "waived"
    ok, _ = validate(
        [d],
        resolution_kind="waived_by_human",
        resolver_username="author",
        waiver_type="by_design",
        resolution_basis="author confirmed the behaviour is intended",
        resolution_evidence="author replied: by design for legacy clients",
    )
    assert ok


def test_waiver_from_outsider_is_ignored():
    d = discussion(replies=[("drive-by", "by design")])
    assert classify_discussion_state(d, {"author"}) == "open"
