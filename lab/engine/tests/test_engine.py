"""Engine tests: the gate, the budget reserve, the event log and the sandbox.

These cover the properties the project's claims rest on. If the gate can be
bypassed, "the prediction was recorded first" is not true; if the scorer can see
the agent's sandbox, the score is not trustworthy.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.events import EventLog, read_jsonl
from engine.notebook import NotebookEntry
from engine.scoring import score_answer
from engine.specs import load_curriculum
from engine.tools import ToolContext, dispatch, tool_schemas
from sandbox import get_executor

CURRICULUM = Path(__file__).resolve().parents[2] / "curricula" / "glp1r"


@pytest.fixture
def curriculum():
    return load_curriculum(CURRICULUM)


@pytest.fixture
def ctx(tmp_path, curriculum):
    spec = curriculum.experiments[0]
    log = EventLog(tmp_path / "run", "run_test")
    ex = get_executor("local", name="test")
    ex.start()
    entry = NotebookEntry(spec.id, spec.title, spec.order)
    c = ToolContext(spec=spec, entry=entry, log=log, executor=ex, earned_lessons=[])
    yield c
    ex.close()


# --- the gate -------------------------------------------------------------
def test_tools_are_locked_until_prediction_and_plan_exist(ctx):
    for tool in ("list_datasets", "run_python", "read_file", "submit_answer",
                 "read_lessons"):
        text, is_error = dispatch(ctx, tool, {"path": "x", "code": "print(1)",
                                              "answer": {}})
        assert is_error, f"{tool} should be locked"
        assert "LOCKED" in text


def test_prediction_requires_a_numeric_confidence(ctx):
    text, is_error = dispatch(ctx, "write_notebook_section", {
        "section": "hypothesis_and_prediction", "text": "I predict X"})
    assert is_error and "confidence" in text
    assert not ctx.gates_open

    _, is_error = dispatch(ctx, "write_notebook_section", {
        "section": "hypothesis_and_prediction", "text": "I predict X",
        "confidence": 1.4})
    assert is_error, "confidence outside [0, 1] must be rejected"


def test_gate_opens_only_after_both_sections(ctx):
    dispatch(ctx, "write_notebook_section", {
        "section": "hypothesis_and_prediction", "text": "I predict X",
        "confidence": 0.7})
    assert not ctx.gates_open, "a prediction alone must not unlock the tools"
    text, is_error = dispatch(ctx, "list_datasets", {})
    assert is_error

    dispatch(ctx, "write_notebook_section", {"section": "plan", "text": "do Y"})
    assert ctx.gates_open
    _, is_error = dispatch(ctx, "list_datasets", {})
    assert not is_error
    assert ctx.entry.confidence == 0.7


def test_teaching_sections_cannot_be_written_during_the_attempt(ctx):
    _, is_error = dispatch(ctx, "write_notebook_section", {
        "section": "lesson_learned", "text": "cheating early"})
    assert is_error


def test_only_one_submission_is_accepted(ctx):
    _open_gate(ctx)
    _, is_error = dispatch(ctx, "submit_answer", {"answer": {"ranked_genes": ["A"]}})
    assert not is_error
    text, is_error = dispatch(ctx, "submit_answer", {"answer": {"ranked_genes": ["B"]}})
    assert is_error and "one attempt" in text
    assert ctx.submitted_answer == {"ranked_genes": ["A"]}


# --- budget ---------------------------------------------------------------
def test_budget_reserve_withdraws_exploration_tools(ctx):
    _open_gate(ctx)
    names = {t["name"] for t in tool_schemas(ctx)}
    assert "run_python" in names

    ctx.tool_calls_used = ctx.spec.limits.max_tool_calls - 1
    assert ctx.in_reserve
    names = {t["name"] for t in tool_schemas(ctx)}
    assert names == {"write_notebook_section", "submit_answer"}
    assert "Submit your best answer" in ctx.budget_note()


# --- the sandbox ----------------------------------------------------------
def test_sandbox_blocks_network_and_keeps_datasets_readable(ctx):
    _open_gate(ctx)
    ctx.executor.put_file("data/x.csv", b"a,b\n1,2\n", read_only=True)
    text, is_error = dispatch(ctx, "run_python", {
        "code": "import pandas as pd; print(pd.read_csv('../data/x.csv').sum().sum())"})
    assert not is_error and "3" in text

    text, _ = dispatch(ctx, "run_python", {
        "code": "import socket; socket.create_connection(('example.com', 80))"})
    assert "network access is disabled" in text


def test_sandbox_enforces_a_timeout(ctx):
    _open_gate(ctx)
    ctx.spec.limits.__dict__  # frozen dataclass; use the executor directly
    res = ctx.executor.run_python("while True: pass", timeout_s=2)
    assert res.timed_out and not res.ok


def test_read_file_cannot_escape_the_sandbox(ctx):
    _open_gate(ctx)
    text, is_error = dispatch(ctx, "read_file", {"path": "../../../../etc/passwd"})
    assert is_error


# --- scoring isolation ----------------------------------------------------
def test_ground_truth_is_never_mounted_in_the_agent_sandbox(ctx, curriculum):
    """The whole scoring claim rests on this."""
    _open_gate(ctx)
    for spec in curriculum.experiments:
        for path in spec.dataset_paths():
            ctx.executor.put_file(f"data/{path.name}", path.read_bytes(), read_only=True)
    files = " ".join(ctx.executor.list_files("."))
    assert "private" not in files
    assert "ground_truth" not in files
    assert "exp1.json" not in files


def test_scorer_runs_and_is_deterministic(curriculum):
    spec = curriculum.by_id("exp2_structure_contacts")
    truth = json.loads(spec.ground_truth_path.read_text())
    answer = {"contact_residues": truth["contact_resnums"]}
    a = score_answer(spec, answer)
    b = score_answer(spec, answer)
    assert a["score"] == b["score"] == 1.0


def test_scorer_failure_is_contained(curriculum):
    """A malformed answer must score zero, not crash the run."""
    spec = curriculum.by_id("exp2_structure_contacts")
    result = score_answer(spec, {"wrong_key": "nonsense"})
    assert result["score"] == 0.0
    assert "error" in json.dumps(result["details"])


# --- event log ------------------------------------------------------------
def test_event_log_is_append_only_and_round_trips(tmp_path):
    log = EventLog(tmp_path / "run", "run_x")
    seen = []
    log.subscribe(seen.append)
    log.append("run_started", {"a": 1})
    log.append("experiment_started", {"b": 2}, experiment_id="exp1")
    log.append("run_finished", {})
    assert [e.seq for e in log.all()] == [1, 2, 3]
    assert len(seen) == 3
    on_disk = read_jsonl(tmp_path / "run" / "events.jsonl")
    assert [e.type for e in on_disk] == ["run_started", "experiment_started",
                                         "run_finished"]
    assert on_disk[1].experiment_id == "exp1"


def test_unknown_event_types_are_rejected(tmp_path):
    log = EventLog(tmp_path / "run", "run_x")
    with pytest.raises(ValueError):
        log.append("not_a_real_event", {})


def test_a_broken_subscriber_cannot_break_the_run(tmp_path):
    log = EventLog(tmp_path / "run", "run_x")
    log.subscribe(lambda ev: (_ for _ in ()).throw(RuntimeError("boom")))
    log.append("run_started", {})
    assert len(log.all()) == 1


# --- curriculum ------------------------------------------------------------
def test_lesson_dependencies_only_point_backwards(curriculum):
    order = {e.id: e.order for e in curriculum.experiments}
    for e in curriculum.experiments:
        for req in e.requires_lessons:
            assert order[req] < e.order


def test_every_experiment_has_data_ground_truth_and_a_lesson(curriculum):
    for e in curriculum.experiments:
        assert e.scorer is not None
        assert e.ground_truth_path and e.ground_truth_path.exists()
        assert e.lesson_card_path.exists()
        assert len(e.lesson_card_path.read_text().split()) <= 520, \
            f"{e.id}: lesson card is too long"
        for d in e.dataset_paths():
            assert d.exists()


def _cards(curriculum, upto_order):
    return [(e.id, e.title, f"card for {e.id}")
            for e in curriculum.experiments if e.order < upto_order]


def test_an_experiment_is_shown_only_the_cards_it_requires(curriculum):
    from engine.agent import relevant_lessons
    for e in curriculum.experiments:
        shown = relevant_lessons(e, _cards(curriculum, e.order))
        assert [c[0] for c in shown] == [
            r for r in (x.id for x in curriculum.experiments)
            if r in e.requires_lessons], e.id


def test_exp3_is_not_shown_the_exp1_card(curriculum):
    from engine.agent import relevant_lessons
    e3 = curriculum.by_id("exp3_peptide_engineering")
    shown = relevant_lessons(e3, _cards(curriculum, e3.order))
    assert [c[0] for c in shown] == ["exp2_structure_contacts"]


def test_an_experiment_with_no_required_lessons_is_shown_none(curriculum):
    from engine.agent import lesson_block, relevant_lessons
    e2 = curriculum.by_id("exp2_structure_contacts")
    shown = relevant_lessons(e2, _cards(curriculum, e2.order))
    assert shown == []
    assert lesson_block(shown) == ""


def test_lesson_block_puts_the_card_text_in_the_prompt():
    from engine.agent import lesson_block
    block = lesson_block([("exp2", "Structure", "  Check the chain IDs.  ")])
    assert "Check the chain IDs." in block
    assert "Structure (exp2)" in block
    assert "read_lessons" in block


def _open_gate(ctx) -> None:
    dispatch(ctx, "write_notebook_section", {
        "section": "hypothesis_and_prediction", "text": "prediction",
        "confidence": 0.5})
    dispatch(ctx, "write_notebook_section", {"section": "plan", "text": "plan"})


def test_a_second_writer_is_refused(tmp_path):
    """Two processes in one run directory interleave seqs and corrupt the log."""
    import json
    import os
    from engine.events import RunLockedError

    log = EventLog(tmp_path / "run", "run_x")
    log.append("run_started", {})
    (tmp_path / "run" / "run.lock").write_text(
        json.dumps({"pid": 1, "run_id": "run_x"}))      # pid 1 is always alive
    with pytest.raises(RunLockedError):
        EventLog(tmp_path / "run", "run_x")
    # a stale lock from a dead process must not block a legitimate re-open
    (tmp_path / "run" / "run.lock").write_text(
        json.dumps({"pid": 999_999, "run_id": "run_x"}))
    reopened = EventLog(tmp_path / "run", "run_x")
    reopened.append("run_finished", {})
    assert [e.seq for e in reopened.all()] == [1, 2]
    reopened.close()
    assert not (tmp_path / "run" / "run.lock").exists()
    os.environ.pop("FL_UNUSED", None)


def test_metered_provider_totals_tokens_per_model():
    from types import SimpleNamespace as NS
    from engine.provider import MeteredProvider, ScriptedProvider
    resp = lambda i, o: NS(usage=NS(input_tokens=i, output_tokens=o,
                                    cache_read_input_tokens=None))
    inner = ScriptedProvider([resp(10, 5), resp(20, 7), NS()])
    m = MeteredProvider(inner)
    m.complete(model="a")
    m.complete(model="a")
    m.complete(model="b")          # a response with no usage is not counted
    assert m.usage == {"a": {"calls": 2, "input_tokens": 30, "output_tokens": 12,
                             "cache_read_input_tokens": 0,
                             "cache_creation_input_tokens": 0}}


_CARD = ("# Check the chain\n\nRead the **file** first:\n- one two three\n"
         "- four five\n\n1. last step here\n")


@pytest.mark.parametrize("kind", ["placebo", "null"])
def test_filler_matches_the_card_in_shape_and_carries_no_topic(kind):
    from engine.agent import filler_cards
    (cid, title, text), = filler_cards([("exp2_structure_contacts", "Structure", _CARD)], kind)
    assert (cid, title) == ("card_1", "Lesson card")        # neutral id and title
    assert len(text.split("\n")) == len(_CARD.split("\n"))
    for a, b in zip(_CARD.split("\n"), text.split("\n")):
        assert len(a.split()) == len(b.split()), (a, b)      # same words per line
        for mark in ("# ", "- ", "1. "):
            assert a.startswith(mark) == b.startswith(mark)  # same markdown marks
    assert "chain" not in text and "structure" not in text.lower()


def test_null_filler_has_no_letters_and_filler_is_deterministic():
    from engine.agent import filler_cards
    card = [("e1", "T", _CARD)]
    null = filler_cards(card, "null")[0][2]
    assert not any(ch.isalpha() for ch in null)
    assert filler_cards(card, "null") == filler_cards(card, "null")
    assert filler_cards(card, "placebo") == filler_cards(card, "placebo")


def test_unknown_filler_is_refused():
    from engine.agent import filler_cards
    with pytest.raises(ValueError):
        filler_cards([("e1", "T", "x")], "bogus")
