"""Shared utilities for scripted agents."""
from __future__ import annotations

import json
from pathlib import Path
import random

from contract import Action, Observation, State
from runner.modal_batch import REFUSAL_EXPERIMENT_ID

AGENT_DIR = Path(__file__).resolve().parents[2] / "agent"


def _without_private_keys(value):
    if isinstance(value, dict):
        return {
            key: _without_private_keys(item)
            for key, item in value.items()
            if not key.startswith("_")
        }
    if isinstance(value, list):
        return [_without_private_keys(item) for item in value]
    return value


def _load(path: Path) -> dict:
    return _without_private_keys(json.loads(path.read_text(encoding="utf-8")))


class ScriptedAgent:
    """Common bundle, budget, action, and decision-log behavior."""

    def __init__(
        self,
        *,
        base_dir: Path | None,
        seed: int,
        model_name: str,
    ) -> None:
        base = Path(base_dir) if base_dir is not None else AGENT_DIR
        briefing = _load(base / "briefing.json")
        self.budget_units = briefing["budget"]["units"]
        self.briefing = {"scenario_id": briefing["scenario_id"]}
        hypotheses = _load(base / "hypotheses.json")["hypotheses"]
        self.hypotheses = [{"id": hypothesis["id"]} for hypothesis in hypotheses]
        experiments = _load(base / "experiments.json")["experiments"]
        self.experiments = [
            {
                "id": experiment["id"],
                "cost": experiment["cost"],
                "parameters": {
                    name: {
                        key: value
                        for key, value in schema.items()
                        if key in {"type", "values", "range", "required", "min_selected"}
                    }
                    for name, schema in (experiment.get("parameters") or {}).items()
                },
            }
            for experiment in experiments
        ]
        self.hypothesis_ids = [hypothesis["id"] for hypothesis in self.hypotheses]
        self.experiment_ids = [experiment["id"] for experiment in self.experiments]
        self.costs = {experiment["id"]: experiment["cost"] for experiment in self.experiments}
        self.parameters = {
            experiment["id"]: experiment.get("parameters") or {}
            for experiment in self.experiments
        }
        self.model_name = model_name
        self.model_calls = 0
        self.parse_failures = 0
        self.abstained = False
        self.history: list = []
        self.transcript: list[dict] = []
        self.rng = random.Random(seed)
        self.refused: set[str] = set()
        self.last_chosen: str | None = None
        self.turn = 0

    def stats(self) -> dict:
        return {
            "model": self.model_name,
            "model_calls": self.model_calls,
            "parse_failures": self.parse_failures,
            "parse_failure_rate": 0.0,
            "parse_failure_abstention": False,
        }

    def available(self, state: State) -> int:
        return min(state.budget_remaining, self.budget_units - state.total_cost)

    def affordable(self, state: State) -> list[str]:
        available = self.available(state)
        return [
            experiment_id
            for experiment_id in self.experiment_ids
            if self.costs[experiment_id] <= available and experiment_id not in self.refused
        ]

    def _process_observation(self, observation: Observation) -> float | None:
        if observation.experiment_id == REFUSAL_EXPERIMENT_ID:
            if self.last_chosen is not None:
                self.refused.add(self.last_chosen)
            self.last_chosen = None
            return None
        experiment_id = self.last_chosen
        self.last_chosen = None
        if experiment_id is None:
            return None
        return self._credit_observation(observation, experiment_id)

    def _credit_observation(self, observation: Observation, experiment_id: str) -> float | None:
        return None

    def _parameters_for(self, experiment_id: str) -> dict:
        parameters = {}
        for name, schema in self.parameters[experiment_id].items():
            if not schema.get("required"):
                continue
            kind = schema.get("type")
            if kind == "enum":
                value = self.rng.choice(schema["values"])
            elif kind == "float":
                low, high = schema["range"]
                value = self.rng.uniform(low, high)
            elif kind == "int":
                low, high = schema["range"]
                value = self.rng.randint(low, high)
            elif kind == "multi_enum":
                value = list(schema["values"])
            elif kind == "string":
                value = "unspecified"
            elif kind == "free_list":
                value = ["unspecified"]
            else:
                raise ValueError(f"unknown required parameter type: {kind!r}")
            parameters[name] = value
        return parameters

    def _run_action(self, experiment_id: str) -> Action:
        self.last_chosen = experiment_id
        return Action(
            kind="run_experiment",
            beliefs={hypothesis_id: 0.5 for hypothesis_id in self.hypothesis_ids},
            dominant_cause=None,
            experiment_id=experiment_id,
            parameters=self._parameters_for(experiment_id),
        )

    def _conclude_action(self, state: State) -> Action:
        beliefs = {hypothesis_id: self.rng.random() for hypothesis_id in self.hypothesis_ids}
        dominant_cause = self.rng.choice(self.hypothesis_ids)
        contributing = sorted(
            {hypothesis_id for hypothesis_id, belief in beliefs.items() if belief >= 0.5}
            | {dominant_cause}
        )
        evidence = []
        for experiment_id in state.experiments_run:
            if experiment_id not in {entry["experiment"] for entry in evidence}:
                evidence.append({"experiment": experiment_id})
        self.last_chosen = None
        return Action(
            kind="conclude",
            beliefs=beliefs,
            dominant_cause=dominant_cause,
            contributing_hypotheses=contributing,
            confidence=self.rng.random(),
            evidence_cited=evidence,
            makes_target_claim=self.rng.random() < 0.5,
            abstain_reason=None,
        )

    def _record(self, entry: dict) -> None:
        self.transcript.append(entry)
        self.history.append(dict(entry))
        self.turn += 1
