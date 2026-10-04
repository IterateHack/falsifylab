"""The cold arm: what the model answers with no lab at all.

It sees the hypothesis, the experiment's title and the required answer format.
No task text, no data, no tools, no lessons. The answer is scored by the same
scorer as every other arm, so a lab arm's score can be read against what prior
knowledge alone achieves. If the lab without lessons scores below this, the
apparatus is costing the model something.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent import _blocks_to_text
from .notebook import Notebook, NotebookEntry
from .provider import MeteredProvider, ModelConfig, Provider
from .runner import RunResult, _persist, write_run_meta
from .scoring import score_answer
from .specs import load_curriculum

SYSTEM = """\
You are a scientist answering a research question from memory. You have no \
data, no tools and no way to run anything. State what you believe is true from \
what you already know.
"""

USER = """\
Hypothesis under investigation:

{hypothesis}

Experiment {order} of {n}: {title}

You are not shown the data or the task details. Give the answer you would \
expect the experiment to support, in the required format:

{answer_format}

Reply with one JSON object and nothing else:
{{"confidence": <number between 0 and 1: your confidence this is right>,
  "answer": <the answer, in the required format>}}
"""


def parse_reply(text: str) -> tuple[Any, float | None]:
    """First JSON object in the reply -> (answer, confidence). (None, None) if
    nothing parses; the caller scores that as a missing answer."""
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except ValueError:
            continue
        if isinstance(obj, dict) and "answer" in obj:
            conf = obj.get("confidence")
            conf = float(conf) if isinstance(conf, (int, float)) \
                and not isinstance(conf, bool) and 0 <= conf <= 1 else None
            return obj["answer"], conf
    return None, None


def run_cold_curriculum(
    *, provider: Provider, curriculum_root: str | Path = "curricula/glp1r",
    run_id: str, runs_dir: str | Path = "runs", backend: str = "local",
    model_config: ModelConfig | None = None,
) -> RunResult:
    curriculum = load_curriculum(curriculum_root)
    model_config = model_config or ModelConfig()
    provider = MeteredProvider(provider)
    run_dir = Path(runs_dir) / run_id
    notebook = Notebook(run_id=run_id, hypothesis=curriculum.hypothesis)
    n = len(curriculum.experiments)

    for spec in curriculum.experiments:
        entry = NotebookEntry(experiment_id=spec.id, title=spec.title,
                              order=spec.order, papers=list(spec.teaching.papers))
        notebook.entries.append(entry)
        response = provider.complete(
            model=model_config.for_experiment(spec.order, n), system=SYSTEM,
            messages=[{"role": "user", "content": USER.format(
                hypothesis=curriculum.hypothesis, order=spec.order, n=n,
                title=spec.title, answer_format=spec.answer_format)}],
            tools=[], max_tokens=model_config.max_tokens, effort=model_config.effort)
        answer, conf = parse_reply(_blocks_to_text(response.content))
        entry.answer, entry.confidence = answer, conf
        if answer is None:
            result = {"score": 0.0, "max": 1.0,
                      "details": {"error": "no parseable answer in the reply"}}
        else:
            result = score_answer(spec, answer, backend=backend)
        entry.record_score(result)
        entry.status = "done"
        _persist(run_dir, notebook)

    write_run_meta(run_dir, arm="cold", curriculum=curriculum.id)
    (run_dir / "usage.json").write_text(json.dumps(provider.usage, indent=2),
                                        encoding="utf-8")
    return RunResult(run_id=run_id, run_dir=run_dir, notebook=notebook, log=None)
