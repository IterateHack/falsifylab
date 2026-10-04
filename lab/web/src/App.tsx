import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Lab } from "./components/Lab";
import { NotebookOverlay } from "./components/Notebook";
import { ProgressBar } from "./components/ProgressBar";
import { api, type LabEvent, type Notebook, type RunSummary } from "./lib/api";
import { SCENE_H, SCENE_W } from "./lib/scene";
import { usePlayback } from "./lib/usePlayback";

type Mode = "replay" | "live";

export default function App() {
  const [experiments, setExperiments] = useState<
    { id: string; title: string; order: number; requires_lessons: string[] }[]
  >([]);
  const [hypothesis, setHypothesis] = useState("");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [notebook, setNotebook] = useState<Notebook | null>(null);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [openCalibration, setOpenCalibration] = useState(false);
  const params = useMemo(
    () => new URLSearchParams(typeof window === "undefined" ? "" : window.location.search),
    [],
  );
  const [speed, setSpeed] = useState(() => {
    const s = Number(params.get("speed"));
    return [1, 2, 4].includes(s) ? s : 1;
  });
  const [mode, setMode] = useState<Mode>("replay");
  const [runAll, setRunAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0); // next experiment to play

  const reducedMotion = useMemo(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
    [],
  );

  const experimentIds = useMemo(() => experiments.map((e) => e.id), [experiments]);
  const titles = useMemo(() => experiments.map((e) => e.title), [experiments]);

  const eventsByExp = useRef<Map<string, LabEvent[]>>(new Map());
  const sse = useRef<EventSource | null>(null);
  // The room is sized from the space actually left for it, so these two are
  // measured rather than guessed at: the slot gives the width and the top edge,
  // the strip under the room gives back what it takes.
  const slotRef = useRef<HTMLDivElement>(null);
  const underRef = useRef<HTMLDivElement>(null);

  const refreshNotebook = useCallback(async (id: string) => {
    try {
      setNotebook(await api.notebook(id));
    } catch {
      /* a live run has no notebook until the first experiment finishes */
    }
  }, []);

  const { scene, enqueue, reset } = usePlayback({
    experimentIds,
    speed,
    reducedMotion,
    onExperimentDone: (expId) => {
      if (runId) refreshNotebook(runId);
      const idx = experimentIds.indexOf(expId);
      setCursor(idx + 1);
      // Opening the notebook after every experiment is right for a click-through
      // demo and wrong for "Run all", which should play straight through.
      if (!runAll) setOpenIndex(idx);
    },
  });

  // --- bootstrap ---------------------------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const c = await api.curriculum();
        setExperiments(c.experiments);
        setHypothesis(c.hypothesis);
        const r = await api.runs();
        setRuns(r.runs);
        const wanted = params.get("run");
        const best =
          (wanted ? r.runs.find((x) => x.run_id === wanted) : undefined) ??
          r.runs.find((x) => x.run_id.startsWith("demo")) ??
          r.runs.find((x) => (x.n_entries ?? 0) > 0) ??
          r.runs[0];
        if (best) setRunId(best.run_id);
      } catch (e) {
        setError(String(e));
      }
    })();
  }, [params]);

  useEffect(() => {
    if (runId) refreshNotebook(runId);
    eventsByExp.current.clear();
    setCursor(0);
    reset();
  }, [runId, refreshNotebook, reset]);

  // --- replay ------------------------------------------------------------
  const playExperiment = useCallback(
    async (index: number) => {
      if (!runId || index >= experimentIds.length) return;
      const expId = experimentIds[index];
      let evs = eventsByExp.current.get(expId);
      if (!evs) {
        const res = await api.events(runId, expId);
        evs = res.events;
        eventsByExp.current.set(expId, evs);
      }
      if (!evs.length) {
        setError(`Run "${runId}" has no recorded events for ${expId}.`);
        return;
      }
      setError(null);
      enqueue(evs);
    },
    [runId, experimentIds, enqueue],
  );

  // ?notebook=3 or ?notebook=cal deep-links straight to a notebook page, which
  // is handy mid-presentation and in a headless check.
  useEffect(() => {
    const want = params.get("notebook");
    if (!want) return;
    if (want === "cal" || want === "calibration") {
      setOpenCalibration(true);
      setOpenIndex(0);
      return;
    }
    const n = Number(want);
    if (Number.isInteger(n) && n >= 1 && n <= 6) setOpenIndex(n - 1);
  }, [params]);

  // ?autostart=1 begins playback once the curriculum and run are loaded. Used
  // for recording the demo, and to drive the UI in a headless browser check.
  const autostarted = useRef(false);
  useEffect(() => {
    if (!params.get("autostart")) return;
    if (autostarted.current || !runId || !experimentIds.length) return;
    autostarted.current = true;
    if (params.get("runall") !== "0") setRunAll(true);
    playExperiment(0);
  }, [params, runId, experimentIds.length, playExperiment]);

  // "Run all" chains straight into the next experiment as each one finishes.
  useEffect(() => {
    if (!runAll || mode !== "replay") return;
    if (scene.busy) return;
    if (cursor === 0 || cursor >= experimentIds.length) return;
    playExperiment(cursor);
  }, [runAll, mode, scene.busy, cursor, experimentIds.length, playExperiment]);

  // --- live --------------------------------------------------------------
  const startLive = useCallback(async () => {
    try {
      setError(null);
      reset();
      const { run_id } = await api.startRun({ use_lessons: true, backend: "local" });
      setRunId(run_id);
      sse.current?.close();
      const es = new EventSource(`/api/run/${run_id}/stream`);
      sse.current = es;
      const types = [
        "run_started", "experiment_started", "prediction_written", "plan_written",
        "tool_call", "tool_result", "scored", "audited", "teaching_started", "lesson_learned",
        "notebook_entry_ready", "experiment_done", "run_finished", "error",
      ];
      for (const t of types) {
        es.addEventListener(t, (ev) => {
          try {
            enqueue([JSON.parse((ev as MessageEvent).data) as LabEvent]);
          } catch {
            /* ignore a malformed frame rather than killing the stream */
          }
        });
      }
      es.onerror = () => {
        es.close();
        sse.current = null;
      };
    } catch (e) {
      setError(String(e));
    }
  }, [enqueue, reset]);

  useEffect(() => () => sse.current?.close(), []);

  const nextLabel =
    cursor === 0
      ? "Start Experiment 1"
      : cursor >= experimentIds.length
        ? "Curriculum complete"
        : `Next: Experiment ${cursor + 1}`;

  // The notebook is a view over what has happened so far, not over the whole
  // recorded run: only experiments the animation has finished are visible.
  // ?notebook=... deep links bypass this so a page can be opened directly.
  const revealAll = params.has("notebook");
  const visibleNotebook = useMemo(
    () =>
      revealAll || !notebook
        ? notebook
        : filterNotebook(notebook, scene.finishedIndexes),
    [notebook, scene.finishedIndexes, revealAll],
  );

  const scale = useScale(slotRef, underRef);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">FalsifyLab</span>
        </div>
        <div className="controls">
          <select
            value={runId ?? ""}
            onChange={(e) => setRunId(e.target.value)}
            aria-label="Run"
          >
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id}
                {r.mean_score != null ? ` (mean ${r.mean_score.toFixed(2)})` : ""}
              </option>
            ))}
          </select>
          <div className="seg" role="group" aria-label="Mode">
            {(["replay", "live"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                className={mode === m ? "on" : ""}
                onClick={() => setMode(m)}
              >
                {m}
              </button>
            ))}
          </div>
          <div className="seg" role="group" aria-label="Speed">
            {[1, 2, 4].map((s) => (
              <button
                key={s}
                type="button"
                className={speed === s ? "on" : ""}
                onClick={() => setSpeed(s)}
              >
                {s}x
              </button>
            ))}
          </div>
          <label className="toggle">
            <input
              type="checkbox"
              checked={runAll}
              onChange={(e) => setRunAll(e.target.checked)}
            />
            Run all
          </label>
          <button type="button" className="ghost" onClick={() => setOpenIndex(0)}>
            Notebook
            {scene.notebookPulse > 0 && <span className="pulse-dot" />}
          </button>
          <button
            type="button"
            className="primary"
            disabled={scene.busy || cursor >= experimentIds.length}
            onClick={() => (mode === "live" ? startLive() : playExperiment(cursor))}
          >
            {mode === "live" ? "Run live" : nextLabel}
          </button>
        </div>
      </header>

      <p className="hypothesis">
        {hypothesis && <span className="claim-label">Curriculum claim</span>}
        {hypothesis}
      </p>
      {error && <p className="error">{error}</p>}

      <div className="stage-slot" ref={slotRef}>
        <div className="stage" style={{ width: SCENE_W * scale, height: SCENE_H * scale }}>
          <div className="stage-inner" style={{ transform: `scale(${scale})` }}>
            <Lab
              scene={scene}
              titles={titles}
              reducedMotion={!!reducedMotion}
              onOpenStation={(i) => setOpenIndex(i)}
              onOpenNotebook={() => setOpenIndex(0)}
            />
          </div>
        </div>
      </div>

      {/* Pinned to the room's own width, so the bar reads as part of it. */}
      <div className="under-stage" ref={underRef} style={{ width: SCENE_W * scale }}>
        <ProgressBar scene={scene} titles={titles} live={mode === "live"} />

        <footer className="legend">
          <span><i className="dot locked" /> locked</span>
          <span><i className="dot ready" /> ready</span>
          <span><i className="dot running" /> running</span>
          <span><i className="dot done" /> done - click a finished station to open its notebook page</span>
        </footer>
      </div>

      <NotebookOverlay
        data={visibleNotebook}
        openIndex={openIndex}
        titles={titles}
        showCalibration={openCalibration}
        onClose={() => {
          setOpenIndex(null);
          setOpenCalibration(false);
        }}
        onSelect={(i) => {
          setOpenCalibration(false);
          setOpenIndex(i);
        }}
      />
    </div>
  );
}

/** Keep only entries (and calibration rows) for experiments finished so far. */
function filterNotebook(nb: Notebook, finished: number[]): Notebook {
  const orders = new Set(finished.map((i) => i + 1));
  const entries = nb.entries.filter((e) => orders.has(e.order));
  const c = nb.calibration;
  const rows = c.rows.filter((r) => orders.has(r.order));
  if (rows.length === c.rows.length) return { ...nb, entries };
  const mean = (xs: number[]) =>
    xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  // Audit headline for the experiments finished so far (the written verdict and
  // Brier score describe the whole run, so they are withheld while partial).
  const audited = rows.filter((r) => r.verdict && r.verdict !== "UNAUDITED");
  const clean = audited.filter((r) => r.clean);
  const counts: Record<string, number> = {};
  audited.forEach((r) => {
    counts[r.verdict as string] = (counts[r.verdict as string] ?? 0) + 1;
  });
  const meanOut = mean(audited.map((r) => r.score));
  const cleanOut = clean.length ? mean(clean.map((r) => r.score)) ?? 0 : 0;
  const gaps = rows.flatMap((r) => (r.gap != null ? [r.gap] : []));
  const confs = rows.flatMap((r) => (r.confidence != null ? [r.confidence] : []));
  return {
    ...nb,
    entries,
    calibration: {
      rows,
      n_scored: rows.length,
      mean_confidence: mean(confs),
      mean_score: mean(rows.map((r) => r.score)),
      mean_gap: mean(gaps),
      mean_absolute_gap: mean(gaps.map(Math.abs)),
      n_overconfident: gaps.filter((g) => g > 0.15).length,
      verdict: "", // the written verdict describes the whole run
      n_audited: audited.length,
      clean_success: audited.length ? clean.length : null,
      clean_success_rate: audited.length ? clean.length / audited.length : null,
      mean_process: mean(audited.flatMap((r) => (r.process != null ? [r.process] : []))),
      lucky_rate: audited.length
        ? audited.filter((r) => r.lucky).length / audited.length : null,
      hack_gap: meanOut == null ? null
        : meanOut - (clean.length / audited.length) * cleanOut,
      brier_clean: null,
      verdict_counts: counts,
    },
  };
}

const MAX_SCALE = 6;
/** Breathing room under the room, so it is not flush against the viewport. */
const STAGE_MARGIN = 4;

/**
 * How many screen pixels one scene pixel gets.
 *
 * A scene pixel has to land on whole device pixels or the art blurs, which
 * normally means whole steps. On a 2x display a half step qualifies too - 3.5
 * CSS pixels is exactly 7 device pixels - and since the scene is 384x208, every
 * sprite position stays whole as well. That half step is most of a size up, and
 * on a laptop it is usually the difference between the room filling the window
 * and leaving a third of it empty.
 *
 * The space itself is measured rather than assumed: the slot gives the width
 * the room may use and where it starts, the strip below gives back its own
 * height, and the shell gives back its bottom padding - miss that last one and
 * the room claims a couple of pixels it does not have, which costs a scrollbar.
 * Measuring rather than reserving a constant also means the fit holds when the
 * header wraps or the legend runs to two lines.
 */
function useScale(
  slot: RefObject<HTMLDivElement>,
  under: RefObject<HTMLDivElement>,
): number {
  const [scale, setScale] = useState(3);
  useEffect(() => {
    const compute = () => {
      const el = slot.current;
      if (!el) return;
      const shell = el.parentElement;
      const padBottom = shell
        ? parseFloat(getComputedStyle(shell).paddingBottom) || 0
        : 0;
      const top = el.getBoundingClientRect().top;
      const below = under.current?.getBoundingClientRect().height ?? 0;
      const w = Math.max(320, el.clientWidth);
      const h = Math.max(
        240, window.innerHeight - top - below - padBottom - STAGE_MARGIN);
      const step = (window.devicePixelRatio || 1) >= 2 ? 0.5 : 1;
      const fit = Math.min(w / SCENE_W, h / SCENE_H);
      setScale(Math.max(1, Math.min(MAX_SCALE, Math.floor(fit / step) * step)));
    };
    compute();
    window.addEventListener("resize", compute);
    // The header and the hypothesis arrive with the curriculum and can wrap,
    // which moves the top edge; watching the document catches that without the
    // scale feeding back into it, since neither measurement includes the room.
    const ro = new ResizeObserver(compute);
    ro.observe(document.body);
    return () => {
      window.removeEventListener("resize", compute);
      ro.disconnect();
    };
  }, [slot, under]);
  return scale;
}
