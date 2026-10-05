"""The docs/ fence is default-deny; this test enforces the published rule
rather than leaving it as a hand-maintained list in a different font.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
GUIDE = ROOT / "auditor" / "validation" / "real" / "LABELLER-GUIDE.md"

# A docs/ file may be opened by a blind labeller only with an entry here and a
# reason. Empty by design: every docs/ file today is answer-bearing or verdict-
# bearing. Adding an entry is the deliberate act of unfencing a document.
ALLOWLIST: dict[str, str] = {}


def _docs_files() -> list[str]:
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in DOCS.rglob("*")
        if path.is_file()
        and not any(
            part == "__pycache__" or part.startswith(".")
            for part in path.relative_to(DOCS).parts
        )
    )


def _guide_section_5() -> str:
    text = GUIDE.read_text()
    match = re.search(r"(?ms)^## 5\..*?\n(.*?)(?=^## |\Z)", text)
    assert match and match.group(1).strip(), "LABELLER-GUIDE.md §5 is missing or empty"
    return match.group(1)


def _guide_named_paths() -> set[str]:
    return {
        token
        for token in re.findall(r"`([^`]+)`", _guide_section_5())
        if "/" in token or token.endswith(".md")
    }


def _is_named_in_guide(path: str, named_paths: set[str]) -> bool:
    if path in named_paths:
        return True
    parts = path.split("/")
    for length in range(1, len(parts)):
        ancestor = "/".join(parts[:length])
        if ancestor in named_paths or f"{ancestor}/" in named_paths:
            return True
    return False


def test_there_are_docs_to_fence():
    assert _docs_files(), "docs/ has no files; the fence would pass vacuously"


@pytest.mark.parametrize("path", _docs_files())
def test_every_docs_file_is_fenced_or_allowlisted(path):
    assert _is_named_in_guide(path, _guide_named_paths()) or path in ALLOWLIST, (
        f"{path} must be fenced by naming it in LABELLER-GUIDE.md §5, or "
        "allowlisted in tests/test_docs_fence.py with a reason why it reveals "
        "no gold answer, verdict, or trigger logic."
    )


def test_allowlist_entries_are_live_and_not_double_counted():
    named_paths = _guide_named_paths()
    for path, reason in ALLOWLIST.items():
        assert (ROOT / path).exists(), f"allowlist entry does not exist: {path}"
        assert reason.strip(), f"allowlist entry needs a reason: {path}"
        assert not _is_named_in_guide(path, named_paths), (
            f"{path} is both allowlisted and named in LABELLER-GUIDE.md §5"
        )


def test_guide_names_only_paths_that_exist():
    for path in _guide_named_paths():
        if not path.startswith("docs/"):
            continue
        target = ROOT / path
        if path.endswith("/"):
            assert target.is_dir(), f"LABELLER-GUIDE.md names missing docs directory: {path}"
        else:
            assert target.is_file(), f"LABELLER-GUIDE.md names missing docs file: {path}"


def test_no_agent_facing_file_references_docs():
    files = sorted((ROOT / "agent").glob("*.json"))
    files.extend(sorted((ROOT / "scenarios").glob("*/agent/*.json")))
    files.extend(sorted((ROOT / "agents" / "prompts").glob("*.md")))
    for path in files:
        assert "docs/" not in path.read_text(), f"{path.relative_to(ROOT)} references docs/"


@pytest.mark.parametrize("scenario", ["a", "b"])
def test_worker_bundle_ships_no_docs_file(scenario):
    from runner import modal_batch

    for local_path, remote_path in modal_batch.worker_bundle_files(scenario):
        assert "docs" not in local_path.parts, f"worker bundle includes {local_path}"
        assert "/docs/" not in remote_path, f"worker bundle includes {remote_path}"
