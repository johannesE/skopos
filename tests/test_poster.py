from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import PATCH

import post.comment_handlers as handlers
import post.publisher as publisher
import post_review_comments as prc
from review_shared import DASHBOARD_MARKER


def write_context(tmp_path: Path, notes=None, discussions=None) -> Path:
    context = {
        "project": {"full_name": "acme/shop"},
        "changes": {
            "base_sha": "base",
            "head_sha": "head",
            "files": [{"path": "calc.py", "patch": PATCH}],
        },
        "review_state": {
            "bot_login": "skopos[bot]",
            "participants": {"allowed_resolution_users": ["author"]},
            "discussions": discussions or [],
            "notes": notes or [],
        },
    }
    path = tmp_path / "context.json"
    path.write_text(json.dumps(context))
    return path


def write_review(tmp_path: Path, files: dict[str, str]) -> Path:
    review = tmp_path / "review"
    review.mkdir()
    for name, text in files.items():
        (review / name).write_text(text)
    (review / "_scratch").mkdir()
    (review / "_scratch" / "notes.md").write_text("scratch, must be ignored")
    return review


INLINE = """---
type: inline
file: calc.py
line: {line}
finding_key: edge/div-zero/{line}
certainty: high
---
_⚠️ Potential issue_ | _Major_

**`div` raises on zero divisor**
"""


def run_offline(tmp_path, files, notes=None, discussions=None):
    context = write_context(tmp_path, notes, discussions)
    review = write_review(tmp_path, files)
    poster = prc.ReviewPoster(pr_number="7", review_dir=review, dry_run=False, context_path=context)
    poster.process_all()
    poster.submit_review()
    return poster, review


def test_offline_validation_queues_valid_and_skips_out_of_diff(tmp_path):
    poster, review = run_offline(
        tmp_path,
        {
            "00-dashboard.md": f"{DASHBOARD_MARKER}\n\n## Skopos review\n",
            "01-ok.md": INLINE.format(line=6),
            "02-bad.md": INLINE.format(line=12),
        },
    )
    assert poster.dry_run is True
    assert poster.ai_reviewer_username == "skopos"
    assert [entry["line"] for _, entry in poster.pending_inline] == [6]
    skipped = [json.loads(line) for line in (review / "posting-skipped.jsonl").read_text().splitlines()]
    assert [s["reason"] for s in skipped] == ["inline_line_not_in_diff"]
    assert poster.total == 3  # scratch file ignored


@pytest.mark.parametrize(
    ("counter", "expected"),
    [("resolve_failed", 0), ("resolve_validation_failed", 1), ("failed", 1)],
)
def test_exit_code_treats_rejected_resolve_as_warning(tmp_path, counter, expected):
    # A resolve GitHub rejects (token without contents: write) is reported as a
    # warning by run-review.sh; invalid resolution metadata and failed posts still fail.
    poster, _ = run_offline(tmp_path, {"00-dashboard.md": f"{DASHBOARD_MARKER}\n"})
    assert poster.exit_code() == 0
    setattr(poster, counter, 1)
    assert poster.exit_code() == expected


def test_dashboard_updates_only_own_comment(tmp_path):
    notes = [
        {"id": "50", "body": f"{DASHBOARD_MARKER} quoted by a human", "author": {"username": "octocat"}},
        {"id": "40", "body": f"{DASHBOARD_MARKER}\nold", "author": {"username": "skopos"}},
    ]
    poster, review = run_offline(tmp_path, {"00-dashboard.md": f"{DASHBOARD_MARKER}\nnew"}, notes=notes)
    updated = json.loads((review / "posting-updated.jsonl").read_text().splitlines()[0])
    assert updated["comment_id"] == "40"
    assert poster.updated == 1


def test_existing_open_thread_suppresses_duplicate(tmp_path):
    discussions = [
        {
            "id": "101",
            "kind": "review_thread",
            "resolved": False,
            "notes": [
                {
                    "id": "101",
                    "body": "**x**\n<!-- skopos:review-metadata finding_key=edge/div-zero/6 -->",
                    "author": {"username": "skopos"},
                    "position": {"new_path": "calc.py", "new_line": 6},
                }
            ],
        }
    ]
    poster, _ = run_offline(tmp_path, {"01-ok.md": INLINE.format(line=6)}, discussions=discussions)
    assert poster.pending_inline == []
    assert poster.skipped == 1


class FakeResult:
    def __init__(self, returncode: int, payload: dict):
        self.returncode = returncode
        self.stdout = json.dumps(payload)
        self.stderr = ""


def test_rejected_batch_review_falls_back_to_single_comments(tmp_path, monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_api_call(path, *, method="GET", payload=None):
        calls.append((path, payload))
        if path.endswith("/reviews"):
            return FakeResult(1, {"message": "Unprocessable Entity"})
        if payload and payload.get("line") == 6:
            return FakeResult(0, {"id": 999})
        return FakeResult(1, {"message": "line must be part of the diff"})

    monkeypatch.setattr(publisher, "api_call", fake_api_call)
    poster = type("P", (), {})()
    poster.pending_inline = [
        ("a.md", {"path": "calc.py", "line": 6, "side": "RIGHT", "body": "a"}),
        ("b.md", {"path": "calc.py", "line": 7, "side": "RIGHT", "body": "b"}),
    ]
    poster.dry_run = False
    poster.slug = "acme/shop"
    poster.pr_number = "7"
    poster.head_sha = "head"
    poster.inline_posted = 0
    poster.failed = 0
    poster.posted_log = tmp_path / "posted.jsonl"

    assert publisher.submit_review(poster) == 1
    assert poster.inline_posted == 1 and poster.failed == 1
    assert calls[0][1]["event"] == "COMMENT"
    assert all(c[1].get("commit_id") == "head" for c in calls[1:])


def test_reply_to_plain_comment_quotes_it(tmp_path, monkeypatch):
    sent: list[tuple[str, dict]] = []

    def fake_api_call(path, *, method="GET", payload=None):
        sent.append((path, payload))
        return FakeResult(0, {"id": 1})

    monkeypatch.setattr(handlers, "api_call", fake_api_call)
    poster = type("P", (), {})()
    poster.dry_run = False
    poster.slug = "acme/shop"
    poster.pr_number = "7"
    poster.replied = 0
    poster.failed = 0
    poster.replied_log = tmp_path / "replied.jsonl"
    poster.discussion_by_id = lambda _id: {
        "id": "ic-5",
        "kind": "issue_comment",
        "notes": [{"body": "Why is this cached?"}],
    }
    comment = type("C", (), {})()
    comment.discussion_id = "ic-5"
    comment.filename = "03-reply.md"
    comment.resolve_thread = "false"
    comment.body = "Because the lookup is expensive; see `cache.py`."
    handlers.post_reply_note(poster, comment)
    path, payload = sent[0]
    assert path == "repos/acme/shop/issues/7/comments"
    assert payload["body"].startswith("> Why is this cached?")


@pytest.mark.skipif(subprocess.run(["git", "--version"], capture_output=True).returncode != 0, reason="git missing")
def test_local_packaging_end_to_end(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "AGENTS.md").write_text("Use tabs.")
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    subprocess.run([*git, "checkout", "-qb", "feature"], check=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef div(a, b):\n    return a / b\n")
    subprocess.run([*git, "commit", "-qam", "div"], check=True)
    script = Path(prc.__file__).with_name("package_review_context.py")
    result = subprocess.run(
        ["python3", str(script), "local", "--base-ref", "main", "--output-dir", str(tmp_path / "ctx")],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(result.stdout)
    context = json.loads(Path(out["context_json"]).read_text())
    assert out["changed_lines"] == 4
    assert context["changes"]["files"][0]["path"] == "calc.py"
    assert context["standards"]["agents_md"][0]["path"] == "AGENTS.md"
