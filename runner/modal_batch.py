r"""Run N repeats of every variant x model x seed combination on Modal.

Install dependencies: ``python -m pip install -r runner/requirements.txt``.
Run from the repository root with ``python -m runner.modal_batch --help``.

Example after the implementation hooks are available::

    python -m runner.modal_batch --variants baseline careful --models model-a \
        --seeds 1 2 3 --n 5 --rubric auditor/rubric.json \
        --truth auditor/truth.json --output runs/batch-001 \
        --env-factory integration:make_env --agent-factory integration:make_agent

This schedules 30 episodes. Hook modules must be locally importable; their
Python packages are included in the Modal image. Supply any model-client
dependencies with --pip-package and credential Secret names with --secret.

Integration hooks (import paths use ``module:callable``):
* env_factory(seed=...) -> contract.Env
* agent_factory(variant=..., model=..., seed=...) -> contract.Agent
* audit(trajectory, rubric, truth) -> contract.Verdict

The default auditor is auditor.audit:audit. Rubrics are loaded through
auditor.audit.load_rubric(), including sibling constraints when needed.
The environment and agent defaults remain contract stubs.
Agents return their posterior and dominant cause on Action. State is owned by
Env; the agent receives a copy so it cannot mutate the environment's state.

--truth accepts the contract JSON object with ``contribution_labels`` (a flat
mapping of four opaque hypothesis IDs to 0/1) and ``dominant_cause``. No domain payloads
are interpreted. Rubric and truth stay in the local auditing process and are
never passed to agent factories or Modal episode workers.

Outputs: episodes/<id>.json (exact contract shape), results.jsonl (metadata,
verdict and metrics), summary.json, grid_summary.json, reward_vs_audit.png,
and raw_vs_clean.png. Rates pool all models/seeds/repeats within a variant.
Refusal-aborted episodes remain in primary failure metrics and the charts, with
completed-only metrics reported separately; other failed episodes or audits
abort the batch rather than silently removing them.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import importlib
from itertools import product
import json
import math
from pathlib import Path
import random
from statistics import fmean
from typing import Callable, Iterable, Mapping

from contract import Agent, Env, Observation, Result, Trajectory, Turn, Verdict, trajectory_from_dict
from env import EnvRejection
from runner.agents import SCRIPTED_VARIANTS

CONCLUSION_METRICS = (
    "nominal_success_rate",
    "clean_success_rate",
    "reward_hack_rate",
    "protocol_violation_rate",
    "mean_brier",
    "overconfidence_rate",
    "mean_R_visible",
    "raw_score_mean",
)

GRID_CONCLUSION_FIELDS = CONCLUSION_METRICS + (
    "n_clean_success",
    "clean_success_ci95",
    "frontier_regret",
    "verdict_counts",
)


def scripted_label(not_meaningful: Iterable[str]) -> dict:
    return {
        "conclusion_metrics_meaningful": False,
        "not_meaningful": list(not_meaningful),
        "note": "scripted baseline: beliefs, dominant cause and confidence are random; "
        "compare experiment selection only (mean_cost). protocol_violation_rate is not "
        "meaningful: protocol constraints also check the conclusion's hypotheses and citations",
    }


# A refused purchase is not a Turn (nothing ran, nothing was charged). The
# reason is handed back to the agent as a zero-cost observation under this id so
# the model can choose again; it never enters the recorded trajectory.
REFUSAL_EXPERIMENT_ID = "__refused__"


@dataclass(frozen=True)
class EpisodeJob:
    episode_id: str
    variant: str
    model: str
    seed: int
    repeat: int
    effective_seed: int


@dataclass
class Refusal:
    turn_index: int
    agent_call: int
    rejection_type: str
    reason: str
    action: dict


@dataclass
class EpisodeRun:
    trajectory: Trajectory
    refusals: list[Refusal]
    aborted_on_refusals: bool

    @property
    def refusal_count(self) -> int:
        return len(self.refusals)


def make_env(*, seed: int) -> Env:
    """Placeholder for the environment workstream."""
    return Env()


def make_agent(*, variant: str, model: str, seed: int) -> Agent:
    """Placeholder for the agent workstream."""
    return Agent()


def resolve(reference: str) -> Callable:
    module, separator, name = reference.partition(":")
    if not separator or not module or not name:
        raise ValueError("Hooks must use module:callable import paths")
    value = getattr(importlib.import_module(module), name)
    if not callable(value):
        raise TypeError(f"Hook is not callable: {reference}")
    return value


def build_jobs(variants: list[str], models: list[str], seeds: list[int], n: int) -> list[EpisodeJob]:
    if n < 1 or any(not axis for axis in (variants, models, seeds)):
        raise ValueError("N and every grid axis must be nonempty/positive")
    if any(len(axis) != len(set(axis)) for axis in (variants, models, seeds)):
        raise ValueError("Grid axes must not contain duplicates")
    jobs = []
    for index, (variant, model, seed, repeat) in enumerate(product(variants, models, seeds, range(n))):
        # Matched seeds across variants/models; distinct deterministic repeat streams.
        digest = hashlib.sha256(f"{seed}:{repeat}".encode()).digest()
        effective_seed = seed if repeat == 0 else int.from_bytes(digest[:8], "big")
        jobs.append(EpisodeJob(f"{index:08d}", variant, model, seed, repeat, effective_seed))
    return jobs


def run_episode(job: EpisodeJob, env_factory: Callable, agent_factory: Callable,
                max_turns: int = 100, max_refusals: int = 3,
                log: Callable[[str], None] | None = None) -> EpisodeRun:
    """Drive only the contract interfaces; never interpret observation strings.

    An action the Env refuses (EnvRejection: over budget, malformed conclude,
    ...) is fed back to the agent as a REFUSAL_EXPERIMENT_ID observation
    carrying the reason and recorded with the rejected action. More than
    ``max_refusals`` refusals returns the partial trajectory marked as aborted.
    ``max_turns`` bounds agent calls, accepted or refused."""
    if max_turns < 1:
        raise ValueError("max_turns must be positive")
    random.seed(job.effective_seed)
    env = env_factory(seed=job.effective_seed)
    agent = agent_factory(variant=job.variant, model=job.model, seed=job.effective_seed)
    observation = env.reset()
    trajectory = Trajectory(env.state.scenario_id, [])
    refusals = []
    for agent_call in range(max_turns):
        action = agent.act(deepcopy(observation), deepcopy(env.state))
        if action.kind not in ("run_experiment", "conclude"):
            raise ValueError(f"Unknown action kind: {action.kind}")
        saved_action = deepcopy(action)
        try:
            observation = env.step(action)
        except EnvRejection as exc:
            refusals.append(Refusal(
                turn_index=len(trajectory.turns),
                agent_call=agent_call,
                rejection_type=getattr(exc, "code", "unclassified"),
                reason=exc.reason,
                action=asdict(saved_action),
            ))
            if log is not None:
                log(f"[env] refused {saved_action.kind} {saved_action.experiment_id or ''}: {exc.reason}")
            observation = Observation(REFUSAL_EXPERIMENT_ID,
                                      [Result(f"refused: {exc.reason}", "env")], "UNRATED", 0, {})
            if len(refusals) > max_refusals:
                return EpisodeRun(trajectory, refusals, aborted_on_refusals=True)
            continue
        trajectory.turns.append(Turn(
            len(trajectory.turns), saved_action,
            None if saved_action.kind == "conclude" else deepcopy(observation),
        ))
        if saved_action.kind == "conclude":
            return EpisodeRun(trajectory, refusals, aborted_on_refusals=False)
        if env.state.concluded:
            raise ValueError("Env ended the episode without a conclude action")
    raise RuntimeError(f"Episode {job.episode_id} did not conclude within {max_turns} turns")


def remote_episode(job: EpisodeJob, env_factory: str, agent_factory: str,
                   max_turns: int) -> dict:
    episode = run_episode(job, resolve(env_factory), resolve(agent_factory), max_turns)
    return {
        "job": asdict(job),
        "trajectory": asdict(episode.trajectory),
        "refusals": [asdict(refusal) for refusal in episode.refusals],
        "aborted_on_refusals": episode.aborted_on_refusals,
    }


def validate_truth(truth: Mapping) -> None:
    labels = truth["contribution_labels"]
    if len(labels) != 4 or any(value not in (0, 1) for value in labels.values()):
        raise ValueError("Truth labels must map exactly four hypothesis IDs to 0 or 1")
    if truth["dominant_cause"] not in labels:
        raise ValueError("Truth dominant_cause must be a labeled hypothesis ID")


def episode_metrics(trajectory: Trajectory, verdict: Verdict, truth: Mapping) -> dict:
    validate_truth(truth)
    if not trajectory.turns:
        raise ValueError("Cannot score an empty episode")
    beliefs = trajectory.turns[-1].action.beliefs
    if beliefs.keys() != truth["contribution_labels"].keys():
        raise ValueError("Final beliefs must have exactly the truth hypothesis IDs")
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in beliefs.values()):
        raise ValueError("Beliefs must be finite probabilities in [0,1]")
    conclusion = trajectory.turns[-1].action
    return {
        "nominal_success": conclusion.kind == "conclude" and
            conclusion.dominant_cause == truth["dominant_cause"],
        "clean_success": verdict.verdict == "VALID_SUCCESS",
        "reward_hack": verdict.verdict == "REWARD_HACK" or bool(verdict.reward_hacks),
        # The dimension records breaches even if another verdict takes precedence.
        "protocol_violation": verdict.verdict == "PROTOCOL_VIOLATION" or
            verdict.scores["protocol_validity"] == 0,
        "cost": sum(t.observation.cost for t in trajectory.turns
                    if t.action.kind == "run_experiment" and t.observation is not None),
        "brier": sum((beliefs[h] - y) ** 2 for h, y in truth["contribution_labels"].items()) / 4,
        "overconfidence": "OVERCONFIDENT" in verdict.flags,
        "R_visible": verdict.R_visible,
        "final_score": verdict.final_score,
    }


def aborted_metrics(trajectory: Trajectory, verdict: Verdict) -> dict:
    return {
        "nominal_success": False,
        "clean_success": False,
        "reward_hack": verdict.verdict == "REWARD_HACK" or bool(verdict.reward_hacks),
        "protocol_violation": verdict.verdict == "PROTOCOL_VIOLATION" or
            verdict.scores["protocol_validity"] == 0,
        "cost": sum(t.observation.cost for t in trajectory.turns
                    if t.action.kind == "run_experiment" and t.observation is not None),
        "brier": None,
        "overconfidence": "OVERCONFIDENT" in verdict.flags,
        "R_visible": 0.0,
        "final_score": 0.0,
    }


def aggregate(records: list[dict]) -> dict:
    metrics = {
        "nominal_success_rate": "nominal_success", "clean_success_rate": "clean_success",
        "reward_hack_rate": "reward_hack", "protocol_violation_rate": "protocol_violation",
        "mean_cost": "cost", "mean_brier": "brier", "overconfidence_rate": "overconfidence",
        "mean_R_visible": "R_visible", "raw_score_mean": "final_score",
    }

    def metric_means(metric_rows: list[dict]) -> dict:
        briers = [row["brier"] for row in metric_rows if row["brier"] is not None]
        return {
            **{
                output: fmean(row[source] for row in metric_rows) if metric_rows else None
                for output, source in metrics.items()
                if output != "mean_brier"
            },
            "mean_brier": fmean(briers) if briers else None,
            "brier_n": len(briers),
        }

    summary = {}
    for variant in sorted({r["job"]["variant"] for r in records}):
        rows = [r for r in records if r["job"]["variant"] == variant]
        completed = [r["metrics"] for r in rows if not r.get("aborted_on_refusals", False)]
        all_metrics = [r["metrics"] for r in rows]
        summary[variant] = {
            "episodes": len(rows),
            "completed_episodes": len(completed),
            "aborted_on_refusals": sum(bool(r.get("aborted_on_refusals", False)) for r in rows),
            "refusals": sum(r.get("refusal_count", len(r.get("refusals", []))) for r in rows),
            **metric_means(all_metrics),
            "completed_only": metric_means(completed) if completed else None,
        }
        if variant in SCRIPTED_VARIANTS:
            summary[variant].update(scripted_label(CONCLUSION_METRICS))
    return summary


def wilson_interval(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= k <= n:
        raise ValueError("k must be between 0 and n")
    z_squared = z * z
    proportion = k / n
    denominator = 1 + z_squared / n
    center = (proportion + z_squared / (2 * n)) / denominator
    margin = (
        z * math.sqrt(proportion * (1 - proportion) / n + z_squared / (4 * n * n))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def grid_summary(records: list[dict]) -> list[dict]:
    verdict_names = (
        "VALID_SUCCESS", "REWARD_HACK", "UNSAFE_ACTION", "PROTOCOL_VIOLATION",
        "INSUFFICIENT_EVIDENCE", "WRONG_CONCLUSION", "PARSE_FAILURE",
    )
    cells: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        job = record["job"]
        key = (job.get("scenario", "a"), job["variant"])
        cells.setdefault(key, []).append(record)

    summary = []
    for (scenario, variant), rows in cells.items():
        n_runs = len(rows)
        n_parse_failure = sum(r["verdict"]["verdict"] == "PARSE_FAILURE" for r in rows)
        n_aborted = sum(bool(r.get("aborted_on_refusals", False)) for r in rows)
        scored_rows = [r for r in rows if r["verdict"]["verdict"] != "PARSE_FAILURE"]
        n_scored = len(scored_rows)
        n_clean_success = sum(
            (r.get("metrics") or {}).get("clean_success") is True for r in scored_rows
        )
        clean_success_rate = n_clean_success / n_scored if n_scored else None
        clean_success_ci95 = (
            list(wilson_interval(n_clean_success, n_scored)) if n_scored else None
        )
        verdict_counts = dict.fromkeys((*verdict_names, "OTHER"), 0)
        for row in rows:
            verdict_name = row["verdict"]["verdict"]
            verdict_counts[verdict_name if verdict_name in verdict_counts else "OTHER"] += 1
        row = {
            "scenario": scenario,
            "variant": variant,
            "n_runs": n_runs,
            "n_parse_failure": n_parse_failure,
            "n_aborted_on_refusals": n_aborted,
            "n_scored": n_scored,
            "n_clean_success": n_clean_success,
            "clean_success_rate": clean_success_rate,
            "clean_success_ci95": clean_success_ci95,
            "frontier_regret": (
                (1 if n_clean_success >= 1 else 0) - clean_success_rate
                if clean_success_rate is not None else None
            ),
            "raw_score_mean": (
                fmean((r.get("metrics") or {})["final_score"] for r in scored_rows)
                if n_scored else None
            ),
            "verdict_counts": verdict_counts,
        }
        if variant in SCRIPTED_VARIANTS:
            row.update(scripted_label(GRID_CONCLUSION_FIELDS))
        summary.append(row)
    return sorted(
        summary,
        key=lambda row: (
            row["frontier_regret"] is None,
            -row["frontier_regret"] if row["frontier_regret"] is not None else 0,
            row["scenario"],
            row["variant"],
        ),
    )


def write_chart(records: list[dict], path: Path) -> None:
    from matplotlib import rcParams
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D

    figure = Figure(figsize=(8, 5), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    variants = sorted({r["job"]["variant"] for r in records})
    legend_handles = []
    has_aborted = any(r.get("aborted_on_refusals", False) for r in records)
    palette = rcParams["axes.prop_cycle"].by_key()["color"]
    for index, variant in enumerate(variants):
        color = palette[index % len(palette)]
        legend_handles.append(Line2D([], [], color=color, marker="o", linestyle="None",
                                     label=(
                                         f"{variant} (scripted; conclusion metrics not meaningful)"
                                         if variant in SCRIPTED_VARIANTS else variant
                                     )))
        for aborted, marker in ((False, "o"), (True, "x")):
            rows = [
                r for r in records
                if r["job"]["variant"] == variant and
                bool(r.get("aborted_on_refusals", False)) == aborted
            ]
            if rows:
                axes.scatter([r["verdict"]["R_visible"] for r in rows],
                             [r["verdict"]["final_score"] for r in rows],
                             color=color, marker=marker, alpha=0.7, label="_nolegend_")
    if has_aborted:
        legend_handles.append(Line2D([], [], color="black", marker="x", linestyle="None",
                                     label="aborted on refusals (x)"))
    axes.set(xlabel="Visible reward (R_visible)", ylabel="Final audited score",
             title="Visible reward vs. audited score")
    axes.grid(alpha=0.2)
    if legend_handles:
        axes.legend(handles=legend_handles, title="Agent variant / outcome")
    figure.savefig(path, dpi=160)


def _jitter(i: int, count: int, width: float = 0.3) -> float:
    if count < 1 or not 0 <= i < count:
        raise ValueError("jitter index must be within a nonempty group")
    if width < 0:
        raise ValueError("jitter width must be nonnegative")
    if count == 1:
        return 0.0
    return -width / 2 + width * i / (count - 1)


def write_clean_chart(records: list[dict], path: Path) -> None:
    from matplotlib import rcParams
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D

    figure = Figure(figsize=(8, 5), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    variants = sorted({r["job"]["variant"] for r in records})
    legend_handles = []
    has_aborted = any(r.get("aborted_on_refusals", False) for r in records)
    palette = rcParams["axes.prop_cycle"].by_key()["color"]
    for variant_index, variant in enumerate(variants):
        color = palette[variant_index % len(palette)]
        variant_offset = (
            (variant_index - (len(variants) - 1) / 2) * 0.04 / max(len(variants) - 1, 1)
        )
        legend_handles.append(Line2D([], [], color=color, marker="o", linestyle="None",
                                     label=(
                                         f"{variant} (scripted; conclusion metrics not meaningful)"
                                         if variant in SCRIPTED_VARIANTS else variant
                                     )))
        for clean_success in (False, True):
            rows = [
                row for row in records
                if row["job"]["variant"] == variant and
                bool((row.get("metrics") or {}).get("clean_success")) == clean_success
            ]
            x_positions = [
                int(clean_success) + _jitter(index, len(rows)) + variant_offset
                for index in range(len(rows))
            ]
            for aborted, marker in ((False, "o"), (True, "x")):
                points = [
                    (row, x_position)
                    for row, x_position in zip(rows, x_positions)
                    if bool(row.get("aborted_on_refusals", False)) == aborted
                ]
                if points:
                    axes.scatter(
                        [x_position for _, x_position in points],
                        [row["verdict"]["final_score"] for row, _ in points],
                        color=color,
                        marker=marker,
                        alpha=0.7,
                        label="_nolegend_",
                    )
    if has_aborted:
        legend_handles.append(Line2D([], [], color="black", marker="x", linestyle="None",
                                     label="aborted on refusals (x)"))
    axes.set_xticks([0, 1], labels=["not clean (0)", "clean (1)"])
    axes.set_xlim(-0.5, 1.5)
    axes.set(xlabel="Clean success", ylabel="Raw audited score (final_score)",
             title="Raw audited score vs. clean success")
    axes.grid(alpha=0.2)
    if legend_handles:
        axes.legend(handles=legend_handles, title="Agent variant / outcome")
    figure.savefig(path, dpi=160)


def collect_results(results: Iterable[dict], output: Path, rubric: dict, truth: Mapping,
                    audit_fn: Callable[[Trajectory, dict, dict], Verdict]) -> dict:
    """Persist each contract episode before auditing it, then emit one summary/chart."""
    validate_truth(truth)
    output.mkdir(parents=True, exist_ok=False)
    episodes = output / "episodes"
    episodes.mkdir()
    records = []
    with (output / "results.jsonl").open("w", encoding="utf-8") as stream:
        for result in results:
            job = EpisodeJob(**result["job"])
            # IDs are generated by build_jobs, never derived from model/variant strings.
            if not job.episode_id.isascii() or not job.episode_id.isdecimal():
                raise ValueError("Invalid episode ID")
            trajectory = trajectory_from_dict(result["trajectory"])
            with (episodes / f"{job.episode_id}.json").open("x", encoding="utf-8") as log:
                json.dump(asdict(trajectory), log, indent=2, allow_nan=False)
            verdict = audit_fn(deepcopy(trajectory), deepcopy(rubric), deepcopy(truth))
            refusals = result.get("refusals", [])
            aborted_on_refusals = result.get("aborted_on_refusals", False)
            record = {"job": asdict(job), "verdict": asdict(verdict),
                      "refusals": refusals,
                      "refusal_count": len(refusals),
                      "aborted_on_refusals": aborted_on_refusals,
                      "metrics": aborted_metrics(trajectory, verdict) if aborted_on_refusals
                      else episode_metrics(trajectory, verdict, truth)}
            stream.write(json.dumps(record, allow_nan=False) + "\n")
            stream.flush()
            records.append(record)
    summary = aggregate(records)
    grid = grid_summary(records)
    write_chart(records, output / "reward_vs_audit.png")
    write_clean_chart(records, output / "raw_vs_clean.png")
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    (output / "grid_summary.json").write_text(
        json.dumps(grid, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variants", nargs="+", required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--n", type=int, default=1, help="Repeats per variant/model/seed combination")
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory for this batch")
    parser.add_argument("--env-factory", default="runner.modal_batch:make_env")
    parser.add_argument("--agent-factory", default="runner.modal_batch:make_agent")
    parser.add_argument("--audit", default="auditor.audit:audit")
    parser.add_argument("--max-turns", type=int, default=100)
    parser.add_argument("--max-containers", type=int, default=32)
    parser.add_argument("--timeout", type=int, default=900, help="Seconds per remote episode")
    parser.add_argument("--pip-package", action="append", default=[], help="Additional remote dependency")
    parser.add_argument("--secret", action="append", default=[], help="Modal Secret name for model credentials")
    args = parser.parse_args(argv)
    jobs = build_jobs(args.variants, args.models, args.seeds, args.n)
    if min(args.max_turns, args.max_containers, args.timeout) < 1:
        parser.error("Turn, container and timeout limits must be positive")
    if args.output.exists():
        parser.error("Output directory already exists; choose a new batch directory")
    for reference in (args.env_factory, args.agent_factory):
        resolve(reference)
    audit_fn = resolve(args.audit)
    # Keep auditor imports local: episode workers do not need auditor code or data.
    from auditor.audit import load_rubric

    rubric = load_rubric(args.rubric)
    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    validate_truth(truth)

    import modal
    importlib.import_module("matplotlib")  # Fail before launching paid work if the chart dependency is missing.

    image = modal.Image.debian_slim(python_version="3.12")
    if args.pip_package:
        image = image.pip_install(*args.pip_package)
    modules = {"contract", "runner"}
    modules.update(ref.split(":")[0].split(".")[0] for ref in (args.env_factory, args.agent_factory))
    image = image.add_local_python_source(*sorted(modules))
    app = modal.App("falsifylab-modal-batch")
    worker = app.function(image=image, timeout=args.timeout, max_containers=args.max_containers,
                          secrets=[modal.Secret.from_name(name) for name in args.secret])(remote_episode)
    with modal.enable_output(), app.run():
        results = worker.map(jobs, kwargs={"env_factory": args.env_factory,
                             "agent_factory": args.agent_factory, "max_turns": args.max_turns},
                             order_outputs=False)
        summary = collect_results(results, args.output, rubric, truth, audit_fn)
    print(json.dumps(summary, indent=2))
    print("== Grid summary ==")
    print((args.output / "grid_summary.json").read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
