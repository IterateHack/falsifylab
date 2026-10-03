import { Sprite } from "./Sprite";
import {
  STATION_W, STATION_PROP_Y, STATION_LIGHT_Y, STATUS_FRAME, stationX,
  type StationStatus,
} from "../lib/scene";

interface Props {
  index: number;
  status: StationStatus;
  score: number | null;
  confidence: number | null;
  title: string;
  active: boolean;
  onOpen: () => void;
}

export function Station({
  index, status, score, confidence, title, active, onOpen,
}: Props) {
  const x = stationX(index);
  const clickable = status === "done";
  return (
    <>
      <Sprite
        sheet={`station_${index + 1}`}
        frameW={STATION_W}
        frameH={32}
        x={x}
        y={STATION_PROP_Y}
        className={status === "locked" ? "station-prop dim" : "station-prop"}
      />
      <Sprite
        sheet="status_lights"
        frameW={8}
        frameH={8}
        frames={4}
        frame={STATUS_FRAME[status]}
        x={x + STATION_W / 2 - 4}
        y={STATION_LIGHT_Y}
        className={status === "running" ? "status-light blink" : "status-light"}
      />
      <div className="station-plate" style={{ left: x, top: STATION_LIGHT_Y + 10 }}>
        {index + 1}
      </div>
      {score !== null && (
        <div
          className={"score-badge " + (score >= 0.6 ? "good" : "poor")}
          style={{ left: x - 4, top: STATION_LIGHT_Y - 14 }}
        >
          {score.toFixed(2)}
        </div>
      )}
      <button
        type="button"
        className={
          "station-hit" +
          (clickable ? " clickable" : "") +
          (active ? " active" : "")
        }
        style={{ left: x - 2, top: STATION_PROP_Y - 2, width: STATION_W + 4, height: 40 }}
        onClick={clickable ? onOpen : undefined}
        disabled={!clickable}
        aria-label={
          clickable
            ? `Open notebook page for experiment ${index + 1}: ${title}`
            : `Experiment ${index + 1}: ${title} (${status})`
        }
        title={
          clickable
            ? `${title} - score ${score?.toFixed(2)}${
                confidence !== null ? `, stated confidence ${confidence.toFixed(2)}` : ""
              }. Click to open the notebook.`
            : `${title} (${status})`
        }
      />
    </>
  );
}
