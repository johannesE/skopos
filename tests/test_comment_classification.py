from __future__ import annotations

from conftest import PATCH
from post.comment_classification import (
    new_side_hunk_index,
    normalize_suggestion_range,
    parse_suggestion_blocks,
    range_outside_single_hunk,
    suggestion_duplicates_enclosing_structure,
)


def test_new_side_lines_map_to_hunks():
    assert new_side_hunk_index(PATCH, 1) == 0
    assert new_side_hunk_index(PATCH, 6) == 0
    assert new_side_hunk_index(PATCH, 7) is None
    assert new_side_hunk_index(PATCH, 24) == 1
    assert new_side_hunk_index(PATCH, 27) == 1
    assert new_side_hunk_index(PATCH, 28) is None


def test_old_side_only_lines_are_not_commentable():
    # Line 20-22 exist only on the old side of the second hunk.
    assert new_side_hunk_index(PATCH, 20) is None


def test_range_must_stay_in_one_hunk():
    assert not range_outside_single_hunk(PATCH, 5, 6)
    assert range_outside_single_hunk(PATCH, 6, 24)
    assert range_outside_single_hunk(PATCH, 0, 2)
    assert range_outside_single_hunk(PATCH, 6, 5)


def test_legacy_offsets_become_github_range():
    body = "fix\n\n```suggestion:-1+0\ndef div(a, b):\n    return a / b if b else 0\n```\n"
    new_body, start, end, error = normalize_suggestion_range(body, 6, None)
    assert error is None
    assert (start, end) == (5, 6)
    assert "```suggestion\n" in new_body
    assert "suggestion:-" not in new_body


def test_plain_suggestion_keeps_explicit_range():
    body = "```suggestion\nx\n```"
    assert normalize_suggestion_range(body, 6, 5) == (body, 5, 6, None)


def test_conflicting_suggestion_ranges_are_rejected():
    body = "```suggestion:-1+0\na\n```\n\n```suggestion:-0+1\nb\n```"
    assert normalize_suggestion_range(body, 6, None)[3] == "multiple_suggestion_ranges"


def test_offsets_plus_start_line_are_rejected():
    body = "```suggestion:-1+0\na\n```"
    assert normalize_suggestion_range(body, 6, 5)[3] == "suggestion_offsets_with_start_line"


def test_suggestion_repeating_enclosing_loop_is_detected():
    body = "```suggestion\n        for row in rows:\n            self.db.insert(row)\n```"
    blocks = parse_suggestion_blocks(body)
    # Replacing only line 26 (inside the loop) while re-declaring the loop header.
    assert suggestion_duplicates_enclosing_structure(PATCH, 26, blocks)
    # Replacing from the loop header itself is fine.
    assert not suggestion_duplicates_enclosing_structure(PATCH, 25, blocks)
