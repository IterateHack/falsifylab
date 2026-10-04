"""FalsifyLab environment — the stateful simulator.

Implements the Env side of CONTRACT.md:
    Env.reset() -> Observation
    Env.step(action: Action) -> Observation
    Env.state -> State              (env-owned; nothing outside Env writes to it)
    Env.trajectory -> Trajectory    (the accepted turns so far, for the auditor)

It replays the blocks in auditor/expected_observations.json and enforces the
purchase rules. It does NOT score and does NOT know the answer: it never loads
auditor/truth.json or auditor/rubric.json. Protocol correctness (PR1-PR4) and
the gold answer belong to the auditor; the environment's only jobs are to charge
the budget, hand back the right observation, and faithfully record what the
agent declared so the auditor can judge it from the trajectory alone.

Scenario specifics live entirely in the JSON bundle this Env is pointed at
(agent/briefing.json, agent/experiments.json, auditor/expected_observations.json).
No experiment id, hypothesis id or scientific value is hardcoded here.

Refusals raise EnvRejection with a reason: over budget, too few E6 arms, a
purchase after the episode ended, an unknown experiment, or a conclude whose
evidence_cited is not structured. A refusal is not an Observation and is not a
Turn — the experiment did not run, nothing was charged, and State is unchanged.
Rejection codes are overspend, malformed_conclude, unknown_experiment, and other.
A conclude's citations must be {experiment, supports?} objects so the auditor
judges them structurally and never text-matches (a prose citation is an
auditor-invisible reward-hack loophole, per the ENV WORKSTREAM note in
CONTRACT.md).
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Optional, Union

from contract import Action, Observation, Result, State, Trajectory, Turn
from control_matching import matches_control_aliases

REJECTION_CODES = ("overspend", "malformed_conclude", "unknown_experiment", "other")
BRIEFING_EXPERIMENT_ID = "__briefing__"

# EC1 / experiments.json: E6's arms run together; all three, never fewer.
_E6_ARMS = ("parent_diacid", "diethyl_ester", "monoacid")
_E6_MIN_ARMS = 3

# CONTRACT.md: the closed set a citation's optional `supports` may take. Defined
# here, not imported, because main's contract.py models a citation as a plain
# dict (no EvidenceCitation dataclass) — the environment validates that shape.
_SUPPORTS = ("mechanism", "durability", "target_claim", "potency", "target_engagement")


class EnvRejection(Exception):
    """A purchase or conclusion the environment refuses. `reason` is
    human-readable. Nothing ran, nothing was charged, State is unchanged, and no
    Turn was recorded."""

    def __init__(self, reason: str, code: str = "other") -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


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
        self._turns: list[Turn] = []

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

    @property
    def trajectory(self) -> Trajectory:
        """A defensive deep copy of the episode so far, one Turn per accepted
        step (a refused purchase is not a turn — nothing ran). Each Turn carries
        the agent's action verbatim, including every declared parameter (buffer,
        atc_free_days, read_day, normalisation_control, arms, controls, ...), so
        the auditor can check PR1-PR4 from the trajectory alone. The conclude
        turn's observation is None, per CONTRACT.md."""
        return Trajectory(scenario_id=self._scenario_id, turns=deepcopy(self._turns))

    # --- episode lifecycle ----------------------------------------------------
    def reset(self) -> Observation:
        self._state = self._fresh_state()
        self._turns = []
        return self._briefing_observation()

    def step(self, action: Action) -> Observation:
        if action.kind == "conclude":
            self._check_citations(action.evidence_cited)  # malformed -> refuse; episode not ended
            self._state.concluded = True                  # cost 0; episode ends
            self._record(action, None)                     # conclude turn: observation is None
            return self._briefing_observation()
        if action.kind != "run_experiment":
            raise EnvRejection(f"unknown action kind: {action.kind!r}", code="other")
        if self._state.concluded:
            raise EnvRejection("episode already concluded; no further purchases", code="other")

        eid = action.experiment_id
        if eid not in self._observations:
            raise EnvRejection(f"unknown experiment: {eid!r}", code="unknown_experiment")
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
                    f"({', '.join(_E6_ARMS)}); got arms={arms!r}. Refused, not truncated.",
                    code="other",
                )

        # Budget: reject a purchase that would exceed it; do not charge.
        cost = self._costs[eid]
        if cost > self._state.budget_remaining:
            raise EnvRejection(
                f"insufficient budget for {eid}: it costs {cost} unit(s) but "
                f"{self._state.budget_remaining} of {self._budget_units} remain",
                code="overspend",
            )

        # Charge and record. The same experiment bought twice is charged twice
        # and returns the same block — a legitimate waste, not an error.
        self._state.budget_remaining -= cost
        self._state.total_cost += cost
        self._state.experiments_run.append(eid)

        observation = self._build_observation(eid, params)
        self._record(action, observation)
        return observation

    # --- conclude validation --------------------------------------------------
    def _check_citations(self, evidence_cited) -> None:
        """conclude.evidence_cited, when present, must be structured citations:
        each entry a dict {"experiment": <known id>, "supports"?: <_SUPPORTS>}.
        `experiment` is required and must be a known experiment id; `supports`
        may be omitted but, if given, must be one of _SUPPORTS.

        A bare string — a prose citation — is refused: the auditor scores
        citations structurally and never text-matches, so an unstructured
        citation would be an auditor-invisible reward-hack loophole. None is
        allowed: citing nothing is a sufficiency question the auditor owns, not
        a shape error the environment owns."""
        if evidence_cited is None:
            return
        if not isinstance(evidence_cited, (list, tuple)):
            raise EnvRejection(
                "malformed conclude: evidence_cited must be a list of "
                "{experiment, supports?} citation objects, got "
                f"{type(evidence_cited).__name__}",
                code="malformed_conclude",
            )
        for i, c in enumerate(evidence_cited):
            if not isinstance(c, dict):
                raise EnvRejection(
                    f"malformed conclude: evidence_cited[{i}] is a bare "
                    f"{type(c).__name__} ({c!r}); a citation must be an object "
                    "{experiment, supports?}. Bare strings are rejected — a prose "
                    "citation is an auditor-invisible reward-hack loophole.",
                    code="malformed_conclude",
                )
            if not c.get("experiment"):
                raise EnvRejection(
                    f"malformed conclude: evidence_cited[{i}] is missing the required "
                    f"'experiment' field: {c!r}",
                    code="malformed_conclude",
                )
            experiment = c["experiment"]
            if experiment not in self._costs:
                raise EnvRejection(
                    f"malformed conclude: evidence_cited[{i}] cites unknown experiment "
                    f"{experiment!r}; valid ids are {sorted(self._costs)}",
                    code="malformed_conclude",
                )
            supports = c.get("supports")
            if supports is not None and supports not in _SUPPORTS:
                raise EnvRejection(
                    f"malformed conclude: evidence_cited[{i}] has invalid supports "
                    f"{supports!r}; must be one of {', '.join(_SUPPORTS)} or omitted",
                    code="malformed_conclude",
                )

    # --- trajectory capture ---------------------------------------------------
    def _record(self, action: Action, observation: Optional[Observation]) -> None:
        """Append one accepted turn. The action is deep-copied so a later caller
        mutation cannot rewrite what was declared at this turn."""
        self._turns.append(
            Turn(
                index=len(self._turns),
                action=deepcopy(action),
                observation=deepcopy(observation),
            )
        )

    # --- observation assembly -------------------------------------------------
    def _briefing_observation(self) -> Observation:
        return Observation(
            experiment_id=BRIEFING_EXPERIMENT_ID,
            results=[Result(value=f, source="agent/briefing.json") for f in self._starting_facts],
            informativeness="UNRATED",
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
            # "UNRATED", not block["informativeness"]: the rating is auditor-view
            # metadata in expected_observations.json and must never reach the
            # agent — it names which experiments matter. It is also withheld
            # from the recorded trajectory, which must reflect what the agent
            # actually saw. The auditor scores on `structured`, never this field.
            informativeness="UNRATED",
            cost=self._costs[eid],
            structured=structured,
        )

    @staticmethod
    def _bacteria_free_declared(controls) -> bool:
        """True iff the agent named a bacteria-free (cell-free) control in the
        E6 controls free-list. The agent must name it itself — this is PR4's
        real test, not a checkbox."""
        return matches_control_aliases(controls, "bacteria_free_control")
