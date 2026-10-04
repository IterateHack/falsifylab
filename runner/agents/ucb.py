"""Select affordable experiments with UCB1."""
from __future__ import annotations

import math
from pathlib import Path

from contract import Action, Observation, State
from runner.agents._common import ScriptedAgent


class UCBAgent(ScriptedAgent):
    """Select experiments using content-free novelty rewards."""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        seed: int = 0,
        c: float = 2.0,
        budget: int | None = None,
        model_name: str = "ucb",
    ) -> None:
        super().__init__(base_dir=base_dir, seed=seed, budget=budget, model_name=model_name)
        self.c = c
        self.counts = dict.fromkeys(self.experiment_ids, 0)
        self.sums = dict.fromkeys(self.experiment_ids, 0.0)
        self.total_pulls = 0
        self.seen: set[str] = set()

    def reward(self, observation: Observation, cost: int) -> float:
        """Use novelty because Env has no reward signal and auditor evidence scores leak the answer key."""
        entries = {f"r:{result.value}" for result in observation.results}
        entries.update(f"s:{path}={repr(value)}" for path, value in _structured_leaves(observation.structured))
        novelty = len(entries - self.seen) / len(entries) if entries else 0.0
        self.seen.update(entries)
        return novelty * min(self.costs.values()) / cost

    def _credit_observation(self, observation: Observation, experiment_id: str) -> float | None:
        if observation.experiment_id != experiment_id:
            return None
        value = self.reward(observation, self.costs[experiment_id])
        self.counts[experiment_id] += 1
        self.sums[experiment_id] += value
        self.total_pulls += 1
        return value

    def _means(self) -> dict[str, float | None]:
        return {
            experiment_id: (
                self.sums[experiment_id] / self.counts[experiment_id]
                if self.counts[experiment_id]
                else None
            )
            for experiment_id in self.experiment_ids
        }

    def _indices(self) -> dict[str, float | None]:
        means = self._means()
        return {
            experiment_id: (
                means[experiment_id]
                + self.c * math.sqrt(math.log(self.total_pulls) / self.counts[experiment_id])
                if self.counts[experiment_id]
                else None
            )
            for experiment_id in self.experiment_ids
        }

    def act(self, observation: Observation, state: State) -> Action:
        reward = self._process_observation(observation)

        affordable = self.affordable(state)
        available = self.available(state)
        means = self._means()
        indices = self._indices()
        if affordable:
            unpulled = [experiment_id for experiment_id in affordable if not self.counts[experiment_id]]
            if unpulled:
                experiment_id = self.rng.choice(unpulled)
            else:
                best = max(indices[experiment_id] for experiment_id in affordable)
                tied = [experiment_id for experiment_id in affordable if indices[experiment_id] == best]
                experiment_id = self.rng.choice(tied)
            action = self._run_action(experiment_id)
            entry = {
                "turn": self.turn,
                "action": "run_experiment",
                "experiment_id": experiment_id,
                "available": available,
                "refused": sorted(self.refused),
                "counts": dict(self.counts),
                "means": means,
                "index": indices,
                "reward": reward,
            }
        else:
            action = self._conclude_action(state)
            entry = {
                "turn": self.turn,
                "action": "conclude",
                "available": available,
                "refused": sorted(self.refused),
                "counts": dict(self.counts),
                "means": means,
                "index": indices,
                "reward": reward,
            }
        self._record(entry)
        return action


def _structured_leaves(value, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from _structured_leaves(item, child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _structured_leaves(item, f"{path}[{index}]")
    else:
        yield path, value
