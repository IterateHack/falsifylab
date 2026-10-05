"""The local sandbox on a host without POSIX descriptor passing or setrlimit.

Live mode crashed on Windows at the first `run_python` with
`AssertionError: pass_fds not supported on Windows`, and the preamble's
`import resource` would have killed the child next. These tests exercise that
code path on a POSIX machine by simulating the platform: the trace, the
protected-path refusal and the network block must all survive, and a memory
cap that cannot be applied must be recorded rather than dropped.

They cannot prove the fix on Windows itself; see the PR for the commands to
run there.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import sandbox.local as local
from engine.events import EventLog
from engine.notebook import NotebookEntry
from engine.specs import load_curriculum
from engine.tools import ToolContext, dispatch
from sandbox import get_executor
from sandbox.local import PREAMBLE, LocalExecutor, child_env

LAB = Path(__file__).resolve().parents[2]
CURRICULUM = LAB / "curricula" / "glp1r"
ANSWER_KEY = CURRICULUM / "private" / "exp2.json"

# What `import resource` does on Windows: ImportError. Prepended to the
# preamble so the shipped text is exercised unchanged.
NO_RESOURCE = "import sys as _s; _s.modules['resource'] = None\n"


def _windows_subprocess_run(real):
    """`subprocess.run` as Windows behaves: descriptor passing is refused."""
    def run(*args, **kwargs):
        if kwargs.get("pass_fds"):
            raise AssertionError("pass_fds not supported on Windows.")
        return real(*args, **kwargs)
    return run


@pytest.fixture
def windows_like(monkeypatch):
    """A local executor whose child has no `resource` module and whose parent
    may not pass descriptors - the two things that broke on Windows."""
    monkeypatch.setattr(local.subprocess, "run",
                        _windows_subprocess_run(subprocess.run))
    ex = LocalExecutor(name="winlike")
    ex.preamble = NO_RESOURCE + PREAMBLE
    ex.start()
    yield ex
    ex.close()


def test_run_python_does_not_need_descriptor_passing(windows_like):
    res = windows_like.run_python("print(6 * 7)", timeout_s=20)
    assert res.ok, res.stderr
    assert "42" in res.stdout


def test_the_trace_still_records_what_the_code_did(windows_like, tmp_path):
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x")
    res = windows_like.run_python(f"print(open({str(outside)!r}).read())", timeout_s=20)
    assert res.ok, res.stderr
    fs = [r for r in res.trace if r.get("kind") == "fs"]
    assert any(r["path"] == str(outside.resolve()) for r in fs), res.trace
    # the limits record is the sandbox's own report, not evidence about the code
    assert not any(r.get("kind") == "limits" for r in res.trace)


def test_the_answer_key_is_still_refused(windows_like):
    res = windows_like.run_python(
        f"print(open({str(ANSWER_KEY)!r}).read()[:20])", timeout_s=20)
    assert not res.ok, "the read must be refused, not just logged"
    assert "PermissionError" in res.stderr
    assert "exp2" not in res.stdout
    blocked = [r for r in res.trace if r.get("kind") == "fs" and r.get("blocked")]
    assert blocked and blocked[0]["path"] == str(ANSWER_KEY.resolve())


def test_the_network_is_still_blocked(windows_like):
    res = windows_like.run_python(
        "import socket\n"
        "try:\n    socket.create_connection(('example.com', 80), 1)\n"
        "except Exception as e:\n    print(type(e).__name__, e)",
        timeout_s=20)
    assert res.ok, res.stderr
    assert "network access is disabled" in res.stdout
    assert any(r.get("kind") == "net" for r in res.trace), res.trace


def test_a_memory_cap_that_cannot_be_applied_is_recorded(windows_like):
    res = windows_like.run_python("print('hi')", timeout_s=20)
    assert res.ok, res.stderr
    assert res.memory_cap_enforced is False
    assert "unavailable" in res.limits_note and "resource" in res.limits_note


@pytest.mark.skipif(sys.platform == "win32", reason="setrlimit is POSIX-only")
def test_on_posix_the_memory_cap_is_reported_enforced():
    with LocalExecutor(name="posix") as ex:
        res = ex.run_python("print('hi')", timeout_s=20)
    assert res.ok, res.stderr
    assert res.memory_cap_enforced is True and res.limits_note == ""
    assert not any(r.get("kind") == "limits" for r in res.trace)


def test_a_child_that_never_reports_is_unconfirmed_not_enforced():
    with LocalExecutor(name="silent") as ex:
        ex.preamble = ""          # no preamble at all: nothing is reported
        res = ex.run_python("print('hi')", timeout_s=20)
    assert res.ok
    assert res.memory_cap_enforced is None
    assert "not reported" in res.limits_note


def test_the_trace_file_is_not_left_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(local.tempfile, "tempdir", str(tmp_path))
    with LocalExecutor(name="tidy") as ex:
        ex.run_python("print(1)", timeout_s=20)
        ex.run_python("while True: pass", timeout_s=1)
    assert not list(tmp_path.glob("falsifylab-trace-*"))


# --- the child environment ------------------------------------------------
def test_windows_child_env_carries_systemroot_and_the_real_path(tmp_path):
    source = {
        "PATH": r"C:\Python312;C:\Windows\system32",
        "SYSTEMROOT": r"C:\Windows",
        "TEMP": r"C:\Users\don\AppData\Local\Temp",
        "ANTHROPIC_API_KEY": "sk-not-for-the-child",
        "HOME": r"C:\Users\don",
    }
    env = child_env(tmp_path / "work", tmp_path, LAB, "trace.jsonl", 123,
                    platform="win32", source=source)
    assert env["SYSTEMROOT"] == r"C:\Windows"
    assert env["PATH"] == source["PATH"]
    assert env["TEMP"] == source["TEMP"]
    assert env["USERPROFILE"] == env["HOME"] == str(tmp_path / "work")
    assert env["FL_TRACE_PATH"] == "trace.jsonl"
    assert "FL_TRACE_FD" not in env
    assert "ANTHROPIC_API_KEY" not in env


def test_posix_child_env_is_unchanged_in_shape(tmp_path):
    source = {"PATH": "/usr/bin:/bin", "SYSTEMROOT": "leak?",
              "ANTHROPIC_API_KEY": "sk-not-for-the-child"}
    env = child_env(tmp_path / "work", tmp_path, LAB, "t", 1,
                    platform="linux", source=source)
    assert "SYSTEMROOT" not in env and "USERPROFILE" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["FL_PROTECTED"] == str(LAB)


def test_no_code_path_passes_descriptors():
    src = (LAB / "sandbox" / "local.py").read_text()
    assert "pass_fds" not in src
    assert "FL_TRACE_FD" not in src


# --- the run record ---------------------------------------------------------
def _open_gate(ctx: ToolContext) -> None:
    dispatch(ctx, "write_notebook_section", {
        "section": "hypothesis_and_prediction", "text": "prediction",
        "confidence": 0.5})
    dispatch(ctx, "write_notebook_section", {"section": "plan", "text": "plan"})


def test_an_unenforced_cap_reaches_the_event_log_and_the_notebook(tmp_path, monkeypatch):
    monkeypatch.setattr(local.subprocess, "run",
                        _windows_subprocess_run(subprocess.run))
    spec = load_curriculum(CURRICULUM).experiments[0]
    log = EventLog(tmp_path / "run", "run_test")
    ex = LocalExecutor(name="winlike")
    ex.preamble = NO_RESOURCE + PREAMBLE
    ex.start()
    try:
        entry = NotebookEntry(spec.id, spec.title, spec.order, model="m")
        ctx = ToolContext(spec=spec, entry=entry, log=log, executor=ex, earned_lessons=[])
        _open_gate(ctx)
        text, is_error = dispatch(ctx, "run_python", {"code": "print(1)"})
        assert not is_error, text
    finally:
        ex.close()
    run = next(e for e in log.all()
               if e.type == "tool_result" and e.payload.get("tool") == "run_python")
    assert run.payload["memory_cap_enforced"] is False
    assert "unavailable" in run.payload["limits_note"]
    assert entry.unenforced_limits == [run.payload["limits_note"]]
    md = entry.to_markdown()
    assert "not enforced on this host" in md and "not comparable" in md
    assert entry.to_dict()["unenforced_limits"] == entry.unenforced_limits


def test_an_enforced_cap_leaves_the_notebook_clean(tmp_path):
    spec = load_curriculum(CURRICULUM).experiments[0]
    log = EventLog(tmp_path / "run", "run_test")
    ex = get_executor("local", name="posix")
    ex.start()
    try:
        entry = NotebookEntry(spec.id, spec.title, spec.order, model="m")
        ctx = ToolContext(spec=spec, entry=entry, log=log, executor=ex, earned_lessons=[])
        _open_gate(ctx)
        dispatch(ctx, "run_python", {"code": "print(1)"})
    finally:
        ex.close()
    run = next(e for e in log.all()
               if e.type == "tool_result" and e.payload.get("tool") == "run_python")
    assert run.payload["memory_cap_enforced"] is (os.name == "posix")
    if os.name == "posix":
        assert entry.unenforced_limits == []
        assert "not enforced" not in entry.to_markdown()
