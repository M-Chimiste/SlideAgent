"""Slide-type content contracts.

A ``SlideType`` is the *kind* of a slide (decided at planning time), carrying a
content contract: its structural shape, how many substantive points it needs
(density floor) and tolerates (ceiling), how much source evidence it wants, and
the render primitive / composition family it pins to. This unifies onto the
existing ``slide_type`` vocabulary (already on ``GeneratedSlideSpec``) rather
than adding a fourth parallel concept, and adds the genuinely-missing non-list
shapes (``stat``, ``statement``, ``deep_dive``) so a thin beat can become a
finished single-idea slide instead of a half-empty grid.

Per-element text budgets are NOT duplicated here — they are resolved from the
single source of truth in ``slide_design/fit.py`` keyed by the pinned primitive.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.slide_design import fit

# Shapes
TITLE = "title"          # cover/section: a headline, little body
STATEMENT = "statement"  # one bold idea (+ minimal support)
LIST = "list"            # parallel points (cards/rows/callouts) — the old default
STRUCTURED = "structured"  # relational/ordered (compare/process/matrix/framework)
DATA = "data"            # numbers (chart/stat)


@dataclass(frozen=True)
class SlideType:
    key: str
    shape: str
    is_list: bool
    primitive: str            # html render primitive (fit.CAPACITIES key)
    composition_family: str   # authored/HTML composition family pin
    min_points: int           # density floor — fewer than this reads as sparse
    max_points: int           # density ceiling
    evidence_need: str        # "low" | "medium" | "high" | "metrics"

    def budget(self) -> fit.PrimitiveCapacity:
        return fit.capacity_for(self.primitive)


_TYPES: tuple[SlideType, ...] = (
    SlideType("cover", TITLE, False, "cover", "editorial_cover", 0, 3, "low"),
    SlideType("section", TITLE, False, "statement", "section_divider", 0, 1, "low"),
    SlideType("executive_summary", LIST, True, "callout_list", "editorial_spread", 3, 5, "medium"),
    SlideType("content", LIST, True, "cards", "why_it_matters_cards", 3, 5, "medium"),
    SlideType("callouts", LIST, True, "callout_list", "circular_trap", 3, 5, "medium"),
    SlideType("checklist", LIST, True, "cards", "toolkit_grid", 3, 6, "medium"),
    SlideType("anti_pattern", LIST, True, "cards", "challenge_cards", 3, 4, "medium"),
    SlideType("reference", LIST, True, "rows", "operating_map", 3, 5, "high"),
    SlideType("chart", DATA, False, "metrics", "metric_signal", 3, 6, "metrics"),
    SlideType("stat", DATA, False, "big_stat", "metric_signal", 1, 3, "metrics"),
    SlideType("comparison", STRUCTURED, False, "table", "reframe_comparison", 3, 6, "high"),
    SlideType("process", STRUCTURED, False, "steps", "lifecycle_timeline", 3, 6, "high"),
    SlideType("framework", STRUCTURED, False, "layers", "architecture_layers", 3, 5, "high"),
    SlideType("matrix", STRUCTURED, False, "matrix", "decision_matrix", 4, 4, "high"),
    SlideType("quote", STATEMENT, False, "quote", "spotlight_quote", 1, 1, "low"),
    SlideType("statement", STATEMENT, False, "statement", "statement_canvas", 1, 3, "low"),
    SlideType("decision", STATEMENT, False, "statement", "statement_canvas", 1, 3, "low"),
    SlideType("deep_dive", STATEMENT, False, "split", "reframe_split", 3, 4, "high"),
    SlideType("closing", TITLE, False, "closing", "path_forward_close", 2, 4, "low"),
)

SLIDE_TYPES: dict[str, SlideType] = {t.key: t for t in _TYPES}
DEFAULT_TYPE = "content"

LIST_TYPES: frozenset[str] = frozenset(t.key for t in _TYPES if t.is_list)
NON_LIST_TYPES: frozenset[str] = frozenset(t.key for t in _TYPES if not t.is_list)
# Roomier single-idea types a thin slide can be converted into.
STATEMENT_TYPES: tuple[str, ...] = ("statement", "stat", "quote")

# Canonical archetype -> slide_type (mirrors specs._slide_type_for_archetype;
# this is the single map both should use).
ARCHETYPE_TO_TYPE: dict[str, str] = {
    "cover": "cover",
    "executive_summary": "executive_summary",
    "anti_patterns": "anti_pattern",
    "dependency_map": "framework",
    "framework_cycle": "framework",
    "section_divider": "section",
    "comparison_table": "comparison",
    "code_panel": "reference",
    "reference": "reference",
    "checklist": "checklist",
    "quote_sidebar": "quote",
    "table_reference": "reference",
    "metric_chart": "chart",
    "matrix_2x2": "matrix",
    "callouts": "callouts",
    "icon_rows": "content",
    "two_column": "content",
    "closing_recommendation": "closing",
}


def get_slide_type(key: str | None) -> SlideType:
    return SLIDE_TYPES.get((key or "").strip().lower(), SLIDE_TYPES[DEFAULT_TYPE])


def slide_type_for_archetype(archetype: str | None) -> str:
    return ARCHETYPE_TO_TYPE.get((archetype or "").strip().lower(), DEFAULT_TYPE)


def is_list_type(key: str | None) -> bool:
    return (key or "").strip().lower() in LIST_TYPES
