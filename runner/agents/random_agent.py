"""Uniformly select affordable experiments."""
from __future__ import annotations

from pathlib import Path

from contract import Action, Observation, State
from runner.agents._common import ScriptedAgent


class RandomAgent(ScriptedAgent):
    """Uniformly sample affordable experiments with a seeded RNG."""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        seed: int = 0,
        model_name: str = "random",
    ) -> None:
        super().__init__(base_dir=base_dir, seed=seed, model_name=model_name)

    def act(self, observation: Observation, state: State) -> Action:
        self._process_observation(observation)

        affordable = self.affordable(state)
        available = self.available(state)
        if affordable:
            experiment_id = self.rng.choice(affordable)
            action = self._run_action(experiment_id)
            entry = {
                "turn": self.turn,
                "action": "run_experiment",
                "experiment_id": experiment_id,
                "available": available,
                "refused": sorted(self.refused),
            }
        else:
            action = self._conclude_action(state)
            entry = {
                "turn": self.turn,
                "action": "conclude",
                "available": available,
                "refused": sorted(self.refused),
            }
        self._record(entry)
        return action
