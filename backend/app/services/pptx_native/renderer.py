"""NativePptxRenderer — builds a fully editable, polished PPTX from outlines.

Matches the renderer interface used by ``PptxBuilder`` (``render(outlines, brand,
output_path)``). Each slide is real shapes/text (no images): background → motif →
header → the planned primitive (``pinned_primitive``) → footer chrome.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR
from pptx.util import Inches

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.services.slide_design.content import _content
from app.services.slide_types import get_slide_type

from . import components as C
from . import primitives as P
from .theme import resolve_theme, slide_content_area, slide_modes, pt

_SELF_HEADER = {"cover", "statement", "quote", "closing"}


class NativePptxRenderer:
    """Render generated freeform/brand decks as polished, editable native PPTX."""

    def render(
        self,
        outlines: list[SlideOutline],
        brand: BrandDNA,
        output_path: Path,
        enable_diagrams: bool = True,
    ) -> list[dict[str, str | int]]:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        warnings: list[dict[str, str | int]] = []

        theme = resolve_theme(brand)
        modes = slide_modes(outlines)
        total = len(outlines)

        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)
        blank = prs.slide_layouts[6]

        for i, outline in enumerate(outlines):
            content = _content(outline)
            mode = modes[i] if i < len(modes) else "light"
            slide = prs.slides.add_slide(blank)
            pal = C.palette(theme, mode)
            C.add_background(slide, theme, pal)

            primitive = self._primitive(content)
            if primitive == "cover" and i > 0:
                # Only the first slide is a cover; a mid-deck "cover" (model
                # variance) renders as a statement so the deck never shows two
                # title pages.
                primitive = "statement"
            builder = P.BUILDERS.get(primitive, P.cards)
            area = slide_content_area(theme, cover=(primitive == "cover"))
            try:
                if primitive in _SELF_HEADER:
                    slot = "cover" if primitive == "cover" else ("closing" if primitive == "closing" else "statement")
                    C.add_motif(slide, theme, slot, pal)
                    builder(slide, content, theme, pal, area)
                    if primitive == "closing":
                        P._footer(slide, content, theme, pal, i, total)
                else:
                    body = P._header(slide, content, theme, pal, area)
                    builder(slide, content, theme, pal, body)
                    P._footer(slide, content, theme, pal, i, total)
            except Exception as exc:  # never let one slide break the deck
                warnings.append({
                    "slide_index": i,
                    "field": "render",
                    "severity": "warning",
                    "message": f"native slide fallback: {exc}",
                })
                self._fallback(slide, content, theme, pal, area)

            if theme.logo_path and primitive in ("cover", "closing"):
                self._add_logo(slide, theme)

            notes = content.get("speaker_notes")
            if notes:
                try:
                    slide.notes_slide.notes_text_frame.text = str(notes)
                except Exception:
                    pass

        prs.save(output_path.as_posix())
        return warnings

    def _add_logo(self, slide, theme) -> None:
        """Brand logo on the cover/closing, top-left, aspect-preserved."""
        path = Path(str(theme.logo_path))
        if not path.exists():
            return
        try:
            from PIL import Image

            with Image.open(path) as img:
                w, h = img.size
            height = 0.5
            width = min(2.2, height * (w / max(1, h)))
            slide.shapes.add_picture(
                path.as_posix(), Inches(0.875), Inches(0.62),
                Inches(width), Inches(height),
            )
        except Exception:
            return

    def _primitive(self, content: dict) -> str:
        pinned = (content.get("pinned_primitive") or "").strip().lower()
        if pinned in P.BUILDERS:
            return pinned
        return get_slide_type(content.get("slide_type")).primitive

    def _fallback(self, slide, content, theme, pal, area) -> None:
        from app.services.slide_design.content import _clean_sentence
        title = _clean_sentence(content.get("action_title") or content.get("title") or "")
        bullets = [str(b.get("text") if isinstance(b, dict) else b) for b in (content.get("bullets") or [])][:5]
        paras = [C.Para(title, pt(38, theme.heading_scale), pal.headline, bold=True, space_after_pt=12)]
        for b in bullets:
            paras.append(C.Para(f"{P._TICK}{b}", pt(16), pal.body, line_spacing=1.4, space_after_pt=6))
        C.add_paragraphs(slide, area, paras, anchor=MSO_ANCHOR.TOP)
