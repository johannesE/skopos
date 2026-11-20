from __future__ import annotations

from github_api import build_review_state, normalize_review_thread, pr_participants


def thread(resolved=False, author="skopos", line=6, original=None):
    return {
        "id": "PRRT_kw1",
        "isResolved": resolved,
        "isOutdated": False,
        "path": "calc.py",
        "line": line,
        "originalLine": original,
        "resolvedBy": {"login": "octocat"} if resolved else None,
        "comments": {
            "nodes": [
                {"databaseId": 101, "body": "**root**", "createdAt": "t1", "updatedAt": "t1", "author": {"login": author}},
                {"databaseId": 102, "body": "by design", "createdAt": "t2", "updatedAt": "t2", "author": {"login": "octocat"}},
            ]
        },
    }


def test_review_thread_normalizes_to_discussion_shape():
    discussion = normalize_review_thread(thread(resolved=True))
    assert discussion["id"] == "101"
    assert discussion["kind"] == "review_thread"
    assert discussion["thread_node_id"] == "PRRT_kw1"
    assert discussion["resolved"] is True
    assert discussion["resolved_by"] == {"username": "octocat"}
    first = discussion["notes"][0]
    assert first["author"] == {"username": "skopos"}
    assert first["position"] == {"new_path": "calc.py", "new_line": 6}


def test_outdated_thread_falls_back_to_original_line():
    discussion = normalize_review_thread(thread(line=None, original=9))
    assert discussion["notes"][0]["position"]["new_line"] == 9


def test_rest_bot_logins_are_normalized():
    _, notes = build_review_state([], [{"id": 5, "body": "x", "user": {"login": "skopos[bot]"}}])
    assert notes[0]["author"]["username"] == "skopos"


def test_issue_comments_become_unresolvable_discussions():
    discussions, notes = build_review_state(
        [thread()], [{"id": 7, "body": "hello", "user": {"login": "octocat"}}]
    )
    kinds = {d["id"]: d["kind"] for d in discussions}
    assert kinds == {"101": "review_thread", "ic-7": "issue_comment"}
    assert notes[0]["id"] == "7"


def test_participants_include_people_who_reviewed():
    pr = {
        "user": {"login": "author"},
        "assignees": [{"login": "assignee"}],
        "requested_reviewers": [{"login": "pending"}],
    }
    reviews = [{"user": {"login": "reviewer"}}]
    participants = pr_participants(pr, reviews)
    assert participants["allowed_resolution_users"] == ["assignee", "author", "pending", "reviewer"]
