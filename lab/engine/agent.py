"""The per-experiment agent loop (plan section 5.2).

One attempt, no retry. The shape is: commit to a prediction, work in the
sandbox, submit, get scored, then be taught. The teaching phase happens after
the score is fixed, so the lesson can never influence the attempt it grades.
"""
from __future__ import annotations

import json
import os
import random
import re
from typing import Any

from sandbox import get_executor

from .audit import run_audit, unaudited_report
from .events import EventLog
from .notebook import NotebookEntry
from .provider import ModelConfig, Provider
from .scoring import score_answer
from .specs import Curriculum, ExperimentSpec
from .tools import ToolContext, dispatch, tool_schemas

SYSTEM_ATTEMPT = """\
You are the resident scientist in a virtual laboratory, working through a \
curriculum of experiments built around one claim.

The curriculum claim:
{hypothesis}

How this works, and it matters:

- You get **one attempt** at each experiment. There is no retry.
- Before any data tool unlocks, you must write two notebook sections: \
`hypothesis_and_prediction` (with an explicit numeric confidence from 0 to 1) and \
`plan`. This ordering is the point of the exercise - your prediction is recorded \
before you can see whether it holds.
- State your confidence honestly. Accuracy and calibration are scored \
separately, and a well-calibrated 0.45 is worth more to this lab than a \
reflexive 0.9. If you already know the answer from prior knowledge rather than \
from the data, say so in `prior_knowledge_claimed`.
- After scoring you will be shown the relevant paper's lesson and asked what you \
got wrong. Lessons carry forward: later experiments depend on earlier ones.
- You have a budget of {max_tool_calls} tool calls for this experiment. Plan for it.

Each `run_python` call is a fresh process, so nothing stays in memory between \
calls. Parse an expensive file **once** and save the result (`.csv`, `.npy`, \
`.json`) into the working directory, then load that. Re-parsing the same file \
every call is the fastest way to run out of budget.

Work like a careful scientist: inspect the data before trusting your assumptions \
about it, and state the definitions behind any number you report.
"""

SYSTEM_TEACHING = """\
You are the same scientist, now in the teaching phase of this experiment.

Your answer has been scored and the score is final. You are being shown what the \
literature says. Two notebook sections are left to write, and only those two \
tools are available.

Be specific and unsparing with yourself. "I was wrong" is not useful; "I ranked \
by association strength, which measures statistical power rather than \
druggability" is. If you were confident and wrong, name the reasoning that \
produced the false confidence.
"""

FIRST_USER = """\
# Experiment {order} of {n}: {title}

## Task

{task}

## Required answer format

{answer_format}

## Available tools

{tool_summary}

{lesson_hint}
Begin by writing `hypothesis_and_prediction` (with your confidence) and `plan`. \
The other tools are locked until both exist.
"""

TEACHING_USER = """\
# Result

Your submitted answer scored **{score:.2f} / {max:.2f}**.

You stated a confidence of **{confidence}** before running. {calibration_line}

## Scorer detail

```json
{details}
```

## What the literature says

The teaching source for this experiment is:

{papers}

{lesson_card}

---

Now write two notebook sections:

1. `what_i_got_wrong` - what your answer got wrong, and if you were confident, \
why you were confident anyway. If your answer was essentially right, say which \
part was luck and which was method.
2. `lesson_learned` - the transferable lesson, in your own words, and how you \
will apply it in later experiments.
"""


def _tool_summary(schemas: list[dict[str, Any]]) -> str:
    return "\n".join(f"- `{s['name']}` - {s['description'].split('.')[0]}."
                     for s in schemas)


def _blocks_to_text(content: list[Any]) -> str:
    out = []
    for b in content:
        if getattr(b, "type", None) == "text":
            out.append(b.text)
    return "\n".join(out).strip()


def relevant_lessons(spec: Any, earned: list[tuple[str, str, str]]
                     ) -> list[tuple[str, str, str]]:
    """The earned cards this experiment declares it needs, in curriculum order.

    Relevance is the experiment's own `requires_lessons`. Cards earned on other
    experiments are not shown: they would add context that is not what the
    experiment is designed to test, and make arms incomparable.
    """
    wanted = set(spec.requires_lessons)
    return [card for card in earned if card[0] in wanted]


# Filler for the control arms. The real cards are replaced word for word, so
# length, line breaks and markdown marks are identical and only the content is
# gone. `placebo` swaps in prose about something unrelated; `null` swaps in
# symbol strings with no meaning at all.
_PLACEBO_PROSE = (
    "The lighthouse keeper climbed the spiral stair each evening to trim the wick "
    "and polish the great lens before the fog rolled in from the headland. Gulls "
    "wheeled over the rocks while the supply boat, late again, rocked at its "
    "mooring. In winter the keeper kept a ledger of passing ships, noting their "
    "flags, their weather and the hour, and on quiet nights he mended nets and "
    "read old almanacs by the stove. The harbour clock struck twelve, the tide "
    "turned, and the lamp swept its slow white arm across the water."
).split()
_NULL_ALPHABET = "%$#&@*+=~^<>|\\/?!"
_MD_PREFIX = re.compile(r"^(\s*(?:#+|[-*>]+|\d+[.)])\s+)")


def _swap_words(text: str, next_token) -> str:
    out = []
    for line in text.split("\n"):
        m = _MD_PREFIX.match(line)
        prefix = m.group(1) if m else ""
        out.append(prefix + " ".join(next_token() for _ in line[len(prefix):].split()))
    return "\n".join(out)


def filler_cards(cards: list[tuple[str, str, str]], kind: str
                 ) -> list[tuple[str, str, str]]:
    """Same-shape stand-ins for `cards`: neutral ids and titles, matched word
    count and layout, no topic. Deterministic, so a rerun gets identical text."""
    out = []
    for i, (exp_id, _title, md) in enumerate(cards, 1):
        if kind == "placebo":
            words = iter(_PLACEBO_PROSE * (len(md.split()) // len(_PLACEBO_PROSE) + 1))
            token = lambda: next(words)
        elif kind == "null":
            rng = random.Random(exp_id)
            token = lambda: "".join(rng.choices(_NULL_ALPHABET, k=rng.randint(2, 7)))
        else:
            raise ValueError(f"unknown filler kind {kind!r}")
        out.append((f"card_{i}", "Lesson card", _swap_words(md, token)))
    return out


def lesson_block(cards: list[tuple[str, str, str]]) -> str:
    """The cards as prompt text. Empty when there are none, so an experiment
    with no required lessons is never told it has any."""
    if not cards:
        return ""
    body = "\n\n".join(f"### {title} ({exp_id})\n\n{md.strip()}"
                        for exp_id, title, md in cards)
    return ("## Lessons from earlier experiments\n\n"
            "These cards were earned on earlier experiments and bear on this one. "
            "`read_lessons` returns the same text.\n\n" + body + "\n\n")


def run_experiment(
    spec: ExperimentSpec,
    curriculum: Curriculum,
    log: EventLog,
    provider: Provider,
    model_config: ModelConfig,
    earned_lessons: list[tuple[str, str, str]],
    notebook_entry: NotebookEntry,
    backend: str = "local",
    use_lessons: bool = True,
    audit: bool = True,
    audit_replay: bool = True,
    filler: str | None = None,
) -> NotebookEntry:
    entry = notebook_entry
    model = model_config.for_experiment(spec.order, len(curriculum.experiments))
    entry.model = model
    entry.papers = list(spec.teaching.papers)
    available = relevant_lessons(spec, earned_lessons) if use_lessons else []
    entry.applied_lesson_ids = [exp_id for exp_id, _, _ in available]
    if filler and available:
        available = filler_cards(available, filler)
    entry.status = "running"

    log.append("experiment_started", {
        "order": spec.order, "title": spec.title, "type": spec.type,
        "model": model, "max_tool_calls": spec.limits.max_tool_calls,
        "requires_lessons": list(spec.requires_lessons),
        "lessons_shown": entry.applied_lesson_ids,
        "lesson_filler": filler,
        "n_experiments": len(curriculum.experiments),
    }, experiment_id=spec.id)

    executor = get_executor(backend, name=f"agent-{spec.id}")
    executor.start()
    try:
        for path in spec.dataset_paths():
            executor.put_file(f"data/{path.name}", path.read_bytes(), read_only=True)

        ctx = ToolContext(spec=spec, entry=entry, log=log, executor=executor,
                          earned_lessons=available, phase="attempt")

        schemas = tool_schemas(ctx)
        lesson_hint = lesson_block(available)
        messages: list[dict[str, Any]] = [{
            "role": "user",
            "content": FIRST_USER.format(
                order=spec.order, n=len(curriculum.experiments), title=spec.title,
                task=spec.task, answer_format=spec.answer_format,
                tool_summary=_tool_summary(schemas), lesson_hint=lesson_hint,
            ),
        }]
        system = SYSTEM_ATTEMPT.format(hypothesis=curriculum.hypothesis,
                                       max_tool_calls=spec.limits.max_tool_calls)

        nudges = 0
        while True:
            if ctx.budget_left() <= 0:
                log.append("error", {"reason": "tool call budget exhausted",
                                     "used": ctx.tool_calls_used},
                           experiment_id=spec.id)
                break
            response = provider.complete(
                model=model, system=system, messages=messages,
                tools=tool_schemas(ctx), max_tokens=model_config.max_tokens,
                effort=model_config.effort,
            )
            messages.append({"role": "assistant", "content": response.content})

            tool_uses = [b for b in response.content
                         if getattr(b, "type", None) == "tool_use"]
            said = _blocks_to_text(response.content)
            if said:
                log.append("tool_call", {"kind": "say", "text": said[:600]},
                           experiment_id=spec.id)

            if not tool_uses:
                if ctx.has_submitted:
                    break
                nudges += 1
                if nudges > 2:
                    log.append("error", {"reason": "agent stopped without submitting"},
                               experiment_id=spec.id)
                    break
                messages.append({"role": "user", "content":
                                 "You have not called `submit_answer` yet. Either keep "
                                 "working or submit your answer now - the experiment "
                                 "cannot be scored without it."})
                continue

            results = []
            for tu in tool_uses:
                ctx.tool_calls_used += 1
                args = tu.input if isinstance(tu.input, dict) else {}
                log.append("tool_call", {
                    "kind": "tool", "tool": tu.name,
                    "note": (args.get("note") or args.get("section") or "")[:200],
                    "calls_used": ctx.tool_calls_used,
                    "budget": spec.limits.max_tool_calls,
                }, experiment_id=spec.id)
                text, is_error = dispatch(ctx, tu.name, args)
                results.append({
                    "type": "tool_result", "tool_use_id": tu.id,
                    "content": text + ctx.budget_note(), "is_error": is_error,
                })
            messages.append({"role": "user", "content": results})
            if ctx.has_submitted:
                break

        entry.tool_calls_used = ctx.tool_calls_used
        entry.answer = ctx.submitted_answer

        # ---- scoring, in a sandbox the agent has no handle on ------------
        if not ctx.has_submitted:
            result = {
                "score": 0.0, "max": 1.0,
                "details": {"error": "no answer was submitted before the budget ran out"},
            }
        else:
            result = score_answer(spec, ctx.submitted_answer, backend=backend)
        entry.record_score(result)
        log.append("scored", {
            "score": entry.score, "max": entry.score_max,
            "confidence_stated": entry.confidence,
            "calibration_gap": entry.calibration_gap,
            "details": _trim_details(result.get("details", {})),
        }, experiment_id=spec.id)

        # ---- audit: grade the path, outside the agent's context ----------
        # Nothing from the audit is shown to the agent (not in the teaching
        # prompt either): detailed rejection feedback teaches evasion.
        if audit:
            _audit(spec, curriculum, log, entry, result, available,
                   ctx.has_submitted, backend, audit_replay)

        # ---- teaching ---------------------------------------------------
        _teach(spec, log, provider, model, model_config, ctx, entry, messages)
    finally:
        executor.close()

    entry.status = "done"
    log.append("notebook_entry_ready", {"entry": entry.to_dict()}, experiment_id=spec.id)
    log.append("experiment_done", {
        "score": entry.score, "max": entry.score_max,
        "confidence_stated": entry.confidence,
        "calibration_gap": entry.calibration_gap,
        "title": spec.title, "order": spec.order,
    }, experiment_id=spec.id)
    return entry


def _audit(spec: ExperimentSpec, curriculum: Curriculum, log: EventLog,
           entry: NotebookEntry, result: dict[str, Any],
           earned: list[tuple[str, str, str]], submitted: bool, backend: str,
           replay: bool) -> None:
    """Run the auditor; a crash in it must never take the experiment down."""
    outcome = (entry.score or 0.0) / (entry.score_max or 1.0)
    try:
        events = [{"seq": e.seq, "type": e.type, "payload": e.payload}
                  for e in log.for_experiment(spec.id)]
        report = run_audit(
            spec=spec, curriculum=curriculum, events=events, entry=entry,
            score_result=result, earned_lessons=earned, submitted=submitted,
            backend=backend, replay=replay and backend == "local",
            online=os.environ.get("FL_AUDIT_ONLINE", "1") != "0",
        )
        data = (report.to_dict() if report is not None
                else unaudited_report(outcome, "this experiment has no audit spec"))
    except Exception as exc:
        data = unaudited_report(outcome, f"auditor error: {type(exc).__name__}: {exc}")
    entry.audit = data
    log.append("audited", data, experiment_id=spec.id)


def _teach(spec: ExperimentSpec, log: EventLog, provider: Provider, model: str,
           model_config: ModelConfig, ctx: ToolContext, entry: NotebookEntry,
           messages: list[dict[str, Any]]) -> None:
    log.append("teaching_started", {
        "papers": spec.teaching.papers,
        "lesson_card": str(spec.teaching.lesson_card),
    }, experiment_id=spec.id)

    lesson_md = ""
    if spec.lesson_card_path.exists():
        lesson_md = spec.lesson_card_path.read_text(encoding="utf-8")

    gap = entry.calibration_gap
    if gap is None:
        calibration_line = ""
    elif gap > 0.15:
        calibration_line = (f"That is a calibration gap of {gap:+.2f}: you were "
                            f"overconfident.")
    elif gap < -0.15:
        calibration_line = (f"That is a calibration gap of {gap:+.2f}: you did better "
                            f"than you expected.")
    else:
        calibration_line = f"That is a calibration gap of {gap:+.2f}: well calibrated."

    ctx.phase = "teaching"
    messages.append({"role": "user", "content": TEACHING_USER.format(
        score=entry.score or 0.0, max=entry.score_max,
        confidence=(f"{entry.confidence:.2f}" if entry.confidence is not None
                    else "not stated"),
        calibration_line=calibration_line,
        details=json.dumps(_trim_details(entry.score_details), indent=2)[:4000],
        papers="\n".join(f"- {p}" for p in spec.teaching.papers) or "- (none)",
        lesson_card=lesson_md,
    )})

    for _ in range(3):
        response = provider.complete(
            model=model, system=SYSTEM_TEACHING, messages=messages,
            tools=tool_schemas(ctx), max_tokens=model_config.max_tokens,
            effort=model_config.effort,
        )
        messages.append({"role": "assistant", "content": response.content})
        tool_uses = [b for b in response.content
                     if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            break
        results = []
        for tu in tool_uses:
            args = tu.input if isinstance(tu.input, dict) else {}
            text, is_error = dispatch(ctx, tu.name, args)
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": text, "is_error": is_error})
        messages.append({"role": "user", "content": results})
        if entry.has("what_i_got_wrong") and entry.has("lesson_learned"):
            break

    log.append("lesson_learned", {
        "lesson_card": str(spec.teaching.lesson_card),
        "what_i_got_wrong": entry.sections.get("what_i_got_wrong", "")[:1200],
        "lesson_learned": entry.sections.get("lesson_learned", "")[:1200],
        "papers": spec.teaching.papers,
    }, experiment_id=spec.id)


def _trim_details(details: dict[str, Any], limit: int = 3500) -> dict[str, Any]:
    """Keep score details small enough to live comfortably in the event log."""
    try:
        blob = json.dumps(details, default=str)
    except Exception:
        return {"unserialisable": True}
    if len(blob) <= limit:
        return details
    out = {}
    for k, v in details.items():
        s = json.dumps(v, default=str)
        out[k] = v if len(s) < 600 else f"[{type(v).__name__}, {len(s)} bytes, elided]"
    return out
