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
  speech: string | null;
  speechKind: "say" | "tool" | "score" | "lesson";
  showBook: boolean;
  notebookPulse: number;
  busy: boolean;
  finishedIndexes: number[];
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
    speech: null,
    speechKind: "say",
    showBook: false,
    notebookPulse: 0,
    busy: false,
    finishedIndexes: [],
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

      setScene((s) => {
        const next: SceneState = { ...s, statuses: [...s.statuses],
          scores: [...s.scores], confidences: [...s.confidences] };

        switch (ev.type) {
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
            posX.current = targetX;
            // Hold the queue until the walk finishes, then settle into work.
            extra = walkMs + 250;
            break;
          }
          case "prediction_written": {
            if (idx >= 0) next.confidences[idx] = ev.payload?.confidence ?? null;
            next.pose = "idle";
            const c = ev.payload?.confidence;
            next.speech =
              `Prediction recorded. Confidence ${typeof c === "number" ? c.toFixed(2) : "?"}.`;
            next.speechKind = "say";
            break;
          }
          case "plan_written":
            next.pose = "work";
            next.speech = "Plan written. Tools unlocked.";
            next.speechKind = "say";
            break;
          case "tool_call": {
            next.pose = "work";
            if (ev.payload?.kind === "say") {
              next.speech = String(ev.payload?.text ?? "").slice(0, 180);
              next.speechKind = "say";
            } else {
              const tool = ev.payload?.tool ?? "";
              const note = String(ev.payload?.note ?? "").slice(0, 70);
              next.speech = note ? `${tool}: ${note}` : tool;
              next.speechKind = "tool";
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
            next.speech =
              `Scored ${score.toFixed(2)}` +
              (typeof gap === "number"
                ? ` - calibration gap ${gap > 0 ? "+" : ""}${gap.toFixed(2)}`
                : "");
            next.speechKind = "score";
            break;
          }
          case "teaching_started":
            next.pose = "read";
            next.showBook = true;
            next.speech = "Reading the paper...";
            next.speechKind = "lesson";
            break;
          case "lesson_learned":
            next.pose = "read";
            next.showBook = true;
            next.speech = "Lesson learned - filed to the notebook.";
            next.speechKind = "lesson";
            next.notebookPulse = s.notebookPulse + 1;
            break;
          case "experiment_done": {
            if (idx < 0) break;
            next.showBook = false;
            next.pose = "idle";
            next.speech = null;
            next.statuses[idx] = "done";
            next.finishedIndexes = Array.from(new Set([...s.finishedIndexes, idx]));
            if (idx + 1 < n && next.statuses[idx + 1] === "locked") {
              next.statuses[idx + 1] = "ready";
            }
            break;
          }
          case "error":
            next.speech = `! ${ev.payload?.reason ?? ev.payload?.error ?? "error"}`;
            next.speechKind = "score";
            break;
          default:
            break;
        }
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
