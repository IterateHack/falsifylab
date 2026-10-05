"""Agent tools, and the gate that keeps them shut until a prediction exists.

The ordering rule is the whole experiment: the agent must commit to a
prediction and a stated confidence *before* it can look at any data. Section 1
and section 2 of the notebook are therefore the only things it can write at the
start, and every other tool refuses until they exist (plan section 5.2).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .events import EventLog
from .notebook import NotebookEntry, SECTION_TITLES
from .specs import ExperimentSpec

ATTEMPT_SECTIONS = ("hypothesis_and_prediction", "plan", "what_i_did",
                    "lessons_applied", "prior_knowledge_claimed")
TEACHING_SECTIONS = ("what_i_got_wrong", "lesson_learned")


class ToolError(Exception):
    """Returned to the model as an error tool_result rather than raised.

    `code` marks an integrity-relevant refusal (e.g. an attempt to rewrite the
    prediction); it is logged so the auditor can see the attempt.
    """

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


@dataclass
class ToolContext:
    spec: ExperimentSpec
    entry: NotebookEntry
    log: EventLog
    executor: Any
    earned_lessons: list[tuple[str, str, str]]   # (experiment_id, title, markdown)
    phase: str = "attempt"                       # "attempt" | "teaching"
    tool_calls_used: int = 0
    submitted_answer: Any = None
    has_submitted: bool = False
    status_lines: list[str] = field(default_factory=list)
    # Calls held back so the agent can always afford to submit. Without this an
    # agent that explores enthusiastically scores zero for running out of budget,
    # which tells us nothing about whether it understood the science.
    submit_reserve: int = 2
    last_run_logged: bool = False        # set by run_python, read by dispatch

    @property
    def gates_open(self) -> bool:
        return (self.entry.has("hypothesis_and_prediction")
                and self.entry.confidence is not None
                and self.entry.has("plan"))

    def budget_left(self) -> int:
        return max(0, self.spec.limits.max_tool_calls - self.tool_calls_used)

    @property
    def in_reserve(self) -> bool:
        """True once only the held-back submission calls remain."""
        return not self.has_submitted and self.budget_left() <= self.submit_reserve

    def budget_note(self) -> str:
        left = self.budget_left()
        if self.has_submitted:
            return ""
        if self.in_reserve:
            return (f"\n\n[BUDGET: {left} of {self.spec.limits.max_tool_calls} tool "
                    f"calls left. Exploration tools are now withdrawn. Submit your best "
                    f"answer with `submit_answer` on this turn - an unsubmitted "
                    f"experiment scores zero.]")
        if left <= 6:
            return (f"\n\n[BUDGET: {left} of {self.spec.limits.max_tool_calls} tool "
                    f"calls left. Start converging on an answer.]")
        return (f"\n\n[BUDGET: {left} of {self.spec.limits.max_tool_calls} tool "
                f"calls left.]")


# --------------------------------------------------------------------------
# tool schemas
# --------------------------------------------------------------------------
def tool_schemas(ctx: ToolContext) -> list[dict[str, Any]]:
    if ctx.phase == "teaching":
        sections = list(TEACHING_SECTIONS)
        return [_write_section_schema(sections)]

    sections = list(ATTEMPT_SECTIONS)
    if ctx.in_reserve and ctx.gates_open:
        return [_write_section_schema(sections), _submit_schema()]
    schemas = [
        _write_section_schema(sections),
        {
            "name": "list_datasets",
            "description": "List the files available in the sandbox, with sizes. "
                           "Locked until the notebook has a prediction with a stated "
                           "confidence and a plan.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the sandbox. Returns at most "
                           "20000 characters. For large structure files, prefer "
                           "run_python so you can parse rather than read.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Path relative to the sandbox root, "
                                            "e.g. data/exp1_gwas_targets.csv"},
                    "max_chars": {"type": "integer",
                                  "description": "Truncate after this many characters "
                                                 "(default 20000)."},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "run_python",
            "description": "Execute Python in the experiment sandbox and return stdout, "
                           "stderr and any figures written. pandas, numpy, scipy and "
                           "matplotlib are available. The working directory is work/ and "
                           "datasets are at ../data/. There is no network access. State "
                           "does not persist between calls - each call is a fresh process, "
                           "so write files if you need to carry results forward.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "The Python source to run."},
                    "note": {"type": "string",
                             "description": "One short line on what this call is for. "
                                            "Shown in the lab UI as a status message."},
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        },
        {
            "name": "read_lessons",
            "description": "Retrieve the lesson cards earned in earlier experiments. "
                           "Returns nothing for the first experiment. The lesson for the "
                           "current experiment is not available until after scoring.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        _submit_schema(),
    ]
    return schemas


def _submit_schema() -> dict[str, Any]:
    return {
        "name": "submit_answer",
        "description": "Submit the final answer for scoring. This ends the attempt - "
                       "there is exactly one attempt per experiment, with no retry. "
                       "Match the required answer format exactly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "object",
                    "description": "The answer object, in the format the task specifies.",
                    "additionalProperties": True,
                },
            },
            "required": ["answer"],
            "additionalProperties": False,
        },
    }


def _write_section_schema(sections: list[str]) -> dict[str, Any]:
    return {
        "name": "write_notebook_section",
        "description": "Write (or overwrite) one section of the lab notebook. "
                       "Sections 'hypothesis_and_prediction' and 'plan' must both be "
                       "written before any other tool unlocks, and "
                       "'hypothesis_and_prediction' requires a numeric confidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "enum": sections,
                            "description": "Which section to write."},
                "text": {"type": "string", "description": "The section body, in markdown."},
                "confidence": {
                    "type": "number", "minimum": 0.0, "maximum": 1.0,
                    "description": "Required for 'hypothesis_and_prediction': your "
                                   "probability, from 0 to 1, that your prediction is "
                                   "correct. State it honestly - calibration is scored "
                                   "separately from accuracy.",
                },
            },
            "required": ["section", "text"],
            "additionalProperties": False,
        },
    }


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------
def dispatch(ctx: ToolContext, name: str, args: dict[str, Any]) -> tuple[str, bool]:
    """Run one tool. Returns (result_text, is_error).

    Every attempt-phase call leaves a `tool_result` event, including refused and
    locked ones: the auditor grades the path, and a refusal is part of the path.
    `run_python` logs its own richer result when it actually runs.
    """
    violation: str | None = None
    try:
        handler: Callable[[ToolContext, dict[str, Any]], str] = _HANDLERS[name]
    except KeyError:
        text, is_error, locked = f"unknown tool {name!r}", True, False
    else:
        locked = False
        gated = name not in ("write_notebook_section",)
        if gated and not ctx.gates_open:
            locked = True
            text, is_error = (
                "LOCKED. Write the notebook sections 'hypothesis_and_prediction' "
                "(with a numeric confidence) and 'plan' first. Nothing else is available "
                "until you have committed to a prediction.",
                True,
            )
        else:
            ctx.last_run_logged = False
            try:
                text, is_error = handler(ctx, args), False
            except ToolError as exc:
                text, is_error, violation = str(exc), True, exc.code
            except Exception as exc:  # a tool bug must not kill the run
                text, is_error = f"{type(exc).__name__}: {exc}", True

    if ctx.phase == "attempt" and not (name == "run_python" and ctx.last_run_logged):
        payload: dict[str, Any] = {"tool": name, "ok": not is_error, "locked": locked}
        if violation:
            payload["violation"] = violation
        if name == "read_file":
            payload["path"] = str(args.get("path", ""))[:300]
        if is_error:
            payload["error"] = text[:300]
        ctx.log.append("tool_result", payload, experiment_id=ctx.spec.id)
    return text, is_error


def _h_write_section(ctx: ToolContext, args: dict[str, Any]) -> str:
    section = args.get("section", "")
    text = args.get("text", "")
    allowed = TEACHING_SECTIONS if ctx.phase == "teaching" else ATTEMPT_SECTIONS
    if section not in allowed:
        raise ToolError(f"section {section!r} cannot be written during the "
                        f"{ctx.phase} phase; allowed: {list(allowed)}")
    if not text.strip():
        raise ToolError("section text is empty")

    # Write-once after the gate opens. Without this the agent could see the data
    # and then quietly "predict" what it found, which empties the gate of meaning.
    if (ctx.phase == "attempt" and ctx.gates_open
            and section in ("hypothesis_and_prediction", "plan")):
        raise ToolError(
            f"'{section}' is already recorded and cannot be changed now that the "
            f"data tools are open. Describe anything that changed in 'what_i_did'.",
            code=("prediction_rewritten" if section == "hypothesis_and_prediction"
                  else "plan_rewritten"),
        )

    confidence = args.get("confidence")
    if section == "hypothesis_and_prediction":
        if confidence is None:
            raise ToolError("'hypothesis_and_prediction' requires a numeric "
                            "'confidence' between 0 and 1")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            raise ToolError("'confidence' must be a number between 0 and 1")
        if not 0.0 <= confidence <= 1.0:
            raise ToolError("'confidence' must be between 0 and 1")
        ctx.entry.confidence = confidence

    was_open = ctx.gates_open
    ctx.entry.set(section, text)

    if section == "hypothesis_and_prediction":
        ctx.log.append("prediction_written",
                       {"confidence": ctx.entry.confidence,
                        "excerpt": text.strip()[:400]},
                       experiment_id=ctx.spec.id)
    elif section == "plan":
        ctx.log.append("plan_written", {"excerpt": text.strip()[:400]},
                       experiment_id=ctx.spec.id)

    suffix = ""
    if not was_open and ctx.gates_open:
        suffix = ("\n\nPrediction and plan are both recorded. The data tools are now "
                  "unlocked.")
    return f"wrote notebook section '{SECTION_TITLES[section]}' ({len(text)} chars).{suffix}"


def _h_list_datasets(ctx: ToolContext, args: dict[str, Any]) -> str:
    files = ctx.executor.list_files(".")
    if not files:
        return "the sandbox contains no files"
    lines = []
    for rel in files:
        if rel.endswith("_snippet.py"):
            continue
        size = (Path(ctx.executor.root) / rel).stat().st_size
        lines.append(f"  {rel}  ({size:,} bytes)")
    return ("files in the sandbox (paths are relative to the sandbox root; your "
            "working directory is work/, so datasets are at ../data/):\n"
            + "\n".join(lines))


def _h_read_file(ctx: ToolContext, args: dict[str, Any]) -> str:
    path = args.get("path", "")
    if not path:
        raise ToolError("'path' is required")
    max_chars = int(args.get("max_chars") or 20000)
    max_chars = max(200, min(max_chars, 20000))
    try:
        content = ctx.executor.read_file(path)
    except FileNotFoundError:
        available = [f for f in ctx.executor.list_files(".")
                     if not f.endswith("_snippet.py")]
        raise ToolError(f"no such file {path!r}. Available: {available}")
    if len(content) > max_chars:
        return (content[:max_chars]
                + f"\n\n... [truncated: {len(content) - max_chars:,} more characters. "
                  f"Use run_python to parse this file instead of reading it.]")
    return content


_EVENT_CODE_CAP = 12000
_EVENT_TEXT_CAP = 12000


def _h_run_python(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args.get("code", "")
    if not code.strip():
        raise ToolError("'code' is empty")
    note = (args.get("note") or "").strip()
    if note:
        ctx.status_lines.append(note)
    res = ctx.executor.run_python(code, timeout_s=ctx.spec.limits.max_python_seconds)
    # The code, its output and what it did are recorded in full (capped): the
    # auditor needs the path, and a result with only "ok: true" has none.
    ctx.log.append("tool_result", {
        "tool": "run_python", "ok": res.ok, "timed_out": res.timed_out,
        "duration_s": round(res.duration_s, 2),
        "figures": res.figures,
        "note": note,
        "code": code[:_EVENT_CODE_CAP],
        "code_truncated": len(code) > _EVENT_CODE_CAP,
        "stdout": res.stdout[:_EVENT_TEXT_CAP],
        "stderr": res.stderr[-2000:],
        "trace": res.trace,
        "files_written": res.files_written,
        "memory_cap_enforced": res.memory_cap_enforced,
        "limits_note": res.limits_note,
    }, experiment_id=ctx.spec.id)
    ctx.last_run_logged = True
    if res.memory_cap_enforced is not True:
        # Not comparable to a capped run; the notebook says so, every time.
        ctx.entry.note_unenforced_limit(res.limits_note or "memory cap not reported")
    return res.as_tool_result()


def _h_read_lessons(ctx: ToolContext, args: dict[str, Any]) -> str:
    if not ctx.earned_lessons:
        return ("no lessons earned yet - this is the first experiment in the "
                "curriculum.")
    parts = [f"You have earned {len(ctx.earned_lessons)} lesson card(s) from earlier "
             f"experiments. They are reproduced in full below."]
    for exp_id, title, md in ctx.earned_lessons:
        parts.append(f"\n--- lesson from {exp_id} ({title}) ---\n{md.strip()}")
    return "\n".join(parts)


def _h_submit_answer(ctx: ToolContext, args: dict[str, Any]) -> str:
    answer = args.get("answer")
    if answer is None:
        raise ToolError("'answer' is required")
    if ctx.has_submitted:
        raise ToolError("an answer has already been submitted for this experiment; "
                        "there is one attempt only")
    ctx.submitted_answer = answer
    ctx.has_submitted = True
    try:
        size = len(json.dumps(answer, default=str))
    except Exception:
        size = -1
    return (f"answer submitted for scoring ({size} bytes of JSON). The attempt is "
            f"now closed. Write nothing further until the result comes back.")


_HANDLERS: dict[str, Callable[[ToolContext, dict[str, Any]], str]] = {
    "write_notebook_section": _h_write_section,
    "list_datasets": _h_list_datasets,
    "read_file": _h_read_file,
    "run_python": _h_run_python,
    "read_lessons": _h_read_lessons,
    "submit_answer": _h_submit_answer,
}
