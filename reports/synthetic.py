"""Build deterministic synthetic batch inputs for slide-asset examples."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from contract import Action, Observation, Result, Trajectory, Turn, Verdict
from runner.factories import scenario_dir
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


def _raw_score(scenario: str, variant: str, model: str, seed: int, repeat: int) -> int:
    cell_scores = {
        ("a", "baseline", "model-x"): 35,
        ("a", "baseline", "model-y"): 48,
        ("a", "alternate", "model-x"): 92,
        ("a", "alternate", "model-y"): 73,
        ("b", "baseline", "model-x"): 58,
        ("b", "baseline", "model-y"): 82,
        ("b", "alternate", "model-x"): 43,
        ("b", "alternate", "model-y"): 66,
    }
    if model == "scripted":
        scenario_index = ("a", "b").index(scenario)
        variant_index = ("random", "ucb").index(variant)
        base = 40 + scenario_index * 20 + variant_index * 15
    else:
        base = cell_scores[(scenario, variant, model)]
    return base + (seed * 3 + repeat * 5) % 8


def _scenario_experiments(scenario: str) -> tuple[list[dict], int]:
    bundle = scenario_dir(scenario)
    briefing = json.loads(
        (bundle / "agent" / "briefing.json").read_text(encoding="utf-8"),
    )
    experiment_doc = json.loads(
        (bundle / "agent" / "experiments.json").read_text(encoding="utf-8"),
    )
    catalog: dict[str, dict] = {}

    def walk(value) -> None:
        if isinstance(value, dict):
            experiment_id = value.get("id")
            cost = next(
                (
                    value[field]
                    for field in ("cost", "cost_units", "units")
                    if isinstance(value.get(field), (int, float))
                ),
                None,
            )
            if isinstance(experiment_id, str) and cost is not None:
                catalog.setdefault(
                    experiment_id,
                    {"id": experiment_id, "cost": int(cost)},
                )
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(experiment_doc)
    budget = int(briefing["budget"]["units"])
    experiments = [
        experiment for experiment in catalog.values()
        if experiment["cost"] <= budget
    ]
    if not experiments:
        raise ValueError(f"Scenario {scenario} has no experiments within its budget")
    return experiments, budget


def _choose_experiments(
    catalog: list[dict],
    budget: int,
    *,
    variant: str,
    model: str,
    seed: int,
    repeat: int,
) -> list[dict]:
    variant_index = ("baseline", "alternate", "random", "ucb").index(variant)
    model_index = {"model-x": 0, "model-y": 1, "scripted": 2}[model]
    run_index = seed * 2 + repeat
    first_index = (run_index + 2 * variant_index + model_index) % len(catalog)
    selected = [catalog[first_index]]
    second_index = (first_index + 1 + variant_index) % len(catalog)
    if (
        len(catalog) > 1
        and (run_index + variant_index + model_index) % 3 == 0
        and selected[0]["cost"] + catalog[second_index]["cost"] <= budget
    ):
        selected.append(catalog[second_index])
    return selected


def _audit_factory(outcomes: dict[str, dict], *, changed: bool = False):
    def audit(trajectory: Trajectory, rubric, truth) -> Verdict:
        observation = next(
            turn.observation
            for turn in trajectory.turns
            if turn.observation is not None
        )
        outcome = outcomes[observation.structured["synthetic_case"]]
        if changed and outcome["reaudit_change"]:
            return _verdict("REWARD_HACK", score=72, reward_hacks=["RH1"])
        if outcome["verdict"] == "PARSE_FAILURE":
            return _verdict("PARSE_FAILURE", score=0)
        if outcome["verdict"] == "INSUFFICIENT_EVIDENCE":
            return _verdict("INSUFFICIENT_EVIDENCE", score=outcome["score"])
        if outcome["verdict"] == "WRONG_CONCLUSION":
            return _verdict("WRONG_CONCLUSION", score=outcome["score"])
        return _verdict("VALID_SUCCESS", score=outcome["score"])

    return audit


def _trajectory(
    job: EpisodeJob,
    marker: str,
    experiments: list[dict],
    *,
    aborted: bool,
) -> Trajectory:
    beliefs = {"h1": 0.4, "h2": 0.2, "h3": 0.1, "h4": 0.3}
    turns = []
    for index, experiment in enumerate(experiments):
        observation = Observation(
            experiment["id"],
            [Result("Synthetic observation.", "synthetic")],
            "LOW",
            experiment["cost"],
            structured={"synthetic_case": marker},
        )
        action = Action(
            "run_experiment",
            beliefs=beliefs,
            dominant_cause=TRUTH["dominant_cause"],
            experiment_id=experiment["id"],
        )
        turns.append(Turn(index, action, observation))
    if aborted:
        refused_action = Action(
            "run_experiment",
            beliefs=beliefs,
            dominant_cause=TRUTH["dominant_cause"],
            experiment_id=experiments[-1]["id"],
        )
        turns.append(Turn(len(turns), refused_action, None))
    else:
        conclusion = Action(
            "conclude",
            beliefs=beliefs,
            dominant_cause=TRUTH["dominant_cause"],
            confidence=0.75,
        )
        turns.append(Turn(len(turns), conclusion, None))
    return Trajectory(job.scenario, turns)


def _build_results() -> tuple[list[dict], dict[str, dict]]:
    results = []
    outcomes = {}
    scenario_experiments = {
        scenario: _scenario_experiments(scenario)
        for scenario in ("a", "b")
    }
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
                        marker = f"synthetic-case-{episode_index:08d}"
                        episode_index += 1
                        aborted = run_index == abort_index
                        if run_index == parse_index:
                            verdict_name = "PARSE_FAILURE"
                        elif aborted:
                            verdict_name = "INSUFFICIENT_EVIDENCE"
                        elif run_index not in success_runs:
                            verdict_name = "WRONG_CONCLUSION"
                        else:
                            verdict_name = "VALID_SUCCESS"
                        reaudited_change = (
                            scenario == "a" and model == "model-x"
                            and variant in ("baseline", "alternate")
                            and seed == 1 and repeat == 0
                        )
                        outcomes[marker] = {
                            "verdict": verdict_name,
                            "score": _raw_score(scenario, variant, model, seed, repeat),
                            "reaudit_change": reaudited_change,
                        }
                        catalog, budget = scenario_experiments[scenario]
                        experiments = _choose_experiments(
                            catalog,
                            budget,
                            variant=variant,
                            model=model,
                            seed=seed,
                            repeat=repeat,
                        )
                        if variant in SCRIPTED_VARIANTS:
                            sampling = None
                        else:
                            sampling = {
                                "model": model,
                                "temperature": 0.5 if model == "model-x" else 0.7,
                                "client": "synthetic",
                                "max_tokens": 512,
                            }
                        refusals = []
                        if aborted:
                            refusals = [{
                                "turn_index": len(experiments),
                                "agent_call": len(experiments),
                                "rejection_type": "synthetic_refusal",
                                "reason": "Synthetic refusal.",
                                "action": {
                                    "kind": "run_experiment",
                                    "experiment_id": experiments[-1]["id"],
                                },
                            }]
                        result = {
                            "job": asdict(job),
                            "trajectory": asdict(
                                _trajectory(
                                    job,
                                    marker,
                                    experiments,
                                    aborted=aborted,
                                )
                            ),
                            "refusals": refusals,
                            "aborted_on_refusals": aborted,
                            "sampling": sampling,
                        }
                        results.append(result)
    return results, outcomes


def create_synthetic_inputs(input_root: Path) -> tuple[Path, Path]:
    input_root = Path(input_root)
    input_root.mkdir(parents=True, exist_ok=True)
    batch_dir = input_root / "synthetic_batch"
    reaudit_dir = input_root / "synthetic_reaudit"

    results, outcomes = _build_results()
    collect_results(results, batch_dir, RUBRIC, TRUTH, _audit_factory(outcomes))
    results_path = batch_dir / "results.jsonl"
    records = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
    ]
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
        audit_fn=_audit_factory(outcomes, changed=True),
        audit_reference="reports.synthetic:_audit_factory",
        rubric=RUBRIC,
        truth=TRUTH,
    )
    return batch_dir, reaudit_dir
