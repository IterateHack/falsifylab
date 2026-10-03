"""The sandbox contract shared by the local and Modal backends."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ExecResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_s: float
    timed_out: bool = False
    figures: list[str] = field(default_factory=list)   # paths inside the workspace

    def as_tool_result(self, max_chars: int = 6000) -> str:
        parts = []
        if self.timed_out:
            parts.append(f"[TIMED OUT after {self.duration_s:.1f}s - no output captured]")
        if self.stdout.strip():
            parts.append("stdout:\n" + _clip(self.stdout, max_chars))
        if self.stderr.strip():
            parts.append("stderr:\n" + _clip(self.stderr, max_chars // 2))
        if self.figures:
            parts.append("figures saved: " + ", ".join(self.figures))
        if not parts:
            parts.append("(no output - remember to print() your results)")
        return "\n\n".join(parts)


def _clip(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    half = n // 2
    return s[:half] + f"\n... [{len(s) - n} chars elided] ...\n" + s[-half:]


class Executor(Protocol):
    """A sandbox the agent (or the scorer) runs code in.

    Two instances are used per experiment and they never share a filesystem:
    sandbox A holds the agent workspace and the public datasets; sandbox B holds
    the scorer and the ground truth. That separation is what makes the score
    something the agent cannot reach around (plan section 5.4).
    """

    def start(self) -> None: ...
    def put_file(self, rel_path: str, content: bytes, read_only: bool = False) -> None: ...
    def put_dir(self, src: Path, rel_dest: str, read_only: bool = False) -> None: ...
    def read_file(self, rel_path: str) -> str: ...
    def list_files(self, rel_path: str = ".") -> list[str]: ...
    def run_python(self, code: str, timeout_s: int) -> ExecResult: ...
    def close(self) -> None: ...
