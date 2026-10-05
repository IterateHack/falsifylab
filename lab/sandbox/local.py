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
from typing import Mapping

from .base import ExecResult

# Injected ahead of every snippet. Blocks outbound sockets and DNS so an
# experiment cannot quietly fetch the answer, and caps address space.
PREAMBLE = r'''
import os, sys, socket, builtins
try:
    import resource
except ImportError:          # Windows has no resource module
    resource = None

# --- audit trace ---------------------------------------------------------
# Interpreter audit hooks (PEP 578) report what the code actually did, whatever
# it is called and however the path was built. Records go to a trace file the
# parent created outside the sandbox and names in FL_TRACE_PATH; it is opened
# here before the hook is installed, so the open is not itself traced. A path
# rather than an inherited descriptor because descriptor passing is POSIX-only.
# This is evidence, not a boundary: hooks cannot be removed, but a determined
# adversary could still write to the file, so the auditor treats the trace as
# a record of attempts.
_TRACE_EMIT = None


def _install_trace():
    global _TRACE_EMIT
    import json as _json
    trace_path = os.environ.get("FL_TRACE_PATH", "")
    if not trace_path:
        return
    out = open(trace_path, "a", encoding="utf-8")
    # Comparisons use normcase so a Windows path differing only in case
    # cannot slip past; the recorded path keeps its real spelling.
    norm = os.path.normcase
    root = norm(os.path.realpath(os.environ["FL_ROOT"]))
    # The repository holds the answer keys and scorers. Anything under it is
    # refused (and recorded); other paths outside the sandbox are only recorded.
    protected = tuple(norm(os.path.realpath(p)) for p in
                      os.environ.get("FL_PROTECTED", "").split(os.pathsep) if p)
    system = tuple({norm(os.path.realpath(p)) for p in
                    (sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix)})
    seen, state = set(), {"busy": False, "n": 0}
    windows = sys.platform == "win32"
    system32 = (norm(os.path.join(os.environ["SYSTEMROOT"], "System32"))
                if windows and os.environ.get("SYSTEMROOT") else "")

    def dll_target(name):
        """What a ctypes load of `name` opens, and whether it is a system library.

        A name with a directory part is opened at that path. A bare name is not
        looked up in the working directory by the loader (ctypes' default
        search on Windows, dlopen on POSIX), so resolving it against the cwd
        mislabels `kernel32` as a file in the sandbox. A file of that name in
        the working directory is still reported, because an explicit search
        mode would load it; otherwise a bare name is a system library only if
        System32 holds it, and anything else is reported as given.
        """
        if os.path.dirname(name):
            return os.path.realpath(name), False
        candidates = [name]
        if windows and not os.path.splitext(name)[1]:
            candidates.append(name + ".dll")
        for cand in candidates:
            if os.path.exists(cand):
                return os.path.realpath(cand), False
        if system32:
            for cand in candidates:
                if os.path.exists(os.path.join(system32, cand)):
                    return os.path.join(system32, cand), True
        return name, False

    def under(path, base):
        path = norm(path)
        return path == base or path.startswith(base + os.sep)

    def emit(rec):
        key = _json.dumps(rec, sort_keys=True, default=str)
        if key in seen or state["n"] >= 400:
            return
        seen.add(key)
        state["n"] += 1
        out.write(key + "\n")
        out.flush()

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
                if isinstance(raw, (str, bytes)):
                    path, system_dll = dll_target(os.fsdecode(raw))
                else:
                    path, system_dll = str(raw), False
                if not system_dll and not any(under(path, b) for b in system):
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
# The address-space cap is POSIX-only (setrlimit). Where it cannot be applied
# the fact is recorded in the trace rather than dropped: a run without the cap
# is not comparable to one with it, and the run record has to say so.
_MEM_BYTES = int(os.environ.get("FL_MEM_BYTES", str(2 * 1024 ** 3)))
if resource is None:
    _MEM_CAP = "unavailable: no resource module on " + sys.platform
else:
    try:
        resource.setrlimit(resource.RLIMIT_AS, (_MEM_BYTES, _MEM_BYTES))
        _MEM_CAP = "enforced"
    except (ValueError, OSError) as _exc:
        _MEM_CAP = "failed: setrlimit %s on %s" % (type(_exc).__name__, sys.platform)
if _TRACE_EMIT is not None:
    _TRACE_EMIT({"kind": "limits", "memory_cap": _MEM_CAP,
                 "memory_bytes": _MEM_BYTES, "platform": sys.platform})

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


# Variables a Windows Python child needs from the parent to start at all.
# SYSTEMROOT is the known one (the interpreter fails to initialise without
# it); the rest are what the stdlib reaches for on that platform. Nothing
# here carries a secret.
_WINDOWS_PASSTHROUGH = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP")


def child_env(workdir: Path, root: Path, protected: Path, trace_path: str,
              mem_bytes: int, platform: str = sys.platform,
              source: Mapping[str, str] | None = None) -> dict[str, str]:
    """The scrubbed environment the snippet runs in.

    Built from scratch rather than copied, so ANTHROPIC_API_KEY and friends are
    never inherited. `platform` and `source` are parameters so the Windows
    branch can be exercised on a POSIX test machine.
    """
    src = os.environ if source is None else source
    env = {
        "PATH": src.get("PATH", "/usr/bin:/bin"),
        "HOME": str(workdir),
        "FL_WORKDIR": str(workdir),
        "FL_ROOT": str(root),
        "FL_PROTECTED": str(protected),
        "FL_TRACE_PATH": trace_path,
        "FL_MEM_BYTES": str(mem_bytes),
        "MPLBACKEND": "Agg",
        # One thread for every BLAS/OpenMP pool, on every platform. OpenBLAS
        # sizes its pool and per-thread buffers from the visible CPU count, which
        # can exhaust the FL_MEM_BYTES cap on import (#38); and thread count
        # changes reduction order, so one thread also keeps results reproducible.
        # OPENBLAS_NUM_THREADS: measured necessary — the pinned numpy/scipy wheels link
        #   OpenBLAS, and it outranks GOTO_/OPENBLAS_DEFAULT_ in OpenBLAS's own precedence.
        # OMP_NUM_THREADS: read by the pinned OpenBLAS, redundant under the above, kept so a
        #   future wheel that drops the OPENBLAS_ prefix is still covered.
        # MKL_NUM_THREADS, VECLIB_MAXIMUM_THREADS: unmeasured here — no MKL in the pinned
        #   wheels, and Accelerate only appears on macOS arm64. Set defensively: the failure
        #   they prevent is an honest run scored REWARD_HACK, and a no-op env var costs nothing.
        # All of these must be set before `import numpy`.
        # Measured for OpenBLAS: scipy_openblas_get_num_threads64_ returns 1 when the variable
        # is set before `import numpy` and this host's CPU count when set after. MKL and
        # Accelerate are assumed to behave the same way, which is their documented behaviour
        # but is not measured here.
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if platform == "win32":
        env["USERPROFILE"] = str(workdir)
        for key in _WINDOWS_PASSTHROUGH:
            if key in src:
                env[key] = src[key]
    return env


class LocalExecutor:
    # Class attribute so a test can prepend to it (e.g. to make `resource`
    # unimportable in the child) without touching the shipped preamble.
    preamble = PREAMBLE

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
        script.write_text(self.preamble + "\n" + code, encoding="utf-8")
        before = _figure_set(workdir)
        t_start = time.time()
        # The trace file lives outside the sandbox root, so the snippet has no
        # legitimate reason to open it; the child appends by path.
        trace_fd, trace_path = tempfile.mkstemp(prefix="falsifylab-trace-")
        os.close(trace_fd)
        env = child_env(workdir, self.root, _REPO_ROOT, trace_path, self.mem_bytes)
        t0 = time.time()
        try:
            proc = subprocess.run(
                [self.python, "-I", str(script)],
                cwd=workdir, env=env, capture_output=True, text=True,
                timeout=timeout_s,
            )
            dt = time.time() - t0
            figs = sorted(_figure_set(workdir) - before)
            trace, limits = _read_trace(trace_path)
            return ExecResult(
                ok=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                duration_s=dt,
                figures=figs,
                trace=trace,
                files_written=_files_written(workdir, t_start),
                **limits,
            )
        except subprocess.TimeoutExpired:
            trace, limits = _read_trace(trace_path)
            return ExecResult(
                ok=False, stdout="", stderr="", exit_code=-1,
                duration_s=time.time() - t0, timed_out=True,
                trace=trace, **limits,
            )
        finally:
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


def _read_trace(path: str) -> tuple[list[dict], dict]:
    """The audit trace, and the sandbox's own report of the limits it applied.

    The preamble writes one `kind: limits` record before any user code runs.
    It is split out here so the trace handed to the auditor holds only what
    the code did. No record at all means the child never got that far (or the
    preamble was replaced), and the cap is reported as unconfirmed, not as
    enforced.
    """
    out: list[dict] = []
    limits = {"memory_cap_enforced": None,
              "limits_note": "memory cap not reported by the sandbox"}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("kind") == "limits":
                    cap = str(rec.get("memory_cap", ""))
                    limits = {
                        "memory_cap_enforced": cap == "enforced",
                        "limits_note": "" if cap == "enforced"
                        else f"memory cap {cap}",
                    }
                else:
                    out.append(rec)
    except OSError:
        pass
    return out, limits


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
