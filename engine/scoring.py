"""Run a scorer in its own sandbox, with the ground truth it needs and nothing else.

The separation is the point (plan section 5.4). Sandbox A holds the agent's
workspace and the public datasets; sandbox B is created here, holds the scorer
and the private ground truth, and is destroyed as soon as the score comes back.
The agent never gets a handle on B, so it cannot read, edit or reward-hack the
answer key - the worst it can do is submit a bad answer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sandbox import get_executor

from .specs import ExperimentSpec

DRIVER = r'''
import json, sys, traceback
sys.path.insert(0, "scorer")

BEGIN = "<<<FALSIFYLAB_SCORE_BEGIN>>>"
END = "<<<FALSIFYLAB_SCORE_END>>>"

def main():
    with open("answer.json", encoding="utf-8") as fh:
        answer = json.load(fh)
    with open("ground_truth.json", encoding="utf-8") as fh:
        truth = json.load(fh)
    import importlib
    mod = importlib.import_module("MODULE_NAME")
    fn = getattr(mod, "FUNCTION_NAME")
    return fn(answer, truth)

try:
    result = main()
    if not isinstance(result, dict) or "score" not in result:
        raise ValueError("scorer must return a dict containing 'score'")
    s = float(result["score"])
    if not (0.0 <= s <= 1.0):
        raise ValueError(f"score {s} outside [0, 1]")
    print(BEGIN + json.dumps(result, default=str) + END)
except Exception as exc:
    print(BEGIN + json.dumps({
        "score": 0.0, "max": 1.0,
        "details": {"scorer_error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc()[-2000:]},
    }) + END)
'''

BEGIN = "<<<FALSIFYLAB_SCORE_BEGIN>>>"
END = "<<<FALSIFYLAB_SCORE_END>>>"


def score_answer(spec: ExperimentSpec, answer: Any, backend: str = "local",
                 timeout_s: int = 120) -> dict[str, Any]:
    gt_path = spec.ground_truth_path
    if gt_path is None:
        raise ValueError(f"{spec.id}: scorer has no ground_truth path")

    ex = get_executor(backend, name=f"scorer-{spec.id}")
    ex.start()
    try:
        # The whole scorers/ directory goes in, so shared helpers (rubric.py)
        # resolve by plain import without packaging gymnastics.
        ex.put_dir(spec.scorer_path.parent, "work/scorer", read_only=True)
        ex.put_file("work/ground_truth.json", gt_path.read_bytes(), read_only=True)
        ex.put_file("work/answer.json",
                    json.dumps(answer, default=str).encode("utf-8"))
        module_name = Path(spec.scorer.module_path).stem
        driver = (DRIVER
                  .replace("MODULE_NAME", module_name)
                  .replace("FUNCTION_NAME", spec.scorer.function))
        res = ex.run_python(driver, timeout_s=timeout_s)
        out = res.stdout
        if BEGIN in out and END in out:
            payload = out.split(BEGIN, 1)[1].split(END, 1)[0]
            parsed = json.loads(payload)
            parsed.setdefault("max", 1.0)
            parsed["scorer_type"] = spec.scorer.type
            return parsed
        return {
            "score": 0.0, "max": 1.0, "scorer_type": spec.scorer.type,
            "details": {
                "scorer_error": "scorer produced no parsable result",
                "timed_out": res.timed_out,
                "stdout": out[-1500:],
                "stderr": res.stderr[-1500:],
            },
        }
    finally:
        ex.close()
