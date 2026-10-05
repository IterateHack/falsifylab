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
    arm = "baseline" if args.no_lessons else args.arm
    print(f"  backend={args.backend}  arm={arm}")
    print(f"  models: loop={mc.loop_model} capstone={mc.capstone_model} effort={mc.effort}")

    if arm == "cold":
        from .cold import run_cold_curriculum
        from .provider import AnthropicProvider
        if args.only:
            raise SystemExit("--only does not apply to the cold arm")
        result = run_cold_curriculum(
            provider=AnthropicProvider(), curriculum_root=args.curriculum,
            run_id=args.run_id, runs_dir=args.runs_dir, backend=args.backend,
            model_config=mc)
        cal = result.notebook.calibration_summary()
        print(f"\n  mean score {cal['mean_score']}  mean confidence {cal['mean_confidence']}")
        print(f"notebook: {result.run_dir / 'notebook.md'}")
        return 0

    result = run_curriculum(
        curriculum_root=args.curriculum,
        run_id=args.run_id,
        runs_dir=args.runs_dir,
        backend=args.backend,
        model_config=mc,
        use_lessons=arm in ("lessons", "placebo", "null"),
        arm=arm,
        filler=arm if arm in ("placebo", "null") else None,
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


def cmd_compare(args: argparse.Namespace) -> int:
    from .compare import compare, render

    result = compare(args.with_lessons, args.without_lessons, args.curriculum)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render(result))
    return 0


def cmd_aggregate(args: argparse.Namespace) -> int:
    from . import aggregate as agg

    runs = agg.load_runs(args.paths)
    summary = agg.summarise(runs)
    if not (args.baseline and args.treatment):
        print(json.dumps(summary, indent=2))
        return 0
    res = agg.compare_arms(runs, args.baseline, args.treatment, n_boot=args.boots)
    print(json.dumps(res, indent=2) if args.json else agg.render(res))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from .audit import load_audit_spec
    from .specs import load_curriculum
    c = load_curriculum(args.curriculum)
    print(f"{c.id}: {c.title}")
    problems: list[str] = []
    for e in c.experiments:
        gt = e.ground_truth_path
        audit = "MISSING"
        if e.audit and e.audit_path.exists():
            a = load_audit_spec(e.audit_path)
            audit = f"ok({len(a.checkpoints)} steps{', replay' if a.replayable else ''})"
            if a.experiment != e.id:
                problems.append(f"{e.id}: audit spec is for {a.experiment!r}")
            data = {f"data/{p.name}" for p in e.dataset_paths()}
            for op in a.null + a.stability:
                if op["file"] not in data:
                    problems.append(f"{e.id}: replay op targets {op['file']!r}, "
                                    f"which is not one of its datasets")
        else:
            problems.append(f"{e.id}: no audit spec (a path audit is required)")
        print(f"  {e.order}. {e.id:36s} {e.type:13s} "
              f"scorer={e.scorer.type:13s} "
              f"data={len(e.datasets)} "
              f"gt={'ok' if gt and gt.exists() else 'MISSING'} "
              f"lesson={'ok' if e.lesson_card_path.exists() else 'MISSING'} "
              f"audit={audit} "
              f"requires={e.requires_lessons or '-'}")
    if problems:
        for p in problems:
            print(f"  PROBLEM: {p}")
        return 1
    print("curriculum is valid")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Audit a recorded run. Runs recorded before the path was logged cannot be
    audited and are marked UNAUDITED rather than guessed at."""
    from types import SimpleNamespace

    from .audit import run_audit, unaudited_report
    from .specs import load_curriculum

    run_dir = Path(args.run_dir)
    nb_path = run_dir / "notebook.json"
    data = json.loads(nb_path.read_text())
    curriculum = load_curriculum(args.curriculum)
    events = read_jsonl(run_dir / "events.jsonl")
    by_exp: dict[str, list[dict]] = {}
    for ev in events:
        by_exp.setdefault(ev.experiment_id or "", []).append(
            {"seq": ev.seq, "type": ev.type, "payload": ev.payload})
    earned: list[tuple[str, str, str]] = []
    n_ok = 0
    for e in data["entries"]:
        spec = curriculum.by_id(e["experiment_id"])
        evs = by_exp.get(spec.id, [])
        logged = any(x["type"] == "tool_result" and "code" in x["payload"] for x in evs)
        outcome = (e.get("score") or 0.0) / (e.get("score_max") or 1.0)
        if e.get("score") is None:
            continue
        if not logged and any(x["type"] == "tool_call" for x in evs):
            e["audit"] = unaudited_report(
                outcome, "recorded before the path was logged; cannot be audited")
        else:
            entry = SimpleNamespace(answer=e.get("answer"),
                                    sections=e.get("sections", {}))
            result = {"score": e["score"], "max": e.get("score_max", 1.0),
                      "details": e.get("score_details", {})}
            report = run_audit(
                spec=spec, curriculum=curriculum, events=evs, entry=entry,
                score_result=result, earned_lessons=list(earned),
                submitted=e.get("answer") is not None, backend=args.backend,
                replay=args.replay, online=not args.offline)
            e["audit"] = (report.to_dict() if report
                          else unaudited_report(outcome, "no audit spec"))
            n_ok += 1
        a = e["audit"]
        print(f"  {spec.order}. {spec.title[:34]:34s} outcome {outcome:.2f}  "
              f"verdict {a['verdict']}")
        if spec.lesson_card_path.exists():
            earned.append((spec.id, spec.title,
                           spec.lesson_card_path.read_text(encoding="utf-8")))
    if args.write:
        nb_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        print(f"wrote audits to {nb_path}")
    print(f"{n_ok} experiment(s) audited")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="falsifylab")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a curriculum end to end")
    r.add_argument("--curriculum", default="curricula/glp1r")
    r.add_argument("--run-id", default="run_001")
    r.add_argument("--runs-dir", default="runs")
    r.add_argument("--backend", default="local", choices=["local", "modal"])
    r.add_argument("--arm", choices=["lessons", "baseline", "cold", "placebo", "null"], default="lessons",
                   help="lessons: the lab with the required cards (default); "
                        "baseline: the lab with no cards; cold: no lab at all, the "
                        "hypothesis and titles only; placebo / null: the lab with "
                        "same-length cards that are irrelevant prose / meaningless "
                        "symbols")
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

    c = sub.add_parser("compare",
                       help="compare a with-lessons run against a without-lessons run")
    c.add_argument("with_lessons", help="run directory for the with-lessons arm")
    c.add_argument("without_lessons", help="run directory for the control arm")
    c.add_argument("--curriculum", default="curricula/glp1r")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_compare)

    ag = sub.add_parser("aggregate", help="compare arms over many runs, with a CI")
    ag.add_argument("paths", nargs="+", help="run dirs, or dirs of run dirs")
    ag.add_argument("--baseline", help="arm to compare against, e.g. cold or baseline")
    ag.add_argument("--treatment", help="arm under test, e.g. lessons")
    ag.add_argument("--boots", type=int, default=10000)
    ag.add_argument("--json", action="store_true")
    ag.set_defaults(func=cmd_aggregate)

    au = sub.add_parser("audit", help="audit the path of a recorded run")
    au.add_argument("run_dir")
    au.add_argument("--curriculum", default="curricula/glp1r")
    au.add_argument("--backend", default="local", choices=["local", "modal"])
    au.add_argument("--replay", action="store_true",
                    help="also run the null/stability replays (slow)")
    au.add_argument("--offline", action="store_true",
                    help="do not look citations up online")
    au.add_argument("--write", action="store_true",
                    help="write the audits back into notebook.json")
    au.set_defaults(func=cmd_audit)

    v = sub.add_parser("validate", help="check a curriculum's specs, data and scorers")
    v.add_argument("--curriculum", default="curricula/glp1r")
    v.set_defaults(func=cmd_validate)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
