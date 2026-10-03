/**
 * Scene geometry, in logical pixels. The whole room is 384x208 (24x13 tiles at
 * 16px) and is scaled by an integer factor, so every sprite lands on a whole
 * pixel and nothing blurs.
 */
export const TILE = 16;
export const SCENE_W = 384;
export const SCENE_H = 208;

export const WALL_H = 48;

/** The bench: 19 tiles wide, with a worktop surface band and a front face. */
export const BENCH = { x: 40, y: 88, w: 304, h: 64 };

/** Six 2-tile stations with 1-tile gaps along the front of the bench. */
export const STATION_W = 32;
export const STATION_GAP = 16;
export const STATION_X0 = 56;
export const STATION_PROP_Y = 82;
export const STATION_LIGHT_Y = 66;

export function stationX(index: number): number {
  return STATION_X0 + index * (STATION_W + STATION_GAP);
}

/** Where the scientist stands to work at station `index`. */
export function stationStandX(index: number): number {
  return stationX(index) + STATION_W / 2 - 8;
}

export const SCIENTIST = { y: 140, w: 16, h: 24, homeX: 20 };

/**
 * Decor sits in the gaps between stations and on the end caps, never over a
 * station's footprint or its click target.
 */
export const DECOR_Y = 88;
export const DECOR_SLOTS: { x: number; sprite: string }[] = [
  { x: 40, sprite: "decor_tubes" },
  { x: stationX(0) + STATION_W, sprite: "decor_beaker" },
  { x: stationX(1) + STATION_W, sprite: "decor_burner" },
  { x: stationX(2) + STATION_W, sprite: "decor_centrifuge" },
  { x: stationX(3) + STATION_W, sprite: "decor_flask" },
  { x: stationX(4) + STATION_W, sprite: "decor_laptop" },
  { x: 328, sprite: "decor_microscope" },
];

/** Floor-level clutter, drawn in front of the bench but behind the scientist. */
export const FLOOR_DECOR = [
  { x: 348, y: 150, sprite: "decor_petri" },
  { x: 14, y: 150, sprite: "decor_clipboard" },
  { x: 356, y: 118, sprite: "decor_pipettes" },
];

export const WALL_DECOR = [
  { x: 24, y: 10, sprite: "whiteboard", w: 64, h: 32 },
  { x: 160, y: 8, sprite: "window", w: 48, h: 32 },
  { x: 288, y: 22, sprite: "shelf", w: 48, h: 16 },
];

export type StationStatus = "locked" | "ready" | "running" | "done";

export const STATUS_FRAME: Record<StationStatus, number> = {
  locked: 0,
  ready: 1,
  running: 2,
  done: 3,
};
