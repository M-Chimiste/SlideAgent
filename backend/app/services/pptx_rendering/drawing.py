# ruff: noqa: F401
from pathlib import Path
import math
import re
import shutil
import subprocess
from typing import Any

from PIL import Image, ImageDraw
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.util import Inches, Pt

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.services.concept_diagram_renderer import ConceptDiagramRenderer, DiagramRenderError
from app.services.pptx_rendering.constants import ICON_SCALE, SLIDE_H, SLIDE_W


class DrawingMixin:
    def _add_card(self, slide, x: float, y: float, w: float, h: float, fill: str, line: str) -> None:
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        shape.fill.solid()
        shape.fill.fore_color.rgb = self._rgb(fill)
        shape.line.color.rgb = self._rgb(line)

    def _add_label(self, slide, text: str, x: float, y: float, w: float, brand: BrandDNA, bold: bool = False) -> None:
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(0.35))
        frame = box.text_frame
        frame.clear()
        run = frame.paragraphs[0].add_run()
        run.text = text
        run.font.name = brand.fonts.body
        run.font.size = Pt(12)
        run.font.bold = bold
        run.font.color.rgb = self._rgb(brand.colors.primary)

    def _add_dark_text(
        self,
        slide,
        text: str,
        x: float,
        y: float,
        w: float,
        h: float,
        brand: BrandDNA,
        size: int = 12,
        bold: bool = False,
        color: str | None = None,
    ) -> None:
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = box.text_frame
        frame.clear()
        self._autofit(frame)
        para = frame.paragraphs[0]
        para.line_spacing = 1.12
        run = para.add_run()
        run.text = text[:360]
        run.font.name = brand.fonts.heading if bold else brand.fonts.body
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = self._rgb(color or brand.colors.text_light)

    def _add_code_text(
        self,
        slide,
        lines: list[str],
        x: float,
        y: float,
        w: float,
        h: float,
        brand: BrandDNA,
    ) -> None:
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = box.text_frame
        frame.clear()
        self._autofit(frame)
        for idx, line in enumerate(lines[:8]):
            para = frame.paragraphs[0] if idx == 0 else frame.add_paragraph()
            para.line_spacing = 1.0
            run = para.add_run()
            run.text = line
            run.font.name = "Courier New"
            run.font.size = Pt(10)
            run.font.color.rgb = self._rgb(brand.colors.text_light)
            para.space_after = Pt(2)

    def _add_arrow(
        self,
        slide,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str,
        width: float = 1.4,
    ) -> None:
        connector = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            Inches(x1),
            Inches(y1),
            Inches(x2),
            Inches(y2),
        )
        connector.line.color.rgb = self._rgb(color)
        connector.line.width = Pt(width)

    def _add_arrowhead(
        self,
        slide,
        x: float,
        y: float,
        dx: float,
        dy: float,
        color: str,
    ) -> None:
        arrow = slide.shapes.add_shape(
            MSO_SHAPE.ISOSCELES_TRIANGLE,
            Inches(x - 0.08),
            Inches(y - 0.08),
            Inches(0.16),
            Inches(0.16),
        )
        arrow.fill.solid()
        arrow.fill.fore_color.rgb = self._rgb(color)
        arrow.line.color.rgb = self._rgb(color)
        arrow.rotation = math.degrees(math.atan2(dy, dx)) + 90

    def _add_badge(
        self,
        slide,
        text: str,
        x: float,
        y: float,
        size: float,
        brand: BrandDNA,
        fill: str,
    ) -> None:
        badge = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            Inches(x),
            Inches(y),
            Inches(size),
            Inches(size),
        )
        badge.fill.solid()
        badge.fill.fore_color.rgb = self._rgb(fill)
        badge.line.color.rgb = self._rgb(fill)
        frame = badge.text_frame
        frame.clear()
        frame.margin_left = Inches(0.02)
        frame.margin_right = Inches(0.02)
        frame.margin_top = Inches(0.02)
        frame.margin_bottom = Inches(0.02)
        para = frame.paragraphs[0]
        para.alignment = 1
        run = para.add_run()
        run.text = text[:2]
        run.font.name = brand.fonts.heading
        run.font.size = Pt(max(10, int(size * 22)))
        run.font.bold = True
        run.font.color.rgb = self._rgb(self._readable_text_color(fill, brand))

    def _add_body_text(
        self,
        slide,
        text: str,
        x: float,
        y: float,
        w: float,
        h: float,
        brand: BrandDNA,
        center: bool = False,
        size: int = 13,
    ) -> None:
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = box.text_frame
        frame.clear()
        self._autofit(frame)
        para = frame.paragraphs[0]
        para.line_spacing = 1.15
        if center:
            para.alignment = 1
        run = para.add_run()
        run.text = text[:420]
        run.font.name = brand.fonts.body
        run.font.size = Pt(size)
        run.font.color.rgb = self._rgb(brand.colors.text_dark)

    def _add_bullets(self, slide, bullets: list[str], x: float, y: float, w: float, h: float, brand: BrandDNA) -> None:
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = box.text_frame
        frame.clear()
        self._autofit(frame)
        for idx, bullet in enumerate(bullets[:4]):
            para = frame.paragraphs[0] if idx == 0 else frame.add_paragraph()
            para.level = 0
            para.text = f"• {self._truncate_at_word(bullet, 175)}"
            para.font.name = brand.fonts.body
            para.font.size = Pt(13)
            para.font.color.rgb = self._rgb(brand.colors.text_dark)
            para.line_spacing = 1.12
            para.space_after = Pt(6)

    def _add_big_number(self, slide, text: str, x: float, y: float, w: float, brand: BrandDNA) -> None:
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(0.8))
        frame = box.text_frame
        frame.clear()
        self._autofit(frame)
        para = frame.paragraphs[0]
        para.alignment = 1
        run = para.add_run()
        run.text = text[:12]
        run.font.name = brand.fonts.heading
        run.font.size = Pt(42)
        run.font.bold = True
        run.font.color.rgb = self._rgb(brand.colors.primary)

    def _add_text_in_shape(
        self,
        shape,
        text: str,
        brand: BrandDNA,
        size: int = 10,
        bold: bool = False,
        color: str | None = None,
        center: bool = False,
    ) -> None:
        frame = shape.text_frame
        frame.clear()
        self._autofit(frame)
        frame.margin_left = Inches(0.05)
        frame.margin_right = Inches(0.05)
        para = frame.paragraphs[0]
        if center:
            para.alignment = 1
        run = para.add_run()
        run.text = text[:90]
        run.font.name = brand.fonts.body
        run.font.size = Pt(size)
        run.font.bold = bold
        fill_hex = self._shape_fill_hex(shape)
        if fill_hex:
            if color and self._contrast_ratio(color, fill_hex) >= 4.5:
                chosen = color
            else:
                chosen = self._readable_text_color(fill_hex, brand)
        else:
            chosen = color or brand.colors.text_dark
        run.font.color.rgb = self._rgb(chosen)

    def _exhibit(self, outline: SlideOutline) -> dict[str, Any]:
        exhibit = outline.content_json.get("exhibit_spec")
        if isinstance(exhibit, dict):
            return exhibit
        return {}

    def _bullets(self, outline: SlideOutline) -> list[str]:
        bullets = outline.content_json.get("bullets")
        if isinstance(bullets, list) and bullets:
            return [
                cleaned
                for item in bullets
                if (cleaned := self._clean_display_text(str(item)))
            ]
        blocks = outline.content_json.get("content_blocks") or []
        collected: list[str] = []
        for block in blocks:
            for item in block.get("body", []):
                if isinstance(item, str):
                    cleaned = self._clean_display_text(item)
                    if cleaned:
                        collected.append(cleaned)
        return collected

    def _clean_display_text(self, text: str) -> str:
        cleaned = re.sub(
            r"\[\s*diagram description\s*:[^\]]+\]",
            "",
            str(text),
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\bdiagram description\s*:[^.]+\.?",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\b(\d+)\.0(?=[A-Za-z]|\b)", r"\1", cleaned)
        cleaned = re.sub(
            r"(\d(?:[\d,]*\.?\d*)?)(tokens\b)",
            r"\1 \2",
            cleaned,
            flags=re.IGNORECASE,
        )
        return " ".join(cleaned.split()).strip(" -:;")

    def _truncate_phrase(self, text: str, limit: int) -> str:
        cleaned = self._clean_display_text(text)
        if len(cleaned) <= limit:
            return cleaned
        window = cleaned[:limit]
        for delimiter in (". ", "; ", ": ", " - "):
            index = window.rfind(delimiter)
            if index >= max(24, int(limit * 0.45)):
                return window[: index + len(delimiter)].strip(" -:;")
        truncated = window.rsplit(" ", 1)[0].strip(" -:;,.")
        stop_words = {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "by",
            "for",
            "from",
            "has",
            "have",
            "in",
            "of",
            "or",
            "that",
            "the",
            "to",
            "with",
            "who",
            "whose",
        }
        while truncated.split() and truncated.split()[-1].lower() in stop_words:
            truncated = " ".join(truncated.split()[:-1]).strip(" -:;,.")
        return truncated or self._truncate_at_word(cleaned, limit)

    def _nonduplicate_closing_recommendation(
        self,
        recommendation: str,
        title: str,
    ) -> str:
        cleaned_recommendation = self._clean_display_text(recommendation)
        cleaned_title = self._clean_display_text(title)
        if cleaned_recommendation.casefold() != cleaned_title.casefold():
            return cleaned_recommendation
        lowered = cleaned_title.lower()
        if "reset" in lowered:
            return "Make the reset habit the default operating rule before scaling."
        if "six-phase" in lowered or "cycle" in lowered or "loop" in lowered:
            return "Use the operating loop as the default delivery cadence."
        if "memory" in lowered or "context" in lowered:
            return "Keep persistent context current through named ownership."
        return "Adopt the operating model through a named pilot and review gate."

    def _icons(self, outline: SlideOutline) -> list[str]:
        icons = outline.layout_json.get("icons") or []
        normalized = [str(icon) for icon in icons if str(icon).strip()]
        if not normalized:
            normalized = ["default"]
        while len(normalized) < 4:
            normalized.append(normalized[-1])
        return normalized[:4]

    def _line(
        self,
        draw: ImageDraw.ImageDraw,
        points: list[tuple[float, float]],
        color,
        width: int,
        rounded: bool = True,
    ) -> None:
        scaled = [self._point(point) for point in points]
        stroke_width = self._stroke(width)
        draw.line(scaled, fill=color, width=stroke_width, joint="curve")
        if rounded:
            radius = stroke_width / 2
            for x, y in scaled:
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)

    def _ellipse(
        self,
        draw: ImageDraw.ImageDraw,
        box: tuple[float, float, float, float],
        outline=None,
        fill=None,
        width: int = 1,
    ) -> None:
        draw.ellipse(self._box(box), outline=outline, fill=fill, width=self._stroke(width))

    def _arc(
        self,
        draw: ImageDraw.ImageDraw,
        box: tuple[float, float, float, float],
        start: float,
        end: float,
        color,
        width: int,
    ) -> None:
        draw.arc(self._box(box), start, end, fill=color, width=self._stroke(width))

    def _polygon(self, draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], fill) -> None:
        draw.polygon([self._point(point) for point in points], fill=fill)

    def _rounded_rectangle(
        self,
        draw: ImageDraw.ImageDraw,
        box: tuple[float, float, float, float],
        outline=None,
        fill=None,
        width: int = 1,
        radius: int = 8,
    ) -> None:
        draw.rounded_rectangle(
            self._box(box),
            radius=self._scale(radius),
            outline=outline,
            fill=fill,
            width=self._stroke(width),
        )

    def _dot(self, draw: ImageDraw.ImageDraw, x: float, y: float, radius: float, color) -> None:
        scaled_x, scaled_y = self._point((x, y))
        scaled_radius = self._scale(radius)
        draw.ellipse(
            (
                scaled_x - scaled_radius,
                scaled_y - scaled_radius,
                scaled_x + scaled_radius,
                scaled_y + scaled_radius,
            ),
            fill=color,
        )

    def _point(self, point: tuple[float, float]) -> tuple[int, int]:
        return (self._scale(point[0]), self._scale(point[1]))

    def _box(self, box: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
        return tuple(self._scale(value) for value in box)

    def _scale(self, value: float) -> int:
        return int(round(value * ICON_SCALE))

    def _stroke(self, width: int | float) -> int:
        return max(1, self._scale(width))

    def _tint(self, hex_color: str, white_mix: float) -> str:
        cleaned = self._clean_hex(hex_color)
        try:
            red = int(cleaned[0:2], 16)
            green = int(cleaned[2:4], 16)
            blue = int(cleaned[4:6], 16)
        except ValueError:
            red, green, blue = 0, 0, 0
        white_mix = min(1.0, max(0.0, white_mix))
        tinted = [
            round(channel * (1 - white_mix) + 255 * white_mix)
            for channel in (red, green, blue)
        ]
        return "".join(f"{channel:02X}" for channel in tinted)

    def _relative_luminance(self, hex_color: str) -> float:
        cleaned = self._clean_hex(hex_color)
        channels = []
        for offset in (0, 2, 4):
            value = int(cleaned[offset : offset + 2], 16) / 255.0
            value = (
                value / 12.92
                if value <= 0.03928
                else ((value + 0.055) / 1.055) ** 2.4
            )
            channels.append(value)
        red, green, blue = channels
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    def _contrast_ratio(self, fg_hex: str, bg_hex: str) -> float:
        light = self._relative_luminance(fg_hex)
        dark = self._relative_luminance(bg_hex)
        lighter, darker = max(light, dark), min(light, dark)
        return (lighter + 0.05) / (darker + 0.05)

    def _readable_text_color(
        self,
        background_hex: str,
        brand: BrandDNA,
        light: str | None = None,
        dark: str | None = None,
        min_ratio: float = 4.5,
    ) -> str:
        """Pick the most legible text color for a given background.

        Prefer the brand's light/dark text color that best contrasts with the
        background; if neither clears AA (4.5:1), fall back to the higher-contrast
        of white/near-black so text on a light brand fill never goes illegible.
        """
        bg = self._clean_hex(background_hex)
        light_hex = self._clean_hex(light or brand.colors.text_light)
        dark_hex = self._clean_hex(dark or brand.colors.text_dark)
        brand_best = max(
            (light_hex, dark_hex), key=lambda candidate: self._contrast_ratio(candidate, bg)
        )
        if self._contrast_ratio(brand_best, bg) >= min_ratio:
            return brand_best
        return (
            "FFFFFF"
            if self._contrast_ratio("FFFFFF", bg) >= self._contrast_ratio("111111", bg)
            else "111111"
        )

    def _shape_fill_hex(self, shape) -> str | None:
        try:
            rgb = shape.fill.fore_color.rgb
        except Exception:
            return None
        if rgb is None:
            return None
        return str(rgb)

    def _fit_font_size(
        self,
        text: str,
        box_width_in: float,
        sizes: list[int],
        max_lines: int = 2,
        char_factor: float = 0.52,
    ) -> int:
        """Pick the largest size (from sizes, largest-first) whose wrapped text fits.

        Width-aware: estimates characters-per-line from the box width and point
        size instead of the raw character count, so a wide box keeps large type.
        Pair with a TEXT_TO_FIT_SHAPE autofit frame to absorb any residual overflow.
        """
        length = len(" ".join(str(text).split()))
        if length == 0 or not sizes:
            return sizes[0] if sizes else 12
        for size in sizes:
            chars_per_line = max(1, int((box_width_in * 72) / (char_factor * size)))
            if chars_per_line * max_lines >= length:
                return size
        return sizes[-1]

    def _autofit(self, frame) -> None:
        try:
            frame.word_wrap = True
            frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass

    def _rgba(self, hex_color: str) -> tuple[int, int, int, int]:
        cleaned = self._clean_hex(hex_color)
        try:
            return (
                int(cleaned[0:2], 16),
                int(cleaned[2:4], 16),
                int(cleaned[4:6], 16),
                255,
            )
        except ValueError:
            return (0, 0, 0, 255)

    def _clean_hex(self, hex_color: str) -> str:
        cleaned = (hex_color or "000000").replace("#", "")[:6]
        if len(cleaned) != 6:
            return "000000"
        return cleaned.upper()

    def _rgb(self, hex_color: str) -> RGBColor:
        return RGBColor.from_string(self._clean_hex(hex_color))

    def _truncate_at_word(self, text: str, limit: int) -> str:
        cleaned = " ".join(str(text).split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[:limit].rsplit(" ", 1)[0].rstrip(".,;:")

