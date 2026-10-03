/** The notebook overlay: one paper-styled tab per experiment. */
import { useEffect, useMemo, useState } from "react";
import type { Notebook as NotebookData, NotebookEntry } from "../lib/api";

interface Props {
  data: NotebookData | null;
  openIndex: number | null;
  titles: string[];
  onClose: () => void;
  onSelect: (index: number) => void;
}

export function NotebookOverlay({ data, openIndex, titles, onClose, onSelect }: Props) {
  const [showCalibration, setShowCalibration] = useState(false);

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
        {gap != null && (
          <span className={Math.abs(gap) > 0.15 ? "poor" : "good"}>
            gap {gap > 0 ? "+" : ""}
            {gap.toFixed(2)}
          </span>
        )}
      </div>

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

/** Deliberately tiny: headings, bullets, tables and bold are all the notebook uses. */
function Markdownish({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <>
      {blocks.map((block, i) => {
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
        if (/^\s*\d+\.\s+/.test(lines[0]) && lines.every((l) => /^\s*\d+\.\s+/.test(l))) {
          return (
            <ol key={i}>
              {lines.map((l, j) => (
                <li key={j}>{inline(l.replace(/^\s*\d+\.\s+/, ""))}</li>
              ))}
            </ol>
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
