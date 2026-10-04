"""Modal Sandbox backend.

Same contract as the local executor, with the isolation actually enforced by the
platform rather than approximated in-process: `block_network=True` means no
egress at all, the dataset volume is mounted read-only, and the sandbox is torn
down after the experiment.

STATUS: written against Modal's documented Sandbox API but not yet executed -
no Modal credentials were available on the development machine. The local
backend is the tested path; see api/modal_app.py.
"""
from __future__ import annotations

import time
from pathlib import Path

import modal

from .base import ExecResult

PREAMBLE = """
import os, sys
os.chdir("/work")
sys.path.insert(0, "/work")
try:
    import matplotlib
    matplotlib.use("Agg")
except Exception:
    pass
"""


class ModalExecutor:
    def __init__(self, name: str = "sandbox", app_name: str = "falsifylab",
                 timeout_s: int = 600, cpu: float = 2.0, memory_mb: int = 4096):
        self.name = name
        self.app_name = app_name
        self.timeout_s = timeout_s
        self.cpu = cpu
        self.memory_mb = memory_mb
        self._sb: modal.Sandbox | None = None

    def start(self) -> None:
        from api.modal_app import sandbox_image

        app = modal.App.lookup(self.app_name, create_if_missing=True)
        self._sb = modal.Sandbox.create(
            app=app,
            image=sandbox_image,
            # No egress: the agent cannot fetch the answer, and the scorer
            # cannot leak the ground truth.
            block_network=True,
            timeout=self.timeout_s,
            cpu=self.cpu,
            memory=self.memory_mb,
            workdir="/work",
        )
        self._sb.exec("mkdir", "-p", "/work", "/data").wait()

    @property
    def sb(self) -> modal.Sandbox:
        if self._sb is None:
            raise RuntimeError("executor not started")
        return self._sb

    def close(self) -> None:
        if self._sb is not None:
            try:
                self._sb.terminate()
            finally:
                self._sb = None

    def __enter__(self) -> "ModalExecutor":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- filesystem ----------------------------------------------------
    def put_file(self, rel_path: str, content: bytes, read_only: bool = False) -> None:
        dest = f"/{rel_path.lstrip('/')}"
        self.sb.exec("mkdir", "-p", str(Path(dest).parent)).wait()
        with self.sb.open(dest, "wb") as fh:
            fh.write(content)
        if read_only:
            self.sb.exec("chmod", "444", dest).wait()

    def put_dir(self, src: Path, rel_dest: str, read_only: bool = False) -> None:
        for p in sorted(Path(src).rglob("*")):
            if p.is_file():
                rel = p.relative_to(src)
                self.put_file(f"{rel_dest}/{rel}", p.read_bytes(), read_only=read_only)

    def read_file(self, rel_path: str) -> str:
        dest = f"/{rel_path.lstrip('/')}"
        try:
            with self.sb.open(dest, "r") as fh:
                return fh.read()
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise FileNotFoundError(f"{rel_path}: {exc}") from exc

    def list_files(self, rel_path: str = ".") -> list[str]:
        base = "/" if rel_path in (".", "") else f"/{rel_path.lstrip('/')}"
        proc = self.sb.exec("find", base, "-type", "f",
                            "-not", "-path", "*/proc/*", "-not", "-path", "*/sys/*",
                            "-not", "-path", "/usr/*", "-not", "-path", "/lib/*",
                            "-not", "-path", "/bin/*", "-not", "-path", "/sbin/*",
                            "-not", "-path", "/etc/*", "-not", "-path", "/var/*")
        out = proc.stdout.read()
        proc.wait()
        return [line.lstrip("/") for line in out.splitlines() if line.strip()]

    @property
    def root(self) -> str:
        return "/"

    # ---- execution -----------------------------------------------------
    def run_python(self, code: str, timeout_s: int = 60) -> ExecResult:
        script = "/work/_snippet.py"
        with self.sb.open(script, "w") as fh:
            fh.write(PREAMBLE + "\n" + code)
        before = set(self._figures())
        t0 = time.time()
        proc = self.sb.exec("timeout", str(timeout_s), "python", script,
                            workdir="/work")
        stdout = proc.stdout.read()
        stderr = proc.stderr.read()
        proc.wait()
        dt = time.time() - t0
        rc = proc.returncode
        return ExecResult(
            ok=rc == 0, stdout=stdout, stderr=stderr, exit_code=rc,
            duration_s=dt,
            timed_out=rc == 124,          # `timeout` reports 124 on expiry
            figures=sorted(set(self._figures()) - before),
        )

    def _figures(self) -> list[str]:
        proc = self.sb.exec("bash", "-lc",
                            "ls /work/*.png /work/*.svg /work/*.jpg 2>/dev/null || true")
        out = proc.stdout.read()
        proc.wait()
        return [Path(p).name for p in out.split() if p.strip()]
