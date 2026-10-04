/**
 * How far the scientist is through the experiment in front of them.
 *
 * The fill position comes from `usePlayback` along with the time it has to get
 * there; the CSS transition does the rest, so the bar glides rather than
 * ticking. Four states worth telling apart: working (the fill moves), waiting
 * (a live run between model turns - nothing has landed, so the bar holds its
 * place and says so rather than inventing movement), paused (a replay that
 * stopped mid-experiment), and complete.
 */
import type { CSSProperties } from "react";
import type { SceneState } from "../lib/usePlayback";

interface Props {
  scene: SceneState;
  titles: string[];
  /** A live run is genuinely open-ended; a replay is not. */
  live: boolean;
}

export function ProgressBar({ scene, titles, live }: Props) {
  const { progress, phase, progressMs, progressKind, activeIndex } = scene;
  const idle = progress == null;
  const done = progress != null && progress >= 1;
  // In flight with nothing to apply: the model is still thinking (live), or
  // playback has run out of recorded events (replay).
  const stalled = progress != null && !done && !scene.busy;
  const waiting = stalled && live;
  const paused = stalled && !live;
  const pct = Math.round((progress ?? 0) * 100);

  const what =
    activeIndex != null
      ? `Experiment ${activeIndex + 1}${titles[activeIndex] ? ` - ${titles[activeIndex]}` : ""}`
      : "Nothing running";

  return (
    <div
      className={
        "workbar" +
        (idle ? " idle" : "") +
        (waiting ? " waiting" : "") +
        (paused ? " paused" : "") +
        (progressKind === "done" ? " done" : "") +
        // Not " error": app.css styles a bare .error as a red panel.
        (progressKind === "error" ? " failed" : "")
      }
    >
      <div className="workbar-top">
        <span className="workbar-what">{what}</span>
        <span className="workbar-phase">
          {idle
            ? "press play"
            : (phase ?? "working") +
              (waiting ? " - waiting" : paused ? " - paused" : "")}
        </span>
        <span className="workbar-pct">{idle ? "--" : `${pct}%`}</span>
      </div>
      <div
        className="workbar-track"
        role="progressbar"
        aria-label="Experiment progress"
        aria-valuemin={0}
        aria-valuemax={100}
        // An indeterminate bar omits aria-valuenow, and a live run genuinely is
        // indeterminate while it waits on the model.
        aria-valuenow={idle || waiting ? undefined : pct}
        aria-valuetext={idle ? "not started" : `${pct}% - ${phase ?? "working"}`}
      >
        <div
          className="workbar-fill"
          style={{ width: `${pct}%`, "--fill-ms": `${Math.round(progressMs)}ms` } as CSSProperties}
        />
        {waiting && <div className="workbar-wait" />}
      </div>
    </div>
  );
}
