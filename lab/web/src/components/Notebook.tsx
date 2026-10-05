/** The notebook overlay: one paper-styled tab per experiment. */
import { useEffect, useMemo, useState } from "react";
import type { Audit, Notebook as NotebookData, NotebookEntry } from "../lib/api";

const VERDICT_LABEL: Record<string, string> = {
  VALID_SUCCESS: "Clean success",
  WRONG_CONCLUSION: "Wrong conclusion",
  INSUFFICIENT_EVIDENCE: "Insufficient evidence",
  PROTOCOL_VIOLATION: "Protocol violation",
  UNSAFE_ACTION: "Unsafe action",
  REWARD_HACK: "Reward hack",
  PARSE_FAILURE: "Parse failure",
  UNAUDITED: "Unaudited",
};

function verdictClass(v: string): string {
  if (v === "VALID_SUCCESS") return "v-clean";
  if (v === "WRONG_CONCLUSION") return "v-wrong";
  if (v === "INSUFFICIENT_EVIDENCE") return "v-weak";
  if (v === "UNAUDITED") return "v-none";
  return "v-bad";
}

export function VerdictChip({ verdict }: { verdict: string }) {
  return (
    <span className={"verdict-chip " + verdictClass(verdict)}>
      {VERDICT_LABEL[verdict] ?? verdict}
    </span>
  );
}

function AuditBox({ audit }: { audit: Audit }) {
  const unaudited = audit.verdict === "UNAUDITED";
  return (
    <div className="audit-box">
      <div>
        <strong>Audit of the path: </strong>
        <VerdictChip verdict={audit.verdict} />{" "}
        {!unaudited && (
          <span className="muted">
            outcome {audit.outcome.toFixed(2)}
            {audit.process != null && <>, process {audit.process.toFixed(2)}</>}
            {audit.stability != null && <>, stability {audit.stability.toFixed(2)}</>}
          </span>
        )}
      </div>
      {unaudited && audit.process_note && <p className="muted">{audit.process_note}</p>}
      {audit.flags.length > 0 && (
        <ul>
          {audit.flags.map((f, i) => (
            <li key={i} className={f.severity === "hard" ? "flag-hard" : "flag-soft"}>
              {f.code.replace(/_/g, " ")}
              <span className="muted"> - {f.evidence}</span>
            </li>
          ))}
        </ul>
      )}
      {audit.checkpoints.length > 0 && (
        <table className="audit-steps">
          <tbody>
            {audit.checkpoints.map((c) => (
              <tr key={c.id}>
                <td>{c.desc || c.id}</td>
                <td className={c.passed ? "good" : "poor"}>{c.passed ? "shown" : "not shown"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!unaudited && audit.process_note && <p className="muted">{audit.process_note}</p>}
    </div>
  );
}

interface Props {
  data: NotebookData | null;
  openIndex: number | null;
  titles: string[];
  showCalibration?: boolean;
  onClose: () => void;
  onSelect: (index: number) => void;
}

export function NotebookOverlay({
  data, openIndex, titles, showCalibration: initialCalibration, onClose, onSelect,
}: Props) {
  const [showCalibration, setShowCalibration] = useState(!!initialCalibration);
  useEffect(() => {
    setShowCalibration(!!initialCalibration);
  }, [initialCalibration]);

  useEffect(() => {
    if (openIndex === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openIndex, onClose]);

  const entry: NotebookEntry | null = useMemo(() => {
    if (!data || openIndex === null) return null;
    return data.entries.find((e) => e.order === openIndex + 1) ?? null;
  }, [data, openIndex]);

  if (openIndex === null) return null;

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label="Lab notebook">
      <div className="notebook">
        <div className="notebook-head">
          <h2>Lab notebook</h2>
          <div className="notebook-actions">
            <button
              type="button"
              className={"tab-btn" + (showCalibration ? " on" : "")}
              onClick={() => setShowCalibration((v) => !v)}
            >
              Calibration
            </button>
            <button type="button" className="close-btn" onClick={onClose}>
              close
            </button>
          </div>
        </div>

        <div className="notebook-tabs">
          {titles.map((t, i) => {
            const e = data?.entries.find((x) => x.order === i + 1);
            const done = e && e.status === "done";
            return (
              <button
                key={i}
                type="button"
                className={
                  "tab" + (i === openIndex ? " current" : "") + (done ? " done" : "")
                }
                onClick={() => {
                  setShowCalibration(false);
                  onSelect(i);
                }}
              >
                <span className="tab-num">{i + 1}</span>
                <span className="tab-title">{t}</span>
                {e?.score != null && (
                  <span className={"tab-score " + (e.score >= 0.6 ? "good" : "poor")}>
                    {e.score.toFixed(2)}
                  </span>
                )}
                {e?.audit && e.audit.verdict !== "VALID_SUCCESS" && (
                  <span title={VERDICT_LABEL[e.audit.verdict] ?? e.audit.verdict}
                        className="tab-score poor">!</span>
                )}
              </button>
            );
          })}
        </div>

        <div className="notebook-page">
          {showCalibration ? (
            <CalibrationPage data={data} />
          ) : entry && entry.status !== "locked" ? (
            <EntryPage entry={entry} />
          ) : (
            <div className="blank-page">
              <p>This page is blank.</p>
              <p className="muted">
                Experiment {openIndex + 1} has not been run yet.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function EntryPage({ entry }: { entry: NotebookEntry }) {
  const gap = entry.calibration_gap;
  return (
    <article>
      <h3>
        Experiment {entry.order}: {entry.title}
      </h3>
      <div className="entry-meta">
        {entry.model && <span>model {entry.model}</span>}
        <span>{entry.tool_calls_used} tool calls</span>
        {entry.confidence != null && (
          <span>stated confidence {entry.confidence.toFixed(2)}</span>
        )}
        {entry.score != null && (
          <span className={entry.score >= 0.6 ? "good" : "poor"}>
            score {entry.score.toFixed(2)}
          </span>
        )}
        {entry.unenforced_limits && entry.unenforced_limits.length > 0 && (
          <span className="poor" title="A run without the sandbox's memory cap is not comparable to the recorded runs.">
            sandbox limits not enforced on this host: {entry.unenforced_limits.join("; ")}
          </span>
        )}
        {gap != null && (
          <span className={Math.abs(gap) > 0.15 ? "poor" : "good"}>
            gap {gap > 0 ? "+" : ""}
            {gap.toFixed(2)}
          </span>
        )}
      </div>

      {entry.audit && <AuditBox audit={entry.audit} />}

      {entry.applied_lesson_ids.length > 0 && (
        <div className="applied">
          Applied lessons from: {entry.applied_lesson_ids.join(", ")}
        </div>
      )}

      {entry.section_order.map((key, i) => {
        const body = entry.sections[key];
        if (!body) return null;
        return (
          <section key={key} className={`nb-section nb-${key}`}>
            <h4>
              {i + 1}. {entry.section_titles[key]}
            </h4>
            <Markdownish text={body} />
          </section>
        );
      })}

      {entry.papers.length > 0 && (
        <section className="nb-section">
          <h4>Teaching source</h4>
          <ul>
            {entry.papers.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

function CalibrationPage({ data }: { data: NotebookData | null }) {
  if (!data) return <div className="blank-page">No run loaded.</div>;
  const c = data.calibration;
  if (!c.rows.length)
    return <div className="blank-page">Nothing scored yet.</div>;
  return (
    <article>
      <h3>Calibration summary</h3>
      {c.n_audited ? (
        <div className="audit-box">
          <strong>
            Clean success: {c.clean_success} of {c.n_audited}
          </strong>
          <span className="muted">
            {" "}
            (raw mean score {c.mean_score?.toFixed(2)}
            {c.mean_process != null && <>, mean process {c.mean_process.toFixed(2)}</>}
            {c.hack_gap != null && <>, hack gap {c.hack_gap.toFixed(2)}</>}
            {c.lucky_rate != null && c.lucky_rate > 0 && (
              <>, right-answer-wrong-path {Math.round(c.lucky_rate * 100)}%</>
            )}
            )
          </span>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            Only an attempt whose answer, method and integrity all hold counts. The raw
            score stays beside it because a flagged path can still score high.
          </p>
        </div>
      ) : (
        <p className="muted">
          This run has no path audit (it was recorded before the path was logged), so no
          clean-success figure is claimed.
        </p>
      )}
      <p className="muted">
        Stated confidence is written before any tool unlocks. The gap is
        confidence minus score: positive means overconfident.
      </p>
      <table className="cal-table">
        <thead>
          <tr>
            <th>#</th>
            <th>experiment</th>
            <th>confidence</th>
            <th>score</th>
            <th>gap</th>
            <th>audit</th>
          </tr>
        </thead>
        <tbody>
          {c.rows.map((r) => (
            <tr key={r.experiment_id}>
              <td>{r.order}</td>
              <td>{r.title}</td>
              <td>{r.confidence?.toFixed(2) ?? "-"}</td>
              <td>{r.score.toFixed(2)}</td>
              <td className={r.gap != null && Math.abs(r.gap) > 0.15 ? "poor" : "good"}>
                {r.gap != null ? (r.gap > 0 ? "+" : "") + r.gap.toFixed(2) : "-"}
              </td>
              <td>{r.verdict ? <VerdictChip verdict={r.verdict} /> : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="cal-bars">
        {c.rows.map((r) => (
          <div className="cal-row" key={r.experiment_id}>
            <span className="cal-label">{r.order}</span>
            <div className="cal-track">
              <div
                className="cal-bar conf"
                style={{ width: `${(r.confidence ?? 0) * 100}%` }}
                title={`stated confidence ${r.confidence?.toFixed(2)}`}
              />
              <div
                className="cal-bar score"
                style={{ width: `${r.score * 100}%` }}
                title={`score ${r.score.toFixed(2)}`}
              />
            </div>
          </div>
        ))}
        <div className="cal-key">
          <span className="swatch conf" /> stated confidence
          <span className="swatch score" /> score
        </div>
      </div>
      <p className="verdict">{c.verdict}</p>
    </article>
  );
}

const ORDERED_ITEM = /^\s*(\d+)\.\s+/;

/**
 * Consecutive numbered blocks form one list even when blank lines separate the
 * items, so they count 1. 2. 3. instead of each restarting at 1.
 */
function groupOrderedLists(blocks: string[]): (string | string[])[] {
  const out: (string | string[])[] = [];
  for (const block of blocks) {
    if (!ORDERED_ITEM.test(block.split("\n")[0])) {
      out.push(block);
      continue;
    }
    const last = out[out.length - 1];
    const items = Array.isArray(last) ? last : [];
    if (!Array.isArray(last)) out.push(items);
    for (const line of block.split("\n")) {
      if (ORDERED_ITEM.test(line) || items.length === 0) items.push(line);
      else items[items.length - 1] += "\n" + line;
    }
  }
  return out;
}

/** Deliberately tiny: headings, bullets, numbered lists, tables and bold are all the notebook uses. */
function Markdownish({ text }: { text: string }) {
  const blocks = groupOrderedLists(text.split(/\n{2,}/));
  return (
    <>
      {blocks.map((block, i) => {
        if (Array.isArray(block)) {
          const start = Number(block[0].match(ORDERED_ITEM)?.[1] ?? 1);
          return (
            <ol key={i} start={start}>
              {block.map((item, j) => (
                <li key={j}>{inline(item.replace(ORDERED_ITEM, ""))}</li>
              ))}
            </ol>
          );
        }
        const lines = block.split("\n");
        if (lines.every((l) => l.trim().startsWith("|")) && lines.length > 1) {
          const rows = lines
            .filter((l) => !/^\|[\s|:-]+\|$/.test(l.trim()))
            .map((l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
          const [head, ...body] = rows;
          return (
            <table className="nb-table" key={i}>
              <thead>
                <tr>{head.map((h, j) => <th key={j}>{inline(h)}</th>)}</tr>
              </thead>
              <tbody>
                {body.map((r, j) => (
                  <tr key={j}>{r.map((c, k) => <td key={k}>{inline(c)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          );
        }
        if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
          return (
            <ul key={i}>
              {lines.map((l, j) => (
                <li key={j}>{inline(l.replace(/^\s*[-*]\s+/, ""))}</li>
              ))}
            </ul>
          );
        }
        return <p key={i}>{inline(block)}</p>;
      })}
    </>
  );
}

function inline(s: string): React.ReactNode {
  const parts = s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("`") && p.endsWith("`")) return <code key={i}>{p.slice(1, -1)}</code>;
    return <span key={i}>{p}</span>;
  });
}
