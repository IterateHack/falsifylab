"""Experiment and curriculum specs (plan section 8.1).

A curriculum is a config folder, so the engine is hypothesis-agnostic: swapping
`curricula/glp1r` for `curricula/wrn` changes the science, not the code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Limits:
    max_tool_calls: int = 25
    timeout_s: int = 300
    max_python_seconds: int = 60


@dataclass(frozen=True)
class ScorerSpec:
    type: str                    # "deterministic" | "rubric"
    entrypoint: str              # "scorers/exp1.py::score"
    ground_truth: str | None = None

    @property
    def module_path(self) -> str:
        return self.entrypoint.split("::")[0]

    @property
    def function(self) -> str:
        parts = self.entrypoint.split("::")
        return parts[1] if len(parts) > 1 else "score"


@dataclass(frozen=True)
class TeachingSpec:
    papers: list[str] = field(default_factory=list)
    lesson_card: str = ""


@dataclass(frozen=True)
class ExperimentSpec:
    id: str
    hypothesis_id: str
    order: int
    title: str
    type: str                    # "computational" | "reasoning"
    task: str                    # the prompt shown to the agent
    answer_format: str           # what submit_answer must contain
    datasets: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    requires_lessons: list[str] = field(default_factory=list)
    limits: Limits = field(default_factory=Limits)
    scorer: ScorerSpec | None = None
    teaching: TeachingSpec = field(default_factory=TeachingSpec)
    root: Path = field(default=Path("."))

    @property
    def lesson_card_path(self) -> Path:
        return self.root / self.teaching.lesson_card

    @property
    def ground_truth_path(self) -> Path | None:
        if not self.scorer or not self.scorer.ground_truth:
            return None
        return self.root / self.scorer.ground_truth

    @property
    def scorer_path(self) -> Path:
        assert self.scorer is not None
        return self.root / self.scorer.module_path

    def dataset_paths(self) -> list[Path]:
        return [self.root / d for d in self.datasets]


@dataclass(frozen=True)
class Curriculum:
    id: str
    title: str
    hypothesis: str
    hypothesis_id: str
    experiments: list[ExperimentSpec]
    root: Path

    def by_id(self, experiment_id: str) -> ExperimentSpec:
        for e in self.experiments:
            if e.id == experiment_id:
                return e
        raise KeyError(experiment_id)

    def up_to(self, order: int) -> list[ExperimentSpec]:
        return [e for e in self.experiments if e.order <= order]


def _limits(d: dict[str, Any] | None) -> Limits:
    d = d or {}
    return Limits(
        max_tool_calls=int(d.get("max_tool_calls", 25)),
        timeout_s=int(d.get("timeout_s", 300)),
        max_python_seconds=int(d.get("max_python_seconds", 60)),
    )


def load_experiment(path: str | Path, root: Path) -> ExperimentSpec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    inputs = raw.get("inputs") or {}
    sc = raw.get("scorer") or {}
    te = raw.get("teaching") or {}
    spec = ExperimentSpec(
        id=raw["id"],
        hypothesis_id=raw["hypothesis_id"],
        order=int(raw["order"]),
        title=raw["title"],
        type=raw.get("type", "computational"),
        task=raw["task"].strip(),
        answer_format=raw.get("answer_format", "").strip(),
        datasets=list(inputs.get("datasets") or []),
        tools=list(inputs.get("tools") or ["run_python"]),
        requires_lessons=list(raw.get("requires_lessons") or []),
        limits=_limits(raw.get("limits")),
        scorer=ScorerSpec(
            type=sc.get("type", "deterministic"),
            entrypoint=sc["entrypoint"],
            ground_truth=sc.get("ground_truth"),
        ) if sc else None,
        teaching=TeachingSpec(
            papers=list(te.get("papers") or []),
            lesson_card=te.get("lesson_card", ""),
        ),
        root=root,
    )
    _validate(spec)
    return spec


def _validate(spec: ExperimentSpec) -> None:
    if spec.scorer is None:
        raise ValueError(f"{spec.id}: scorer is required")
    if spec.scorer.type not in ("deterministic", "rubric"):
        raise ValueError(f"{spec.id}: scorer.type must be deterministic or rubric")
    if not spec.scorer_path.exists():
        raise FileNotFoundError(f"{spec.id}: scorer missing at {spec.scorer_path}")
    gt = spec.ground_truth_path
    if gt is not None and not gt.exists():
        raise FileNotFoundError(f"{spec.id}: ground truth missing at {gt}")
    if spec.teaching.lesson_card and not spec.lesson_card_path.exists():
        raise FileNotFoundError(f"{spec.id}: lesson card missing at {spec.lesson_card_path}")
    for d in spec.dataset_paths():
        if not d.exists():
            raise FileNotFoundError(
                f"{spec.id}: dataset missing at {d} - run `python -m curricula.glp1r.fetch`"
            )


def load_curriculum(root: str | Path) -> Curriculum:
    root = Path(root)
    meta = yaml.safe_load((root / "curriculum.yaml").read_text(encoding="utf-8"))
    exp_dir = root / "experiments"
    specs = [load_experiment(p, root) for p in sorted(exp_dir.glob("*.yaml"))]
    specs.sort(key=lambda s: s.order)
    orders = [s.order for s in specs]
    if orders != list(range(1, len(orders) + 1)):
        raise ValueError(f"experiment orders must be 1..N with no gaps, got {orders}")
    known = {s.id for s in specs}
    for s in specs:
        for req in s.requires_lessons:
            if req not in known:
                raise ValueError(f"{s.id}: requires_lessons references unknown {req!r}")
            if next(x for x in specs if x.id == req).order >= s.order:
                raise ValueError(
                    f"{s.id}: requires_lessons must point at an earlier experiment, got {req!r}"
                )
    return Curriculum(
        id=meta["id"],
        title=meta["title"],
        hypothesis=meta["hypothesis"].strip(),
        hypothesis_id=meta["hypothesis_id"],
        experiments=specs,
        root=root,
    )
