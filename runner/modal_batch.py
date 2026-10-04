r"""Run N repeats of every variant x model x seed combination on Modal.

Install dependencies: ``python -m pip install -r runner/requirements.txt``.
Run from the repository root with ``python -m runner.modal_batch --help``.

The default is a local, no-network dry run using an abstaining stub client::

    python -m runner.modal_batch --variants baseline --models claude-sonnet-4-5 \
        --seeds 0 1 --output runs/dry-run

Real Anthropic calls on Modal require explicit ``--live``::

    python -m runner.modal_batch --live --variants baseline --models claude-sonnet-4-5 \
        --seeds 0 1 --output runs/live

Hook modules must be locally importable; their Python packages are included in
the Modal image. Supply additional dependencies with --pip-package and
additional Modal Secret names with --secret. The ``falsifylab-keys`` Secret is
always attached to live workers.

Integration hooks (import paths use ``module:callable``):
* env_factory(seed=..., scenario=..., budget=...) -> contract.Env
* agent_factory(variant=..., model=..., seed=..., client=..., scenario=...) -> contract.Agent
* audit(trajectory, rubric, truth) -> contract.Verdict

The default auditor is auditor.audit:audit. Rubrics are loaded through
auditor.audit.load_rubric(), including sibling constraints when needed.
The default factories construct the real scenario Env and LLMAgent.
Agents return their posterior and dominant cause on Action. State is owned by
Env; the agent receives a copy so it cannot mutate the environment's state.

--truth accepts the contract JSON object with ``contribution_labels`` (a flat
mapping of four opaque hypothesis IDs to 0/1) and ``dominant_cause``. No domain payloads
are interpreted. Rubric and truth stay in the local auditing process and are
never passed to agent factories or Modal episode workers.

Outputs: episodes/<id>.json (exact contract shape), results.jsonl (metadata,
verdict and metrics), summary.json, grid_summary.json, spend.json, and
reward_vs_audit.png. Rates pool all models/seeds/repeats within a variant.
Refusal-aborted episodes remain in primary failure metrics and the chart, with
completed-only metrics reported separately; other failed episodes or audits
abort the batch rather than silently removing them.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import importlib
import os
from functools import partial
from itertools import product
import json
import math
from pathlib import Path
import random
import socket
from statistics import fmean
import sys
from typing import Callable, Iterable, Mapping

from contract import Agent, Env, Observation, Result, Trajectory, Turn, Verdict, trajectory_from_dict
from env import EnvRejection
from runner.model_clients import DEFAULT_TEMPERATURE, SpendLimitExceeded, price_for

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
    scenario: str = "a"


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


def worker_bundle_files(scenario: str) -> list[tuple[Path, str]]:
    from runner.factories import PROMPTS_DIR, REPO_ROOT, scenario_dir

    bundle = scenario_dir(scenario).resolve()
    repository = REPO_ROOT.resolve()
    remote_bundle = Path("/root") / bundle.relative_to(repository)
    files = [
        (path, str(remote_bundle / "agent" / path.name))
        for path in sorted((bundle / "agent").glob("*.json"))
        if path.name not in {"rubric.json", "truth.json", "constraints.json"}
    ]
    expected_observations = bundle / "auditor" / "expected_observations.json"
    if not expected_observations.is_file():
        raise FileNotFoundError(expected_observations)
    files.append((
        expected_observations,
        str(remote_bundle / "auditor" / "expected_observations.json"),
    ))
    files.extend(
        (path, str(Path("/root") / "agents" / "prompts" / path.name))
        for path in sorted(PROMPTS_DIR.glob("*.md"))
    )
    return files


def build_jobs(variants: list[str], models: list[str], seeds: list[int], n: int,
               scenario: str = "a") -> list[EpisodeJob]:
    if n < 1 or any(not axis for axis in (variants, models, seeds)):
        raise ValueError("N and every grid axis must be nonempty/positive")
    if any(len(axis) != len(set(axis)) for axis in (variants, models, seeds)):
        raise ValueError("Grid axes must not contain duplicates")
    jobs = []
    for index, (variant, model, seed, repeat) in enumerate(product(variants, models, seeds, range(n))):
        # Matched seeds across variants/models; distinct deterministic repeat streams.
        digest = hashlib.sha256(f"{seed}:{repeat}".encode()).digest()
        effective_seed = seed if repeat == 0 else int.from_bytes(digest[:8], "big")
        jobs.append(EpisodeJob(f"{index:08d}", variant, model, seed, repeat, effective_seed, scenario))
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
                   max_turns: int, client_spec: dict | None = None) -> dict:
    result = {
        "job": asdict(job),
    }
    if client_spec is None:
        episode = run_episode(job, resolve(env_factory), resolve(agent_factory), max_turns)
    else:
        from runner.factories import make_client

        client = make_client(
            mode=client_spec["mode"],
            model=job.model,
            scenario=job.scenario,
            temperature=client_spec["temperature"],
            max_tokens=client_spec["max_tokens"],
            usd_per_mtok_in=client_spec["usd_per_mtok_in"],
            usd_per_mtok_out=client_spec["usd_per_mtok_out"],
            spend_limit_usd=client_spec["spend_limit_usd"],
        )
        env_maker = partial(
            resolve(env_factory), scenario=job.scenario, budget=client_spec["budget"],
        )
        agent_maker = partial(
            resolve(agent_factory), client=client, scenario=job.scenario,
        )
        episode = run_episode(job, env_maker, agent_maker, max_turns)
        result.update({
            "sampling": {
                "model": client.model,
                "temperature": client.temperature,
                "max_tokens": client.max_tokens,
                "seed_applied_to_model": False,
                "client": client_spec["mode"],
            },
            "tokens": client.ledger.snapshot(),
            "model_call_log": client.call_log,
            "worker": {
                "hostname": socket.gethostname(),
                "modal_task_id": os.environ.get("MODAL_TASK_ID"),
                "on_modal": bool(os.environ.get("MODAL_TASK_ID")),
            },
        })
    result.update({
        "trajectory": asdict(episode.trajectory),
        "refusals": [asdict(refusal) for refusal in episode.refusals],
        "aborted_on_refusals": episode.aborted_on_refusals,
    })
    return result


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
        "valid_success": verdict.verdict == "VALID_SUCCESS",
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
        "valid_success": False,
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
        "nominal_success_rate": "nominal_success", "valid_success_rate": "valid_success",
        "reward_hack_rate": "reward_hack", "protocol_violation_rate": "protocol_violation",
        "mean_cost": "cost", "mean_brier": "brier", "overconfidence_rate": "overconfidence",
        "mean_R_visible": "R_visible", "mean_final_score": "final_score",
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
    return summary


def grid_summary(records: list[dict]) -> list[dict]:
    cells: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        job = record["job"]
        key = (job.get("scenario", "a"), job["variant"])
        cells.setdefault(key, []).append(record)

    summary = []
    for (scenario, variant), rows in cells.items():
        n_runs = len(rows)
        n_parse_failure = sum(r["verdict"]["verdict"] == "PARSE_FAILURE" for r in rows)
        n_success = sum(
            (r.get("metrics") or {}).get("valid_success") is True for r in rows
        )
        denominator = n_runs - n_parse_failure
        success_rate = n_success / denominator if denominator else None
        summary.append({
            "scenario": scenario,
            "variant": variant,
            "n_runs": n_runs,
            "n_parse_failure": n_parse_failure,
            "n_success": n_success,
            "success_rate": success_rate,
            "frontier_regret": (
                (1 if n_success >= 1 else 0) - success_rate if success_rate is not None else None
            ),
            "success_metric": "valid_success",
        })
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
                                     label=variant))
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


def collect_results(results: Iterable[dict], output: Path, rubric: dict, truth: Mapping,
                    audit_fn: Callable[[Trajectory, dict, dict], Verdict],
                    spend_limit_usd: float | None = None) -> dict:
    """Persist each contract episode before auditing it, then emit one summary/chart."""
    validate_truth(truth)
    output.mkdir(parents=True, exist_ok=False)
    episodes = output / "episodes"
    episodes.mkdir()
    records = []
    total_input_tokens = 0
    total_output_tokens = 0
    stage_cost_usd = 0.0
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
            for field_name in ("sampling", "tokens", "model_call_log", "worker"):
                if field_name in result:
                    record[field_name] = result[field_name]
            stream.write(json.dumps(record, allow_nan=False) + "\n")
            stream.flush()
            records.append(record)
            tokens = result.get("tokens")
            if tokens is not None:
                episode_cost = float(tokens["cost_usd"])
                stage_cost_usd += episode_cost
                total_input_tokens += int(tokens["input_tokens"])
                total_output_tokens += int(tokens["output_tokens"])
                limit_label = (
                    f"${spend_limit_usd:.2f}" if spend_limit_usd is not None else "unlimited"
                )
                print(
                    f"[spend] episode {job.episode_id}: ${episode_cost:.4f}  "
                    f"stage cumulative ${stage_cost_usd:.4f} "
                    f"(limit {limit_label})",
                    file=sys.stderr,
                    flush=True,
                )
                if spend_limit_usd is not None and stage_cost_usd > spend_limit_usd:
                    raise SpendLimitExceeded(
                        f"STOP: stage estimated spend ${stage_cost_usd:.4f} exceeded "
                        f"${spend_limit_usd:.2f} after {len(records)} episodes; "
                        "results.jsonl holds them; no summary/chart written"
                    )
    summary = aggregate(records)
    grid = grid_summary(records)
    write_chart(records, output / "reward_vs_audit.png")
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    (output / "grid_summary.json").write_text(
        json.dumps(grid, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    spend = {
        "episodes": len(records),
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_usd": round(stage_cost_usd, 6),
        "cost_per_episode_usd": (
            round(stage_cost_usd / len(records), 6) if records else None
        ),
        "limit_usd": spend_limit_usd,
        "estimated": any(
            record.get("sampling", {}).get("client") == "dry-run" for record in records
        ),
    }
    (output / "spend.json").write_text(
        json.dumps(spend, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variants", nargs="+", required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--n", type=int, default=1, help="Repeats per variant/model/seed combination")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="mode", action="store_const", const="dry-run")
    mode.add_argument("--live", dest="mode", action="store_const", const="live")
    parser.set_defaults(mode="dry-run")
    parser.add_argument("--scenario", default="a")
    parser.add_argument("--budget", type=int)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--max-spend-usd", type=float, default=20.0)
    parser.add_argument("--usd-per-mtok-in", type=float)
    parser.add_argument("--usd-per-mtok-out", type=float)
    parser.add_argument("--rubric", type=Path)
    parser.add_argument("--truth", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New directory for this batch")
    parser.add_argument("--env-factory", default="runner.factories:make_env")
    parser.add_argument("--agent-factory", default="runner.factories:make_agent")
    parser.add_argument("--audit", default="auditor.audit:audit")
    parser.add_argument("--max-turns", type=int, default=100)
    parser.add_argument("--max-containers", type=int, default=32)
    parser.add_argument("--timeout", type=int, default=900, help="Seconds per remote episode")
    parser.add_argument("--pip-package", action="append", default=[], help="Additional remote dependency")
    parser.add_argument("--secret", action="append", default=[], help="Modal Secret name for model credentials")
    args = parser.parse_args(argv)
    jobs = build_jobs(args.variants, args.models, args.seeds, args.n, scenario=args.scenario)
    if min(args.max_turns, args.max_containers, args.timeout) < 1:
        parser.error("Turn, container and timeout limits must be positive")
    if not 0.0 <= args.temperature <= 1.0:
        parser.error("temperature must be in [0, 1]")
    if args.output.exists():
        parser.error("Output directory already exists; choose a new batch directory")
    from runner.factories import make_env as validate_env, scenario_dir

    try:
        checked_env = validate_env(
            seed=args.seeds[0], scenario=args.scenario, budget=args.budget,
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    budget = checked_env.state.budget_remaining
    if (args.usd_per_mtok_in is None) != (args.usd_per_mtok_out is None):
        parser.error("Both --usd-per-mtok-in and --usd-per-mtok-out must be provided together")
    try:
        for model in args.models:
            price_for(model, args.usd_per_mtok_in, args.usd_per_mtok_out)
    except ValueError as exc:
        parser.error(str(exc))
    for reference in (args.env_factory, args.agent_factory):
        resolve(reference)
    audit_fn = resolve(args.audit)
    bundle = scenario_dir(args.scenario)
    rubric_path = args.rubric or bundle / "auditor" / "rubric.json"
    truth_path = args.truth or bundle / "auditor" / "truth.json"
    # Keep auditor imports local: episode workers do not need auditor code or data.
    from auditor.audit import load_rubric

    rubric = load_rubric(rubric_path)
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    validate_truth(truth)

    importlib.import_module("matplotlib")  # Fail before launching paid work if the chart dependency is missing.

    client_spec = {
        "mode": args.mode,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "usd_per_mtok_in": args.usd_per_mtok_in,
        "usd_per_mtok_out": args.usd_per_mtok_out,
        "spend_limit_usd": args.max_spend_usd,
        "budget": budget,
    }
    try:
        if args.mode == "dry-run":
            print(
                "DRY RUN: stub client, in-process, no network; nothing launched on Modal. "
                "Use --live for real runs."
            )
            results = (
                remote_episode(
                    job, args.env_factory, args.agent_factory, args.max_turns,
                    client_spec=client_spec,
                )
                for job in jobs
            )
            summary = collect_results(
                results, args.output, rubric, truth, audit_fn,
                spend_limit_usd=args.max_spend_usd,
            )
        else:
            secrets = ["falsifylab-keys", *args.secret]
            print(
                f"LIVE PLAN: episodes={len(jobs)} scenario={args.scenario} "
                f"variants={','.join(args.variants)} model={','.join(args.models)} "
                f"temperature={args.temperature} secrets={','.join(secrets)} "
                f"spend_limit=${args.max_spend_usd:.2f}"
            )
            import modal

            requirements = Path(__file__).with_name("requirements.txt").read_text(
                encoding="utf-8",
            )
            packages = [
                line.strip() for line in requirements.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            image = modal.Image.debian_slim(python_version="3.12")
            image = image.pip_install(*packages, *args.pip_package)
            modules = {"contract", "env", "runner", "agents"}
            modules.update(ref.split(":")[0].split(".")[0]
                           for ref in (args.env_factory, args.agent_factory))
            image = image.add_local_python_source(*sorted(modules))
            for local_path, remote_path in worker_bundle_files(args.scenario):
                image = image.add_local_file(local_path, remote_path)
            app = modal.App("falsifylab-modal-batch")
            worker = app.function(
                image=image,
                timeout=args.timeout,
                max_containers=args.max_containers,
                secrets=[modal.Secret.from_name(name) for name in secrets],
            )(remote_episode)
            with modal.enable_output(), app.run():
                results = worker.map(
                    jobs,
                    kwargs={
                        "env_factory": args.env_factory,
                        "agent_factory": args.agent_factory,
                        "max_turns": args.max_turns,
                        "client_spec": client_spec,
                    },
                    order_outputs=False,
                )
                summary = collect_results(
                    results, args.output, rubric, truth, audit_fn,
                    spend_limit_usd=args.max_spend_usd,
                )
    except SpendLimitExceeded as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(summary, indent=2))
    print("== Grid summary ==")
    print((args.output / "grid_summary.json").read_text(encoding="utf-8"), end="")
    print("== Spend ==")
    print((args.output / "spend.json").read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
