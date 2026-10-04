"""Local sandbox: a throwaway directory plus a hardened subprocess.

This is not a security boundary the way a container is - it is the backend that
runs on a laptop with no cloud credentials. It enforces the same *contract* as
the Modal backend (no network, read-only datasets, wall-clock timeout, memory
cap) so an experiment that passes here behaves the same on Modal.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .base import ExecResult

# Injected ahead of every snippet. Blocks outbound sockets and DNS so an
# experiment cannot quietly fetch the answer, and caps address space.
PREAMBLE = r'''
import os, sys, socket, resource, builtins

# --- audit trace ---------------------------------------------------------
# Interpreter audit hooks (PEP 578) report what the code actually did, whatever
# it is called and however the path was built. Records go to a file descriptor
# the parent opened, not to a path the snippet could just as easily open. This
# is evidence, not a boundary: hooks cannot be removed, but a determined
# adversary could still write to the descriptor, so the auditor treats the
# trace as a record of attempts.
_TRACE_EMIT = None


def _install_trace():
    global _TRACE_EMIT
    import json as _json
    fd = int(os.environ.get("FL_TRACE_FD", "-1"))
    if fd < 0:
        return
    root = os.path.realpath(os.environ["FL_ROOT"])
    # The repository holds the answer keys and scorers. Anything under it is
    # refused (and recorded); other paths outside the sandbox are only recorded.
    protected = tuple(p for p in os.environ.get("FL_PROTECTED", "").split(os.pathsep) if p)
    system = tuple({os.path.realpath(p) for p in
                    (sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix)})
    seen, state = set(), {"busy": False, "n": 0}

    def under(path, base):
        return path == base or path.startswith(base + os.sep)

    def emit(rec):
        key = _json.dumps(rec, sort_keys=True, default=str)
        if key in seen or state["n"] >= 400:
            return
        seen.add(key)
        state["n"] += 1
        os.write(fd, (key + "\n").encode())

    def hook(event, args):
        if state["busy"]:
            return
        state["busy"] = True
        try:
            if event in ("open", "os.listdir", "os.scandir", "os.remove",
                         "os.rename", "os.rmdir", "os.mkdir", "shutil.rmtree",
                         "shutil.copyfile", "shutil.move"):
                raw = args[0]
                if raw is None:
                    raw = "."
                if isinstance(raw, int):
                    return
                path = os.path.realpath(os.fsdecode(raw))
                if any(under(path, b) for b in system):
                    return
                if under(path, root):
                    return
                if any(under(path, b) for b in protected):
                    emit({"kind": "fs", "event": event, "path": path, "blocked": True})
                    raise PermissionError(
                        "access outside the experiment sandbox is not permitted")
                emit({"kind": "fs", "event": event, "path": path})
            elif event.startswith("socket.") and event.split(".", 1)[1] in (
                    "connect", "bind", "getaddrinfo", "gethostbyname",
                    "gethostbyname_ex", "gethostbyaddr", "sendto"):
                emit({"kind": "net", "event": event,
                      "target": repr(args[1] if len(args) > 1 else args)[:200]})
            elif event in ("subprocess.Popen", "os.system", "os.exec",
                           "os.posix_spawn", "os.spawn", "os.fork",
                           "os.forkpty"):
                emit({"kind": "proc", "event": event,
                      "target": repr(args[:2])[:200]})
            elif event == "ctypes.dlopen":
                raw = args[0]
                if raw is None:        # dlopen(None) is the interpreter itself
                    return
                path = os.path.realpath(os.fsdecode(raw)) if isinstance(raw, (str, bytes)) else str(raw)
                if not any(under(path, b) for b in system):
                    emit({"kind": "proc", "event": event, "target": path})
        except PermissionError:
            raise
        except Exception:
            pass
        finally:
            state["busy"] = False

    _TRACE_EMIT = emit
    sys.addaudithook(hook)

_install_trace()
_MEM_BYTES = int(os.environ.get("FL_MEM_BYTES", str(2 * 1024 ** 3)))
try:
    resource.setrlimit(resource.RLIMIT_AS, (_MEM_BYTES, _MEM_BYTES))
except (ValueError, OSError):
    pass

class _NetworkBlocked(OSError):
    """Raised instead of opening a socket: attempts are visible in stderr."""

def _blocked(*a, **k):
    # The sandbox refuses before the interpreter would raise its own audit
    # event, so the attempt is recorded here as well.
    if _TRACE_EMIT is not None:
        _TRACE_EMIT({"kind": "net", "event": "socket.blocked",
                     "target": repr(a[:1])[:200]})
    raise _NetworkBlocked(
        "network access is disabled inside the experiment sandbox"
    )

# Subclass rather than replace socket.socket: the stdlib's ssl module builds
# SSLSocket on top of it at import time, so swapping in a plain function makes
# `import ssl` fail with a confusing TypeError instead of a clear refusal.
_RealSocket = socket.socket

class _BlockedSocket(_RealSocket):
    def connect(self, *a, **k):
        _blocked()
    def connect_ex(self, *a, **k):
        _blocked()
    def sendto(self, *a, **k):
        _blocked()
    def sendall(self, *a, **k):
        _blocked()

socket.socket = _BlockedSocket
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
socket.gethostbyname = _blocked
socket.gethostbyname_ex = _blocked

try:
    import matplotlib
    matplotlib.use("Agg")
except Exception:
    pass
os.chdir(os.environ["FL_WORKDIR"])
sys.path.insert(0, os.environ["FL_WORKDIR"])
'''


_REPO_ROOT = Path(__file__).resolve().parent.parent


class LocalExecutor:
    def __init__(self, name: str = "sandbox", mem_bytes: int = 2 * 1024 ** 3,
                 python: str | None = None):
        self.name = name
        self.mem_bytes = mem_bytes
        self.python = python or sys.executable
        self._dir: Path | None = None
        self._readonly: set[str] = set()

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        # resolve() matters on macOS, where the temp dir lives under a /var ->
        # /private/var symlink: without it, paths built by rglob() and paths
        # built from self.root disagree and relative_to() raises.
        self._dir = Path(tempfile.mkdtemp(prefix=f"falsifylab-{self.name}-")).resolve()
        (self._dir / "work").mkdir()
        (self._dir / "data").mkdir()

    @property
    def root(self) -> Path:
        if self._dir is None:
            raise RuntimeError("executor not started")
        return self._dir

    def close(self) -> None:
        if self._dir and self._dir.exists():
            # chmod back so rmtree can remove read-only dataset files
            for p in self._dir.rglob("*"):
                try:
                    p.chmod(0o700)
                except OSError:
                    pass
            shutil.rmtree(self._dir, ignore_errors=True)
        self._dir = None

    def __enter__(self) -> "LocalExecutor":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- filesystem ------------------------------------------------------
    def put_file(self, rel_path: str, content: bytes, read_only: bool = False) -> None:
        dest = self.root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        if read_only:
            dest.chmod(0o444)
            self._readonly.add(rel_path)

    def put_dir(self, src: Path, rel_dest: str, read_only: bool = False) -> None:
        dest = self.root / rel_dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, dirs_exist_ok=True)
        if read_only:
            for p in dest.rglob("*"):
                if p.is_file():
                    p.chmod(0o444)

    def read_file(self, rel_path: str) -> str:
        p = (self.root / rel_path).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("path escapes the sandbox")
        if not p.exists():
            raise FileNotFoundError(rel_path)
        return p.read_text(encoding="utf-8", errors="replace")

    def list_files(self, rel_path: str = ".") -> list[str]:
        root = self.root.resolve()
        base = (root / rel_path).resolve()
        if not base.exists():
            return []
        out = []
        for p in sorted(base.rglob("*")):
            if p.is_file():
                out.append(str(p.resolve().relative_to(root)))
        return out

    # ---- execution -------------------------------------------------------
    def run_python(self, code: str, timeout_s: int = 60) -> ExecResult:
        workdir = self.root / "work"
        script = workdir / "_snippet.py"
        script.write_text(PREAMBLE + "\n" + code, encoding="utf-8")
        before = _figure_set(workdir)
        t_start = time.time()
        trace_fd, trace_path = tempfile.mkstemp(prefix="falsifylab-trace-")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(workdir),
            "FL_WORKDIR": str(workdir),
            "FL_ROOT": str(self.root),
            "FL_PROTECTED": str(_REPO_ROOT),
            "FL_TRACE_FD": str(trace_fd),
            "FL_MEM_BYTES": str(self.mem_bytes),
            "MPLBACKEND": "Agg",
            "PYTHONDONTWRITEBYTECODE": "1",
            # deliberately NOT inherited: ANTHROPIC_API_KEY and friends
        }
        t0 = time.time()
        try:
            proc = subprocess.run(
                [self.python, "-I", str(script)],
                cwd=workdir, env=env, capture_output=True, text=True,
                timeout=timeout_s, pass_fds=(trace_fd,),
            )
            dt = time.time() - t0
            figs = sorted(_figure_set(workdir) - before)
            return ExecResult(
                ok=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                duration_s=dt,
                figures=figs,
                trace=_read_trace(trace_path),
                files_written=_files_written(workdir, t_start),
            )
        except subprocess.TimeoutExpired:
            return ExecResult(
                ok=False, stdout="", stderr="", exit_code=-1,
                duration_s=time.time() - t0, timed_out=True,
                trace=_read_trace(trace_path),
            )
        finally:
            os.close(trace_fd)
            try:
                os.unlink(trace_path)
            except OSError:
                pass


def _figure_set(workdir: Path) -> set[str]:
    return {
        str(p.relative_to(workdir))
        for ext in ("png", "svg", "jpg")
        for p in workdir.glob(f"*.{ext}")
    }


def _read_trace(path: str) -> list[dict]:
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return out


_TEXT_SUFFIXES = {".csv", ".tsv", ".json", ".txt", ".md", ".log"}


def _files_written(workdir: Path, since: float, per_file: int = 6000,
                   total: int = 12000) -> dict[str, str]:
    """Text of files the snippet created or changed, for answer provenance."""
    out: dict[str, str] = {}
    budget = total
    for p in sorted(workdir.rglob("*")):
        if budget <= 0:
            break
        if not p.is_file() or p.name == "_snippet.py" or p.suffix not in _TEXT_SUFFIXES:
            continue
        try:
            if p.stat().st_mtime < since:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")[:min(per_file, budget)]
        except OSError:
            continue
        out[str(p.relative_to(workdir))] = text
        budget -= len(text)
    return out
