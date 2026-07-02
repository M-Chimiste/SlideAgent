"""Theme adapter for the native renderer.

Re-uses ``slide_design/design_system`` (``Theme``, ``resolve_theme``, the
dark/light rhythm ``resolve_modes``) as-is and adds the px->pt / px->inch helpers
the native primitives need. Display type is scaled by the design language's
``heading_scale``; body text is scale-invariant (matching the current css).
"""

from __future__ import annotations

from app.models.outline import SlideOutline
from app.services.slide_design.design_system import Theme, resolve_modes, resolve_theme

from .geometry import Rect, content_area, parse_padding_px, px

__all__ = ["Theme", "resolve_theme", "resolve_modes", "slide_modes", "pt",
           "slide_content_area", "card_radius_in", "card_gap_in", "card_inset_in"]

# CSS px -> PowerPoint points (96 px/in screen vs 72 pt/in).
PT_PER_PX = 0.75


def pt(px_size: float, scale: float = 1.0) -> float:
    """CSS px font size -> points, optionally scaled by heading_scale."""
    return round(px_size * PT_PER_PX * scale, 1)


def slide_modes(outlines: list[SlideOutline]) -> list[str]:
    """Per-slide dark/light modes: an explicit ``background_mode`` on the
    outline (a user- or deck-level choice) wins; everything else follows the
    shared rhythm logic."""
    keyed = [
        (
            (o.content_json or {}).get("narrative_role") or (o.content_json or {}).get("slide_type"),
            (o.content_json or {}).get("composition_family") or (o.layout_json or {}).get("composition_family"),
        )
        for o in outlines
    ]
    modes = resolve_modes(keyed)
    for index, outline in enumerate(outlines):
        override = str((outline.content_json or {}).get("background_mode") or "").strip().lower()
        if override in {"dark", "light"} and index < len(modes):
            modes[index] = override
    return modes


def slide_content_area(theme: Theme, cover: bool = False) -> Rect:
    return content_area(theme.cover_padding if cover else theme.slide_padding)


def card_radius_in(theme: Theme) -> float:
    return px(theme.card_radius)


def card_gap_in(theme: Theme) -> float:
    return px(theme.card_gap)


def card_inset_in(theme: Theme) -> tuple[float, float, float, float]:
    """Card padding (top, right, bottom, left) in inches from the preset."""
    t, r, b, left = parse_padding_px(theme.card_padding)
    return (px(t), px(r), px(b), px(left))
