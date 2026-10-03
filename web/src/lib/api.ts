export interface LabEvent {
  seq: number;
  ts: string;
  run_id: string;
  experiment_id: string | null;
  type: string;
  payload: Record<string, any>;
}

export interface NotebookEntry {
  experiment_id: string;
  title: string;
  order: number;
  status: "locked" | "running" | "scored" | "done";
  sections: Record<string, string>;
  section_order: string[];
  section_titles: Record<string, string>;
  confidence: number | null;
  score: number | null;
  score_max: number;
  score_details: Record<string, any>;
  calibration_gap: number | null;
  applied_lesson_ids: string[];
  papers: string[];
  tool_calls_used: number;
  model: string;
  markdown: string;
}

export interface Calibration {
  rows: {
    experiment_id: string;
    order: number;
    title: string;
    confidence: number | null;
    score: number;
    gap: number | null;
  }[];
  n_scored: number;
  mean_confidence: number | null;
  mean_score: number | null;
  mean_gap: number | null;
  mean_absolute_gap: number | null;
  n_overconfident: number;
  verdict: string;
}

export interface Notebook {
  run_id: string;
  hypothesis: string;
  entries: NotebookEntry[];
  calibration: Calibration;
}

export interface RunSummary {
  run_id: string;
  kind: string;
  n_entries?: number;
  mean_score?: number | null;
  mean_gap?: number | null;
  live?: boolean;
}

const base = "";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(base + path);
  if (!r.ok) throw new Error(`${path} -> ${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

export const api = {
  runs: () => get<{ runs: RunSummary[] }>("/api/runs"),
  notebook: (runId: string) => get<Notebook>(`/api/run/${runId}/notebook`),
  events: (runId: string, experiment?: string) =>
    get<{ events: LabEvent[]; live: boolean }>(
      `/api/run/${runId}/events` + (experiment ? `?experiment=${experiment}` : ""),
    ),
  curriculum: () =>
    get<{
      id: string;
      title: string;
      hypothesis: string;
      experiments: {
        id: string;
        order: number;
        title: string;
        type: string;
        requires_lessons: string[];
        papers: string[];
      }[];
    }>("/api/curriculum"),
  startRun: async (body: { use_lessons?: boolean; backend?: string }) => {
    const r = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`start run -> ${r.status}`);
    return (await r.json()) as { run_id: string; stream: string };
  },
};
