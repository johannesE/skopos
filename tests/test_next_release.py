"""scripts/next-release.sh against throwaway git repositories."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "next-release.sh"


def _bash() -> str | None:
    # The script needs bash 4+ (mapfile); macOS ships 3.2 as /bin/bash.
    for candidate in (shutil.which("bash"), "/opt/homebrew/bin/bash", "/usr/local/bin/bash"):
        if not candidate or not Path(candidate).exists():
            continue
        version = subprocess.run(
            [candidate, "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True
        ).stdout.strip()
        if version.isdigit() and int(version) >= 4:
            return candidate
    return None


BASH = _bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash 4 or newer")


class Repo:
    def __init__(self, path: Path):
        self.path = path
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.path, check=True, capture_output=True, text=True
        ).stdout

    def commit(self, subject: str, body: str = "") -> None:
        args = ["commit", "-q", "--allow-empty", "-m", subject]
        if body:
            args += ["-m", body]
        self.git(*args)

    def release(self) -> tuple[dict[str, str], str]:
        notes = self.path / "notes.md"
        result = subprocess.run(
            [BASH, str(SCRIPT)],
            cwd=self.path,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "NOTES_FILE": str(notes)},
            check=True,
            capture_output=True,
            text=True,
        )
        outputs = dict(line.split("=", 1) for line in result.stdout.splitlines())
        return outputs, notes.read_text() if notes.exists() else ""


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


def test_first_release_without_tags(repo):
    repo.commit("chore: init")
    assert repo.release()[0] == {"tag": "v0.0.1", "major": "v0"}


def test_nothing_new_releases_nothing(repo):
    repo.commit("feat: init")
    repo.git("tag", "v1.0.0")
    assert repo.release()[0] == {}


@pytest.mark.parametrize(
    ("subject", "body", "expected"),
    [
        ("docs: words", "", "v1.0.1"),
        ("fix: bug", "", "v1.0.1"),
        ("feat(api): thing", "", "v1.1.0"),
        ("refactor!: drop input", "", "v2.0.0"),
        ("fix: input", "BREAKING CHANGE: renamed model to llm_model", "v2.0.0"),
    ],
)
def test_bump_follows_conventional_commits(repo, subject, body, expected):
    repo.commit("chore: init")
    repo.git("tag", "v1.0.0")
    repo.commit(subject, body)
    outputs, _ = repo.release()
    assert outputs["tag"] == expected
    assert outputs["major"] == expected.split(".")[0]


def test_merge_commit_is_ignored_but_its_commits_count(repo):
    repo.commit("chore: init")
    repo.git("tag", "v1.0.0")
    repo.git("switch", "-q", "-c", "side")
    repo.commit("feat: from a branch")
    repo.git("switch", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "side", "-m", "Merge pull request #9")
    outputs, notes = repo.release()
    assert outputs["tag"] == "v1.1.0"
    assert "Merge pull request" not in notes
    assert "## Features\n\n- feat: from a branch" in notes


def test_irregular_tags_are_ignored(repo):
    repo.commit("chore: init")
    repo.git("tag", "v1.0.0")
    repo.commit("fix: one")
    for tag in ("v1", "v1.1.0-rc1", "v1.2.3.4"):
        repo.git("tag", tag)
    outputs, notes = repo.release()
    assert outputs["tag"] == "v1.0.1"
    assert "compare/v1.0.0...v1.0.1" in notes


def test_notes_group_commits(repo):
    repo.commit("chore: init")
    repo.git("tag", "v1.0.0")
    repo.commit("feat: a")
    repo.commit("fix: b")
    repo.commit("docs: c")
    _, notes = repo.release()
    assert notes.index("## Features") < notes.index("## Fixes") < notes.index("## Other changes")
    assert "## Breaking changes" not in notes
