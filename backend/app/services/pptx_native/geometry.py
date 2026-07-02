"""Auto-layout geometry for the native renderer.

python-pptx has no flexbox/grid — shapes are absolutely positioned in EMU. This
module is the small layout engine that computes positions from item count + area
+ gap, so primitives reflow with content instead of using hardcoded EMU tuples
(the thing that made the old native output look flat). Everything is in inches
(python-pptx ``Inches`` are applied at draw time).

The HTML design system is authored in px on a 1280x720 canvas; the PPTX canvas is
13.333in x 7.5in, i.e. exactly 96 px per inch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

PX_PER_IN = 96.0
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5


def px(value: float) -> float:
    """CSS pixels -> inches (96 px/in on this canvas)."""
    return float(value) / PX_PER_IN


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def inset(self, top: float, right: float | None = None,
              bottom: float | None = None, left: float | None = None) -> "Rect":
        right = top if right is None else right
        bottom = top if bottom is None else bottom
        left = right if left is None else left
        return Rect(self.x + left, self.y + top, self.w - left - right, self.h - top - bottom)


def parse_padding_px(value: str) -> tuple[float, float, float, float]:
    """Parse a CSS padding shorthand ("70px 84px 60px") -> (top,right,bottom,left) in px."""
    parts = [float(p.replace("px", "").strip() or 0) for p in str(value).split()]
    if not parts:
        return (0.0, 0.0, 0.0, 0.0)
    if len(parts) == 1:
        t = r = b = left = parts[0]
    elif len(parts) == 2:
        t, r = parts
        b, left = t, r
    elif len(parts) == 3:
        t, r, b = parts
        left = r
    else:
        t, r, b, left = parts[:4]
    return (t, r, b, left)


def content_area(slide_padding_px: str) -> Rect:
    """The slide content box (inside the design language's slide padding)."""
    t, r, b, left = parse_padding_px(slide_padding_px)
    return Rect(px(left), px(t), SLIDE_W_IN - px(left) - px(r), SLIDE_H_IN - px(t) - px(b))


def grid(n: int, cols: int, area: Rect, gap: float) -> list[Rect]:
    """``n`` equal cells in ``cols`` columns within ``area`` (gap in inches)."""
    if n <= 0:
        return []
    cols = max(1, min(cols, n))
    rows = math.ceil(n / cols)
    cell_w = (area.w - gap * (cols - 1)) / cols
    cell_h = (area.h - gap * (rows - 1)) / rows
    cells: list[Rect] = []
    for i in range(n):
        r, c = divmod(i, cols)
        cells.append(Rect(area.x + c * (cell_w + gap), area.y + r * (cell_h + gap), cell_w, cell_h))
    return cells


def column_split(area: Rect, ratios: list[float], gap: float) -> list[Rect]:
    """Split ``area`` horizontally by ``ratios`` (e.g. [0.82, 1.18])."""
    total = sum(ratios) or 1.0
    avail = area.w - gap * (len(ratios) - 1)
    out: list[Rect] = []
    x = area.x
    for ratio in ratios:
        w = avail * ratio / total
        out.append(Rect(x, area.y, w, area.h))
        x += w + gap
    return out


def stack(area: Rect, n: int, gap: float, row_h: float | None = None) -> list[Rect]:
    """``n`` stacked rows within ``area``; equal-height unless ``row_h`` is given."""
    if n <= 0:
        return []
    if row_h is None:
        row_h = (area.h - gap * (n - 1)) / n
    out: list[Rect] = []
    y = area.y
    for _ in range(n):
        out.append(Rect(area.x, y, area.w, row_h))
        y += row_h + gap
    return out
