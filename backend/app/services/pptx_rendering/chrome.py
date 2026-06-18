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
from pptx.util import Inches, Pt

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.services.concept_diagram_renderer import ConceptDiagramRenderer, DiagramRenderError
from app.services.pptx_rendering.constants import ICON_SCALE, SLIDE_H, SLIDE_W


class ChromeRenderingMixin:
    def _add_header(
        self,
        slide,
        title: str,
        subheading: str,
        brand: BrandDNA,
        outline: SlideOutline,
        slide_number: int,
    ) -> None:
        reserved_logo_width = brand.logo.size_w + 0.35 if brand.logo else 0
        section_number, section_label = self._section_marker(outline, slide_number)
        kicker = slide.shapes.add_textbox(Inches(0.68), Inches(0.18), Inches(5.4), Inches(0.2))
        kicker_frame = kicker.text_frame
        kicker_frame.clear()
        kicker_run = kicker_frame.paragraphs[0].add_run()
        kicker_run.text = f"SECTION {section_number} - {section_label}"
        kicker_run.font.name = brand.fonts.body
        kicker_run.font.size = Pt(7.5)
        kicker_run.font.bold = True
        kicker_run.font.color.rgb = self._rgb(brand.colors.accent)

        number_x = max(9.95, SLIDE_W - 0.7 - reserved_logo_width - 0.78)
        number_box = slide.shapes.add_textbox(
            Inches(number_x),
            Inches(0.16),
            Inches(0.72),
            Inches(0.34),
        )
        number_frame = number_box.text_frame
        number_frame.clear()
        number_para = number_frame.paragraphs[0]
        number_para.alignment = 2
        number_run = number_para.add_run()
        number_run.text = section_number
        number_run.font.name = brand.fonts.heading
        number_run.font.size = Pt(18)
        number_run.font.bold = True
        number_run.font.color.rgb = self._rgb(self._tint(brand.colors.primary, 0.84))

        accent = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.68),
            Inches(0.46),
            Inches(0.62),
            Inches(0.035),
        )
        accent.fill.solid()
        accent.fill.fore_color.rgb = self._rgb(brand.colors.accent)
        accent.line.color.rgb = self._rgb(brand.colors.accent)
        rule = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.68),
            Inches(1.12),
            Inches(11.95),
            Inches(0.012),
        )
        rule.fill.solid()
        rule.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.secondary, 0.82))
        rule.line.color.rgb = rule.fill.fore_color.rgb
        title_font_size = 24
        title_height = 0.55
        title_limit = 112
        show_subheading = True
        if len(title) > 58:
            title_font_size = 20
            title_height = 0.82
            title_limit = 105
            show_subheading = False
        if len(title) > 96:
            title_font_size = 18
            title_height = 0.95
            title_limit = 98
            show_subheading = False
        title_box = slide.shapes.add_textbox(
            Inches(0.68),
            Inches(0.48),
            Inches(12.1 - reserved_logo_width),
            Inches(title_height),
        )
        frame = title_box.text_frame
        frame.word_wrap = True
        frame.clear()
        para = frame.paragraphs[0]
        run = para.add_run()
        run.text = self._truncate_at_word(title, title_limit)
        run.font.name = brand.fonts.heading
        run.font.size = Pt(title_font_size)
        run.font.bold = True
        run.font.color.rgb = self._rgb(brand.colors.text_dark)
        if subheading and show_subheading:
            sub_y = 0.88 if title_height <= 0.55 else 0.48 + title_height + 0.04
            sub_box = slide.shapes.add_textbox(Inches(0.68), Inches(sub_y), Inches(10.6), Inches(0.22))
            sub_frame = sub_box.text_frame
            sub_frame.clear()
            sub = sub_frame.paragraphs[0].add_run()
            sub.text = self._truncate_at_word(subheading, 150)
            sub.font.name = brand.fonts.body
            sub.font.size = Pt(9)
            sub.font.color.rgb = self._rgb(brand.colors.secondary)

    def _section_marker(self, outline: SlideOutline, slide_number: int) -> tuple[str, str]:
        role = str(
            outline.layout_json.get("narrative_role")
            or outline.content_json.get("narrative_role")
            or ""
        ).lower()
        archetype = str(
            outline.layout_json.get("archetype")
            or outline.content_json.get("archetype")
            or outline.layout_json.get("layout")
            or ""
        ).lower()
        role_sections = {
            "executive_summary": ("01", "EXECUTIVE SUMMARY"),
            "problem": ("02", "DIAGNOSIS"),
            "evidence": ("03", "EVIDENCE"),
            "framework": ("04", "OPERATING MODEL"),
            "reference": ("05", "REFERENCE SYSTEM"),
            "implementation": ("06", "IMPLEMENTATION"),
            "decision": ("07", "DECISION"),
            "closing": ("08", "RECOMMENDATION"),
        }
        if role in role_sections:
            return role_sections[role]
        archetype_sections = {
            "executive_summary": ("01", "EXECUTIVE SUMMARY"),
            "anti_patterns": ("02", "DIAGNOSIS"),
            "dependency_map": ("03", "EVIDENCE"),
            "chart": ("03", "EVIDENCE"),
            "metric_chart": ("03", "EVIDENCE"),
            "comparison_table": ("03", "EVIDENCE"),
            "framework_cycle": ("04", "OPERATING MODEL"),
            "code_panel": ("05", "REFERENCE SYSTEM"),
            "table_reference": ("05", "REFERENCE SYSTEM"),
            "checklist": ("06", "IMPLEMENTATION"),
            "quote_sidebar": ("07", "DECISION"),
            "closing_recommendation": ("08", "RECOMMENDATION"),
        }
        if archetype in archetype_sections:
            return archetype_sections[archetype]
        coarse_section = min(8, max(1, (slide_number + 1) // 2))
        return f"{coarse_section:02d}", "ANALYSIS"

    def _add_footer(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        slide_number: int,
        total_slides: int,
    ) -> None:
        sources = outline.content_json.get("sources") or []
        source_text = "Source: " + "; ".join(sources[:2]) if sources else "Source: [source needed]"
        footer = slide.shapes.add_textbox(Inches(0.6), Inches(7.0), Inches(10.8), Inches(0.25))
        frame = footer.text_frame
        frame.clear()
        run = frame.paragraphs[0].add_run()
        run.text = source_text[:180]
        run.font.name = brand.fonts.body
        run.font.size = Pt(8)
        run.font.color.rgb = self._rgb(brand.colors.secondary)
        page = slide.shapes.add_textbox(Inches(12.1), Inches(7.0), Inches(0.8), Inches(0.25))
        page_frame = page.text_frame
        page_frame.clear()
        page_run = page_frame.paragraphs[0].add_run()
        page_run.text = f"{slide_number}/{total_slides}"
        page_run.font.size = Pt(8)
        page_run.font.color.rgb = self._rgb(brand.colors.secondary)

    def _add_dark_slide_chrome(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        slide_number: int,
        total_slides: int,
        label: str,
    ) -> None:
        background = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0),
            Inches(0),
            Inches(SLIDE_W),
            Inches(SLIDE_H),
        )
        background.fill.solid()
        background.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        background.line.color.rgb = self._rgb(brand.colors.primary)
        title = (
            outline.content_json.get("action_title")
            or outline.content_json.get("title")
            or outline.label
        )
        subheading = outline.content_json.get("subheading") or outline.content_json.get("summary", "")
        section_number, _section_label = self._section_marker(outline, slide_number)
        self._add_dark_text(
            slide,
            f"SECTION {section_number} / {label}",
            0.78,
            0.48,
            3.8,
            0.24,
            brand,
            size=8,
            bold=True,
            color=brand.colors.accent,
        )
        rail = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.78),
            Inches(0.83),
            Inches(1.08),
            Inches(0.045),
        )
        rail.fill.solid()
        rail.fill.fore_color.rgb = self._rgb(brand.colors.accent)
        rail.line.color.rgb = rail.fill.fore_color.rgb
        title_size = 27
        title_height = 0.72
        if len(title) > 72:
            title_size = 23
            title_height = 0.92
        if len(title) > 112:
            title_size = 20
            title_height = 1.05
        self._add_dark_text(
            slide,
            self._truncate_at_word(title, 130),
            0.78,
            1.02,
            8.8,
            title_height,
            brand,
            size=title_size,
            bold=True,
        )
        if subheading and len(title) <= 96:
            self._add_dark_text(
                slide,
                self._truncate_at_word(subheading, 150),
                0.8,
                1.92,
                7.6,
                0.36,
                brand,
                size=10,
                color=self._tint(brand.colors.primary, 0.74),
            )
        number = slide.shapes.add_textbox(Inches(11.55), Inches(0.46), Inches(0.95), Inches(0.44))
        number_frame = number.text_frame
        number_frame.clear()
        number_para = number_frame.paragraphs[0]
        number_para.alignment = 2
        number_run = number_para.add_run()
        number_run.text = f"{slide_number:02d}"
        number_run.font.name = brand.fonts.heading
        number_run.font.size = Pt(20)
        number_run.font.bold = True
        number_run.font.color.rgb = self._rgb(self._tint(brand.colors.primary, 0.46))
        self._add_dark_footer(slide, outline, brand, slide_number, total_slides)

    def _add_dark_footer(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        slide_number: int,
        total_slides: int,
    ) -> None:
        sources = outline.content_json.get("sources") or []
        source_text = "Source: " + "; ".join(sources[:2]) if sources else "Source: [source needed]"
        self._add_dark_text(
            slide,
            source_text[:180],
            0.72,
            6.96,
            8.4,
            0.22,
            brand,
            size=7,
            color=self._tint(brand.colors.primary, 0.58),
        )
        self._add_dark_text(
            slide,
            f"{slide_number}/{total_slides}",
            12.0,
            6.96,
            0.64,
            0.22,
            brand,
            size=7,
            color=self._tint(brand.colors.primary, 0.58),
        )

