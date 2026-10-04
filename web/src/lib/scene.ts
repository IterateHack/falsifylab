/**
 * Scene geometry, in logical pixels. The whole room is 384x208 (24x13 tiles at
 * 16px) and is scaled by an integer factor, so every sprite lands on a whole
 * pixel and nothing blurs.
 */
export const TILE = 16;
export const SCENE_W = 384;
export const SCENE_H = 208;

export const WALL_H = 48;

/**
 * The dado rail along the bottom of the tiled wall. Every lab corridor has one
 * and it is the one place the room gets to be a colour, which keeps the white
 * from reading as unfinished.
 */
export const WALL_RAIL = { y: WALL_H - 4, h: 4 };

/** The bench: 19 tiles wide, with a worktop surface band and a front face. */
export const BENCH = { x: 40, y: 88, w: 304, h: 64 };

/** Six 2-tile stations with 1-tile gaps along the front of the bench. */
export const STATION_W = 32;
export const STATION_GAP = 16;
export const STATION_X0 = 56;
/**
 * The bench worktop's top edge is at y=104 (BENCH.y + 16). A 32px prop therefore
 * starts at 72 so its base rests on the worktop rather than sinking into the
 * front face. Decor is 16px and starts at 88 for the same reason.
 */
export const WORKTOP_Y = BENCH.y + 16;
export const STATION_PROP_Y = WORKTOP_Y - 32;
export const STATION_LIGHT_Y = 58;
export const STATION_PLATE_Y = WORKTOP_Y + 10;
export const SCORE_BADGE_Y = 44;

export function stationX(index: number): number {
  return STATION_X0 + index * (STATION_W + STATION_GAP);
}

/** Where the scientist stands to work at station `index`. */
export function stationStandX(index: number): number {
  return stationX(index) + STATION_W / 2 - 8;
}

export const SCIENTIST = { y: 140, w: 16, h: 24, homeX: 20 };

/**
 * The speech bubble, on the floor below the scientist. It has SCENE_H - SPEECH_Y
 * to live in and the scene clips, so a long line used to run off the bottom
 * edge mid-word. Three things keep it inside: the text is cut to roughly what
 * fits, the CSS clamps to whole lines so a cut never slices through glyphs, and
 * the height is capped as a backstop.
 */
export const SPEECH_Y = 162;
export const SPEECH_W = 190;
export const SPEECH_LINES = 3;
export const SPEECH_MAX_H = SCENE_H - SPEECH_Y - 6;
/** Three ragged lines at SPEECH_W, with room left for the ellipsis. */
export const SPEECH_MAX_CHARS = 74;

/**
 * Decor sits in the gaps between stations and on the end caps, never over a
 * station's footprint or its click target.
 */
export const DECOR_Y = WORKTOP_Y - 16;
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
  { x: 356, y: 118, sprite: "decor_pipettes" },
];

/**
 * The lab notebook, lying on the floor where the scientist left it. Drawn like
 * the rest of the clutter but clickable, so the notebook can be opened from
 * inside the room and not only from the top bar.
 *
 * Kept clear of SCIENTIST.homeX so the idle scientist is not standing on it.
 */
export const NOTEBOOK_PROP = { x: 4, y: 178, sprite: "decor_clipboard", size: TILE };

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
