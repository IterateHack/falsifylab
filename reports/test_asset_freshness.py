"""Tests for committed report-asset freshness checks."""
import ast
import json
from pathlib import Path
import subprocess

import pytest

from reports import asset_freshness


def _run_git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def _commit(repo: Path, paths: list[str], message: str) -> None:
    _run_git(repo, "add", "--", *paths)
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-m", message,
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _repo_with_assets(tmp_path: Path, *, manifest: bool = True):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        check=True,
    )
    files = {
        relative: f"{relative}\n"
        for relative in asset_freshness.WATCHED
    }
    files.update({
        "auditor/validation/real/label.py": "label source\n",
        "auditor/validation/test_x.py": "test source\n",
    })
    for relative, contents in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    _commit(repo, list(files), "Add asset generator inputs")
    sha = _run_git(repo, "rev-parse", "--short", "HEAD")
    manifest_path = repo / "reports" / "assets" / "w" / "manifest.json"
    if manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps({
                "assets": [{"path": "example.csv", "stamp": {
                    "git_sha": sha,
                    "git_dirty": False,
                }}],
            }),
            encoding="utf-8",
        )
        _commit(repo, ["reports/assets/w/manifest.json"], "Add stamped assets")
    return repo, sha, manifest_path


def _write_stamps(manifest_path: Path, stamps: list[dict]) -> None:
    manifest_path.write_text(
        json.dumps({
            "assets": [
                {"path": f"asset-{index}", "stamp": stamp}
                for index, stamp in enumerate(stamps)
            ],
        }),
        encoding="utf-8",
    )


def test_committed_assets_are_fresh():
    problems = asset_freshness.check()
    assert problems == [], "\n".join(problems)


def test_fresh_assets_in_temporary_git_repo(tmp_path):
    repo, _, _ = _repo_with_assets(tmp_path)
    assert asset_freshness.check(repo) == []


def test_committed_slide_assets_change_is_reported(tmp_path):
    repo, sha, _ = _repo_with_assets(tmp_path)
    path = repo / "reports" / "slide_assets.py"
    path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    _commit(repo, ["reports/slide_assets.py"], "Change slide asset generator")

    problems = asset_freshness.check(repo)
    assert any(
        "reports/assets/w/manifest.json" in problem
        and sha in problem
        and "reports/slide_assets.py" in problem
        and "python -m reports.slide_assets" in problem
        for problem in problems
    )


def test_uncommitted_replicates_change_is_reported(tmp_path):
    repo, _, _ = _repo_with_assets(tmp_path)
    path = repo / "reports" / "replicates.py"
    path.write_text(path.read_text(encoding="utf-8") + "uncommitted\n", encoding="utf-8")

    problems = asset_freshness.check(repo)
    assert any("reports/replicates.py" in problem for problem in problems)


def test_validation_report_change_is_reported(tmp_path):
    repo, _, _ = _repo_with_assets(tmp_path)
    path = repo / "auditor" / "validation" / "REPORT.md"
    path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    _commit(repo, ["auditor/validation/REPORT.md"], "Change validation report")

    problems = asset_freshness.check(repo)
    assert any("auditor/validation/REPORT.md" in problem for problem in problems)


def test_unlisted_validation_files_are_unwatched(tmp_path):
    repo, _, _ = _repo_with_assets(tmp_path)
    for relative in (
        "auditor/validation/real/label.py",
        "auditor/validation/test_x.py",
    ):
        path = repo / relative
        path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")

    other = repo / "auditor" / "validation" / "other.py"
    other.write_text("new committed validation tool\n", encoding="utf-8")
    _commit(
        repo,
        [
            "auditor/validation/real/label.py",
            "auditor/validation/test_x.py",
            "auditor/validation/other.py",
        ],
        "Change unlisted validation files",
    )
    (repo / "auditor" / "validation" / "new_tool.py").write_text(
        "new untracked validation tool\n",
        encoding="utf-8",
    )

    assert asset_freshness.check(repo) == []


@pytest.mark.parametrize("watched", asset_freshness.WATCHED)
def test_every_watched_file_change_is_reported(tmp_path, watched):
    repo, _, _ = _repo_with_assets(tmp_path)
    path = repo / watched
    path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    _commit(repo, [watched], f"Change {watched}")

    problems = asset_freshness.check(repo)
    assert any(watched in problem for problem in problems), problems


def test_watched_set_is_exact_files():
    for watched in asset_freshness.WATCHED:
        assert not watched.endswith("/")
        assert not watched.startswith(":")
        assert "*" not in watched
        assert (asset_freshness.REPO_ROOT / watched).is_file()


def test_generator_imports_are_watched():
    def repo_module_path(module):
        base = asset_freshness.REPO_ROOT / module.replace(".", "/")
        source = base.with_suffix(".py")
        package = base / "__init__.py"
        if source.is_file():
            return source.relative_to(asset_freshness.REPO_ROOT).as_posix()
        if package.is_file():
            return package.relative_to(asset_freshness.REPO_ROOT).as_posix()
        return None

    modules = (
        "reports/slide_assets.py",
        "reports/replicates.py",
    )
    for source in modules:
        tree = ast.parse(
            (asset_freshness.REPO_ROOT / source).read_text(encoding="utf-8"),
            filename=source,
        )
        imported_modules = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module != "__future__"
            ):
                imported_modules.append(node.module)
        resolved = {
            path
            for module in imported_modules
            if (path := repo_module_path(module)) is not None
        }
        assert resolved <= set(asset_freshness.WATCHED), (
            f"{source} imports unwatched repo modules: "
            f"{sorted(resolved - set(asset_freshness.WATCHED))}"
        )

    assert repo_module_path("runner.agents") == "runner/agents/__init__.py"


def test_dirty_stamp_is_reported(tmp_path):
    repo, sha, manifest = _repo_with_assets(tmp_path)
    _write_stamps(manifest, [{"git_sha": sha, "git_dirty": True}])

    problems = asset_freshness.check(repo)
    assert any("stamped commit" in problem and "is dirty" in problem for problem in problems)


def test_multiple_stamp_shas_are_reported(tmp_path):
    repo, sha, manifest = _repo_with_assets(tmp_path)
    _write_stamps(manifest, [
        {"git_sha": sha, "git_dirty": False},
        {"git_sha": "another-sha", "git_dirty": False},
    ])

    problems = asset_freshness.check(repo)
    assert any("more than one git_sha" in problem for problem in problems)


def test_unknown_stamp_sha_recommends_unshallow_fetch(tmp_path):
    repo, _, manifest = _repo_with_assets(tmp_path)
    _write_stamps(manifest, [{"git_sha": "missing-sha", "git_dirty": False}])

    problems = asset_freshness.check(repo)
    assert any(
        "stamped commit missing-sha not found in local history" in problem
        and "git fetch --unshallow" in problem
        for problem in problems
    )


def test_missing_manifest_is_reported(tmp_path):
    repo, _, _ = _repo_with_assets(tmp_path, manifest=False)
    problems = asset_freshness.check(repo)
    assert len(problems) == 1
    assert "No committed asset manifest found" in problems[0]


def test_main_returns_failure_and_prints_refresh_command(tmp_path, capsys):
    repo, _, _ = _repo_with_assets(tmp_path)
    path = repo / "reports" / "slide_assets.py"
    path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")

    assert asset_freshness.main(["--repo-root", str(repo)]) == 1
    captured = capsys.readouterr()
    assert "python -m reports.slide_assets" in captured.err
    assert "Run it from a clean tree" in captured.err
