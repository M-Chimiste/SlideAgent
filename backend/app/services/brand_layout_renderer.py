"""Brand layout-library instantiation renderer (Feature 3, Phase 2).

Instead of duplicating the uploaded deck's *authored slides* (the clone path,
capped at the file's slide count), this renderer instantiates NEW slides from the
template's *slide-layout library* via ``slides.add_slide(layout)`` and fills the
inherited placeholders. That reuses the real master/layout/theme DNA while giving
unbounded structural variety. It is gated behind the ``BRAND_LAYOUT_INSTANTIATION``
config flag and, when it produces nothing usable, the builder falls back to the
clone path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER

from app.models.outline import SlideOutline
from app.models.template import TemplateProfile

MAX_BODY_ITEMS = 6

_TITLE_TYPES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
_BODY_TYPES = {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT}

# Roles an outline can target. Picture/blank layouts are excluded from general
# use because generated decks rarely carry real image assets (an empty picture
# placeholder renders as dead space), so we never route content to them.
_USABLE_ROLES = ("cover", "section", "two_content", "comparison", "content", "title_only")


def _ptype_name(ptype: Any) -> str:
    try:
        return ptype.name
    except Exception:
        return str(ptype) if ptype is not None else "UNKNOWN"


def role_for_layout(layout: Any) -> str:
    """Classify a python-pptx slide layout into a coarse semantic role."""
    name = (getattr(layout, "name", "") or "").lower()
    if "title slide" in name or name.strip() == "title":
        return "cover"
    if "section" in name:
        return "section"
    if "comparison" in name:
        return "comparison"
    if "two content" in name or "two-content" in name:
        return "two_content"
    if "picture" in name or "caption" in name:
        return "picture_caption"
    if "title only" in name:
        return "title_only"
    if "blank" in name:
        return "blank"

    types = []
    for ph in layout.placeholders:
        try:
            types.append(ph.placeholder_format.type)
        except Exception:
            continue
    has_center = any(t == PP_PLACEHOLDER.CENTER_TITLE for t in types)
    has_subtitle = any(t == PP_PLACEHOLDER.SUBTITLE for t in types)
    body_like = sum(1 for t in types if t in _BODY_TYPES)
    has_picture = any(t == PP_PLACEHOLDER.PICTURE for t in types)
    if has_center or has_subtitle:
        return "cover"
    if has_picture and body_like == 0:
        return "picture_caption"
    if body_like >= 2:
        return "two_content"
    if body_like == 1:
        return "content"
    return "blank"


class BrandLayoutInstantiationRenderer:
    """Render a brand deck by instantiating template layouts and filling them."""

    def render(
        self,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        output_path: Path,
        working_dir: Path,
    ) -> tuple[bool, list[dict[str, str | int]]]:
        warnings: list[dict[str, str | int]] = []
        source = (template.source_file or "").strip()
        if not source or not Path(source).exists():
            return False, [self._warn(0, "Brand template source file is missing for layout instantiation.")]
        if not outlines:
            return False, [self._warn(0, "No outlines available for layout instantiation.")]

        try:
            prs = Presentation(source)
        except Exception as exc:  # corrupt/unreadable template
            return False, [self._warn(0, f"Template PPTX could not be opened: {exc}")]

        layouts = list(prs.slide_layouts)
        if not layouts:
            return False, [self._warn(0, "Template exposes no slide layouts to instantiate.")]

        by_role = self._layouts_by_role(layouts)
        if not any(by_role.get(role) for role in _USABLE_ROLES):
            return False, [self._warn(0, "Template has no usable content layouts to instantiate.")]

        self._strip_existing_slides(prs)

        usage: dict[int, int] = {}
        produced = 0
        for position, outline in enumerate(outlines):
            try:
                layout = self._pick_layout(outline, by_role, layouts, usage)
                if layout is None:
                    continue
                slide = prs.slides.add_slide(layout)
                self._fill_slide(slide, outline)
                produced += 1
            except Exception as exc:  # never let one slide kill the deck
                warnings.append(self._warn(outline.slide_index, f"layout instantiation fallback: {exc}"))

        if produced == 0:
            return False, [*warnings, self._warn(0, "Layout instantiation produced no slides.")]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            prs.save(output_path.as_posix())
        except Exception as exc:  # save failure should fall back to the clone path
            return False, [*warnings, self._warn(0, f"Layout instantiation could not save the deck: {exc}")]
        return True, warnings

    # ---- layout selection ---- #
    def _layouts_by_role(self, layouts: list[Any]) -> dict[str, list[int]]:
        by_role: dict[str, list[int]] = {}
        for index, layout in enumerate(layouts):
            by_role.setdefault(role_for_layout(layout), []).append(index)
        return by_role

    def _target_role(self, outline: SlideOutline) -> str:
        content = outline.content_json or {}
        layout_json = outline.layout_json or {}
        role = str(content.get("narrative_role") or content.get("slide_type") or "").lower()
        family = str(
            content.get("composition_family") or layout_json.get("composition_family") or ""
        ).lower()
        exhibit = str((content.get("exhibit_spec") or {}).get("type") or "").lower()
        if role == "cover" or family == "editorial_cover":
            return "cover"
        if role in ("section", "divider") or family == "section_divider":
            return "section"
        if family in ("reframe_comparison", "reframe_split") or exhibit == "comparison_table":
            return "comparison"
        return "content"

    def _pick_layout(
        self,
        outline: SlideOutline,
        by_role: dict[str, list[int]],
        layouts: list[Any],
        usage: dict[int, int],
    ) -> Any | None:
        target = self._target_role(outline)
        # Fallback chains keep each target on-message while staying within the
        # template's actually-available layouts.
        chains = {
            "cover": ["cover", "section", "title_only", "content", "two_content"],
            "section": ["section", "cover", "title_only", "content"],
            "comparison": ["comparison", "two_content", "content"],
            "content": ["content", "two_content", "title_only"],
        }
        for role in chains.get(target, ["content", "two_content"]):
            candidates = by_role.get(role) or []
            if candidates:
                index = min(candidates, key=lambda i: (usage.get(i, 0), i))
                usage[index] = usage.get(index, 0) + 1
                return layouts[index]
        # last resort: any usable layout, then any layout at all
        for role in _USABLE_ROLES:
            candidates = by_role.get(role) or []
            if candidates:
                index = min(candidates, key=lambda i: (usage.get(i, 0), i))
                usage[index] = usage.get(index, 0) + 1
                return layouts[index]
        return None

    # ---- slide filling ---- #
    def _fill_slide(self, slide: Any, outline: SlideOutline) -> None:
        content = outline.content_json or {}
        title_text = self._clean(content.get("action_title") or content.get("title") or "")
        sub_text = self._clean(content.get("subheading") or "")
        body_items = self._body_items(content)[:MAX_BODY_ITEMS]

        title_phs: list[Any] = []
        sub_phs: list[Any] = []
        body_phs: list[Any] = []
        for ph in slide.placeholders:
            ptype = self._ptype(ph)
            if ptype in _TITLE_TYPES:
                title_phs.append(ph)
            elif ptype == PP_PLACEHOLDER.SUBTITLE:
                sub_phs.append(ph)
            elif ptype in _BODY_TYPES:
                body_phs.append(ph)

        filled: set[int] = set()
        if title_text and title_phs:
            title_phs[0].text = title_text
            filled.add(title_phs[0].placeholder_format.idx)
        if sub_text and sub_phs:
            sub_phs[0].text = sub_text
            filled.add(sub_phs[0].placeholder_format.idx)
        elif not sub_text and not body_items and sub_phs and title_text:
            # cover-style layout with only a subtitle: use it for context if any
            pass
        if body_items and body_phs:
            if len(body_phs) >= 2 and len(body_items) >= 2:
                mid = (len(body_items) + 1) // 2
                chunks = [body_items[:mid], body_items[mid:]]
            else:
                chunks = [body_items]
            for ph, chunk in zip(body_phs, chunks):
                if chunk:
                    self._set_text_frame(ph, chunk)
                    filled.add(ph.placeholder_format.idx)

        # Remove unfilled placeholders so PowerPoint/soffice never renders the
        # "Click to add..." prompt text on a generated slide.
        for ph in list(slide.placeholders):
            try:
                if ph.placeholder_format.idx not in filled:
                    ph._element.getparent().remove(ph._element)
            except Exception:
                continue

        notes = content.get("speaker_notes")
        if notes:
            try:
                slide.notes_slide.notes_text_frame.text = str(notes)
            except Exception:
                pass

    def _set_text_frame(self, placeholder: Any, items: list[str]) -> None:
        tf = placeholder.text_frame
        tf.clear()
        tf.paragraphs[0].text = items[0]
        for item in items[1:]:
            paragraph = tf.add_paragraph()
            paragraph.text = item

    # ---- helpers ---- #
    def _strip_existing_slides(self, prs: Any) -> None:
        sldIdLst = prs.slides._sldIdLst
        for sldId in list(sldIdLst):
            sldIdLst.remove(sldId)

    def _ptype(self, placeholder: Any) -> Any:
        try:
            return placeholder.placeholder_format.type
        except Exception:
            return None

    def _body_items(self, content: dict) -> list[str]:
        exhibit = content.get("exhibit_spec") or {}
        for key in ("points", "items", "steps", "cards", "rows"):
            value = exhibit.get(key)
            if isinstance(value, list) and value:
                items = [self._as_text(entry) for entry in value]
                return [item for item in items if item]
        bullets = content.get("bullets") or []
        items = [self._as_text(entry) for entry in bullets]
        return [item for item in items if item]

    def _as_text(self, value: Any) -> str:
        if isinstance(value, dict):
            for key in ("text", "body", "action", "description", "label", "title", "name", "value"):
                if value.get(key):
                    return self._clean(str(value[key]))
            return ""
        if isinstance(value, (list, tuple)):
            return self._clean(" ".join(self._as_text(v) for v in value))
        return self._clean(str(value or ""))

    def _clean(self, text: str) -> str:
        return " ".join(str(text or "").split()).strip()

    def _warn(self, slide_index: int, message: str) -> dict[str, str | int]:
        return {
            "slide_index": slide_index,
            "field": "brand_layout_instantiation",
            "severity": "warning",
            "message": message,
        }
