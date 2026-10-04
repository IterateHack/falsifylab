"""Run ONE episode locally against the real Env, the real auditor and a real model.

    python -m runner.run_one --scenario a --variant baseline --budget 8 \\
        --model claude-sonnet-4-5 --seed 0

    --agent random|ucb runs a zero-model-call scripted baseline (no API key needed).

Reads ANTHROPIC_API_KEY from the environment. Prints the full trajectory, the
model transcript or decision log, the audit (four dimension scores,
applicable_max_evidence, R_visible, final_score, verdict, flags,
epistemic_flags, reward hacks) and the episode's token usage with its estimated
cost. Every model call is logged to stderr with the cumulative spend; the run
stops with a clear message if the estimate passes --max-spend-usd (default $20).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Callable, Optional

from contract import Trajectory, Verdict
from runner.factories import make_agent, make_env, make_scripted_agent, scenario_dir
from runner.modal_batch import EpisodeJob, run_episode
from runner.model_clients import (
    API_KEY_ENV, DEFAULT_SPEND_LIMIT_USD, DEFAULT_TEMPERATURE, AnthropicClient, SpendLimitExceeded,
    TokenLedger, price_for,
)

DIMENSIONS = ("scientific_correctness", "evidence_sufficiency", "protocol_validity", "safety")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", choices=("llm", "ucb", "random"), default="llm")
    parser.add_argument("--scenario", default="a", help="scenario key (a, b) or bundle directory")
    parser.add_argument("--variant", help="system prompt in agents/prompts/<variant>.md")
    parser.add_argument("--budget", type=int, default=None, help="must equal the bundle budget (8 for scenario a)")
    parser.add_argument("--model", help="Anthropic model id, e.g. claude-sonnet-4-5")
    parser.add_argument("--ucb-c", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-turns", type=int, default=100)
    parser.add_argument("--max-refusals", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=2048, help="max output tokens per model call")
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-spend-usd", type=float, default=DEFAULT_SPEND_LIMIT_USD)
    parser.add_argument("--usd-per-mtok-in", type=float, default=None)
    parser.add_argument("--usd-per-mtok-out", type=float, default=None)
    parser.add_argument("--out", type=Path, default=None, help="write the episode record (JSON) here")
    parser.add_argument("--no-transcript", action="store_true", help="do not print the raw model replies")
    return parser


def main(argv: Optional[list[str]] = None, client_factory: Optional[Callable] = None,
         out=sys.stdout) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        bundle_env = make_env(seed=args.seed, scenario=args.scenario, budget=args.budget)
    except ValueError as exc:
        parser.error(str(exc))
    bundle_budget = bundle_env.state.budget_remaining
    if not 0.0 <= args.temperature <= 1.0:
        parser.error("--temperature must be in [0, 1]")
    if args.agent == "llm":
        missing = [
            option
            for option, value in (("--variant", args.variant), ("--model", args.model))
            if not value
        ]
        if missing:
            parser.error(f"the following arguments are required: {', '.join(missing)}")
    elif args.variant is not None or args.model is not None:
        parser.error("--variant and --model are only valid when --agent=llm")
    say = partial(print, file=out, flush=True)
    bundle = scenario_dir(args.scenario)
    if args.agent == "llm":
        if client_factory is None:
            if not os.environ.get(API_KEY_ENV):
                print(f"{API_KEY_ENV} is not set; export it before running.", file=sys.stderr)
                return 1
            client_factory = partial(AnthropicClient, max_tokens=args.max_tokens, temperature=args.temperature)
        usd_in, usd_out = price_for(args.model, args.usd_per_mtok_in, args.usd_per_mtok_out)
        ledger = TokenLedger(usd_in, usd_out, limit_usd=args.max_spend_usd)
        client = client_factory(args.model, ledger)
    else:
        ledger = TokenLedger(0.0, 0.0, limit_usd=args.max_spend_usd, log=None)
        client = None

    agents = []

    def agent_factory(*, variant, model, seed):
        if args.agent == "llm":
            agent = make_agent(
                variant=variant, model=model, seed=seed, client=client, scenario=args.scenario
            )
        else:
            agent = make_scripted_agent(
                kind=args.agent, seed=seed, scenario=args.scenario, c=args.ucb_c
            )
        agents.append(agent)
        return agent

    if args.agent == "llm":
        job = EpisodeJob(f"{args.seed:08d}", args.variant, args.model, args.seed, 0, args.seed)
    else:
        job = EpisodeJob(f"{args.seed:08d}", args.agent, "none", args.seed, 0, args.seed)
    say(f"# run_one: agent={args.agent} scenario={args.scenario} ({bundle}) "
        f"variant={args.variant} model={args.model} "
        f"seed={args.seed} budget={args.budget if args.budget is not None else 'bundle default'} "
        f"temperature={args.temperature} max_tokens={args.max_tokens}")
    try:
        episode_run = run_episode(
            job, partial(make_env, scenario=args.scenario, budget=args.budget), agent_factory,
            max_turns=args.max_turns, max_refusals=args.max_refusals,
            log=partial(print, file=sys.stderr, flush=True),
        )
    except SpendLimitExceeded as exc:
        say(str(exc))
        return 2
    trajectory = episode_run.trajectory

    from auditor.audit import audit, load_rubric  # auditor stays out of the agent process until here

    rubric = load_rubric(bundle / "auditor" / "rubric.json")
    truth = json.loads((bundle / "auditor" / "truth.json").read_text(encoding="utf-8"))
    verdict = audit(trajectory, rubric, truth)
    agent = agents[0] if agents else None

    say(format_trajectory(trajectory))
    if agent is not None and args.agent != "llm":
        say(format_decision_log(agent.transcript))
    elif agent is not None and not args.no_transcript:
        say(format_transcript(agent.transcript))
    say(format_refusals(episode_run.refusals, episode_run.aborted_on_refusals))
    say(format_verdict(verdict, aborted_on_refusals=episode_run.aborted_on_refusals))
    if args.agent != "llm":
        say("  NOTE: scripted baseline — beliefs, dominant cause and confidence are random; "
            "conclusion metrics above are not meaningful. Compare experiment selection only.")
    say(format_tokens(ledger, agent))

    if args.out is not None:
        record = {
            "job": asdict(job),
            "scenario_dir": str(bundle),
            "trajectory": asdict(trajectory),
            "verdict": asdict(verdict),
            "sampling": None if args.agent != "llm" else {
                "model": args.model,
                "temperature": args.temperature,
                "max_tokens": args.max_tokens,
                "seed_applied_to_model": False,
            },
            "budget": {"requested": args.budget, "bundle": bundle_budget},
            "refusals": [asdict(refusal) for refusal in episode_run.refusals],
            "refusal_count": episode_run.refusal_count,
            "aborted_on_refusals": episode_run.aborted_on_refusals,
            "model_call_log": getattr(client, "call_log", None),
            "tokens": ledger.snapshot(),
            "agent_stats": agent.stats() if agent is not None else None,
            "transcript": agent.transcript if agent is not None else None,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        say(f"\nwrote {args.out}")
    return 3 if episode_run.aborted_on_refusals else 0


def format_trajectory(trajectory: Trajectory) -> str:
    lines = [f"\n== Trajectory ({trajectory.scenario_id}; {len(trajectory.turns)} turns) =="]
    for turn in trajectory.turns:
        a = turn.action
        lines.append(f"\n-- turn {turn.index}: {a.kind}" + (f" {a.experiment_id}" if a.experiment_id else ""))
        if a.parameters:
            lines.append(f"   parameters: {json.dumps(a.parameters)}")
        lines.append(f"   beliefs: {json.dumps(a.beliefs)}  dominant_cause: {a.dominant_cause}")
        if a.kind == "conclude":
            lines.append(f"   contributing_hypotheses: {a.contributing_hypotheses}  confidence: {a.confidence}  "
                         f"makes_target_claim: {a.makes_target_claim}  abstain_reason: {a.abstain_reason}")
            lines.append(f"   evidence_cited: {json.dumps(a.evidence_cited)}")
        o = turn.observation
        if o is not None:
            lines.append(f"   observation {o.experiment_id} (cost {o.cost}):")
            lines += [f"     - {r.value}  [{r.source}]" for r in o.results]
            if o.structured:
                lines.append(f"     structured: {json.dumps(o.structured)}")
    return "\n".join(lines)


def format_transcript(transcript: list[dict]) -> str:
    lines = [f"\n== Model transcript ({len(transcript)} replies) =="]
    for i, entry in enumerate(transcript):
        if entry.get("abstained"):
            lines.append(f"\n-- harness abstained ({entry.get('kind')}): {entry.get('reason')}")
            continue
        status = "ok" if entry.get("error") is None else f"PARSE FAILURE: {entry['error']}"
        lines.append(f"\n-- reply {i} (attempt {entry.get('attempt')}): {status}")
        lines.append(str(entry.get("reply", "")).rstrip())
    return "\n".join(lines)


def format_decision_log(transcript: list[dict]) -> str:
    lines = [f"\n== Decision log ({len(transcript)} decisions) =="]
    lines.extend(json.dumps(entry, allow_nan=False) for entry in transcript)
    return "\n".join(lines)


def format_refusals(refusals: list, aborted_on_refusals: bool) -> str:
    lines = ["\n== Refusals ==",
             f"  refusal_count {len(refusals)}  aborted_on_refusals {aborted_on_refusals}"]
    for refusal in refusals:
        action = refusal.action
        lines.append(
            f"  agent call {refusal.agent_call}, before turn {refusal.turn_index}: "
            f"{refusal.rejection_type} on {action.get('kind')} "
            f"{action.get('experiment_id') or ''}: {refusal.reason}"
        )
    return "\n".join(lines)


def format_verdict(verdict: Verdict, *, aborted_on_refusals: bool = False) -> str:
    scores = verdict.scores
    lines = ["\n== Audit =="]
    for key in DIMENSIONS:
        lines.append(f"  {key:<24} {scores.get(key)}")
    lines.append(f"  {'applicable_max_evidence':<24} {scores.get('applicable_max_evidence')}")
    lines.append(f"  {'brier':<24} {scores.get('brier')}")
    lines.append(f"  {'raw_total':<24} {verdict.raw_total}")
    lines.append(f"  {'R_visible':<24} {verdict.R_visible}")
    lines.append(f"  {'final_score':<24} {verdict.final_score}")
    lines.append(f"  {'verdict':<24} {verdict.verdict}")
    lines.append(f"  {'flags':<24} {verdict.flags}")
    lines.append(f"  {'epistemic_flags':<24} {scores.get('epistemic_flags', [])}")
    lines.append(f"  {'reward_hacks':<24} {verdict.reward_hacks}")
    if aborted_on_refusals:
        lines.append("  NOTE: aborted_on_refusals — no conclude; this verdict scores a partial trajectory")
    return "\n".join(lines)


def format_tokens(ledger: TokenLedger, agent) -> str:
    lines = ["\n== Tokens =="]
    lines.append(f"  model_calls      {ledger.calls}")
    lines.append(f"  input_tokens     {ledger.input_tokens}")
    lines.append(f"  output_tokens    {ledger.output_tokens}")
    lines.append(f"  est_cost_usd     {ledger.cost_usd:.4f}  (${ledger.usd_per_mtok_in}/M in, "
                 f"${ledger.usd_per_mtok_out}/M out; limit ${ledger.limit_usd:.2f})")
    if agent is not None:
        st = agent.stats()
        lines.append(f"  parse_failures   {st['parse_failures']} of {st['model_calls']} replies"
                     f"{'; harness abstained (PARSE_FAILURE)' if st['parse_failure_abstention'] else ''}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
