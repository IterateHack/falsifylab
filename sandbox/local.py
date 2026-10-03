"""Local sandbox: a throwaway directory plus a hardened subprocess.

This is not a security boundary the way a container is - it is the backend that
runs on a laptop with no cloud credentials. It enforces the same *contract* as
the Modal backend (no network, read-only datasets, wall-clock timeout, memory
cap) so an experiment that passes here behaves the same on Modal.
"""
from __future__ import annotations

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
_MEM_BYTES = int(os.environ.get("FL_MEM_BYTES", str(2 * 1024 ** 3)))
try:
    resource.setrlimit(resource.RLIMIT_AS, (_MEM_BYTES, _MEM_BYTES))
except (ValueError, OSError):
    pass

class _NetworkBlocked(OSError):
    """Raised instead of opening a socket: attempts are visible in stderr."""

def _blocked(*a, **k):
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
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(workdir),
            "FL_WORKDIR": str(workdir),
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
                timeout=timeout_s,
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
            )
        except subprocess.TimeoutExpired:
            return ExecResult(
                ok=False, stdout="", stderr="", exit_code=-1,
                duration_s=time.time() - t0, timed_out=True,
            )


def _figure_set(workdir: Path) -> set[str]:
    return {
        str(p.relative_to(workdir))
        for ext in ("png", "svg", "jpg")
        for p in workdir.glob(f"*.{ext}")
    }
