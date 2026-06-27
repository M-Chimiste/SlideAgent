"""Single source of truth for slide text capacity / fit.

Two concerns live here so the planning budget, the spec-gate fit check, the
render-time ``_fit`` trims, and the rendered-slide audit all agree on one set of
numbers instead of duplicating them:

1. A deterministic line-fit estimator (lifted verbatim from
   ``rendered_slide_audit._text_box_has_overflow_risk`` so the audit and the
   planner share the exact same font-metric constants).
2. A per-primitive ``CAPACITIES`` table: how many items each layout primitive
   holds and the character/line budget per text element. These are the authoring
   budgets the planner targets; the render-side ``_fit`` caps and the CSS
   ``-webkit-line-clamp`` values are derived from the same table, giving three
   concentric safety rings (author ≤ render-cap ≤ clamp).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.services.design_languages import get_language

# Item-count caps for the list primitives (single source; re-exported by
# templates.py so existing ``templates.MAX_CARDS`` imports keep working).
MAX_CARDS = 6
MAX_ROWS = 4
MAX_STEPS = 8


# --------------------------------------------------------------------------- #
# Deterministic line-fit estimator (lifted from rendered_slide_audit)
# --------------------------------------------------------------------------- #
def chars_per_line(width_pt: float, font_pt: float) -> int:
    return max(8, int(width_pt / max(font_pt * 0.52, 1)))


def estimate_lines(paragraphs: list[str], width_pt: float, font_pt: float) -> int:
    cpl = chars_per_line(width_pt, font_pt)
    return sum(max(1, math.ceil(len(p) / cpl)) for p in paragraphs)


def capacity_lines(height_pt: float, font_pt: float) -> float:
    return max(1.0, height_pt / max(font_pt * 1.18, 1))


def fits(
    paragraphs: list[str],
    *,
    width_pt: float,
    height_pt: float,
    font_pt: float,
    slack: float = 0.8,
) -> bool:
    """True when the text is estimated to fit the box (with the audit's slack)."""
    return estimate_lines(paragraphs, width_pt, font_pt) <= capacity_lines(height_pt, font_pt) + slack


# --------------------------------------------------------------------------- #
# Per-primitive capacity / budget table
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ElementBudget:
    max_chars: int           # render-cap == authoring ceiling for this element
    max_lines: int           # CSS -webkit-line-clamp (0 = no clamp)
    max_words: int | None = None  # for short bold leads/titles

    def authoring_chars(self) -> int:
        """A slightly tighter target for the LLM, leaving render slack."""
        return max(24, int(self.max_chars * 0.8))


@dataclass(frozen=True)
class PrimitiveCapacity:
    min_items: int
    max_items: int
    lead: ElementBudget      # the bold title / lead phrase per item
    body: ElementBudget      # the supporting text per item


# Seeded from the renderer's per-element fit caps + clamp values + MAX_*;
# turning what were implicit/duplicated numbers into one explicit table.
_DEFAULT = PrimitiveCapacity(
    min_items=1,
    max_items=6,
    lead=ElementBudget(max_chars=70, max_lines=2, max_words=8),
    body=ElementBudget(max_chars=160, max_lines=4),
)

CAPACITIES: dict[str, PrimitiveCapacity] = {
    # list primitives
    "cards": PrimitiveCapacity(3, MAX_CARDS, ElementBudget(50, 2, 6), ElementBudget(150, 6)),
    "rows": PrimitiveCapacity(2, MAX_ROWS, ElementBudget(80, 1, 9), ElementBudget(170, 3)),
    "steps": PrimitiveCapacity(3, MAX_STEPS, ElementBudget(70, 2, 8), ElementBudget(130, 4)),
    "callout_list": PrimitiveCapacity(2, 5, ElementBudget(90, 2, 10), ElementBudget(240, 7)),
    "columns": PrimitiveCapacity(2, 3, ElementBudget(70, 2, 8), ElementBudget(170, 4)),
    "matrix": PrimitiveCapacity(4, 4, ElementBudget(60, 2, 7), ElementBudget(130, 3)),
    "timeline": PrimitiveCapacity(3, 6, ElementBudget(70, 2, 8), ElementBudget(150, 3)),
    "layers": PrimitiveCapacity(3, 5, ElementBudget(70, 2, 8), ElementBudget(160, 3)),
    "table": PrimitiveCapacity(2, 6, ElementBudget(64, 1, 8), ElementBudget(64, 1)),
    # non-list "statement" primitives — one finished idea, roomier per element
    "statement": PrimitiveCapacity(1, 3, ElementBudget(90, 3, 14), ElementBudget(180, 4)),
    "quote": PrimitiveCapacity(1, 1, ElementBudget(150, 4, 26), ElementBudget(60, 1, 10)),
    "split": PrimitiveCapacity(2, 2, ElementBudget(70, 2, 9), ElementBudget(150, 4)),
    "big_stat": PrimitiveCapacity(1, 3, ElementBudget(24, 1, 4), ElementBudget(90, 3)),
    "metrics": PrimitiveCapacity(2, 6, ElementBudget(24, 1, 4), ElementBudget(90, 3)),
    "cover": PrimitiveCapacity(0, 3, ElementBudget(90, 3, 14), ElementBudget(160, 3)),
    "closing": PrimitiveCapacity(1, 4, ElementBudget(70, 2, 9), ElementBudget(120, 2)),
}


def capacity_for(primitive: str) -> PrimitiveCapacity:
    return CAPACITIES.get((primitive or "").strip().lower(), _DEFAULT)


def budget_for(primitive: str, design_language: str = "editorial_serif") -> PrimitiveCapacity:
    """Resolve a primitive's capacity, scaling the bold *lead* char budget by the
    design language's display type scale (a bigger heading fits fewer chars).
    Body text is scale-invariant in the current css (fixed px), so it is left as-is.
    """
    cap = capacity_for(primitive)
    scale = get_language(design_language).heading_scale
    if scale == 1.0:
        return cap
    lead = ElementBudget(
        max_chars=max(24, int(cap.lead.max_chars / scale)),
        max_lines=cap.lead.max_lines,
        max_words=cap.lead.max_words,
    )
    return PrimitiveCapacity(cap.min_items, cap.max_items, lead, cap.body)
