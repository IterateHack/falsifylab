import re
import subprocess

from runner import provenance


def _run_git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_code_sha_reports_commit_and_tracked_worktree_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = repo / "tracked.txt"
    tracked.write_text("initial\n", encoding="utf-8")
    _run_git(repo, "add", "tracked.txt")
    _run_git(
        repo,
        "-c", "user.name=Test",
        "-c", "user.email=test@example.com",
        "commit", "-m", "initial",
    )

    commit = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{40}", commit)
    assert provenance.code_sha(repo) == commit

    tracked.write_text("modified\n", encoding="utf-8")
    assert provenance.code_sha(repo) == f"{commit}-dirty"


def test_code_sha_returns_none_for_non_repository(tmp_path):
    assert provenance.code_sha(tmp_path) is None


def test_code_sha_returns_none_when_git_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        provenance.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("git")),
    )
    assert provenance.code_sha(tmp_path) is None
