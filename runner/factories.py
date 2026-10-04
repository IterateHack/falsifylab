"""Real Env/Agent factories for the runners (local and Modal).

``make_env(seed=...)`` and ``make_agent(variant=..., model=..., seed=...)``
follow the hook signatures ``runner.modal_batch`` expects. A variant is a
system prompt in ``agents/prompts/<variant>.md`` run through the shared
``agents.llm_agent.LLMAgent`` harness; the model client is supplied by the
caller (``client``), with per-episode usage collected by the batch runner.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from agents.llm_agent import LLMAgent
from env import Env
from runner.model_clients import (
    AnthropicClient,
    DEFAULT_PROVIDER_RETRIES,
    DryRunClient,
    TokenLedger,
    price_for,
)
from runner.agents.random_agent import RandomAgent
from runner.agents.ucb import UCBAgent

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "agents" / "prompts"
SCENARIOS: dict[str, Path] = {
    "a": REPO_ROOT,                                   # the root bundle (agent/ + auditor/)
    "b": REPO_ROOT / "scenarios" / "b_cd5_affinity",  # lands with feat/scenario-b
}
SCRIPTED_AGENTS = {"random": RandomAgent, "ucb": UCBAgent}


def scenario_dir(scenario: str) -> Path:
    """A scenario key (``a``, ``b``) or an explicit bundle directory."""
    base = SCENARIOS.get(scenario.lower(), Path(scenario))
    if not (base / "agent" / "briefing.json").exists():
        raise FileNotFoundError(
            f"scenario {scenario!r}: no bundle at {base} (expected agent/briefing.json); "
            f"known keys: {', '.join(sorted(SCENARIOS))}"
        )
    return base


def available_variants() -> list[str]:
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.md"))


def load_prompt(variant: str) -> str:
    path = PROMPTS_DIR / f"{variant}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"unknown variant {variant!r}; prompts available: {', '.join(available_variants())}"
        )
    return path.read_text(encoding="utf-8")


def make_env(*, seed: int, scenario: str = "a", budget: Optional[int] = None) -> Env:
    """The bundle's Env. The simulator is deterministic, so ``seed`` only labels
    the repeat. ``budget`` must match the bundle: both Env and LLMAgent read
    ``briefing.budget.units``, and an override is not wired yet."""
    env = Env(base_dir=scenario_dir(scenario))
    bundle_budget = env.state.budget_remaining
    if budget is not None and budget != bundle_budget:
        raise ValueError(
            f"--budget {budget} differs from the bundle budget of {bundle_budget} units "
            f"(agent/briefing.json). A budget override is not wired yet: Env and LLMAgent "
            f"both read briefing.budget.units, so the budget sweep needs that change first."
        )
    return env


def make_agent(*, variant: str, model: str, seed: int, client, scenario: str = "a") -> LLMAgent:
    """``LLMAgent`` for ``variant`` talking to ``client``. The Anthropic API has
    no sampling seed; ``seed`` labels the repeat and is recorded, not applied."""
    return LLMAgent(
        system_prompt=load_prompt(variant),
        model_client=client,
        base_dir=scenario_dir(scenario) / "agent",
        model_name=model,
    )


def make_client(
    *,
    mode: str,
    model: str,
    scenario: str,
    temperature: float,
    max_tokens: int,
    usd_per_mtok_in: Optional[float],
    usd_per_mtok_out: Optional[float],
    spend_limit_usd: float,
    provider_retries: int = DEFAULT_PROVIDER_RETRIES,
    stage_ledger: Optional[TokenLedger] = None,
):
    if mode not in ("live", "dry-run"):
        raise ValueError(f"unknown client mode {mode!r}")
    usd_in, usd_out = price_for(model, usd_per_mtok_in, usd_per_mtok_out)
    ledger = TokenLedger(usd_in, usd_out, limit_usd=spend_limit_usd)
    if mode == "live":
        return AnthropicClient(
            model,
            ledger,
            temperature=temperature,
            max_tokens=max_tokens,
            provider_retries=provider_retries,
            stage_ledger=stage_ledger,
        )

    hypotheses_path = scenario_dir(scenario) / "agent" / "hypotheses.json"
    with hypotheses_path.open(encoding="utf-8") as stream:
        hypotheses = json.load(stream)["hypotheses"]
    return DryRunClient(
        model,
        ledger,
        hypothesis_ids=[hypothesis["id"] for hypothesis in hypotheses],
        temperature=temperature,
        max_tokens=max_tokens,
    )


def make_scripted_agent(
    *,
    kind: str,
    seed: int,
    scenario: str = "a",
    c: float = 2.0,
):
    """Construct a scripted baseline for a scenario bundle."""
    if kind not in SCRIPTED_AGENTS:
        raise ValueError(f"unknown scripted agent {kind!r}; choose from {', '.join(sorted(SCRIPTED_AGENTS))}")
    agent_type = SCRIPTED_AGENTS[kind]
    kwargs = {
        "base_dir": scenario_dir(scenario) / "agent",
        "seed": seed,
    }
    if kind == "ucb":
        kwargs["c"] = c
    return agent_type(**kwargs)
