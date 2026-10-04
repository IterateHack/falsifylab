"""Re-run the auditor over previously collected batch episodes."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Callable, Mapping

from contract import Trajectory, Verdict, trajectory_from_dict
from runner.factories import scenario_dir
from runner.modal_batch import EpisodeJob, build_record, resolve, validate_truth, write_summaries


def _read_records(results_path: Path) -> list[dict]:
    with results_path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def _validate_output(results_path: Path, output: Path) -> None:
    if output.resolve() == results_path.resolve().parent:
        raise ValueError("Output directory must differ from the results directory")
    if output.exists():
        raise FileExistsError(f"Output directory already exists: {output}")


def _load_rubric(path: Path) -> dict:
    from auditor.audit import load_rubric

    return load_rubric(path)


def _load_default_assets(scenario: str) -> tuple[dict, dict]:
    bundle = scenario_dir(scenario)
    rubric = _load_rubric(bundle / "auditor" / "rubric.json")
    truth = json.loads((bundle / "auditor" / "truth.json").read_text(encoding="utf-8"))
    return rubric, truth


def reaudit(results_path: Path, output: Path, *,
            audit_fn: Callable[[Trajectory, Mapping, Mapping], Verdict],
            rubric: Mapping | None = None, truth: Mapping | None = None) -> dict:
    results_path = Path(results_path)
    output = Path(output)
    _validate_output(results_path, output)
    records = _read_records(results_path)
    scenarios = [record["job"].get("scenario", "a") for record in records]
    if (rubric is not None or truth is not None) and len(set(scenarios)) != 1:
        raise ValueError("--rubric and --truth overrides require every record to share a scenario")

    assets = {}
    for scenario in dict.fromkeys(scenarios):
        if rubric is None or truth is None:
            loaded_rubric, loaded_truth = _load_default_assets(scenario)
        else:
            loaded_rubric, loaded_truth = rubric, truth
        episode_rubric = rubric if rubric is not None else loaded_rubric
        episode_truth = truth if truth is not None else loaded_truth
        validate_truth(episode_truth)
        assets[scenario] = episode_rubric, episode_truth

    output.mkdir(parents=True, exist_ok=False)
    rebuilt_records = []
    changed = []
    for record in records:
        job_data = record["job"]
        episode_id = job_data["episode_id"]
        if not episode_id.isascii() or not episode_id.isdecimal():
            raise ValueError("Invalid episode ID")
        if "trajectory" in record:
            trajectory_doc = record["trajectory"]
        else:
            fallback = results_path.parent / "episodes" / f"{episode_id}.json"
            if not fallback.is_file():
                raise FileNotFoundError(
                    f"Missing trajectory for episode {episode_id}: {fallback}"
                )
            trajectory_doc = json.loads(fallback.read_text(encoding="utf-8"))
        trajectory = trajectory_from_dict(trajectory_doc)
        scenario = job_data.get("scenario", "a")
        episode_rubric, episode_truth = assets[scenario]
        verdict = audit_fn(
            deepcopy(trajectory), deepcopy(episode_rubric), deepcopy(episode_truth),
        )
        rebuilt = build_record(
            EpisodeJob(**job_data),
            trajectory,
            verdict,
            episode_truth,
            refusals=record.get("refusals", []),
            aborted_on_refusals=record.get("aborted_on_refusals", False),
            extra=record,
        )
        if rebuilt["verdict"] != record.get("verdict"):
            changed.append(episode_id)
        rebuilt_records.append(rebuilt)

    with (output / "results.jsonl").open("w", encoding="utf-8") as stream:
        for record in rebuilt_records:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
    write_summaries(rebuilt_records, output)
    audit_reference = getattr(audit_fn, "__dict__", {}).get("__reaudit_reference__")
    if not isinstance(audit_reference, str):
        module = getattr(audit_fn, "__module__", None)
        name = getattr(audit_fn, "__qualname__", None)
        if not isinstance(name, str):
            name = getattr(audit_fn, "__name__", None)
        if not isinstance(module, str):
            module = type(audit_fn).__module__
        if not isinstance(name, str):
            name = type(audit_fn).__qualname__
        audit_reference = f"{module}:{name}"
    result = {
        "source": str(results_path),
        "episodes": len(rebuilt_records),
        "audit": audit_reference,
        "verdicts_changed": changed,
    }
    (output / "reaudit.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, help="results.jsonl from a batch run")
    parser.add_argument("--output", type=Path, required=True, help="new output directory")
    parser.add_argument("--audit", default="auditor.audit:audit")
    parser.add_argument("--rubric", type=Path)
    parser.add_argument("--truth", type=Path)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _validate_output(args.results, args.output)
        rubric_override = None
        truth_override = None
        if args.rubric is not None or args.truth is not None:
            records = _read_records(args.results)
            scenarios = {record["job"].get("scenario", "a") for record in records}
            if len(scenarios) != 1:
                parser.error("--rubric and --truth overrides require every record to share a scenario")
            if args.rubric is not None:
                rubric_override = _load_rubric(args.rubric)
            if args.truth is not None:
                truth_override = json.loads(args.truth.read_text(encoding="utf-8"))

        audit_fn = resolve(args.audit)

        def audit_with_reference(trajectory, rubric, truth):
            return audit_fn(trajectory, rubric, truth)

        audit_with_reference.__reaudit_reference__ = args.audit
        result = reaudit(
            args.results,
            args.output,
            audit_fn=audit_with_reference,
            rubric=rubric_override,
            truth=truth_override,
        )
    except (OSError, ValueError, TypeError, ImportError) as exc:
        parser.error(str(exc))
    print(f"Re-audit complete: {len(result['verdicts_changed'])} verdicts changed")


if __name__ == "__main__":
    main()
