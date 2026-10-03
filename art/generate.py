"""Generate the lab's pixel art as PNG spritesheets.

Everything here is drawn from code, so the art is versioned, licence-clean and
re-tweakable, and there is no asset pack to credit or to get wrong. The palette
is deliberately small and flat - the look comes from consistent 16x16 tiles, a
limited ramp and hard pixel edges, not from gradients.

Run:  python art/generate.py        (writes to web/public/sprites/)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "sprites"
TILE = 16

# A 20-ish colour ramp. Named by role so the drawing code reads like intent.
C = {
    "transparent": (0, 0, 0, 0),
    "outline":     (38, 32, 52, 255),
    "floor_a":     (92, 100, 122, 255),
    "floor_b":     (82, 90, 112, 255),
    "floor_line":  (70, 78, 98, 255),
    "wall":        (58, 66, 92, 255),
    "wall_light":  (72, 82, 112, 255),
    "wall_dark":   (44, 50, 72, 255),
    "bench":       (150, 122, 96, 255),
    "bench_light": (176, 146, 116, 255),
    "bench_dark":  (116, 92, 70, 255),
    "steel":       (176, 186, 198, 255),
    "steel_dark":  (132, 142, 158, 255),
    "glass":       (196, 226, 236, 255),
    "glass_dark":  (150, 190, 208, 255),
    "coat":        (238, 242, 248, 255),
    "coat_shade":  (202, 210, 224, 255),
    "skin":        (226, 176, 140, 255),
    "skin_dark":   (196, 146, 112, 255),
    "hair":        (62, 48, 44, 255),
    "liquid_cyan": (86, 206, 214, 255),
    "liquid_pink": (226, 118, 162, 255),
    "liquid_amber": (240, 176, 76, 255),
    "liquid_green": (126, 206, 124, 255),
    "flame":       (250, 188, 72, 255),
    "flame_hot":   (252, 232, 150, 255),
    "flame_blue":  (120, 190, 240, 255),
    "paper":       (246, 242, 230, 255),
    "screen":      (118, 214, 198, 255),
    "screen_off":  (72, 104, 112, 255),
    "led_red":     (226, 86, 86, 255),
    "led_amber":   (240, 176, 76, 255),
    "led_green":   (126, 216, 124, 255),
    "led_grey":    (104, 112, 132, 255),
    "shadow":      (40, 36, 54, 90),
}


def img(w: int, h: int) -> Image.Image:
    return Image.new("RGBA", (w, h), C["transparent"])


def px(d: ImageDraw.ImageDraw, x: int, y: int, c) -> None:
    d.point((x, y), fill=c)


def rect(d: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, c) -> None:
    # Normalise so callers can pass coordinates derived from a signed offset
    # (a helix strand crossing the centre line) without ordering them first.
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    d.rectangle([x0, y0, x1, y1], fill=c)


# ---------------------------------------------------------------------------
# the scientist
# ---------------------------------------------------------------------------
SCI_W, SCI_H = 16, 24


def _sci_base(d: ImageDraw.ImageDraw, bob: int = 0) -> None:
    """Head, coat and arms shared by every pose. `bob` shifts the body 1px."""
    y = bob
    # head
    rect(d, 5, 2 + y, 10, 7 + y, C["skin"])
    rect(d, 5, 2 + y, 10, 3 + y, C["hair"])
    px(d, 4, 3 + y, C["hair"])
    px(d, 11, 3 + y, C["hair"])
    px(d, 6, 5 + y, C["outline"])        # eyes
    px(d, 9, 5 + y, C["outline"])
    px(d, 7, 7 + y, C["skin_dark"])
    # lab coat torso
    rect(d, 4, 8 + y, 11, 17 + y, C["coat"])
    rect(d, 4, 8 + y, 4, 17 + y, C["coat_shade"])
    rect(d, 11, 8 + y, 11, 17 + y, C["coat_shade"])
    px(d, 7, 9 + y, C["coat_shade"])     # collar
    px(d, 8, 9 + y, C["coat_shade"])
    rect(d, 7, 11 + y, 8, 15 + y, C["coat_shade"])   # coat seam
    px(d, 10, 12 + y, C["liquid_cyan"])  # pocket pen


def _sci_legs(d: ImageDraw.ImageDraw, left_fwd: int, right_fwd: int, bob: int = 0) -> None:
    y = bob
    rect(d, 5, 18 + y, 6, 21 + y - left_fwd, C["wall_dark"])
    rect(d, 9, 18 + y, 10, 21 + y - right_fwd, C["wall_dark"])
    rect(d, 5, 22 + y - left_fwd, 7, 22 + y - left_fwd, C["outline"])
    rect(d, 8, 22 + y - right_fwd, 10, 22 + y - right_fwd, C["outline"])


def sprite_walk() -> Image.Image:
    """Four-frame walk cycle, facing right. Mirrored in CSS for walking left."""
    sheet = img(SCI_W * 4, SCI_H)
    phases = [(0, 0, 0), (2, 0, 1), (0, 0, 0), (0, 2, 1)]
    for i, (lf, rf, bob) in enumerate(phases):
        frame = img(SCI_W, SCI_H)
        d = ImageDraw.Draw(frame)
        rect(d, 4, 23, 11, 23, C["shadow"])
        _sci_base(d, bob)
        _sci_legs(d, lf, rf, bob)
        # trailing arm swings opposite the leading leg
        arm = 1 if lf else (-1 if rf else 0)
        rect(d, 12, 10 + bob, 12, 14 + bob + arm, C["coat"])
        px(d, 12, 15 + bob + arm, C["skin"])
        sheet.paste(frame, (i * SCI_W, 0), frame)
    return sheet


def sprite_idle() -> Image.Image:
    """Two frames, facing the bench (away from the viewer): a breathing loop."""
    sheet = img(SCI_W * 2, SCI_H)
    for i, bob in enumerate((0, 1)):
        frame = img(SCI_W, SCI_H)
        d = ImageDraw.Draw(frame)
        rect(d, 4, 23, 11, 23, C["shadow"])
        y = bob
        rect(d, 5, 2 + y, 10, 7 + y, C["hair"])      # back of the head
        rect(d, 4, 8 + y, 11, 17 + y, C["coat"])
        rect(d, 4, 8 + y, 4, 17 + y, C["coat_shade"])
        rect(d, 11, 8 + y, 11, 17 + y, C["coat_shade"])
        _sci_legs(d, 0, 0, bob)
        rect(d, 3, 10 + y, 3, 15 + y, C["coat"])
        rect(d, 12, 10 + y, 12, 15 + y, C["coat"])
        sheet.paste(frame, (i * SCI_W, 0), frame)
    return sheet


def sprite_work() -> Image.Image:
    """Three frames: facing the bench, arms moving over the apparatus."""
    sheet = img(SCI_W * 3, SCI_H)
    for i, lift in enumerate((0, 1, 2)):
        frame = img(SCI_W, SCI_H)
        d = ImageDraw.Draw(frame)
        rect(d, 4, 23, 11, 23, C["shadow"])
        rect(d, 5, 2, 10, 7, C["hair"])
        rect(d, 4, 8, 11, 17, C["coat"])
        rect(d, 4, 8, 4, 17, C["coat_shade"])
        rect(d, 11, 8, 11, 17, C["coat_shade"])
        _sci_legs(d, 0, 0, 0)
        # both arms reach forward onto the bench, alternating height
        rect(d, 2, 9 + lift, 3, 13 + lift, C["coat"])
        px(d, 2, 14 + lift, C["skin"])
        rect(d, 12, 9 + (2 - lift), 13, 13 + (2 - lift), C["coat"])
        px(d, 13, 14 + (2 - lift), C["skin"])
        sheet.paste(frame, (i * SCI_W, 0), frame)
    return sheet


def sprite_read() -> Image.Image:
    """Two frames: holding a paper, head tilting as it reads."""
    sheet = img(SCI_W * 2, SCI_H)
    for i, tilt in enumerate((0, 1)):
        frame = img(SCI_W, SCI_H)
        d = ImageDraw.Draw(frame)
        rect(d, 4, 23, 11, 23, C["shadow"])
        _sci_base(d, 0)
        _sci_legs(d, 0, 0, 0)
        rect(d, 3, 13 + tilt, 12, 18 + tilt, C["paper"])
        rect(d, 3, 13 + tilt, 12, 13 + tilt, C["coat_shade"])
        for ly in range(15 + tilt, 18 + tilt, 2):
            rect(d, 5, ly, 10, ly, C["steel_dark"])
        sheet.paste(frame, (i * SCI_W, 0), frame)
    return sheet


def sprite_react(kind: str) -> Image.Image:
    """Two frames each for the success and failure poses."""
    sheet = img(SCI_W * 2, SCI_H)
    for i in range(2):
        frame = img(SCI_W, SCI_H)
        d = ImageDraw.Draw(frame)
        rect(d, 4, 23, 11, 23, C["shadow"])
        bob = i if kind == "success" else 0
        _sci_base(d, bob)
        _sci_legs(d, 0, 0, bob)
        if kind == "success":
            raise_by = 4 + i * 2
            rect(d, 2, 10 + bob - raise_by, 3, 14 + bob, C["coat"])
            px(d, 2, 9 + bob - raise_by, C["skin"])
            rect(d, 12, 10 + bob - raise_by, 13, 14 + bob, C["coat"])
            px(d, 13, 9 + bob - raise_by, C["skin"])
            px(d, 6, 5 + bob, C["outline"])
            px(d, 9, 5 + bob, C["outline"])
            rect(d, 7, 7 + bob, 8, 7 + bob, C["outline"])   # smile
        else:
            # hand to the head
            rect(d, 11, 6 + i, 12, 11, C["coat"])
            px(d, 11, 5 + i, C["skin"])
            rect(d, 6, 5, 6, 5, C["outline"])
            rect(d, 9, 5, 9, 5, C["outline"])
            px(d, 7, 7, C["skin_dark"])
            px(d, 8, 7, C["skin_dark"])
        sheet.paste(frame, (i * SCI_W, 0), frame)
    return sheet


# ---------------------------------------------------------------------------
# room tiles and the bench
# ---------------------------------------------------------------------------
def tile_floor() -> Image.Image:
    """Two-tone lab floor tile with a grout line, so the room reads as tiled."""
    t = img(TILE, TILE)
    d = ImageDraw.Draw(t)
    rect(d, 0, 0, TILE - 1, TILE - 1, C["floor_a"])
    rect(d, 0, 0, 7, 7, C["floor_b"])
    rect(d, 8, 8, TILE - 1, TILE - 1, C["floor_b"])
    rect(d, 0, 0, TILE - 1, 0, C["floor_line"])
    rect(d, 0, 0, 0, TILE - 1, C["floor_line"])
    return t


def tile_wall() -> Image.Image:
    t = img(TILE, TILE)
    d = ImageDraw.Draw(t)
    rect(d, 0, 0, TILE - 1, TILE - 1, C["wall"])
    rect(d, 0, 0, TILE - 1, 1, C["wall_light"])
    rect(d, 0, TILE - 2, TILE - 1, TILE - 1, C["wall_dark"])
    return t


def prop_window() -> Image.Image:
    w = img(TILE * 3, TILE * 2)
    d = ImageDraw.Draw(w)
    rect(d, 0, 0, TILE * 3 - 1, TILE * 2 - 1, C["steel_dark"])
    rect(d, 2, 2, TILE * 3 - 3, TILE * 2 - 3, C["glass"])
    rect(d, 2, 2, TILE * 3 - 3, 6, C["glass_dark"])
    rect(d, TILE * 3 // 2 - 1, 2, TILE * 3 // 2, TILE * 2 - 3, C["steel_dark"])
    rect(d, 2, TILE - 1, TILE * 3 - 3, TILE, C["steel_dark"])
    return w


def prop_whiteboard() -> Image.Image:
    w = img(TILE * 4, TILE * 2)
    d = ImageDraw.Draw(w)
    rect(d, 0, 0, TILE * 4 - 1, TILE * 2 - 1, C["steel_dark"])
    rect(d, 1, 1, TILE * 4 - 2, TILE * 2 - 3, C["paper"])
    # a scrawled dose-response curve and the hypothesis
    for i, x in enumerate(range(5, TILE * 4 - 8)):
        y = 22 - int(14 / (1 + 2.718 ** (-(x - 30) / 4.0)))
        px(d, x, y, C["liquid_cyan"])
    rect(d, 5, 6, 28, 6, C["steel_dark"])
    rect(d, 5, 9, 20, 9, C["steel_dark"])
    rect(d, 4, 23, TILE * 4 - 6, 23, C["steel_dark"])
    rect(d, 0, TILE * 2 - 2, TILE * 4 - 1, TILE * 2 - 1, C["steel"])
    return w


def prop_shelf() -> Image.Image:
    w = img(TILE * 3, TILE)
    d = ImageDraw.Draw(w)
    rect(d, 0, TILE - 3, TILE * 3 - 1, TILE - 1, C["bench_dark"])
    rect(d, 0, TILE - 4, TILE * 3 - 1, TILE - 4, C["bench"])
    for i, (x, col) in enumerate([(3, "liquid_cyan"), (9, "liquid_pink"),
                                  (15, "liquid_amber"), (21, "liquid_green"),
                                  (27, "liquid_cyan"), (33, "liquid_pink")]):
        h = 5 + (i % 3)
        rect(d, x, TILE - 4 - h, x + 3, TILE - 5, C["glass"])
        rect(d, x, TILE - 7, x + 3, TILE - 5, C[col])
        rect(d, x, TILE - 4 - h, x + 3, TILE - 4 - h, C["steel"])
    return w


def prop_bench(width_tiles: int = 19) -> Image.Image:
    """The long bench: a worktop, a front panel with drawer lines, and a shadow."""
    w, h = TILE * width_tiles, TILE * 4
    b = img(w, h)
    d = ImageDraw.Draw(b)
    top = TILE
    rect(d, 0, top, w - 1, top + 5, C["bench_light"])       # worktop
    rect(d, 0, top + 6, w - 1, h - 6, C["bench"])           # front face
    rect(d, 0, h - 6, w - 1, h - 3, C["bench_dark"])        # plinth
    rect(d, 0, top, w - 1, top, C["paper"])                 # worktop highlight
    rect(d, 0, h - 2, w - 1, h - 1, C["shadow"])
    for x in range(TILE, w - TILE, TILE * 2):               # drawer seams
        rect(d, x, top + 9, x, h - 8, C["bench_dark"])
        rect(d, x + 6, top + 13, x + 10, top + 13, C["steel"])
    return b


# ---------------------------------------------------------------------------
# station props - one per experiment, plus status lights
# ---------------------------------------------------------------------------
def station_prop(kind: str) -> Image.Image:
    """A 2x2-tile apparatus that sits on the bench front edge."""
    s = img(TILE * 2, TILE * 2)
    d = ImageDraw.Draw(s)
    base_y = TILE * 2 - 1

    if kind == "dna":                       # exp1 - genetics
        for i in range(14):
            y = base_y - 2 - i
            off = int(4 * math.sin(i / 2.2))
            px(d, 10 + off, y, C["liquid_cyan"])
            px(d, 10 - off, y, C["liquid_pink"])
            if i % 3 == 0:
                rect(d, 10 - off, y, 10 + off, y, C["steel_dark"])
        rect(d, 6, base_y - 1, 14, base_y, C["steel_dark"])
    elif kind == "structure":               # exp2 - cryo-EM / model
        rect(d, 4, base_y - 3, 20, base_y, C["steel_dark"])
        rect(d, 11, 14, 12, base_y - 4, C["steel_dark"])   # stand post
        for cx, cy, col in [(9, 12, "liquid_cyan"), (14, 9, "liquid_amber"),
                            (19, 13, "liquid_green"), (12, 5, "liquid_pink")]:
            rect(d, cx - 1, cy - 1, cx + 1, cy + 1, C[col])
        rect(d, 10, 11, 13, 10, C["steel"])
        rect(d, 15, 10, 18, 12, C["steel"])
        rect(d, 13, 8, 13, 6, C["steel"])
    elif kind == "peptide":                 # exp3 - peptide chain
        for i in range(6):
            x = 3 + i * 4
            y = base_y - 6 - (3 if i % 2 else 0)
            rect(d, x, y, x + 2, y + 2, C["liquid_amber"] if i % 2 else C["liquid_pink"])
            if i:
                rect(d, x - 2, y + 1, x, y + 1, C["steel_dark"])
        rect(d, 2, base_y - 1, 21, base_y, C["steel_dark"])
    elif kind == "plate":                   # exp4 - assay plate
        rect(d, 2, base_y - 9, 21, base_y, C["coat_shade"])
        rect(d, 2, base_y - 9, 21, base_y - 9, C["coat"])
        for r in range(3):
            for c in range(6):
                col = [C["liquid_cyan"], C["liquid_green"], C["liquid_amber"]][(r + c) % 3]
                px(d, 4 + c * 3, base_y - 7 + r * 3, col)
    elif kind == "flask":                   # exp5 - species / compound
        rect(d, 9, 4, 14, 8, C["glass"])
        rect(d, 6, 9, 17, base_y - 1, C["glass"])
        rect(d, 6, base_y - 6, 17, base_y - 1, C["liquid_green"])
        rect(d, 9, 3, 14, 3, C["steel"])
        rect(d, 5, base_y, 18, base_y, C["steel_dark"])
    else:                                   # exp6 - the verdict: notebook + pen
        rect(d, 3, base_y - 8, 20, base_y, C["paper"])
        rect(d, 3, base_y - 8, 20, base_y - 8, C["coat_shade"])
        for ly in range(base_y - 6, base_y - 1, 2):
            rect(d, 5, ly, 18, ly, C["steel_dark"])
        rect(d, 16, base_y - 11, 17, base_y - 7, C["liquid_pink"])
    return s


def status_lights() -> Image.Image:
    """Four 8x8 lamps: locked, ready, running, done."""
    sheet = img(8 * 4, 8)
    for i, col in enumerate(["led_grey", "led_amber", "led_red", "led_green"]):
        f = img(8, 8)
        d = ImageDraw.Draw(f)
        rect(d, 1, 1, 6, 6, C["outline"])
        rect(d, 2, 2, 5, 5, C[col])
        px(d, 2, 2, C["paper"])
        sheet.paste(f, (i * 8, 0), f)
    return sheet


# ---------------------------------------------------------------------------
# animated decor (plan section 7.2)
# ---------------------------------------------------------------------------
def decor_beaker() -> Image.Image:
    """Bubbling beaker, 4-frame loop. The UI speeds this up while an experiment runs."""
    sheet = img(TILE * 4, TILE)
    bubbles = [[(4, 9), (9, 11)], [(4, 7), (9, 9), (6, 12)],
               [(4, 5), (9, 7), (6, 10)], [(9, 5), (6, 8), (4, 11)]]
    for i in range(4):
        f = img(TILE, TILE)
        d = ImageDraw.Draw(f)
        rect(d, 3, 4, 12, 14, C["glass"])
        rect(d, 3, 7, 12, 14, C["liquid_cyan"])
        rect(d, 3, 4, 3, 14, C["glass_dark"])
        rect(d, 12, 4, 12, 14, C["glass_dark"])
        rect(d, 2, 15, 13, 15, C["steel_dark"])
        rect(d, 2, 3, 13, 3, C["steel"])
        for (bx, by) in bubbles[i]:
            px(d, bx, by, C["glass"])
        sheet.paste(f, (i * TILE, 0), f)
    return sheet


def decor_burner() -> Image.Image:
    """Bunsen burner, 3-frame flame flicker."""
    sheet = img(TILE * 3, TILE)
    for i, hgt in enumerate((4, 6, 5)):
        f = img(TILE, TILE)
        d = ImageDraw.Draw(f)
        rect(d, 6, 9, 9, 14, C["steel_dark"])
        rect(d, 4, 15, 11, 15, C["steel"])
        rect(d, 6, 9 - hgt, 9, 8, C["flame"])
        rect(d, 7, 9 - hgt + 1, 8, 8, C["flame_hot"])
        rect(d, 6, 8, 9, 8, C["flame_blue"])
        sheet.paste(f, (i * TILE, 0), f)
    return sheet


def decor_centrifuge() -> Image.Image:
    sheet = img(TILE * 2, TILE)
    for i in range(2):
        f = img(TILE, TILE)
        d = ImageDraw.Draw(f)
        rect(d, 2, 6, 13, 14, C["coat_shade"])
        rect(d, 2, 6, 13, 7, C["coat"])
        rect(d, 3, 15, 12, 15, C["steel_dark"])
        if i == 0:
            rect(d, 5, 9, 10, 10, C["steel"])
        else:
            rect(d, 7, 8, 8, 12, C["steel"])
        px(d, 12, 12, C["led_green"])
        sheet.paste(f, (i * TILE, 0), f)
    return sheet


def decor_laptop() -> Image.Image:
    sheet = img(TILE * 2, TILE)
    for i in range(2):
        f = img(TILE, TILE)
        d = ImageDraw.Draw(f)
        rect(d, 3, 4, 12, 11, C["steel_dark"])
        rect(d, 4, 5, 11, 10, C["screen"] if i == 0 else C["screen_off"])
        rect(d, 5, 7, 9, 7, C["wall_dark"])
        rect(d, 5, 9, 8, 9, C["wall_dark"])
        rect(d, 2, 12, 13, 14, C["steel"])
        sheet.paste(f, (i * TILE, 0), f)
    return sheet


def decor_flask_vapour() -> Image.Image:
    """Erlenmeyer flask with a 3-frame vapour wisp."""
    sheet = img(TILE * 3, TILE)
    for i in range(3):
        f = img(TILE, TILE)
        d = ImageDraw.Draw(f)
        rect(d, 6, 5, 9, 7, C["glass"])
        for row, y in enumerate(range(8, 15)):
            half = 2 + row
            rect(d, 8 - half, y, 7 + half, y, C["glass"])
        for row, y in enumerate(range(11, 15)):
            half = 5 + row - 3
            rect(d, 8 - half, y, 7 + half, y, C["liquid_pink"])
        rect(d, 2, 15, 13, 15, C["steel_dark"])
        px(d, 7, 4 - i, C["glass_dark"])
        px(d, 9, 2 - i, C["glass_dark"])
        sheet.paste(f, (i * TILE, 0), f)
    return sheet


def decor_static(kind: str) -> Image.Image:
    f = img(TILE, TILE)
    d = ImageDraw.Draw(f)
    if kind == "tubes":
        rect(d, 1, 9, 14, 15, C["bench_dark"])
        rect(d, 1, 9, 14, 9, C["bench"])
        for i, col in enumerate(["liquid_cyan", "liquid_pink", "liquid_amber",
                                 "liquid_green"]):
            x = 2 + i * 3
            rect(d, x, 3, x + 1, 11, C["glass"])
            rect(d, x, 7, x + 1, 11, C[col])
    elif kind == "pipettes":
        rect(d, 2, 11, 13, 15, C["steel_dark"])
        for i in range(4):
            x = 3 + i * 3
            rect(d, x, 3, x, 11, C["coat"])
            px(d, x, 2, C["liquid_cyan"])
    elif kind == "petri":
        for i, y in enumerate((13, 10, 7)):
            rect(d, 3 + i, y, 12 - i, y + 2, C["glass"])
            rect(d, 4 + i, y + 1, 11 - i, y + 1, C["liquid_green"])
    elif kind == "microscope":
        rect(d, 4, 14, 12, 15, C["steel_dark"])
        rect(d, 7, 6, 9, 14, C["steel"])
        rect(d, 6, 3, 10, 6, C["steel_dark"])
        rect(d, 5, 11, 11, 12, C["steel_dark"])
        px(d, 8, 10, C["glass"])
    elif kind == "clipboard":
        rect(d, 4, 3, 12, 15, C["paper"])
        rect(d, 6, 2, 10, 4, C["steel_dark"])
        for y in range(6, 14, 2):
            rect(d, 6, y, 10, y, C["steel_dark"])
    return f


# ---------------------------------------------------------------------------
SPRITES = {
    "scientist_walk.png": (sprite_walk, {"frames": 4, "w": SCI_W, "h": SCI_H,
                                         "fps": 8, "facing": "right"}),
    "scientist_idle.png": (sprite_idle, {"frames": 2, "w": SCI_W, "h": SCI_H,
                                         "fps": 2, "facing": "away"}),
    "scientist_work.png": (sprite_work, {"frames": 3, "w": SCI_W, "h": SCI_H,
                                         "fps": 6, "facing": "away"}),
    "scientist_read.png": (sprite_read, {"frames": 2, "w": SCI_W, "h": SCI_H,
                                         "fps": 2, "facing": "front"}),
    "scientist_success.png": (lambda: sprite_react("success"),
                              {"frames": 2, "w": SCI_W, "h": SCI_H, "fps": 4,
                               "facing": "front"}),
    "scientist_fail.png": (lambda: sprite_react("fail"),
                           {"frames": 2, "w": SCI_W, "h": SCI_H, "fps": 3,
                            "facing": "front"}),
    "floor.png": (tile_floor, {"frames": 1, "w": TILE, "h": TILE}),
    "wall.png": (tile_wall, {"frames": 1, "w": TILE, "h": TILE}),
    "window.png": (prop_window, {"frames": 1, "w": TILE * 3, "h": TILE * 2}),
    "whiteboard.png": (prop_whiteboard, {"frames": 1, "w": TILE * 4, "h": TILE * 2}),
    "shelf.png": (prop_shelf, {"frames": 1, "w": TILE * 3, "h": TILE}),
    "bench.png": (prop_bench, {"frames": 1, "w": TILE * 19, "h": TILE * 4}),
    "status_lights.png": (status_lights, {"frames": 4, "w": 8, "h": 8}),
    "decor_beaker.png": (decor_beaker, {"frames": 4, "w": TILE, "h": TILE, "fps": 6,
                                        "reactive": True}),
    "decor_burner.png": (decor_burner, {"frames": 3, "w": TILE, "h": TILE, "fps": 8,
                                        "reactive": True}),
    "decor_centrifuge.png": (decor_centrifuge, {"frames": 2, "w": TILE, "h": TILE,
                                                "fps": 8, "reactive": True}),
    "decor_laptop.png": (decor_laptop, {"frames": 2, "w": TILE, "h": TILE, "fps": 2}),
    "decor_flask.png": (decor_flask_vapour, {"frames": 3, "w": TILE, "h": TILE, "fps": 3}),
}
for _k in ("tubes", "pipettes", "petri", "microscope", "clipboard"):
    SPRITES[f"decor_{_k}.png"] = (
        (lambda kind=_k: decor_static(kind)), {"frames": 1, "w": TILE, "h": TILE})
for _i, _kind in enumerate(["dna", "structure", "peptide", "plate", "flask", "verdict"], 1):
    SPRITES[f"station_{_i}.png"] = (
        (lambda kind=_kind: station_prop(kind)),
        {"frames": 1, "w": TILE * 2, "h": TILE * 2, "kind": _kind})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    for name, (fn, meta) in SPRITES.items():
        sheet = fn()
        sheet.save(OUT / name)
        manifest[name] = {**meta, "sheet_w": sheet.width, "sheet_h": sheet.height}
        print(f"  {name:28s} {sheet.width:4d}x{sheet.height:<4d} "
              f"{meta.get('frames', 1)} frame(s)")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\n{len(SPRITES)} spritesheets -> {OUT}")


if __name__ == "__main__":
    main()
