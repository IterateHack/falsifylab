"""Cold-answer test: the capstone question with only the hypothesis and the experiment titles.

No data, no tools, no lesson cards. Same model and call settings as the lab's capstone
(engine/provider.py: claude-opus-5, adaptive thinking, effort high, max_tokens 16000).
Each answer is scored in-process with the curriculum's own scorer and private ground truth.

    python cold_test.py --dry-run      # print the prompts only
    python cold_test.py --n 5          # n samples per curriculum
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LAB = Path(r"C:\Users\Don\falsifylab\keshav-lab\lab")
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
from engine.specs import load_curriculum  # noqa: E402

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
EFFORT = "high"

SYSTEM = (
    "You are a scientist being asked for a verdict on a research hypothesis. In this "
    "conversation you have no data, no tools, no papers and no results from the experiments "
    "listed. Answer from what you already know. Reply with one JSON object and nothing else."
)

USER = """The hypothesis under test:

{hypothesis}

A curriculum of experiments was designed to test it. You have NOT run them and have none of their data or results. Their titles, in order:

{titles}

## The final question

{question}

## Required answer format

{answer_format}

Add one more key to the JSON object: "confidence", your confidence in this answer as a number from 0 to 1.
"""


def _cut(text: str, old: str, new: str = "") -> str:
    assert text.count(old) == 1, f"expected exactly one occurrence of: {old!r}"
    return text.replace(old, new)


def glp1r_question(task: str) -> str:
    # Drop only the closing paragraph, which refers to lessons and earlier answers.
    i = task.index("You have the lessons from all five earlier experiments.")
    return task[:i].rstrip()


def wrn_question(task: str) -> str:
    t = task
    t = _cut(t, "You established in experiment 1 which genes are selective dependencies. WRN is\n"
                "one of them: most cell lines do not care if you knock it out, and a minority\ndie.",
             "WRN is a selective dependency: most cell lines do not care if you knock it out,\n"
             "and a minority die.")
    t = _cut(t, "Using the same file, work out **which tissues those dependent lines belong to**,",
             "Say **which tissues those dependent lines belong to**,")
    t = _cut(t, ", applying the\n   same tail standard to tissues that lesson 1 applied to genes.", ".")
    t = _cut(t, "The file contains no annotation beyond tissue and disease name. Part of the task\n"
                "is recognising what is missing from it.")
    return t.rstrip()


CURRICULA = {
    "glp1r": ("curricula/glp1r", glp1r_question),
    "wrn": ("curricula/wrn", wrn_question),
}


def build(name: str) -> dict:
    rel, edit = CURRICULA[name]
    c = load_curriculum(LAB / rel)
    exps = sorted(c.experiments, key=lambda e: e.order)
    cap = exps[-1]
    prompt = USER.format(
        hypothesis=c.hypothesis.strip(),
        titles="\n".join(f"{e.order}. {e.title}" for e in exps),
        question=edit(cap.task),
        answer_format=cap.answer_format.strip(),
    )
    return {"name": name, "spec": cap, "prompt": prompt}


def call(client, anthropic, prompt: str) -> dict:
    statuses = (408, 409, 429, 500, 502, 503, 504, 529)
    for attempt in range(6):
        try:
            with client.messages.stream(
                model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "adaptive"}, output_config={"effort": EFFORT},
            ) as stream:
                msg = stream.get_final_message()
            text = "\n".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
            return {"model": msg.model, "stop_reason": msg.stop_reason, "text": text,
                    "usage": msg.usage.model_dump() if hasattr(msg.usage, "model_dump") else str(msg.usage)}
        except anthropic.APIStatusError as exc:
            if getattr(exc, "status_code", None) not in statuses or attempt == 5:
                raise
        except anthropic.APIConnectionError:
            if attempt == 5:
                raise
        time.sleep(min(60.0, 2.0 * 2 ** attempt) * (0.5 + random.random()))


def parse(text: str):
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(text[i:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    return None


def score(spec, answer: dict) -> dict:
    scorer_dir = spec.scorer_path.parent
    sys.path.insert(0, str(scorer_dir))
    try:
        mod_spec = importlib.util.spec_from_file_location(f"cold_{spec.id}", spec.scorer_path)
        mod = importlib.util.module_from_spec(mod_spec)
        mod_spec.loader.exec_module(mod)
        truth = json.loads(spec.ground_truth_path.read_text(encoding="utf-8"))
        return getattr(mod, spec.scorer.function)(answer, truth)
    finally:
        sys.path.remove(str(scorer_dir))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--n", type=int, default=5)
    args = ap.parse_args()

    jobs = [build(n) for n in CURRICULA]
    for j in jobs:
        (OUT / f"prompt_{j['name']}.txt").write_text(SYSTEM + "\n\n----\n\n" + j["prompt"], encoding="utf-8")
    if args.dry_run:
        for j in jobs:
            print(f"===== {j['name']} (capstone {j['spec'].id}) =====\n{j['prompt']}")
        return 0

    import anthropic
    client = anthropic.Anthropic(max_retries=4)
    tasks = [(j, k) for j in jobs for k in range(args.n)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda t: (t[0], t[1], call(client, anthropic, t[0]["prompt"])), tasks))

    rows = []
    for j, k, r in results:
        ans = parse(r["text"])
        conf = ans.pop("confidence", None) if isinstance(ans, dict) else None
        s = score(j["spec"], ans) if isinstance(ans, dict) else None
        rows.append({"curriculum": j["name"], "sample": k, "model": r["model"],
                     "stop_reason": r["stop_reason"], "usage": r["usage"], "parsed": ans is not None,
                     "confidence": conf, "score": s["score"] if s else None,
                     "details": s["details"] if s else None, "answer": ans, "raw_text": r["text"]})
    (OUT / "cold_results.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    for row in rows:
        print(row["curriculum"], row["sample"], row["model"], "parsed" if row["parsed"] else "PARSE-FAIL",
              "score", row["score"], "conf", row["confidence"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
