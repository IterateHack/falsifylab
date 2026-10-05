"""The cold arm: what the model answers with no lab at all.

It sees the curriculum claim, the experiment's title and the required answer format.
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
what you already know. Submit your answer with the `submit_answer` tool; it is \
the only tool you have.
"""

USER = """\
Curriculum claim:

{hypothesis}

Experiment {order} of {n}: {title}

You are not shown the data or the task details. Give the answer you would \
expect the experiment to support, in the required format:

{answer_format}

Submit with `submit_answer`, giving your confidence (0 to 1) that the answer \
is right alongside the answer itself.
"""


SUBMIT = {
    "name": "submit_answer",
    "description": "Submit the answer, in the required format, with your confidence.",
    "input_schema": {
        "type": "object",
        "properties": {
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "answer": {"type": "object", "additionalProperties": True},
        },
        "required": ["answer", "confidence"],
        "additionalProperties": False,
    },
}


def parse_submission(content: list[Any]) -> tuple[Any, float | None]:
    """The structured submission if the model made one, else whatever JSON it
    wrote in prose. The tool path is the fair one: the lab arms submit through
    a tool too, so a stray bracket in free text should not cost the cold arm."""
    for block in content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_answer":
            args = block.input or {}
            conf = args.get("confidence")
            ok = isinstance(conf, (int, float)) and not isinstance(conf, bool) \
                and 0 <= conf <= 1
            return args.get("answer"), float(conf) if ok else None
    return parse_reply(_blocks_to_text(content))


def parse_reply(text: str) -> tuple[Any, float | None]:
    """First JSON object in the reply -> (answer, confidence). (None, None) if
    nothing parses; the caller scores that as a missing answer."""
    # strict=False: a long prose answer often carries literal newlines inside
    # its strings, which is a formatting slip and not a wrong answer.
    decoder = json.JSONDecoder(strict=False)
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
            tools=[SUBMIT], max_tokens=model_config.max_tokens, effort=model_config.effort)
        reply = _blocks_to_text(response.content)
        answer, conf = parse_submission(response.content)
        entry.answer, entry.confidence = answer, conf
        if answer is None:
            result = {"score": 0.0, "max": 1.0,
                      "details": {"error": "no parseable answer in the reply",
                                    "stop_reason": getattr(response, "stop_reason", None),
                                    "raw_reply": reply[:6000]}}
        else:
            result = score_answer(spec, answer, backend=backend)
        entry.record_score(result)
        entry.status = "done"
        _persist(run_dir, notebook)

    write_run_meta(run_dir, arm="cold", curriculum=curriculum.id)
    (run_dir / "usage.json").write_text(json.dumps(provider.usage, indent=2),
                                        encoding="utf-8")
    return RunResult(run_id=run_id, run_dir=run_dir, notebook=notebook, log=None)
