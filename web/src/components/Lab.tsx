/**
 * The room: one static scene, drawn from the generated spritesheets.
 *
 * Draw order is explicit and follows y-position - wall, floor, bench, decor on
 * the worktop, station props, then the scientist in front - so the scientist
 * passes correctly in front of the bench.
 */
import { Sprite } from "./Sprite";
import { Scientist } from "./Scientist";
import { Station } from "./Station";
import {
  BENCH, DECOR_SLOTS, DECOR_Y, FLOOR_DECOR, SCENE_H, SCENE_W, TILE, WALL_DECOR,
  WALL_H,
} from "../lib/scene";
import type { SceneState } from "../lib/usePlayback";

const DECOR_META: Record<string, { frames: number; fps: number; reactive?: boolean }> = {
  decor_beaker: { frames: 4, fps: 6, reactive: true },
  decor_burner: { frames: 3, fps: 8, reactive: true },
  decor_centrifuge: { frames: 2, fps: 8, reactive: true },
  decor_laptop: { frames: 2, fps: 2 },
  decor_flask: { frames: 3, fps: 3 },
  decor_tubes: { frames: 1, fps: 1 },
  decor_pipettes: { frames: 1, fps: 1 },
  decor_petri: { frames: 1, fps: 1 },
  decor_microscope: { frames: 1, fps: 1 },
  decor_clipboard: { frames: 1, fps: 1 },
};

interface Props {
  scene: SceneState;
  titles: string[];
  reducedMotion: boolean;
  onOpenStation: (index: number) => void;
}

export function Lab({ scene, titles, reducedMotion, onOpenStation }: Props) {
  const running = scene.activeIndex !== null && scene.statuses[scene.activeIndex] === "running";

  return (
    <div className="scene" style={{ width: SCENE_W, height: SCENE_H }}>
      <div className="wall" style={{ height: WALL_H }} />
      <div className="floor" style={{ top: WALL_H, height: SCENE_H - WALL_H }} />

      {WALL_DECOR.map((d) => (
        <Sprite key={d.sprite} sheet={d.sprite} frameW={d.w} frameH={d.h}
                x={d.x} y={d.y} />
      ))}

      <Sprite sheet="bench" frameW={BENCH.w} frameH={BENCH.h} x={BENCH.x} y={BENCH.y} />

      {DECOR_SLOTS.map((d, i) => {
        const m = DECOR_META[d.sprite] ?? { frames: 1, fps: 1 };
        // Reactive decor speeds up while an experiment is running.
        const fps = m.reactive && running ? m.fps * 2 : m.fps;
        return (
          <Sprite
            key={`${d.sprite}-${i}`}
            sheet={d.sprite}
            frameW={TILE}
            frameH={TILE}
            frames={m.frames}
            fps={fps}
            x={d.x}
            y={DECOR_Y}
            paused={reducedMotion}
            className="decor"
          />
        );
      })}

      {titles.map((title, i) => (
        <Station
          key={i}
          index={i}
          status={scene.statuses[i]}
          score={scene.scores[i]}
          confidence={scene.confidences[i]}
          title={title}
          active={scene.activeIndex === i}
          onOpen={() => onOpenStation(i)}
        />
      ))}

      {FLOOR_DECOR.map((d, i) => (
        <Sprite key={`floor-${i}`} sheet={d.sprite} frameW={TILE} frameH={TILE}
                x={d.x} y={d.y} className="decor" />
      ))}

      <Scientist
        x={scene.scientistX}
        pose={scene.pose}
        facing={scene.facing}
        walkMs={scene.walkMs}
        showBook={scene.showBook}
        reducedMotion={reducedMotion}
      />

      {scene.speech && (
        <div
          className={`speech speech-${scene.speechKind}`}
          style={{
            left: Math.max(4, Math.min(scene.scientistX - 72, SCENE_W - 168)),
            top: 112,
          }}
        >
          {scene.speech}
        </div>
      )}
    </div>
  );
}
