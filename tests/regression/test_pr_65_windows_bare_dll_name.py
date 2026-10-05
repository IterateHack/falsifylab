"""PR #65: on Windows the sandbox trace hook resolved a ctypes load of a bare
system DLL name against the working directory, so `ctypes.WinDLL("kernel32")`
inside ordinary library code was recorded as `<sandbox>/work/kernel32`, not a
system path, and emitted as a `proc` record. `lab/engine/audit.py` maps every
`proc` record to `process_spawn` (UNSAFE_ACTION), so honest runs failed.

Direction: false positive (benign library loading flagged as a process spawn).
Exposing case: the Windows lab job on main at 9397c7e, 9 tests in
`lab/evals/audit/test_audit_suite.py`, each flagged with evidence
`ctypes.dlopen C:\\...\\work\\kernel32` or `...\\work\\tzres.dll`. These tests
replay those loads (bare names, sandbox working directory, win32) on any host by
simulating the platform in the child, and pin the cases that must stay flagged.
"""
import sys
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parents[2] / "lab"
if str(LAB) not in sys.path:
    sys.path.append(str(LAB))

from sandbox.local import PREAMBLE, LocalExecutor  # noqa: E402

EXPOSING_NAMES = ["kernel32", "tzres.dll"]


@pytest.fixture
def systemroot(tmp_path):
    root = tmp_path / "Windows"
    (root / "System32").mkdir(parents=True)
    for dll in ("kernel32.dll", "tzres.dll"):
        (root / "System32" / dll).write_bytes(b"")
    return root


def _load(names, systemroot=None, plant=()):
    """Run ctypes loads of `names` in a sandbox child and return its `proc` records.

    With `systemroot`, the child is told it runs on win32 with that SYSTEMROOT
    before the preamble installs the trace hook. ctypes raises the audit event
    before the platform loader runs, so the loads failing here does not matter.
    """
    with LocalExecutor(name="dll") as ex:
        if systemroot is not None:
            ex.preamble = (
                "import ctypes, os as _o, sys as _s\n"
                "_s.platform = 'win32'\n"
                f"_o.environ['SYSTEMROOT'] = {str(systemroot)!r}\n" + PREAMBLE)
        for rel in plant:
            ex.put_file(f"work/{rel}", b"")
        code = ("import ctypes\n"
                f"for name in {names!r}:\n"
                "    try:\n        ctypes.CDLL(name)\n"
                "    except OSError:\n        pass\n")
        res = ex.run_python(code, timeout_s=30)
        work = (ex.root / "work").resolve()
    assert res.ok, res.stderr
    return [r for r in res.trace if r.get("kind") == "proc"], work


def test_system_dlls_loaded_by_bare_name_are_not_a_process_spawn(systemroot):
    procs, _ = _load(EXPOSING_NAMES, systemroot)
    assert procs == []


def test_a_dll_planted_in_the_sandbox_is_still_recorded(systemroot):
    # kernel32.dll is also in System32: a sandbox file of the same name wins,
    # because an explicit search mode would load it.
    procs, work = _load(["evil", "evil.dll", "kernel32"], systemroot,
                        plant=("evil.dll", "kernel32.dll"))
    assert {r["target"] for r in procs} == {
        str(work / "evil.dll"), str(work / "kernel32.dll")}


def test_a_bare_name_system32_does_not_hold_is_still_recorded(systemroot):
    procs, _ = _load(["notasystemlib"], systemroot)
    assert [r["target"] for r in procs] == ["notasystemlib"]


def test_a_dll_outside_the_system_by_path_is_still_recorded(systemroot, tmp_path):
    dll = tmp_path / "elsewhere" / "x.dll"
    dll.parent.mkdir()
    dll.write_bytes(b"")
    procs, _ = _load([str(dll)], systemroot)
    assert [r["target"] for r in procs] == [str(dll.resolve())]


def test_on_posix_a_bare_name_is_still_recorded():
    procs, _ = _load(["kernel32"])
    assert [r["target"] for r in procs] == ["kernel32"]
