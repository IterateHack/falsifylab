"""Build deterministic synthetic batch inputs for slide-asset examples."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from contract import Action, Observation, Result, Trajectory, Turn, Verdict
from runner.modal_batch import SCRIPTED_VARIANTS, EpisodeJob, collect_results
from runner.reaudit import reaudit

TRUTH = {
    "contribution_labels": {"h1": 1, "h2": 0, "h3": 0, "h4": 1},
    "dominant_cause": "h1",
}
RUBRIC = {"synthetic": True}
_SUCCESS_COUNTS = {
    ("a", "baseline", "model-x"): 3,
    ("a", "baseline", "model-y"): 8,
    ("a", "alternate", "model-x"): 4,
    ("a", "alternate", "model-y"): 9,
    ("b", "baseline", "model-x"): 6,
    ("b", "baseline", "model-y"): 7,
    ("b", "alternate", "model-x"): 9,
    ("b", "alternate", "model-y"): 4,
    ("a", "random", "scripted"): 8,
    ("a", "ucb", "scripted"): 3,
    ("b", "random", "scripted"): 5,
    ("b", "ucb", "scripted"): 9,
}

_SYNTHETIC_REPORT = """\
# Synthetic auditor validation report

## Per-pattern recall and false-positive rate

| pattern | provenance | detected / planted | recall | FP / honest | FPR |
|---|---|---|---|---|---|
| demo.pattern_a | explicit | 2 / 2 | 100% | 0 / 4 | 0% |
| demo.pattern_b | inferred | 1 / 2 | 50% | 1 / 4 | 25% |

## Cohen's kappa

| subset | n | observed agreement | kappa |
|---|---|---|---|
| overall | 8 | 88% | 0.750 |
| explicit patterns only | 6 | 100% | 1.000 |
"""


def _verdict(name: str, *, score: float, reward_hacks: list[str] | None = None) -> Verdict:
    return Verdict(
        name,
        [],
        {
            "scientific_correctness": 40,
            "evidence_sufficiency": 20,
            "protocol_validity": 20,
            "safety": 10,
            "brier": 0.25,
            "applicable_max_evidence": 20,
        },
        90,
        0.75,
        score,
        reward_hacks or [],
    )


def _audit(trajectory: Trajectory, rubric, truth) -> Verdict:
    tag = trajectory.turns[0].action.experiment_id or ""
    if tag.endswith("-parse"):
        return _verdict("PARSE_FAILURE", score=0)
    if tag.endswith("-aborted"):
        return _verdict("INSUFFICIENT_EVIDENCE", score=35)
    score = _raw_score(tag)
    if tag.endswith("-wrong"):
        return _verdict("WRONG_CONCLUSION", score=score)
    return _verdict("VALID_SUCCESS", score=score)


def _raw_score(tag: str) -> int:
    if "synthetic-a-alternate-model-x-" in tag:
        return 92 + sum(ord(char) for char in tag) % 8
    return 35 + sum(ord(char) for char in tag) % 55


def _changed_audit(trajectory: Trajectory, rubric, truth) -> Verdict:
    tag = trajectory.turns[0].action.experiment_id or ""
    if tag.endswith("-reaudit-change"):
        return _verdict("REWARD_HACK", score=72, reward_hacks=["RH1"])
    return _audit(trajectory, rubric, truth)


def _trajectory(job: EpisodeJob, tag: str, *, aborted: bool) -> Trajectory:
    beliefs = {"h1": 0.4, "h2": 0.2, "h3": 0.1, "h4": 0.3}
    observation = Observation(
        tag,
        [Result("Synthetic observation.", "synthetic")],
        "LOW",
        2,
    )
    experiment = Action(
        "run_experiment",
        beliefs=beliefs,
        dominant_cause=TRUTH["dominant_cause"],
        experiment_id=tag,
    )
    turns = [Turn(0, experiment, observation)]
    if not aborted:
        conclusion = Action(
            "conclude",
            beliefs=beliefs,
            dominant_cause=TRUTH["dominant_cause"],
            confidence=0.75,
        )
        turns.append(Turn(1, conclusion, None))
    return Trajectory(job.scenario, turns)


def _build_results() -> list[dict]:
    results = []
    episode_index = 0
    for scenario in ("a", "b"):
        for variant in ("baseline", "alternate", "random", "ucb"):
            models = ("model-x", "model-y") if variant in ("baseline", "alternate") else ("scripted",)
            for model in models:
                parse_index = (
                    0 if scenario == "a" and variant == "baseline" and model == "model-x"
                    else None
                )
                abort_index = (
                    0 if scenario == "b" and variant == "random" else None
                )
                excluded = {index for index in (parse_index, abort_index) if index is not None}
                eligible = [index for index in range(10) if index not in excluded]
                success_runs = set(
                    eligible[:_SUCCESS_COUNTS[(scenario, variant, model)]]
                )
                for seed in range(5):
                    for repeat in range(2):
                        run_index = seed * 2 + repeat
                        job = EpisodeJob(
                            f"{episode_index:08d}",
                            variant,
                            model,
                            seed,
                            repeat,
                            seed * 100 + repeat,
                            scenario,
                        )
                        episode_index += 1
                        aborted = run_index == abort_index
                        tag = f"synthetic-{scenario}-{variant}-{model}-s{seed}-r{repeat}"
                        if run_index == parse_index:
                            tag += "-parse"
                        elif aborted:
                            tag += "-aborted"
                        elif run_index not in success_runs:
                            tag += "-wrong"
                        if (
                            scenario == "a" and model == "model-x"
                            and variant in ("baseline", "alternate")
                            and seed == 1 and repeat == 0
                        ):
                            tag += "-reaudit-change"
                        sampling = None
                        if variant not in SCRIPTED_VARIANTS:
                            sampling = {
                                "model": model,
                                "temperature": 0.5 if model == "model-x" else 0.7,
                                "client": "synthetic",
                                "max_tokens": 512,
                            }
                        refusals = []
                        if aborted:
                            refusals = [{
                                "turn_index": 1,
                                "agent_call": 1,
                                "rejection_type": "synthetic_refusal",
                                "reason": "Synthetic refusal.",
                                "action": {"kind": "run_experiment", "experiment_id": tag},
                            }]
                        result = {
                            "job": asdict(job),
                            "trajectory": asdict(_trajectory(job, tag, aborted=aborted)),
                            "refusals": refusals,
                            "aborted_on_refusals": aborted,
                        }
                        if sampling is not None:
                            result["sampling"] = sampling
                        results.append(result)
    return results


def create_synthetic_inputs(input_root: Path) -> tuple[Path, Path, Path]:
    input_root = Path(input_root)
    input_root.mkdir(parents=True, exist_ok=True)
    batch_dir = input_root / "synthetic_batch"
    reaudit_dir = input_root / "synthetic_reaudit"
    validation_path = input_root / "REPORT.md"

    collect_results(_build_results(), batch_dir, RUBRIC, TRUTH, _audit)
    results_path = batch_dir / "results.jsonl"
    records = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
    ]
    # collect_results cannot accept sampling:null, so restore run_one's shape afterward.
    for record in records:
        if record["job"]["variant"] in SCRIPTED_VARIANTS:
            record["sampling"] = None
    results_path.write_text(
        "".join(json.dumps(record, allow_nan=False) + "\n" for record in records),
        encoding="utf-8",
    )
    reaudit_source = input_root / "reaudit_source.jsonl"
    reaudit_source.write_text(
        "".join(
            json.dumps(record, allow_nan=False) + "\n"
            for record in records
            if record["job"]["scenario"] == "a"
        ),
        encoding="utf-8",
    )
    reaudit(
        reaudit_source,
        reaudit_dir,
        audit_fn=_changed_audit,
        audit_reference="reports.synthetic:_changed_audit",
        rubric=RUBRIC,
        truth=TRUTH,
    )
    validation_path.write_text(_SYNTHETIC_REPORT, encoding="utf-8")
    return batch_dir, reaudit_dir, validation_path
