"""Command line entry point: run the lab, or inspect a recorded run."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from .events import read_jsonl
from .provider import ModelConfig
from .runner import run_curriculum


def cmd_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.runs_dir) / args.run_id
    if run_dir.exists():
        if not args.force:
            raise SystemExit(
                f"{run_dir} already exists. Pass --force to overwrite it, or choose "
                f"another --run-id.")
        shutil.rmtree(run_dir)

    mc = ModelConfig()
    if args.loop_model:
        mc.loop_model = args.loop_model
    if args.capstone_model:
        mc.capstone_model = args.capstone_model
    if args.effort:
        mc.effort = args.effort

    print(f"running curriculum {args.curriculum} as {args.run_id}")
    print(f"  backend={args.backend}  lessons={'off' if args.no_lessons else 'on'}")
    print(f"  models: loop={mc.loop_model} capstone={mc.capstone_model} effort={mc.effort}")

    result = run_curriculum(
        curriculum_root=args.curriculum,
        run_id=args.run_id,
        runs_dir=args.runs_dir,
        backend=args.backend,
        model_config=mc,
        use_lessons=not args.no_lessons,
        only=args.only.split(",") if args.only else None,
    )
    cal = result.notebook.calibration_summary()
    print("\n--- results ---")
    for row in cal["rows"]:
        conf = f"{row['confidence']:.2f}" if row["confidence"] is not None else "  - "
        print(f"  {row['order']}. {row['title'][:38]:38s} "
              f"confidence {conf}  score {row['score']:.2f}  gap {row['gap']:+.2f}")
    print(f"\n  mean confidence {cal['mean_confidence']}  mean score {cal['mean_score']}  "
          f"mean gap {cal['mean_gap']}")
    print(f"  {cal['verdict']}")
    print(f"\nnotebook: {result.run_dir / 'notebook.md'}")
    print(f"events:   {result.run_dir / 'events.jsonl'}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    events = read_jsonl(args.path)
    print(f"{len(events)} events in {args.path}")
    for ev in events:
        if args.types and ev.type not in args.types.split(","):
            continue
        payload = json.dumps(ev.payload, default=str)
        if len(payload) > args.width:
            payload = payload[:args.width] + "..."
        print(f"  {ev.seq:4d} {ev.ts} {ev.experiment_id or '-':34s} "
              f"{ev.type:22s} {payload}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from .specs import load_curriculum
    c = load_curriculum(args.curriculum)
    print(f"{c.id}: {c.title}")
    for e in c.experiments:
        gt = e.ground_truth_path
        print(f"  {e.order}. {e.id:36s} {e.type:13s} "
              f"scorer={e.scorer.type:13s} "
              f"data={len(e.datasets)} "
              f"gt={'ok' if gt and gt.exists() else 'MISSING'} "
              f"lesson={'ok' if e.lesson_card_path.exists() else 'MISSING'} "
              f"requires={e.requires_lessons or '-'}")
    print("curriculum is valid")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="falsifylab")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a curriculum end to end")
    r.add_argument("--curriculum", default="curricula/glp1r")
    r.add_argument("--run-id", default="run_001")
    r.add_argument("--runs-dir", default="runs")
    r.add_argument("--backend", default="local", choices=["local", "modal"])
    r.add_argument("--no-lessons", action="store_true",
                   help="control run: withhold lesson cards from later experiments")
    r.add_argument("--only", help="comma-separated experiment ids or orders")
    r.add_argument("--loop-model")
    r.add_argument("--capstone-model")
    r.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    r.add_argument("--force", action="store_true", help="overwrite an existing run dir")
    r.set_defaults(func=cmd_run)

    p = sub.add_parser("replay", help="print a recorded event log")
    p.add_argument("path")
    p.add_argument("--types", help="comma-separated event types to show")
    p.add_argument("--width", type=int, default=110)
    p.set_defaults(func=cmd_replay)

    v = sub.add_parser("validate", help="check a curriculum's specs, data and scorers")
    v.add_argument("--curriculum", default="curricula/glp1r")
    v.set_defaults(func=cmd_validate)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
