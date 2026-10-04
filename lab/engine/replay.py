"""Counterfactual replay: does the answer depend on the data?

The agent's successful `run_python` calls are re-run, in order, in a fresh
sandbox - once on the original data (a control, to prove the code replays at
all), once on data with the signal destroyed (null), and optionally once on a
subsample (stability). If the submitted answer still appears in the output after
the signal is gone, it did not come from the data: it was hard-coded or recalled.

This is metamorphic testing in the style of null-defining perturbations for
agentic data science. The replay sandbox holds perturbed datasets only: no
ground truth, no network, never the agent's own sandbox.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from sandbox import get_executor

from .audit import AuditSpec, Call, fraction_present
from .specs import ExperimentSpec


# --------------------------------------------------------------------------
# perturbation ops (deterministic: seeds are part of the audit spec)
# --------------------------------------------------------------------------
def _split_csv(raw: bytes) -> tuple[str, list[str]]:
    lines = raw.decode("utf-8", errors="replace").splitlines()
    return lines[0], lines[1:]


def shuffle_column(raw: bytes, column: str, seed: int = 0) -> bytes:
    """Permute one column across rows, decoupling identity from evidence.

    Done on parsed rows so quoted commas survive.
    """
    import csv
    import io
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8", errors="replace"))))
    header, body = rows[0], rows[1:]
    if column not in header:
        raise ValueError(f"column {column!r} not in {header}")
    i = header.index(column)
    values = [r[i] for r in body]
    random.Random(seed).shuffle(values)
    for r, v in zip(body, values):
        r[i] = v
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    w.writerows(body)
    return out.getvalue().encode("utf-8")


def subsample(raw: bytes, frac: float = 0.8, seed: int = 0) -> bytes:
    header, body = _split_csv(raw)
    rng = random.Random(seed)
    keep = [ln for ln in body if rng.random() < frac]
    return ("\n".join([header] + keep) + "\n").encode("utf-8")


def translate_chain(raw: bytes, chains: list[str], dx: float = 1000.0) -> bytes:
    """Move whole chains far away so any contact computed from coordinates vanishes.

    mmCIF `_atom_site` rows are whitespace-delimited; the column order is read
    from the loop header rather than assumed.
    """
    lines = raw.decode("utf-8", errors="replace").splitlines()
    cols: list[str] = []
    out: list[str] = []
    for ln in lines:
        if ln.startswith("_atom_site."):
            cols.append(ln.strip().split(".", 1)[1])
            out.append(ln)
            continue
        if cols and (ln.startswith("ATOM") or ln.startswith("HETATM")):
            parts = ln.split()
            if len(parts) >= len(cols):
                asym = parts[cols.index("label_asym_id")]
                auth = parts[cols.index("auth_asym_id")] if "auth_asym_id" in cols else ""
                if asym in chains or auth in chains:
                    xi = cols.index("Cartn_x")
                    parts[xi] = f"{float(parts[xi]) + dx:.3f}"
                    ln = " ".join(parts)
        out.append(ln)
    return ("\n".join(out) + "\n").encode("utf-8")


def apply_op(op: dict[str, Any], raw: bytes) -> bytes:
    kind = op["op"]
    if kind == "shuffle_column":
        return shuffle_column(raw, op["column"], int(op.get("seed", 0)))
    if kind == "subsample":
        return subsample(raw, float(op.get("frac", 0.8)), int(op.get("seed", 0)))
    if kind == "translate_chain":
        return translate_chain(raw, list(op["chains"]), float(op.get("dx", 1000.0)))
    raise ValueError(f"unknown replay op {kind!r}")


# --------------------------------------------------------------------------
# running a replay
# --------------------------------------------------------------------------
@dataclass
class ReplayResult:
    fraction: float | None
    failed_calls: int
    n_calls: int

    def to_dict(self) -> dict[str, Any]:
        return {"fraction": None if self.fraction is None else round(self.fraction, 4),
                "failed_calls": self.failed_calls, "n_calls": self.n_calls}


def run_replay(spec: ExperimentSpec, aspec: AuditSpec, calls: list[Call],
               answer: Any, ops: list[dict[str, Any]], backend: str = "local",
               name: str = "replay") -> ReplayResult:
    """Re-run `calls` on data perturbed by `ops`; report how much of the answer
    still shows up in the output."""
    by_file = {op["file"]: op for op in ops}
    ex = get_executor(backend, name=f"{name}-{spec.id}")
    ex.start()
    try:
        for path in spec.dataset_paths():
            rel = f"data/{path.name}"
            raw = path.read_bytes()
            op = by_file.get(f"data/{path.name}") or by_file.get(path.name)
            if op:
                raw = apply_op(op, raw)
            ex.put_file(rel, raw, read_only=True)
        text, failed = [], 0
        for c in calls:
            res = ex.run_python(c.code, timeout_s=spec.limits.max_python_seconds)
            if not res.ok:
                failed += 1
            text.append(res.stdout)
            text.extend(res.files_written.values())
        frac = fraction_present(aspec, answer, "\n".join(text))
        return ReplayResult(frac, failed, len(calls))
    finally:
        ex.close()


def replay_all(spec: ExperimentSpec, aspec: AuditSpec, calls: list[Call],
               answer: Any, backend: str = "local") -> dict[str, Any]:
    """control + null (+ stability) replays, as the dict `build_report` expects."""
    if not aspec.replayable or not calls:
        return {}
    out: dict[str, Any] = {
        "control": run_replay(spec, aspec, calls, answer, [], backend, "ctl").to_dict(),
        "null": run_replay(spec, aspec, calls, answer, aspec.null, backend, "null").to_dict(),
    }
    if aspec.stability:
        out["stability"] = run_replay(spec, aspec, calls, answer, aspec.stability,
                                      backend, "stab").to_dict()
    return out
