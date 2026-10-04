import { Sprite } from "./Sprite";
import { SCIENTIST } from "../lib/scene";
import type { Pose } from "../lib/usePlayback";

const SHEETS: Record<Pose, { sheet: string; frames: number; fps: number }> = {
  idle: { sheet: "scientist_idle", frames: 2, fps: 2 },
  walk: { sheet: "scientist_walk", frames: 4, fps: 8 },
  work: { sheet: "scientist_work", frames: 3, fps: 6 },
  read: { sheet: "scientist_read", frames: 2, fps: 2 },
  success: { sheet: "scientist_success", frames: 2, fps: 4 },
  fail: { sheet: "scientist_fail", frames: 2, fps: 3 },
};

interface Props {
  x: number;
  pose: Pose;
  facing: "left" | "right";
  walkMs: number;
  showBook: boolean;
  reducedMotion: boolean;
}

export function Scientist({ x, pose, facing, walkMs, showBook, reducedMotion }: Props) {
  const cfg = SHEETS[pose];
  return (
    <div
      className="scientist-layer"
      style={{
        transform: `translateX(${x}px)`,
        transition: walkMs > 0 ? `transform ${walkMs}ms linear` : "none",
      }}
    >
      <Sprite
        sheet={cfg.sheet}
        frameW={SCIENTIST.w}
        frameH={SCIENTIST.h}
        frames={cfg.frames}
        fps={cfg.fps}
        x={0}
        y={SCIENTIST.y}
        flip={pose === "walk" && facing === "left"}
        paused={reducedMotion && pose === "idle"}
      />
      {showBook && (
        <div className="book-pop" style={{ left: 12, top: SCIENTIST.y - 14 }}>
          <div className="book-pop-inner" />
        </div>
      )}
    </div>
  );
}
