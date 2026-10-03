"""FalsifyLab environment — the stateful simulator.

Implements the Env side of CONTRACT.md:
    Env.reset() -> Observation
    Env.step(action: Action) -> Observation
    Env.state -> State        (env-owned; nothing outside Env writes to it)

It replays the blocks in auditor/expected_observations.json and enforces the
purchase rules. It does NOT score and does NOT know the answer: it never loads
auditor/truth.json or auditor/rubric.json. Protocol correctness (PR1-PR4) and
the gold answer belong to the auditor; the environment's only jobs are to charge
the budget, hand back the right observation, and faithfully record what the
agent declared so the auditor can judge it from the trajectory alone.

Refusals (over budget, too few E6 arms, a purchase after the episode ended)
raise EnvRejection with a reason. A refusal is not an Observation — the
experiment did not run and nothing was charged.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Optional, Union

from contract import Action, Observation, Result, State

BRIEFING_EXPERIMENT_ID = "__briefing__"

# EC1 / experiments.json: E6's arms run together; all three, never fewer.
_E6_ARMS = ("parent_diacid", "diethyl_ester", "monoacid")
_E6_MIN_ARMS = 3


class EnvRejection(Exception):
    """A purchase the environment refuses. `reason` is human-readable. The
    experiment did not run, nothing was charged, and State is unchanged."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class Env:
    """One episode of one scenario. Construct, then reset() to (re)start."""

    def __init__(self, base_dir: Optional[Union[str, Path]] = None) -> None:
        base = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent
        briefing = _load_json(base / "agent" / "briefing.json")
        experiments = _load_json(base / "agent" / "experiments.json")["experiments"]
        observations = _load_json(base / "auditor" / "expected_observations.json")["observations"]

        self._scenario_id: str = briefing["scenario_id"]
        self._starting_facts: list[str] = list(briefing.get("starting_facts", []))
        self._budget_units: int = int(briefing["budget"]["units"])
        self._costs: dict[str, int] = {e["id"]: int(e["cost"]) for e in experiments}
        self._observations: dict[str, dict] = observations

        self._state: State = self._fresh_state()

    # --- state (env-owned) ----------------------------------------------------
    def _fresh_state(self) -> State:
        return State(
            scenario_id=self._scenario_id,
            budget_remaining=self._budget_units,
            total_cost=0,
            experiments_run=[],
            concluded=False,
        )

    @property
    def state(self) -> State:
        """A defensive copy. Env is the sole writer of its state; a caller that
        mutates what it gets back changes nothing inside Env."""
        s = self._state
        return replace(s, experiments_run=list(s.experiments_run))

    # --- episode lifecycle ----------------------------------------------------
    def reset(self) -> Observation:
        self._state = self._fresh_state()
        return self._briefing_observation()

    def step(self, action: Action) -> Observation:
        if action.kind == "conclude":
            self._state.concluded = True              # cost 0; episode ends
            return self._briefing_observation()
        if action.kind != "run_experiment":
            raise EnvRejection(f"unknown action kind: {action.kind!r}")
        if self._state.concluded:
            raise EnvRejection("episode already concluded; no further purchases")

        eid = action.experiment_id
        if eid not in self._observations:
            raise EnvRejection(f"unknown experiment: {eid!r}")
        params = action.parameters or {}

        # EC1: E6 runs all three arms together; fewer is refused, not truncated.
        if eid == "E6":
            arms = params.get("arms") or []
            if isinstance(arms, str):
                arms = [arms]
            distinct_valid = {a for a in arms if a in _E6_ARMS}
            if len(distinct_valid) < _E6_MIN_ARMS:
                raise EnvRejection(
                    f"E6 runs all {_E6_MIN_ARMS} arms together "
                    f"({', '.join(_E6_ARMS)}); got arms={arms!r}. Refused, not truncated."
                )

        # Budget: reject a purchase that would exceed it; do not charge.
        cost = self._costs[eid]
        if cost > self._state.budget_remaining:
            raise EnvRejection(
                f"insufficient budget for {eid}: it costs {cost} unit(s) but "
                f"{self._state.budget_remaining} of {self._budget_units} remain"
            )

        # Charge and record. The same experiment bought twice is charged twice
        # and returns the same block — a legitimate waste, not an error.
        self._state.budget_remaining -= cost
        self._state.total_cost += cost
        self._state.experiments_run.append(eid)

        return self._build_observation(eid, params)

    # --- observation assembly -------------------------------------------------
    def _briefing_observation(self) -> Observation:
        return Observation(
            experiment_id=BRIEFING_EXPERIMENT_ID,
            results=[Result(value=f, source="agent/briefing.json") for f in self._starting_facts],
            informativeness="NONE",
            cost=0,
            structured={},
        )

    def _build_observation(self, eid: str, params: dict) -> Observation:
        block = self._observations[eid]
        results = [Result(value=r["value"], source=r["source"]) for r in block["results"]]
        structured = deepcopy(block.get("structured", {}))   # verbatim copy

        if eid == "E6":
            declared = self._bacteria_free_declared(params.get("controls"))
            if not declared:
                # Withhold the control line entirely — absent, not flagged.
                results = [r for r in results if not r.value.startswith("CONTROL")]
            if "bacteria_free_control_returned" in structured:
                structured["bacteria_free_control_returned"] = declared

        return Observation(
            experiment_id=eid,
            results=results,
            informativeness=block["informativeness"],
            cost=self._costs[eid],
            structured=structured,
        )

    @staticmethod
    def _bacteria_free_declared(controls) -> bool:
        """True iff the agent named a bacteria-free (cell-free) control in the
        E6 controls free-list. The agent must name it itself — this is PR4's
        real test, not a checkbox."""
        if not controls:
            return False
        if isinstance(controls, str):
            controls = [controls]
        for c in controls:
            t = str(c).lower()
            if "cell-free" in t or "cell free" in t:
                return True
            if "bacteria" in t and any(
                k in t for k in ("-free", " free", "without", "no bacteria", "lacking", "absent", "sans")
            ):
                return True
        return False
