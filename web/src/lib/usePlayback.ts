/**
 * The animation queue (plan section 7.4).
 *
 * Events are domain-level and arrive as fast as the backend produces them - a
 * whole experiment can land in a few seconds. This buffers them and enforces a
 * minimum on-screen duration per event, so the scientist always walks rather
 * than teleports, and a viewer can read what happened.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LabEvent } from "./api";
import { SCIENTIST, stationStandX, type StationStatus } from "./scene";

export type Pose = "idle" | "walk" | "work" | "read" | "success" | "fail";

export interface SceneState {
  scientistX: number;
  walkMs: number;
  facing: "left" | "right";
  pose: Pose;
  activeIndex: number | null;
  statuses: StationStatus[];
  scores: (number | null)[];
  confidences: (number | null)[];
  verdicts: (string | null)[];
  speech: string | null;
  speechKind: "say" | "tool" | "score" | "lesson";
  showBook: boolean;
  notebookPulse: number;
  busy: boolean;
  finishedIndexes: number[];
  /** How far through the current experiment, 0..1, or null before any run. */
  progress: number | null;
  /** How long the bar has to reach `progress`: the event's on-screen hold. */
  progressMs: number;
  progressKind: "work" | "done" | "error";
  /** Short label for what is being worked on right now. */
  phase: string | null;
}

const WALK_MS_PER_PX = 26;

/** How long each event holds the screen before the next one is applied. */
function durationFor(ev: LabEvent, speed: number): number {
  const base: Record<string, number> = {
    run_started: 400,
    experiment_started: 350,
    prediction_written: 2200,
    plan_written: 1500,
    tool_call: 700,
    tool_result: 260,
    scored: 2000,
    audited: 1800,
    teaching_started: 900,
    lesson_learned: 2600,
    notebook_entry_ready: 400,
    experiment_done: 900,
    run_finished: 600,
    error: 1200,
  };
  let ms = base[ev.type] ?? 500;
  if (ev.type === "tool_call" && ev.payload?.kind === "say") ms = 1800;
  return Math.max(60, ms / speed);
}

/**
 * The bar is filled by one of two models, because how much is known differs.
 *
 * Replaying a recorded run, the whole experiment is enqueued in one batch, so
 * the sum of the on-screen holds is the time left, so the bar is a real
 * estimate of when the scientist will finish. `enqueue` totals it and `apply`
 * spends it down.
 *
 * A live run streams events as the agent produces them, and nothing knows how
 * many are still coming - "applied / queued" would read 100% between every
 * model turn. So the bar falls back to milestones: fractions attached to things
 * that have provably happened. The fractions below are deliberately floors
 * rather than positions, because the recorded order is not the tidy one - the
 * gate is satisfied *through* tool calls, so `prediction_written` and
 * `plan_written` land after the first few of them.
 */
const P_START = 0.04;
const P_PREDICTION = 0.12;
const P_PLAN = 0.18;
const P_TOOLS_LO = 0.08;
const P_TOOLS_HI = 0.78;
const P_SCORED = 0.84;
const P_TEACHING = 0.9;
const P_LESSON = 0.96;
const P_NOTEBOOK = 0.98;

/**
 * Where the tool phase has got to, from the budget line in the `tool_call`
 * payload. Two signals, whichever is further along: the share of the call
 * budget spent - exact, and the one that matters when an agent is burning
 * through it - and a curve that approaches the end of the phase without
 * reaching it, so an agent working well inside its budget still shows
 * movement. Both rise with every call, so the bar never reverses.
 */
function toolProgress(used: number, budget: number): number {
  const burn = budget > 0 ? Math.min(1, used / budget) : 0;
  const creep = 1 - Math.pow(0.86, Math.max(0, used));
  return P_TOOLS_LO + (P_TOOLS_HI - P_TOOLS_LO) * Math.max(burn, creep);
}

/** Events that start a fresh bar; everything else may only move it forward. */
const RESTARTS_PROGRESS = new Set(["run_started", "experiment_started"]);

export interface PlaybackOptions {
  experimentIds: string[];
  speed: number;
  onExperimentDone?: (experimentId: string) => void;
  reducedMotion?: boolean;
}

export function usePlayback(opts: PlaybackOptions) {
  const { experimentIds, speed, onExperimentDone, reducedMotion } = opts;
  const n = experimentIds.length;

  const [scene, setScene] = useState<SceneState>(() => ({
    scientistX: SCIENTIST.homeX,
    walkMs: 0,
    facing: "right",
    pose: "idle",
    activeIndex: null,
    statuses: Array(n).fill("locked") as StationStatus[],
    scores: Array(n).fill(null),
    confidences: Array(n).fill(null),
    verdicts: Array(n).fill(null),
    speech: null,
    speechKind: "say",
    showBook: false,
    notebookPulse: 0,
    busy: false,
    finishedIndexes: [],
    progress: null,
    progressMs: 0,
    progressKind: "work",
    phase: null,
  }));

  /**
   * The completion callback is held in a ref, not captured in the queue's
   * closures. The pump schedules a timeout and the callback it invokes later
   * must reflect current state - capturing it meant a "Run all" toggled on in
   * the same tick was invisible, and the notebook popped open mid-run.
   */
  const onDone = useRef(onExperimentDone);
  useEffect(() => {
    onDone.current = onExperimentDone;
  }, [onExperimentDone]);

  const queue = useRef<LabEvent[]>([]);
  const timer = useRef<number | null>(null);
  const draining = useRef(false);
  const posX = useRef(SCIENTIST.homeX);

  /**
   * Total on-screen time of each experiment whose events arrived as a complete
   * batch, and how much of the one in flight has been spent. Set by `enqueue`,
   * which is the only place that can see a whole experiment at once.
   */
  const runtimeFor = useRef<Map<string, number>>(new Map());
  const spent = useRef<{ expId: string | null; total: number; elapsed: number }>({
    expId: null, total: 0, elapsed: 0,
  });

  /**
   * Resize the per-station arrays when the curriculum arrives.
   *
   * The curriculum is fetched, so on first render `n` is 0 and the useState
   * initialiser - which only ever runs once - produces empty arrays. Without
   * this the arrays stay empty, every station reads `undefined`, and the scene
   * crashes on the first score. Also marks station 1 ready.
   */
  useEffect(() => {
    setScene((s) => {
      if (s.statuses.length === n) return s;
      const grow = <T,>(arr: T[], fill: T): T[] =>
        Array.from({ length: n }, (_, i) => (i < arr.length ? arr[i] : fill));
      const statuses = grow(s.statuses, "locked" as StationStatus);
      if (n > 0 && statuses[0] === "locked") statuses[0] = "ready";
      return {
        ...s,
        statuses,
        scores: grow(s.scores, null as number | null),
        confidences: grow(s.confidences, null as number | null),
        verdicts: grow(s.verdicts, null as string | null),
      };
    });
  }, [n]);

  const indexOf = useCallback(
    (id: string | null) => (id ? experimentIds.indexOf(id) : -1),
    [experimentIds],
  );

  const apply = useCallback(
    (ev: LabEvent): number => {
      const idx = indexOf(ev.experiment_id);
      let extra = 0;
      // The same hold at 1x. The clock is kept in speed-independent units,
      // because the speed buttons work mid-experiment: mixing time spent at 1x
      // with a total measured at 4x would strand the bar short of the end.
      let extra1 = 0;

      setScene((s) => {
        const next: SceneState = { ...s, statuses: [...s.statuses],
          scores: [...s.scores], confidences: [...s.confidences],
          verdicts: [...s.verdicts] };

        switch (ev.type) {
          case "run_started":
            next.progress = 0;
            next.progressKind = "work";
            next.phase = "run started";
            break;
          case "experiment_started": {
            if (idx < 0) break;
            const targetX = stationStandX(idx);
            const dist = Math.abs(targetX - posX.current);
            const walkMs = reducedMotion ? 0 : dist * WALK_MS_PER_PX / speed;
            next.facing = targetX >= posX.current ? "right" : "left";
            next.scientistX = targetX;
            next.walkMs = walkMs;
            next.pose = dist > 1 ? "walk" : "idle";
            next.activeIndex = idx;
            next.statuses[idx] = "running";
            next.speech = `Experiment ${ev.payload?.order ?? idx + 1}: ${ev.payload?.title ?? ""}`;
            next.speechKind = "say";
            next.showBook = false;
            next.progress = P_START;
            next.progressKind = "work";
            next.phase = "walking to the bench";
            posX.current = targetX;
            // Hold the queue until the walk finishes, then settle into work.
            extra = walkMs + 250;
            extra1 = (reducedMotion ? 0 : dist * WALK_MS_PER_PX) + 250;
            // The walk is only measurable here, so it joins the total now -
            // harmless, because this is the first event of the experiment and
            // the bar is still at zero.
            if (ev.experiment_id) {
              const planned = runtimeFor.current.get(ev.experiment_id) ?? 0;
              spent.current = {
                expId: ev.experiment_id,
                total: planned > 0 ? planned + extra1 : 0,
                elapsed: 0,
              };
            }
            break;
          }
          case "prediction_written": {
            if (idx >= 0) next.confidences[idx] = ev.payload?.confidence ?? null;
            next.pose = "idle";
            const c = ev.payload?.confidence;
            next.speech =
              `Prediction recorded. Confidence ${typeof c === "number" ? c.toFixed(2) : "?"}.`;
            next.speechKind = "say";
            next.progress = P_PREDICTION;
            next.phase = "writing the prediction";
            break;
          }
          case "plan_written":
            next.pose = "work";
            next.speech = "Plan written. Tools unlocked.";
            next.speechKind = "say";
            next.progress = P_PLAN;
            next.phase = "planning";
            break;
          case "tool_call": {
            next.pose = "work";
            if (ev.payload?.kind === "say") {
              next.speech = String(ev.payload?.text ?? "").slice(0, 180);
              next.speechKind = "say";
              // Thinking out loud is not a step completed, so the bar holds.
              next.phase = "thinking";
            } else {
              const tool = ev.payload?.tool ?? "";
              const note = String(ev.payload?.note ?? "").slice(0, 70);
              next.speech = note ? `${tool}: ${note}` : tool;
              next.speechKind = "tool";
              const used = Number(ev.payload?.calls_used ?? 0);
              const budget = Number(ev.payload?.budget ?? 0);
              next.progress = toolProgress(used, budget);
              next.phase =
                used > 0 && budget > 0
                  ? `analysis - tool call ${used} of ${budget}`
                  : "running the analysis";
            }
            break;
          }
          case "tool_result":
            next.pose = "work";
            break;
          case "scored": {
            if (idx < 0) break;
            const score = Number(ev.payload?.score ?? 0);
            next.scores[idx] = score;
            next.statuses[idx] = "done";
            next.pose = score >= 0.6 ? "success" : "fail";
            const gap = ev.payload?.calibration_gap;
            next.progress = P_SCORED;
            next.phase = "scoring";
            next.speech =
              `Scored ${score.toFixed(2)}` +
              (typeof gap === "number"
                ? ` - calibration gap ${gap > 0 ? "+" : ""}${gap.toFixed(2)}`
                : "");
            next.speechKind = "score";
            break;
          }
          case "audited": {
            // The audit grades the path. A high score with a flagged path is
            // not celebrated.
            if (idx < 0) break;
            const verdict = String(ev.payload?.verdict ?? "UNAUDITED");
            next.verdicts[idx] = verdict;
            next.pose = verdict === "VALID_SUCCESS" ? "success" : "fail";
            next.speech = `Audit: ${verdict.replace(/_/g, " ").toLowerCase()}`;
            next.speechKind = "score";
            break;
          }
          case "teaching_started":
            next.pose = "read";
            next.showBook = true;
            next.speech = "Reading the paper...";
            next.speechKind = "lesson";
            next.progress = P_TEACHING;
            next.phase = "being taught";
            break;
          case "lesson_learned":
            next.pose = "read";
            next.showBook = true;
            next.speech = "Lesson learned - filed to the notebook.";
            next.speechKind = "lesson";
            next.notebookPulse = s.notebookPulse + 1;
            next.progress = P_LESSON;
            next.phase = "filing the lesson";
            break;
          case "notebook_entry_ready":
            next.progress = P_NOTEBOOK;
            next.phase = "writing up the notebook";
            break;
          case "experiment_done": {
            if (idx < 0) break;
            next.showBook = false;
            next.pose = "idle";
            next.speech = null;
            next.statuses[idx] = "done";
            next.progress = 1;
            next.progressKind = "done";
            next.phase = "experiment complete";
            next.finishedIndexes = Array.from(new Set([...s.finishedIndexes, idx]));
            if (idx + 1 < n && next.statuses[idx + 1] === "locked") {
              next.statuses[idx + 1] = "ready";
            }
            break;
          }
          case "error":
            next.speech = `! ${ev.payload?.reason ?? ev.payload?.error ?? "error"}`;
            next.speechKind = "score";
            next.progressKind = "error";
            next.phase = String(ev.payload?.reason ?? ev.payload?.error ?? "error");
            break;
          default:
            break;
        }

        const hold = durationFor(ev, speed) + extra;

        // Where the whole experiment's runtime is known, the bar is that clock
        // rather than the milestones: it tracks the fill to the end of *this*
        // event, so it arrives exactly as the next one lands.
        const clock = spent.current;
        if (ev.experiment_id && clock.expId === ev.experiment_id && clock.total > 0) {
          clock.elapsed += durationFor(ev, 1) + extra1;
          // The walk that opens an experiment still counts towards the clock,
          // but the bar stays at the start through it: the event after the walk
          // then glides from the start mark, rather than the bar jumping ahead
          // before any work has been done.
          if (!RESTARTS_PROGRESS.has(ev.type)) {
            next.progress = Math.min(1, clock.elapsed / clock.total);
          }
        }
        if (ev.type === "experiment_done") next.progress = 1;

        // Within one experiment the bar only ever moves forward: an event that
        // sets no milestone keeps the one before it, and none may walk it back.
        if (next.progress != null && s.progress != null && !RESTARTS_PROGRESS.has(ev.type)) {
          next.progress = Math.max(next.progress, s.progress);
        }
        // The fill glides over exactly as long as this event holds the screen,
        // so the bar moves with the scientist rather than jumping between poses
        // - except when starting over, which snaps. Sliding back down from a
        // finished 100% to the next experiment's zero reads as work being
        // undone, which is the opposite of what just happened.
        next.progressMs = RESTARTS_PROGRESS.has(ev.type) ? 0 : hold;
        return next;
      });

      if (ev.type === "experiment_done" && ev.experiment_id) {
        onDone.current?.(ev.experiment_id);
      }
      return extra;
    },
    [indexOf, n, reducedMotion, speed],
  );

  const pump = useCallback(() => {
    if (draining.current) return;
    const ev = queue.current.shift();
    if (!ev) {
      setScene((s) => ({ ...s, busy: false, pose: s.pose === "walk" ? "idle" : s.pose }));
      return;
    }
    draining.current = true;
    setScene((s) => ({ ...s, busy: true }));
    const extra = apply(ev);
    const hold = durationFor(ev, speed) + extra;
    timer.current = window.setTimeout(() => {
      draining.current = false;
      pump();
    }, hold);
  }, [apply, speed]);

  const enqueue = useCallback(
    (events: LabEvent[]) => {
      // A batch that carries an experiment's `experiment_done` is that whole
      // experiment, so its runtime can be totalled up front and the bar can be
      // a clock. A batch without one is a live frame: no total, milestones.
      const whole = new Set(
        events.flatMap((e) =>
          e.type === "experiment_done" && e.experiment_id ? [e.experiment_id] : [],
        ),
      );
      for (const expId of whole) {
        const total = events
          .filter((e) => e.experiment_id === expId)
          .reduce((sum, e) => sum + durationFor(e, 1), 0);
        runtimeFor.current.set(expId, total);
      }
      queue.current.push(...events);
      if (!draining.current) pump();
    },
    [pump],
  );

  const reset = useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current);
    queue.current = [];
    draining.current = false;
    posX.current = SCIENTIST.homeX;
    runtimeFor.current.clear();
    spent.current = { expId: null, total: 0, elapsed: 0 };
    setScene((s) => ({
      ...s,
      scientistX: SCIENTIST.homeX,
      walkMs: 0,
      pose: "idle",
      activeIndex: null,
      statuses: Array(n).fill("locked").map((v, i) => (i === 0 ? "ready" : v)) as StationStatus[],
      scores: Array(n).fill(null),
      confidences: Array(n).fill(null),
      speech: null,
      showBook: false,
      busy: false,
      finishedIndexes: [],
      progress: null,
      progressMs: 0,
      progressKind: "work",
      phase: null,
    }));
  }, [n]);

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  const pending = useMemo(() => () => queue.current.length, []);
  return { scene, enqueue, reset, pending };
}
