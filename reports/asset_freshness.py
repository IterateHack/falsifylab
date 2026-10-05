"""Check that committed report assets match the code in their stamped commit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
WATCHED = (
    "reports/replicates.py",
    "reports/slide_assets.py",
    "auditor/validation/",
    ":(exclude)auditor/validation/real/",
    ":(exclude,glob)auditor/validation/**/test_*.py",
)
STAGE2_WAVE1_REFRESH = (
    "rm -rf runs/stage2-wave1-assets && git fetch origin data/wave1 && "
    "git restore --source origin/data/wave1 -- runs/stage2-wave1 && "
    "python -m reports.slide_assets --wave runs/stage2-wave1/a "
    "--wave runs/stage2-wave1/b --output runs/stage2-wave1-assets && "
    "rm -rf reports/assets/stage2-wave1 && "
    "mv runs/stage2-wave1-assets reports/assets/stage2-wave1"
)


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=repo_root,
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def _manifest_refresh(manifest: Path, repo_root: Path) -> str:
    if manifest.parent.name == "stage2-wave1":
        command = STAGE2_WAVE1_REFRESH
    else:
        command = (
            "regenerate with python -m reports.slide_assets "
            "(see reports/README.md)"
        )
    return (
        f"{command}. Run it from a clean tree at a commit that contains the code "
        "change, then commit the result."
    )


def check(
    repo_root: Path = REPO_ROOT, assets_root: Path | None = None,
) -> list[str]:
    repo_root = Path(repo_root).resolve()
    if assets_root is None:
        assets_root = repo_root / "reports" / "assets"
    assets_root = Path(assets_root)
    manifests = sorted(assets_root.glob("*/manifest.json"))
    if not manifests:
        return [f"No committed asset manifest found under {assets_root}"]

    problems = []
    for manifest in manifests:
        try:
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"{manifest}: could not read manifest: {error}")
            continue

        stamps = [
            asset["stamp"]
            for asset in manifest_data.get("assets", [])
            if isinstance(asset, dict) and isinstance(asset.get("stamp"), dict)
        ]
        shas = sorted({
            str(stamp["git_sha"])
            for stamp in stamps
            if stamp.get("git_sha") is not None
        })
        relative_manifest = manifest.resolve().relative_to(repo_root).as_posix()
        if len(shas) > 1:
            problems.append(
                f"{relative_manifest}: asset stamps carry more than one git_sha: "
                f"{', '.join(shas)}"
            )
        if not shas:
            problems.append(f"{relative_manifest}: manifest contains no asset stamps")

        for sha in shas:
            if any(
                stamp.get("git_dirty") is True
                or str(stamp.get("git_sha", "")).endswith("-dirty")
                for stamp in stamps
                if str(stamp.get("git_sha")) == sha
            ):
                problems.append(
                    f"{relative_manifest}: stamped commit {sha} is dirty; "
                    f"{_manifest_refresh(manifest, repo_root)}"
                )

            resolved = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
                cwd=repo_root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if resolved.returncode:
                problems.append(
                    f"{relative_manifest}: stamped commit {sha} not found in local "
                    "history; in a shallow clone run git fetch --unshallow"
                )
                continue

            changed = set(filter(None, _git(
                repo_root, "diff", "--name-only", sha, "--", *WATCHED,
            ).splitlines()))
            changed.update(filter(None, _git(
                repo_root, "ls-files", "--others", "--exclude-standard", "--",
                *WATCHED,
            ).splitlines()))
            if changed:
                changed_files = ", ".join(sorted(changed))
                problems.append(
                    f"{relative_manifest}: assets stamped at {sha} are stale; "
                    f"changed watched files: {changed_files}. "
                    f"{_manifest_refresh(manifest, repo_root)}"
                )
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--assets-root", type=Path)
    args = parser.parse_args(argv)
    problems = check(args.repo_root, args.assets_root)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("Committed report assets are fresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
