import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Lab } from "./components/Lab";
import { NotebookOverlay } from "./components/Notebook";
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
        "tool_call", "tool_result", "scored", "teaching_started", "lesson_learned",
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

  const scale = useScale();

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">FalsifyLab</span>
          <span className="brand-sub">a scientist that finds out it was wrong</span>
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

      <p className="hypothesis">{hypothesis}</p>
      {error && <p className="error">{error}</p>}

      <div className="stage" style={{ width: SCENE_W * scale, height: SCENE_H * scale }}>
        <div className="stage-inner" style={{ transform: `scale(${scale})` }}>
          <Lab
            scene={scene}
            titles={titles}
            reducedMotion={!!reducedMotion}
            onOpenStation={(i) => setOpenIndex(i)}
          />
        </div>
      </div>

      <footer className="legend">
        <span><i className="dot locked" /> locked</span>
        <span><i className="dot ready" /> ready</span>
        <span><i className="dot running" /> running</span>
        <span><i className="dot done" /> done - click a finished station to open its notebook page</span>
      </footer>

      <NotebookOverlay
        data={notebook}
        openIndex={openIndex}
        titles={titles}
        onClose={() => setOpenIndex(null)}
        onSelect={setOpenIndex}
      />
    </div>
  );
}

/** Integer scaling only: a fractional scale would blur the pixel art. */
function useScale(): number {
  const [scale, setScale] = useState(3);
  useEffect(() => {
    const compute = () => {
      const w = Math.max(320, window.innerWidth - 32);
      const h = Math.max(240, window.innerHeight - 260);
      setScale(Math.max(1, Math.min(4, Math.floor(Math.min(w / SCENE_W, h / SCENE_H)))));
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, []);
  return scale;
}
