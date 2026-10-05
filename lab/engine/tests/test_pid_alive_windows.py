"""The Windows branch of the run-lock liveness probe, on any host.

The kernel32 calls are replaced by a fake, so the mapping from what Windows
reports to alive / dead / unknown is pinned on the Linux CI job too. The real
calls run in test_engine.py::test_a_second_writer_is_refused on the Windows job.
"""
import os
import sys

import pytest

from engine import events

ACCESS = events._PROCESS_QUERY_LIMITED_INFORMATION | events._SYNCHRONIZE
PROCESS_TERMINATE = 0x0001
WAIT_FAILED = 0xFFFFFFFF


class FakeKernel32:
    def __init__(self, handle=1234, open_error=0, wait_state=events._WAIT_TIMEOUT,
                 wait_error=0):
        self.handle, self.open_error = handle, open_error
        self.wait_state, self.wait_error = wait_state, wait_error
        self.opened, self.waited, self.closed = [], [], []

    def open_process(self, access, pid):
        self.opened.append((access, pid))
        return self.handle

    def wait(self, handle, timeout_ms):
        self.waited.append((handle, timeout_ms))
        return self.wait_state

    def close(self, handle):
        self.closed.append(handle)

    def last_error(self):
        return self.wait_error if self.handle else self.open_error


def test_only_query_and_wait_rights_are_requested():
    k = FakeKernel32()
    events._pid_alive_windows(42, k)
    assert k.opened == [(ACCESS, 42)]
    assert not ACCESS & PROCESS_TERMINATE


def test_a_running_process_is_alive():
    k = FakeKernel32(wait_state=events._WAIT_TIMEOUT)
    assert events._pid_alive_windows(42, k) is True
    assert k.waited == [(1234, 0)]          # a zero timeout: probe, never block
    assert k.closed == [1234]


def test_an_exited_process_whose_handle_is_still_open_is_dead():
    k = FakeKernel32(wait_state=events._WAIT_OBJECT_0)
    assert events._pid_alive_windows(42, k) is False
    assert k.closed == [1234]


def test_no_process_with_that_pid_is_dead():
    k = FakeKernel32(handle=None, open_error=events._ERROR_INVALID_PARAMETER)
    assert events._pid_alive_windows(42, k) is False
    assert k.closed == []


def test_access_denied_means_the_process_exists():
    k = FakeKernel32(handle=None, open_error=events._ERROR_ACCESS_DENIED)
    assert events._pid_alive_windows(42, k) is True


@pytest.mark.parametrize("k", [
    FakeKernel32(handle=None, open_error=1450),            # ERROR_NO_SYSTEM_RESOURCES
    FakeKernel32(wait_state=WAIT_FAILED, wait_error=6),     # ERROR_INVALID_HANDLE
], ids=["open_failed", "wait_failed"])
def test_an_answer_windows_does_not_give_is_raised_not_defaulted(k):
    with pytest.raises(OSError, match="cannot tell whether the lock owner is alive"):
        events._pid_alive_windows(42, k)
    assert k.closed == ([1234] if k.handle else [])


def test_on_windows_the_lock_never_calls_os_kill(monkeypatch, tmp_path):
    """os.kill(pid, 0) on Windows sends CTRL_C_EVENT to a process group."""
    def no_kill(*a):
        raise AssertionError("os.kill is not a liveness probe on Windows")
    k = FakeKernel32(wait_state=events._WAIT_TIMEOUT)
    monkeypatch.setattr(os, "kill", no_kill)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(events, "_kernel32", lambda: k)
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "run.lock").write_text('{"pid": 42, "run_id": "r"}')
    with pytest.raises(events.RunLockedError):
        events.EventLog(tmp_path / "run", "r")
    assert k.opened == [(ACCESS, 42)]
