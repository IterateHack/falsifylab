/**
 * One spritesheet frame, or an animated loop over frames.
 *
 * Animation is a CSS `steps()` keyframe walking background-position across the
 * sheet - no JS timers per sprite, which keeps a dozen looping decor items free.
 */
import { useMemo } from "react";

interface Props {
  sheet: string;
  frameW: number;
  frameH: number;
  frames?: number;
  fps?: number;
  frame?: number;
  x: number;
  y: number;
  flip?: boolean;
  paused?: boolean;
  className?: string;
  title?: string;
  style?: React.CSSProperties;
}

export function Sprite({
  sheet, frameW, frameH, frames = 1, fps = 6, frame,
  x, y, flip, paused, className, title, style,
}: Props) {
  const animated = frames > 1 && frame === undefined && !paused;
  // The end position is passed as a custom property so one keyframe serves
  // every sheet, whatever its frame width.
  const endX = useMemo(() => `${-frameW * frames}px`, [frameW, frames]);

  const offsetX = frame !== undefined ? -frame * frameW : 0;

  return (
    <div
      className={"sprite" + (className ? ` ${className}` : "")}
      title={title}
      style={{
        left: x,
        top: y,
        width: frameW,
        height: frameH,
        backgroundImage: `url(/sprites/${sheet}.png)`,
        backgroundSize: `${frameW * frames}px ${frameH}px`,
        backgroundPosition: `${offsetX}px 0`,
        transform: flip ? "scaleX(-1)" : undefined,
        animation: animated
          ? `sprite-run ${frames / fps}s steps(${frames}) infinite`
          : undefined,
        ["--sprite-end-x" as string]: endX,
        ...style,
      } as React.CSSProperties}
    />
  );
}
