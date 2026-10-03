"""Create one Devin session per experiment (plan section 9).

Each session gets the same playbook, the spec schema, the reference
implementation and the acceptance criteria, differing only in the experiment it
is asked to build. Humans review every pull request - nothing here merges
anything.

    export DEVIN_API_KEY=...
    python devin/launch_sessions.py --curriculum glp1r --experiments exp3,exp4
    python devin/launch_sessions.py --list            # show sessions created so far
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

API = "https://api.devin.ai/v1"
ROOT = Path(__file__).resolve().parent.parent
STATE = Path(__file__).resolve().parent / "sessions.json"

PROMPT = """\
Add the experiment `{experiment_id}` to the FalsifyLab curriculum
`curricula/{curriculum}` in this repository, and open a pull request.

Read `devin/playbook.md` first and follow it exactly. It lists the files you need
to produce and twelve acceptance criteria that your pull request must satisfy.
`curricula/glp1r/experiments/02_structure_contacts.yaml` together with
`curricula/glp1r/scorers/exp2.py` is the reference implementation - match its
shape.

## This experiment

Title: {title}
Type: {type}
Primary source: {paper}
Requires lessons from: {requires}

{brief}

## Non-negotiables

- The scorer is deterministic. Given the same answer it returns the same score,
  with no network access, no clock and no model call.
- The ground truth lives only in `private/`, and never appears in the spec's
  `inputs.datasets`.
- Check every column you expose to the agent for answer leakage. If a feature
  restates the outcome, drop it and leave a comment saying why.
- Verify the reference against Europe PMC before you write the lesson card.
  Confirm title, authors, journal, year and DOI. Do not trust recall: two of the
  six references in the original project plan were wrong in plausible-looking
  ways.
- Write the golden fixtures, including one test that shows the naive approach
  your lesson card warns about scores materially worse than the correct one.

Do not modify `engine/` or `sandbox/`. If you believe the engine needs a change,
say so in the pull request description instead of making it.
"""


def post(path: str, body: dict[str, Any], key: str) -> dict[str, Any]:
    r = requests.post(f"{API}{path}", json=body, timeout=60,
                      headers={"Authorization": f"Bearer {key}",
                               "Content-Type": "application/json"})
    if r.status_code >= 400:
        raise SystemExit(f"Devin API {r.status_code}: {r.text[:500]}")
    return r.json()


def load_state() -> dict[str, Any]:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(state: dict[str, Any]) -> None:
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--curriculum", default="glp1r")
    ap.add_argument("--experiments", help="comma-separated experiment ids")
    ap.add_argument("--repo", default=os.environ.get("DEVIN_REPO", ""),
                    help="owner/name of the GitHub repository")
    ap.add_argument("--idempotent", action="store_true",
                    help="skip experiments that already have a session")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the prompts without creating sessions")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    state = load_state()
    if args.list:
        if not state:
            print("no sessions recorded")
        for exp, meta in sorted(state.items()):
            print(f"  {exp:36s} {meta.get('session_id', '?'):24s} {meta.get('url', '')}")
        return 0

    sys.path.insert(0, str(ROOT))
    from engine.specs import load_curriculum

    curriculum = load_curriculum(ROOT / "curricula" / args.curriculum)
    wanted = args.experiments.split(",") if args.experiments else None
    specs = [e for e in curriculum.experiments
             if wanted is None or e.id in wanted or str(e.order) in wanted]
    if not specs:
        raise SystemExit(f"no experiments matched {args.experiments!r}")

    key = os.environ.get("DEVIN_API_KEY", "")
    if not key and not args.dry_run:
        raise SystemExit("set DEVIN_API_KEY, or pass --dry-run")

    for spec in specs:
        if args.idempotent and spec.id in state:
            print(f"skip {spec.id} (session {state[spec.id]['session_id']} exists)")
            continue
        prompt = PROMPT.format(
            experiment_id=spec.id,
            curriculum=args.curriculum,
            title=spec.title,
            type=spec.type,
            paper=spec.teaching.papers[0] if spec.teaching.papers else "(choose one)",
            requires=", ".join(spec.requires_lessons) or "nothing",
            brief=spec.task,
        )
        if args.dry_run:
            print("=" * 72)
            print(prompt)
            continue
        body: dict[str, Any] = {
            "prompt": prompt,
            "idempotent": True,
            "tags": ["falsifylab", args.curriculum, spec.id],
            "title": f"FalsifyLab {spec.id}",
        }
        if args.repo:
            body["repo"] = args.repo
        res = post("/sessions", body, key)
        state[spec.id] = {
            "session_id": res.get("session_id"),
            "url": res.get("url"),
            "title": spec.title,
        }
        print(f"created {spec.id} -> {res.get('session_id')} {res.get('url', '')}")
        save_state(state)

    if not args.dry_run:
        save_state(state)
        print(f"\n{len(state)} session(s) recorded in {STATE.relative_to(ROOT)}")
        print("Humans review every PR. Nothing here merges anything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
