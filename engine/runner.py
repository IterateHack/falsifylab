"""Run a whole curriculum, carrying lessons forward as they are earned."""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .events import EventLog
from .notebook import Notebook, NotebookEntry
from .provider import AnthropicProvider, ModelConfig, Provider
from .specs import load_curriculum
from .agent import run_experiment


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    notebook: Notebook
    log: EventLog

    def summary(self) -> dict[str, Any]:
        cal = self.notebook.calibration_summary()
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "n_experiments": len(self.notebook.entries),
            "calibration": cal,
        }


def run_curriculum(
    curriculum_root: str | Path = "curricula/glp1r",
    run_id: str = "run_001",
    runs_dir: str | Path = "runs",
    backend: str = "local",
    provider: Provider | None = None,
    model_config: ModelConfig | None = None,
    use_lessons: bool = True,
    only: list[str] | None = None,
    existing_log: EventLog | None = None,
) -> RunResult:
    curriculum = load_curriculum(curriculum_root)
    model_config = model_config or ModelConfig()
    provider = provider or AnthropicProvider()

    run_dir = Path(runs_dir) / run_id
    # The API creates the log up front so an SSE client can subscribe before the
    # first event is appended; the CLI lets us make it here. Only close what we
    # opened - the API keeps its log alive to serve the stream.
    owns_log = existing_log is None
    log = existing_log or EventLog(run_dir, run_id)
    notebook = Notebook(run_id=run_id, hypothesis=curriculum.hypothesis)

    experiments = curriculum.experiments
    if only:
        wanted = set(only)
        experiments = [e for e in experiments
                       if e.id in wanted or str(e.order) in wanted]
        if not experiments:
            raise SystemExit(f"no experiments matched {only!r}")

    # Entries exist up front so the UI can draw six locked stations immediately.
    for spec in curriculum.experiments:
        notebook.entries.append(NotebookEntry(
            experiment_id=spec.id, title=spec.title, order=spec.order,
            papers=list(spec.teaching.papers),
        ))

    log.append("run_started", {
        "curriculum": curriculum.id,
        "title": curriculum.title,
        "hypothesis": curriculum.hypothesis,
        "hypothesis_id": curriculum.hypothesis_id,
        "backend": backend,
        "use_lessons": use_lessons,
        "loop_model": model_config.loop_model,
        "capstone_model": model_config.capstone_model,
        "experiments": [
            {"id": e.id, "order": e.order, "title": e.title, "type": e.type,
             "requires_lessons": e.requires_lessons}
            for e in curriculum.experiments
        ],
    })

    earned: list[tuple[str, str, str]] = []
    try:
        for spec in experiments:
            entry = notebook.get(spec.id)
            try:
                run_experiment(
                    spec=spec, curriculum=curriculum, log=log, provider=provider,
                    model_config=model_config, earned_lessons=list(earned),
                    notebook_entry=entry, backend=backend, use_lessons=use_lessons,
                )
            except Exception as exc:
                log.append("error", {
                    "fatal": False, "experiment": spec.id,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc()[-3000:],
                }, experiment_id=spec.id)
                entry.status = "done"
                if entry.score is None:
                    entry.record_score({"score": 0.0, "max": 1.0, "details": {
                        "error": f"experiment crashed: {type(exc).__name__}: {exc}"}})
            finally:
                _persist(run_dir, notebook)

            # Lessons are earned by attempting, not by succeeding: the point is
            # that the teaching happened, whatever the score was.
            if spec.lesson_card_path.exists():
                earned.append((spec.id, spec.title,
                               spec.lesson_card_path.read_text(encoding="utf-8")))
    finally:
        cal = notebook.calibration_summary()
        log.append("run_finished", {"calibration": cal})
        _persist(run_dir, notebook)
        if owns_log:
            log.close()          # releases the run-directory lock

    return RunResult(run_id=run_id, run_dir=run_dir, notebook=notebook, log=log)


def _persist(run_dir: Path, notebook: Notebook) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "notebook.md").write_text(notebook.to_markdown(), encoding="utf-8")
    (run_dir / "notebook.json").write_text(
        json.dumps(notebook.to_dict(), indent=2, default=str), encoding="utf-8")
