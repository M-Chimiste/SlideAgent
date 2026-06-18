from pathlib import Path
import math
import re
import shutil
import subprocess
from typing import Any

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.util import Inches, Pt

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.services.concept_diagram_renderer import ConceptDiagramRenderer, DiagramRenderError


SLIDE_W = 13.333
SLIDE_H = 7.5
ICON_SCALE = 4


class DeterministicPptxRenderer:
    def render(
        self,
        outlines: list[SlideOutline],
        brand: BrandDNA,
        output_path: Path,
        enable_diagrams: bool = True,
    ) -> list[dict[str, str | int]]:
        self._warnings: list[dict[str, str | int]] = []
        self._icon_cache_dir = output_path.parent / f"{output_path.stem}-icons"
        self._icon_cache_dir.mkdir(parents=True, exist_ok=True)
        self._diagram_cache_dir = (
            output_path.parent / f"{output_path.stem}-diagrams"
            if enable_diagrams
            else None
        )
        self._diagram_renderer = ConceptDiagramRenderer() if enable_diagrams else None
        prs = Presentation()
        prs.slide_width = Inches(SLIDE_W)
        prs.slide_height = Inches(SLIDE_H)
        blank_layout = prs.slide_layouts[6]
        for index, outline in enumerate(outlines):
            slide = prs.slides.add_slide(blank_layout)
            self._render_slide(slide, outline, brand, index + 1, len(outlines))
        prs.save(output_path.as_posix())
        return self._warnings

    def _render_slide(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        slide_number: int,
        total_slides: int,
    ) -> None:
        title = outline.content_json.get("action_title") or outline.content_json.get("title") or outline.label
        subheading = outline.content_json.get("subheading") or outline.content_json.get("summary", "")
        layout = outline.layout_json.get("layout", "two_column")
        if layout == "cover":
            self._add_cover(slide, outline, brand)
            self._add_logo(slide, brand)
            return
        if layout == "section_divider":
            self._add_section_divider(slide, outline, brand, slide_number)
            self._add_logo(slide, brand)
            return
        if layout == "framework_cycle":
            self._add_framework_cycle_immersive(
                slide, outline, brand, slide_number, total_slides
            )
            self._add_logo(slide, brand)
            return
        if layout == "quote_sidebar":
            self._add_quote_sidebar_immersive(
                slide, outline, brand, slide_number, total_slides
            )
            self._add_logo(slide, brand)
            return
        if layout == "closing_recommendation":
            self._add_closing_recommendation_immersive(
                slide, outline, brand, slide_number, total_slides
            )
            self._add_logo(slide, brand)
            return
        self._add_header(slide, title, subheading, brand, outline, slide_number)
        self._add_logo(slide, brand)
        self._add_footer(slide, outline, brand, slide_number, total_slides)

        if layout == "executive_summary":
            self._add_executive_summary(slide, outline, brand)
        elif layout == "chart":
            self._add_metric_chart(slide, outline, brand)
        elif layout == "comparison_table":
            self._add_comparison_table(slide, outline, brand)
        elif layout == "callouts":
            self._add_callouts(slide, outline, brand)
        elif layout == "process":
            self._add_table_or_process(slide, outline, brand)
        elif layout == "quote_sidebar":
            self._add_quote_sidebar(slide, outline, brand)
        elif layout == "framework_cycle":
            self._add_framework_cycle(slide, outline, brand)
        elif layout == "dependency_map":
            self._add_dependency_map(slide, outline, brand)
        elif layout == "checklist":
            self._add_checklist(slide, outline, brand)
        elif layout == "code_panel":
            self._add_code_panel(slide, outline, brand)
        elif layout == "anti_patterns":
            self._add_anti_patterns(slide, outline, brand)
        elif layout == "table_reference":
            self._add_reference_table(slide, outline, brand)
        elif layout == "closing_recommendation":
            self._add_closing_recommendation(slide, outline, brand)
        elif layout == "icon_grid":
            self._add_grid(slide, outline, brand)
        elif layout == "icon_rows":
            self._add_icon_rows(slide, outline, brand)
        else:
            self._add_two_column(slide, outline, brand)

    def _try_add_diagram_asset(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        x: float,
        y: float,
        width: float,
        height: float,
        dark: bool = False,
    ) -> bool:
        renderer = getattr(self, "_diagram_renderer", None)
        output_dir = getattr(self, "_diagram_cache_dir", None)
        if renderer is None or output_dir is None:
            return False
        try:
            layout = str(outline.layout_json.get("layout") or "diagram")
            artifact = renderer.render(
                outline,
                brand,
                output_dir,
                self._diagram_stem(outline, layout),
                dark=dark,
            )
            slide.shapes.add_picture(
                artifact.png_path.as_posix(),
                Inches(x),
                Inches(y),
                Inches(width),
                Inches(height),
            )
            return True
        except (DiagramRenderError, OSError, RuntimeError, ValueError) as exc:
            self._warnings.append(
                {
                    "slide_index": outline.slide_index,
                    "field": "diagram_render",
                    "message": self._truncate_phrase(
                        f"Diagram asset render failed; used native fallback. Reason: {exc}",
                        220,
                    ),
                }
            )
            return False

    def _diagram_stem(self, outline: SlideOutline, layout: str) -> str:
        label = outline.label or outline.content_json.get("action_title") or layout
        slug = re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")
        return f"{outline.slide_index + 1:02d}-{layout}-{slug[:42] or 'diagram'}"

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

    def _add_logo(self, slide, brand: BrandDNA) -> None:
        if not brand.logo:
            return
        logo_path = Path(brand.logo.path)
        if not logo_path.exists():
            return
        x = SLIDE_W - 0.6 - brand.logo.size_w
        y = 0.3
        slide.shapes.add_picture(
            logo_path.as_posix(),
            Inches(x),
            Inches(y),
            width=Inches(brand.logo.size_w),
            height=Inches(brand.logo.size_h),
        )

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

    def _add_cover(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
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
        exhibit = self._exhibit(outline)
        thesis = (
            exhibit.get("thesis")
            or outline.content_json.get("subheading")
            or outline.content_json.get("summary")
            or "A practical operating model for executive action."
        )
        self._add_dark_text(
            slide,
            "EXECUTIVE PERSPECTIVE",
            0.78,
            0.74,
            2.8,
            0.26,
            brand,
            size=10,
            bold=True,
            color=self._tint(brand.colors.primary, 0.78),
        )
        rail = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.78),
            Inches(1.08),
            Inches(1.15),
            Inches(0.04),
        )
        rail.fill.solid()
        rail.fill.fore_color.rgb = self._rgb(brand.colors.accent)
        rail.line.color.rgb = self._rgb(brand.colors.accent)
        rail.line.width = Pt(0)
        self._add_dark_text(slide, title, 0.78, 1.48, 8.25, 1.45, brand, size=34, bold=True)
        self._add_dark_text(
            slide,
            self._truncate_at_word(thesis, 175),
            0.82,
            3.25,
            7.0,
            0.8,
            brand,
            size=14,
            color=self._tint(brand.colors.primary, 0.76),
        )
        stack_x, stack_y = 9.0, 1.22
        stack_items = [
            ("01", "Context", "Persist the source of truth"),
            ("02", "Rules", "Constrain generation"),
            ("03", "Review", "Verify before scale"),
        ]
        for idx, (number, label, detail) in enumerate(stack_items):
            y = stack_y + idx * 1.22
            card = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(stack_x),
                Inches(y),
                Inches(3.18),
                Inches(0.82),
            )
            card.fill.solid()
            card.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.primary, 0.16 + idx * 0.08))
            card.line.color.rgb = self._rgb(self._tint(brand.colors.primary, 0.36))
            self._add_dark_text(
                slide,
                number,
                stack_x + 0.18,
                y + 0.23,
                0.58,
                0.24,
                brand,
                size=10,
                bold=True,
                color=brand.colors.accent,
            )
            self._add_dark_text(
                slide,
                label,
                stack_x + 0.82,
                y + 0.20,
                1.85,
                0.26,
                brand,
                size=11,
                bold=True,
                color=brand.colors.text_light,
            )
            self._add_dark_text(
                slide,
                detail,
                stack_x + 0.82,
                y + 0.50,
                2.08,
                0.22,
                brand,
                size=8,
                color=self._tint(brand.colors.primary, 0.82),
            )
            if idx < len(stack_items) - 1:
                self._add_arrow(
                    slide,
                    stack_x + 1.6,
                    y + 0.84,
                    stack_x + 1.6,
                    y + 1.18,
                    brand.colors.accent,
                    width=1.2,
                )

    def _add_executive_summary(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        exhibit = self._exhibit(outline)
        messages = exhibit.get("messages") if exhibit.get("type") == "executive_summary" else None
        bullets = [
            str(item.get("text", ""))
            for item in messages
            if isinstance(item, dict) and str(item.get("text", "")).strip()
        ] if isinstance(messages, list) else self._bullets(outline)
        y = 1.55
        labels = [
            str(item.get("label", ""))
            for item in messages
            if isinstance(item, dict) and str(item.get("label", "")).strip()
        ] if isinstance(messages, list) else ["Situation", "Complication", "Resolution"]
        while len(labels) < 3:
            labels.append(["Situation", "Complication", "Resolution"][len(labels)])
        colors = [brand.colors.primary, brand.colors.secondary, brand.colors.accent]
        panel = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(8.42),
            Inches(1.48),
            Inches(3.72),
            Inches(3.95),
        )
        panel.fill.solid()
        panel.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        panel.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_dark_text(
            slide,
            "PROOF POINTS",
            8.72,
            1.82,
            1.5,
            0.22,
            brand,
            size=8,
            bold=True,
            color=brand.colors.accent,
        )
        proof_points = self._summary_proof_points(exhibit, outline)
        for idx, proof in enumerate(proof_points[:3]):
            y_pos = 2.24 + idx * 0.88
            value = str(proof.get("value", ""))
            unit = ""
            if isinstance(proof.get("value"), (int, float)):
                value, unit = self._metric_card_value_parts(proof)
            self._add_dark_text(
                slide,
                value,
                8.72,
                y_pos,
                0.86,
                0.34,
                brand,
                size=18,
                bold=True,
                color=brand.colors.text_light,
            )
            label = str(proof.get("label") or "Signal")
            if unit and unit.lower() not in label.lower():
                label = f"{unit} / {label}"
            self._add_dark_text(
                slide,
                self._truncate_at_word(label, 32),
                9.68,
                y_pos + 0.02,
                2.06,
                0.2,
                brand,
                size=8,
                bold=True,
                color=self._tint(brand.colors.primary, 0.84),
            )
            self._add_dark_text(
                slide,
                self._truncate_phrase(str(proof.get("detail") or ""), 62),
                9.68,
                y_pos + 0.28,
                2.0,
                0.35,
                brand,
                size=7,
                color=self._tint(brand.colors.primary, 0.7),
            )
        rail = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.86),
            Inches(1.55),
            Inches(0.04),
            Inches(3.78),
        )
        rail.fill.solid()
        rail.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.primary, 0.58))
        rail.line.color.rgb = rail.fill.fore_color.rgb
        for idx, label in enumerate(labels[:3]):
            row_y = y + idx * 1.24
            row = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(1.05),
                Inches(row_y),
                Inches(6.95),
                Inches(0.96),
            )
            row.fill.solid()
            row.fill.fore_color.rgb = self._rgb("FFFFFF" if idx % 2 == 0 else "F4F6F8")
            row.line.color.rgb = self._rgb(brand.colors.background_light)
            strip = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(1.05),
                Inches(row_y),
                Inches(0.12),
                Inches(0.96),
            )
            strip.fill.solid()
            strip.fill.fore_color.rgb = self._rgb(colors[idx % len(colors)])
            strip.line.color.rgb = strip.fill.fore_color.rgb
            self._add_dark_text(
                slide,
                f"0{idx + 1}",
                1.34,
                row_y + 0.29,
                0.45,
                0.24,
                brand,
                size=10,
                bold=True,
                color=colors[idx % len(colors)],
            )
            self._add_dark_text(
                slide,
                label,
                2.0,
                row_y + 0.19,
                2.35,
                0.28,
                brand,
                size=13,
                bold=True,
                color=brand.colors.primary,
            )
            text = bullets[idx] if idx < len(bullets) else "Define the critical implication for leadership."
            self._add_body_text(
                slide,
                self._truncate_at_word(text, 128),
                4.42,
                row_y + 0.2,
                3.1,
                0.48,
                brand,
                size=10,
        )
        recommendation = (
            exhibit.get("recommendation")
            or "Manage the work with persistent context, explicit rules, and evidence-backed review."
        )
        rec = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(1.05),
            Inches(5.62),
            Inches(11.1),
            Inches(0.72),
        )
        rec.fill.solid()
        rec.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.accent, 0.86))
        rec.line.color.rgb = self._rgb(self._tint(brand.colors.accent, 0.7))
        self._add_body_text(
            slide,
            "Decision ask",
            1.34,
            5.84,
            1.2,
            0.24,
            brand,
            size=8,
        )
        self._add_body_text(
            slide,
            self._truncate_at_word(str(recommendation), 150),
            2.58,
            5.78,
            8.8,
            0.32,
            brand,
            size=11,
        )

    def _summary_proof_points(
        self, exhibit: dict[str, Any], outline: SlideOutline
    ) -> list[dict[str, Any]]:
        proof_points = exhibit.get("proof_points", [])
        if isinstance(proof_points, list) and proof_points:
            return [
                item
                for item in proof_points
                if isinstance(item, dict) and str(item.get("label") or item.get("value") or "").strip()
            ]
        metrics = [
            metric
            for metric in outline.content_json.get("metrics", [])
            if isinstance(metric, dict)
        ]
        if metrics:
            return metrics
        return [
            {"label": "Context", "value": "1", "detail": "Persistent memory keeps work reproducible."},
            {"label": "Rules", "value": "2", "detail": "Acceptance criteria constrain generation."},
            {"label": "Review", "value": "3", "detail": "Evidence gates protect delivery quality."},
        ]

    def _add_two_column(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        bullets = self._bullets(outline)
        left = bullets[:2] or ["Clarify the decision context and why it matters now."]
        right = bullets[2:5] or ["Focus leadership attention on the highest-value next moves."]
        icons = self._icons(outline)
        self._add_card(slide, 0.85, 1.55, 5.75, 4.75, "FFFFFF", brand.colors.background_light)
        self._add_card(slide, 6.9, 1.55, 5.75, 4.75, "FFFFFF", brand.colors.background_light)
        self._add_icon(slide, icons[0], 1.12, 1.74, 0.78, brand, brand.colors.primary)
        self._add_label(slide, "Implication", 2.06, 1.95, 4.2, brand, bold=True)
        self._add_bullets(slide, left, 1.15, 2.52, 4.95, 2.82, brand)
        self._add_icon(slide, icons[1], 7.17, 1.74, 0.78, brand, brand.colors.secondary)
        self._add_label(slide, "Evidence", 8.11, 1.95, 4.2, brand, bold=True)
        self._add_bullets(slide, right, 7.2, 2.52, 4.95, 2.82, brand)

    def _add_callouts(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        metrics = outline.content_json.get("metrics") or []
        if not metrics:
            metrics = [{"label": item, "value": idx + 1} for idx, item in enumerate(self._bullets(outline)[:3])]
        icons = self._icons(outline)
        for idx, metric in enumerate(metrics[:3]):
            x = 0.95 + idx * 4.05
            self._add_card(slide, x, 1.65, 3.45, 3.75, "FFFFFF", brand.colors.background_light)
            strip = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(x),
                Inches(1.65),
                Inches(3.45),
                Inches(0.12),
            )
            strip.fill.solid()
            strip.fill.fore_color.rgb = self._rgb(brand.colors.accent if idx == 0 else brand.colors.secondary)
            strip.line.color.rgb = strip.fill.fore_color.rgb
            value = str(metric.get("value", "1"))
            unit = metric.get("unit") or ""
            self._add_icon(slide, icons[idx], x + 2.54, 1.86, 0.74, brand, self._icon_fill(brand, idx))
            self._add_big_number(slide, f"{value}{unit}", x + 0.2, 2.05, 3.05, brand)
            self._add_body_text(slide, metric.get("label", "Metric"), x + 0.35, 3.35, 2.75, 1.35, brand, center=True, size=14)

    def _add_metric_chart(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        metrics = outline.content_json.get("metrics") or []
        exhibit = self._exhibit(outline)
        if not metrics and exhibit.get("type") == "metric_chart":
            metrics = exhibit.get("metrics") or []
        metrics = [metric for metric in metrics if isinstance(metric, dict)]
        if not metrics:
            self._add_two_column(slide, outline, brand)
            return
        display_metrics = metrics[:4]
        count = len(display_metrics)
        gap = 0.28
        card_w = (11.75 - gap * (count - 1)) / count
        self._add_label(slide, "SOURCED SIGNALS", 0.9, 1.45, 2.2, brand, bold=True)
        for idx, metric in enumerate(display_metrics):
            x = 0.85 + idx * (card_w + gap)
            accent = self._icon_fill(brand, idx)
            value_text, unit_text = self._metric_card_value_parts(metric)
            self._add_card(slide, x, 1.86, card_w, 2.6, "FFFFFF", brand.colors.background_light)
            strip = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(x),
                Inches(1.86),
                Inches(card_w),
                Inches(0.12),
            )
            strip.fill.solid()
            strip.fill.fore_color.rgb = self._rgb(accent)
            strip.line.color.rgb = strip.fill.fore_color.rgb
            self._add_big_number(
                slide,
                value_text,
                x + 0.22,
                2.26,
                card_w - 0.44,
                brand,
            )
            label_y = 3.28
            if unit_text:
                self._add_dark_text(
                    slide,
                    unit_text,
                    x + 0.3,
                    3.02,
                    card_w - 0.6,
                    0.24,
                    brand,
                    size=16,
                    bold=True,
                    color=brand.colors.primary,
                )
                label_y = 3.58
            self._add_body_text(
                slide,
                self._metric_label_text(metric.get("label", "Metric")),
                x + 0.28,
                label_y,
                card_w - 0.56,
                0.72,
                brand,
                center=True,
                size=12,
            )

        insight = self._metric_insight(outline, display_metrics)
        self._add_card(slide, 1.2, 4.92, 10.9, 0.86, brand.colors.background_light, brand.colors.background_light)
        self._add_body_text(slide, insight, 1.52, 5.14, 10.25, 0.34, brand, center=True, size=13)

    def _metric_card_value_parts(self, metric: dict[str, Any]) -> tuple[str, str]:
        unit = str(metric.get("unit") or "")
        try:
            numeric = float(metric.get("value", ""))
        except (TypeError, ValueError):
            return self._truncate_at_word(str(metric.get("value", "")), 10), ""
        if unit == "%":
            return f"{self._format_compact_number(numeric)}%", ""
        if unit.lower() == "tokens":
            return self._format_compact_number(numeric), "tokens"
        if unit:
            return self._format_compact_number(numeric), self._truncate_at_word(unit, 12)
        return self._format_compact_number(numeric), ""

    def _format_metric_value(self, metric: dict[str, Any]) -> str:
        value = metric.get("value", "")
        unit = str(metric.get("unit") or "")
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)[:12]
        if unit == "%":
            return f"{self._format_compact_number(numeric)}%"
        if unit.lower() == "tokens":
            return f"{self._format_compact_number(numeric)} tokens"
        return self._format_compact_number(numeric)

    def _format_compact_number(self, value: float) -> str:
        if abs(value) >= 1_000_000:
            compact = value / 1_000_000
            suffix = "M"
        elif abs(value) >= 1_000:
            compact = value / 1_000
            suffix = "k"
        else:
            compact = value
            suffix = ""
        if float(compact).is_integer():
            return f"{int(compact)}{suffix}"
        return f"{compact:.1f}".rstrip("0").rstrip(".") + suffix

    def _metric_label_text(self, label: Any) -> str:
        words = " ".join(str(label).split()).split()
        if len(words) <= 8:
            return " ".join(words)
        return " ".join(words[:8])

    def _metric_insight(self, outline: SlideOutline, metrics: list[dict[str, Any]]) -> str:
        units = {str(metric.get("unit") or "").lower() for metric in metrics}
        if "%" in units and "tokens" in units:
            return "Adoption and capacity are high enough to make operating discipline the constraint."
        if "%" in units:
            return "Treat high adoption as a signal to formalize review, ownership, and quality gates."
        if "tokens" in units:
            return "Larger context windows help, but persistent project memory still carries the workflow."
        bullets = self._bullets(outline)
        text = bullets[0] if bullets else outline.content_json.get("subheading", "")
        if str(text).lower().startswith("evidence from"):
            text = outline.content_json.get("subheading", "")
        if not text:
            return "Use these figures as pressure signals, then manage the operating model."
        words = " ".join(str(text).split()).split()
        return " ".join(words[:18])

    def _add_comparison_table(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        exhibit = self._exhibit(outline)
        columns, rows = self._comparison_rows(exhibit, outline)
        display_rows = rows[:5]
        if not display_rows:
            self._add_two_column(slide, outline, brand)
            return

        rail = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.9),
            Inches(1.5),
            Inches(2.72),
            Inches(4.82),
        )
        rail.fill.solid()
        rail.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        rail.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_dark_text(
            slide,
            "COMPARISON LENS",
            1.18,
            1.86,
            1.8,
            0.24,
            brand,
            size=10,
            color=brand.colors.accent,
        )
        self._add_dark_text(
            slide,
            f"{len(display_rows)} shifts",
            1.18,
            2.42,
            1.9,
            0.42,
            brand,
            size=22,
            bold=True,
        )
        self._add_dark_text(
            slide,
            self._comparison_panel_insight(columns, display_rows),
            1.2,
            3.18,
            2.0,
            1.14,
            brand,
            size=11,
            color=self._tint(brand.colors.primary, 0.76),
        )
        self._add_dark_text(
            slide,
            "Read left to right: what changes, what improves, and where the target model tightens control.",
            1.2,
            5.22,
            2.05,
            0.7,
            brand,
            size=9,
            color=self._tint(brand.colors.primary, 0.68),
        )

        current_header = columns[1] if len(columns) > 1 else "Current state"
        target_header = columns[2] if len(columns) > 2 else "Target state"
        self._add_label(slide, str(current_header).upper(), 4.9, 1.54, 2.6, brand, bold=True)
        self._add_label(slide, str(target_header).upper(), 8.78, 1.54, 2.6, brand, bold=True)

        row_count = len(display_rows)
        row_h = 0.72 if row_count <= 4 else 0.62
        gap = 0.22 if row_count <= 4 else 0.14
        start_y = 2.02
        for idx, row in enumerate(display_rows):
            cells = (row + ["", ""])[:3]
            dimension = self._truncate_at_word(cells[0], 28)
            current = self._truncate_at_word(cells[1], 72)
            target = self._truncate_at_word(cells[2], 72)
            y = start_y + idx * (row_h + gap)
            accent = self._icon_fill(brand, idx)

            self._add_card(
                slide,
                3.92,
                y,
                0.78,
                row_h,
                self._tint(accent, 0.84),
                self._tint(accent, 0.66),
            )
            self._add_body_text(slide, dimension, 4.02, y + 0.18, 0.56, 0.28, brand, center=True, size=8)

            self._add_card(slide, 4.92, y, 2.75, row_h, "FFFFFF", brand.colors.background_light)
            self._add_body_text(slide, current, 5.16, y + 0.17, 2.24, 0.3, brand, size=10)

            self._add_arrow(slide, 7.86, y + row_h / 2, 8.42, y + row_h / 2, brand.colors.accent, width=1.6)
            self._add_arrowhead(slide, 8.42, y + row_h / 2, 0.2, 0, brand.colors.accent)

            self._add_card(slide, 8.62, y, 3.62, row_h, "F4F6F8", brand.colors.background_light)
            self._add_body_text(slide, target, 8.88, y + 0.17, 3.02, 0.3, brand, size=10)

        self._add_card(slide, 4.92, 6.0, 7.32, 0.42, self._tint(brand.colors.accent, 0.88), self._tint(brand.colors.accent, 0.74))
        self._add_body_text(slide, "TARGET TEST", 5.18, 6.11, 1.16, 0.16, brand, size=7)
        self._add_body_text(
            slide,
            "Every row should make the behavior change explicit enough to inspect or assign.",
            6.48,
            6.08,
            4.96,
            0.2,
            brand,
            size=9,
        )

    def _comparison_panel_insight(
        self, columns: list[str], rows: list[list[str]]
    ) -> str:
        if not rows:
            return "Use the comparison to make the target-state behavior explicit."
        header_text = " ".join(str(column).lower() for column in columns)
        if "target" in header_text or "after" in header_text:
            return "Make the target model concrete by pairing each current behavior with the operating change."
        if "risk" in header_text or "impact" in header_text:
            return "Separate the issue from the consequence so leaders can judge priority."
        return "Turn the comparison into an operating choice, not a static list of differences."

    def _add_reference_table(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        exhibit = self._exhibit(outline)
        columns, rows = self._reference_rows(exhibit, outline)
        display_rows = rows[:5]
        left = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.9),
            Inches(1.48),
            Inches(3.1),
            Inches(4.92),
        )
        left.fill.solid()
        left.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        left.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_dark_text(
            slide,
            "REFERENCE MAP",
            1.2,
            1.84,
            1.9,
            0.24,
            brand,
            size=10,
            color=brand.colors.accent,
        )
        self._add_dark_text(
            slide,
            f"{len(display_rows)} artifacts",
            1.2,
            2.42,
            2.05,
            0.42,
            brand,
            size=20,
            bold=True,
        )
        self._add_dark_text(
            slide,
            self._reference_table_insight(columns, display_rows),
            1.22,
            3.18,
            2.24,
            1.2,
            brand,
            size=11,
            color=self._tint(brand.colors.primary, 0.76),
        )
        self._add_dark_text(
            slide,
            "Use as the source of truth for ownership, purpose, and refresh triggers.",
            1.22,
            5.24,
            2.28,
            0.62,
            brand,
            size=9,
            color=self._tint(brand.colors.primary, 0.68),
        )

        x = 4.35
        y = 1.54
        row_h = 0.72
        gap = 0.16
        col_w = [2.2, 3.28, 2.46]
        headers = (columns + ["Purpose", "Update trigger"])[:3]
        for idx, header in enumerate(headers):
            self._add_label(
                slide,
                str(header).upper(),
                x + sum(col_w[:idx]) + idx * 0.16,
                y,
                col_w[idx],
                brand,
                bold=True,
            )
        for r_idx, row in enumerate(display_rows):
            row_y = y + 0.48 + r_idx * (row_h + gap)
            fill = "FFFFFF" if r_idx % 2 == 0 else "F4F6F8"
            self._add_card(slide, x, row_y, 8.26, row_h, fill, brand.colors.background_light)
            strip = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(x),
                Inches(row_y),
                Inches(0.08),
                Inches(row_h),
            )
            strip.fill.solid()
            strip.fill.fore_color.rgb = self._rgb(self._icon_fill(brand, r_idx))
            strip.line.color.rgb = strip.fill.fore_color.rgb
            cells = (row + ["", ""])[:3]
            self._add_body_text(
                slide,
                self._truncate_at_word(cells[0], 32),
                x + 0.28,
                row_y + 0.18,
                col_w[0] - 0.34,
                0.24,
                brand,
                size=10,
            )
            self._add_body_text(
                slide,
                self._truncate_at_word(cells[1], 76),
                x + col_w[0] + 0.36,
                row_y + 0.16,
                col_w[1] - 0.22,
                0.3,
                brand,
                size=9,
            )
            self._add_body_text(
                slide,
                self._truncate_at_word(cells[2], 58),
                x + col_w[0] + col_w[1] + 0.54,
                row_y + 0.16,
                col_w[2] - 0.28,
                0.3,
                brand,
                size=9,
            )
        self._add_card(slide, 4.35, 6.02, 8.26, 0.42, self._tint(brand.colors.accent, 0.88), self._tint(brand.colors.accent, 0.74))
        self._add_body_text(slide, "UPDATE CADENCE", 4.62, 6.13, 1.45, 0.16, brand, size=7)
        self._add_body_text(
            slide,
            "Refresh the artifact when source evidence, ownership, or risk changes.",
            6.22,
            6.1,
            5.72,
            0.2,
            brand,
            size=9,
        )

    def _reference_table_insight(
        self, columns: list[str], rows: list[list[str]]
    ) -> str:
        if not rows:
            return "Keep the reusable artifacts explicit so the operating model can be repeated."
        header_text = " ".join(str(column).lower() for column in columns)
        if "update" in header_text or "trigger" in header_text:
            return "Make refresh triggers visible so reference material stays current as conditions change."
        if "owner" in header_text or "timing" in header_text:
            return "Make ownership visible so each artifact has a clear accountable maintainer."
        return "Turn the table into a reusable operating reference, not a one-time appendix."

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

    def _add_framework_cycle_immersive(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        slide_number: int,
        total_slides: int,
    ) -> None:
        self._add_dark_slide_chrome(
            slide, outline, brand, slide_number, total_slides, "OPERATING MODEL"
        )
        if self._try_add_diagram_asset(
            slide, outline, brand, 0.92, 1.76, 11.5, 4.92, dark=True
        ):
            return
        exhibit = self._exhibit(outline)
        steps = exhibit.get("steps") if exhibit.get("type") == "cycle" else None
        if isinstance(steps, list) and steps:
            bullets = [
                str(step.get("label") or step.get("description") or "").strip()
                for step in steps
                if isinstance(step, dict)
            ][:6]
        else:
            bullets = self._bullets(outline)[:6]
        if len(bullets) < 4:
            bullets = (
                bullets
                + [
                    "Load context",
                    "Plan the work",
                    "Execute changes",
                    "Review evidence",
                    "Update memory",
                    "Reset cleanly",
                ]
            )[:6]
        while len(bullets) < 6:
            bullets.append(["Plan", "Execute", "Review", "Update", "Reset", "Repeat"][len(bullets)])
        center_x, center_y = 6.66, 4.18
        loop = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            Inches(center_x - 1.04),
            Inches(center_y - 1.04),
            Inches(2.08),
            Inches(2.08),
        )
        loop.fill.solid()
        loop.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.primary, 0.1))
        loop.line.color.rgb = self._rgb(brand.colors.accent)
        loop.line.width = Pt(1.4)
        self._add_dark_text(
            slide,
            self._truncate_at_word(str(exhibit.get("center_label") or "Operating loop"), 28),
            center_x - 0.62,
            center_y - 0.22,
            1.24,
            0.44,
            brand,
            size=12,
            bold=True,
            color=brand.colors.text_light,
        )
        positions = [
            (3.35, 2.72),
            (6.66, 2.38),
            (9.98, 2.72),
            (9.98, 5.06),
            (6.66, 5.38),
            (3.35, 5.06),
        ]
        icons = self._icons(outline)
        for idx, (x1, y1) in enumerate(positions):
            x2, y2 = positions[(idx + 1) % len(positions)]
            self._add_arrow(slide, x1, y1, x2, y2, brand.colors.accent, width=1.7)
            mid_x = (x1 + x2) / 2
            mid_y = (y1 + y2) / 2
            self._add_arrowhead(slide, mid_x, mid_y, x2 - x1, y2 - y1, brand.colors.accent)
        for idx, (x, y) in enumerate(positions):
            card = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(x - 1.18),
                Inches(y - 0.42),
                Inches(2.36),
                Inches(0.86),
            )
            card.fill.solid()
            card.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.primary, 0.16 + (idx % 2) * 0.05))
            card.line.color.rgb = self._rgb(self._tint(brand.colors.primary, 0.34))
            self._add_icon(slide, icons[idx % len(icons)], x - 1.0, y - 0.26, 0.52, brand, self._icon_fill(brand, idx))
            self._add_dark_text(
                slide,
                self._truncate_at_word(bullets[idx], 34),
                x - 0.32,
                y - 0.19,
                1.2,
                0.34,
                brand,
                size=9,
                bold=True,
                color=self._tint(brand.colors.primary, 0.86),
            )

    def _add_quote_sidebar_immersive(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        slide_number: int,
        total_slides: int,
    ) -> None:
        self._add_dark_slide_chrome(
            slide, outline, brand, slide_number, total_slides, "DECISION LENS"
        )
        exhibit = self._exhibit(outline)
        bullets = [
            str(item)
            for item in exhibit.get("supporting_points", [])
            if str(item).strip()
        ][:4] or self._bullets(outline)[:4]
        if not bullets:
            bullets = ["Shift the operating model from ad hoc execution to managed discipline."]
        quote = (
            exhibit.get("quote")
            or exhibit.get("key_idea")
            or outline.content_json.get("summary")
            or outline.content_json.get("subheading")
            or bullets[0]
        )
        callout = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.86),
            Inches(2.54),
            Inches(5.86),
            Inches(2.8),
        )
        callout.fill.solid()
        callout.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.primary, 0.1))
        callout.line.color.rgb = self._rgb(self._tint(brand.colors.primary, 0.3))
        self._add_dark_text(slide, "THE MENTAL MODEL", 1.16, 2.88, 2.2, 0.22, brand, size=8, bold=True, color=brand.colors.accent)
        self._add_dark_text(
            slide,
            self._truncate_phrase(str(quote), 165),
            1.16,
            3.35,
            4.92,
            1.0,
            brand,
            size=20,
            bold=True,
            color=brand.colors.text_light,
        )
        self._add_dark_text(
            slide,
            "Use the model to decide what must be explicit before the next session.",
            1.18,
            4.72,
            4.8,
            0.34,
            brand,
            size=9,
            color=self._tint(brand.colors.primary, 0.68),
        )
        icons = self._icons(outline)
        for idx, text in enumerate(bullets[:4]):
            y = 2.42 + idx * 0.86
            card = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(7.35),
                Inches(y),
                Inches(4.35),
                Inches(0.64),
            )
            card.fill.solid()
            card.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.primary, 0.15 + idx * 0.03))
            card.line.color.rgb = self._rgb(self._tint(brand.colors.primary, 0.34))
            self._add_icon(slide, icons[idx % len(icons)], 7.58, y + 0.1, 0.42, brand, self._icon_fill(brand, idx))
            self._add_dark_text(
                slide,
                self._truncate_phrase(text, 78),
                8.16,
                y + 0.14,
                3.1,
                0.28,
                brand,
                size=8,
                color=self._tint(brand.colors.primary, 0.84),
            )
        connector = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            Inches(6.74),
            Inches(3.94),
            Inches(7.34),
            Inches(3.94),
        )
        connector.line.color.rgb = self._rgb(brand.colors.accent)
        connector.line.width = Pt(1.4)

    def _add_closing_recommendation_immersive(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        slide_number: int,
        total_slides: int,
    ) -> None:
        self._add_dark_slide_chrome(
            slide, outline, brand, slide_number, total_slides, "FINAL DECISION"
        )
        exhibit = self._exhibit(outline)
        recommendation = (
            exhibit.get("recommendation")
            or outline.content_json.get("action_title")
            or outline.label
        )
        recommendation = self._nonduplicate_closing_recommendation(
            str(recommendation),
            str(outline.content_json.get("action_title") or outline.label),
        )
        next_steps = [str(item) for item in exhibit.get("next_steps", []) if str(item).strip()]
        if not next_steps:
            next_steps = self._bullets(outline)[:3]
        if not next_steps:
            next_steps = [
                "Confirm the decision owner.",
                "Run the first governed workflow.",
                "Update the shared reference after each milestone.",
            ]
        ask = str(exhibit.get("decision_ask") or "Confirm owner, scope, and timing.")
        self._add_dark_text(slide, "RECOMMENDATION", 0.92, 2.5, 2.2, 0.24, brand, size=9, bold=True, color=brand.colors.accent)
        self._add_dark_text(
            slide,
            self._truncate_phrase(recommendation, 155),
            0.92,
            2.96,
            6.1,
            1.05,
            brand,
            size=24,
            bold=True,
            color=brand.colors.text_light,
        )
        ask_box = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.92),
            Inches(4.82),
            Inches(5.86),
            Inches(0.78),
        )
        ask_box.fill.solid()
        ask_box.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.accent, 0.18))
        ask_box.line.color.rgb = self._rgb(self._tint(brand.colors.accent, 0.38))
        self._add_dark_text(slide, "DECISION ASK", 1.16, 5.04, 1.3, 0.18, brand, size=7, bold=True, color=brand.colors.text_light)
        self._add_dark_text(
            slide,
            self._truncate_at_word(ask, 96),
            2.48,
            4.98,
            3.82,
            0.28,
            brand,
            size=9,
            color=brand.colors.text_light,
        )
        for idx, step in enumerate(next_steps[:3]):
            y = 2.42 + idx * 1.04
            card = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(7.78),
                Inches(y),
                Inches(4.12),
                Inches(0.76),
            )
            card.fill.solid()
            card.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.primary, 0.14 + idx * 0.04))
            card.line.color.rgb = self._rgb(self._tint(brand.colors.primary, 0.34))
            self._add_badge(slide, str(idx + 1), 8.02, y + 0.18, 0.38, brand, self._icon_fill(brand, idx))
            self._add_dark_text(
                slide,
                self._truncate_phrase(step, 82),
                8.62,
                y + 0.18,
                2.8,
                0.28,
                brand,
                size=8,
                color=self._tint(brand.colors.primary, 0.84),
            )

    def _add_closing_recommendation(
        self, slide, outline: SlideOutline, brand: BrandDNA
    ) -> None:
        exhibit = self._exhibit(outline)
        recommendation = (
            exhibit.get("recommendation")
            or outline.content_json.get("action_title")
            or outline.label
        )
        next_steps = [str(item) for item in exhibit.get("next_steps", []) if str(item).strip()]
        if not next_steps:
            next_steps = self._bullets(outline)[:3]
        ask = exhibit.get("decision_ask") or "Confirm owner, scope, and timing."
        panel = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.85),
            Inches(1.6),
            Inches(5.25),
            Inches(4.65),
        )
        panel.fill.solid()
        panel.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        panel.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_dark_text(slide, "RECOMMENDATION", 1.18, 2.05, 2.2, 0.3, brand, size=10, color=brand.colors.accent)
        self._add_dark_text(
            slide,
            self._truncate_at_word(recommendation, 140),
            1.18,
            2.58,
            4.45,
            1.3,
            brand,
            size=18,
            bold=True,
        )
        self._add_dark_text(
            slide,
            self._truncate_at_word(str(ask), 120),
            1.2,
            4.55,
            4.25,
            0.66,
            brand,
            size=11,
            color=self._tint(brand.colors.primary, 0.75),
        )
        for idx, step in enumerate(next_steps[:3]):
            y = 1.92 + idx * 1.26
            self._add_badge(slide, str(idx + 1), 6.85, y + 0.08, 0.44, brand, self._icon_fill(brand, idx))
            self._add_body_text(
                slide,
                self._truncate_at_word(step, 108),
                7.5,
                y,
                4.5,
                0.58,
                brand,
                size=13,
            )

    def _add_table_or_process(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        rows = self._table_rows(outline)
        x, y, w = 0.85, 1.55, 11.75
        col_w = w / max(len(rows[0]), 1)
        row_h = 0.68
        for r_idx, row in enumerate(rows[:7]):
            for c_idx, cell in enumerate(row):
                fill = brand.colors.primary if r_idx == 0 else ("F4F6F8" if r_idx % 2 else "FFFFFF")
                rect = slide.shapes.add_shape(
                    MSO_SHAPE.RECTANGLE,
                    Inches(x + c_idx * col_w),
                    Inches(y + r_idx * row_h),
                    Inches(col_w),
                    Inches(row_h),
                )
                rect.fill.solid()
                rect.fill.fore_color.rgb = self._rgb(fill)
                rect.line.color.rgb = self._rgb(brand.colors.background_light)
                text_color = brand.colors.text_light if r_idx == 0 else brand.colors.text_dark
                self._add_text_in_shape(rect, str(cell), brand, size=9 if r_idx else 10, bold=r_idx == 0, color=text_color)

    def _add_section_divider(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        slide_number: int,
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
        title = outline.content_json.get("action_title") or outline.content_json.get("title") or outline.label
        subheading = outline.content_json.get("subheading") or outline.content_json.get("summary", "")
        self._add_dark_text(slide, "SECTION", 0.8, 0.82, 2.0, 0.25, brand, size=10, color=brand.colors.accent)
        self._add_dark_text(slide, title, 0.8, 1.7, 7.4, 1.1, brand, size=30, bold=True)
        self._add_dark_text(slide, subheading, 0.82, 3.12, 6.8, 0.7, brand, size=13, color=self._tint(brand.colors.primary, 0.72))
        rail = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(9.2),
            Inches(0.92),
            Inches(0.12),
            Inches(4.95),
        )
        rail.fill.solid()
        rail.fill.fore_color.rgb = self._rgb(brand.colors.accent)
        rail.line.color.rgb = rail.fill.fore_color.rgb
        for idx, label in enumerate(["Diagnose", "Design", "Execute"]):
            y = 1.0 + idx * 1.52
            marker = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(9.62),
                Inches(y),
                Inches(2.35),
                Inches(0.68),
            )
            marker.fill.solid()
            marker.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.primary, 0.18 + idx * 0.1))
            marker.line.color.rgb = self._rgb(self._tint(brand.colors.primary, 0.34))
            self._add_dark_text(slide, label, 9.86, y + 0.2, 1.6, 0.2, brand, size=10, bold=True)
        number = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(9.62),
            Inches(5.04),
            Inches(1.0),
            Inches(0.62),
        )
        number.fill.solid()
        number.fill.fore_color.rgb = self._rgb(brand.colors.accent)
        number.line.color.rgb = self._rgb(brand.colors.accent)
        self._add_text_in_shape(number, f"{slide_number:02d}", brand, size=15, bold=True, color=brand.colors.text_light, center=True)
        self._add_dark_text(slide, "Source: " + "; ".join((outline.content_json.get("sources") or ["Uploaded source"])[:1]), 0.8, 6.92, 6.0, 0.25, brand, size=8, color=self._tint(brand.colors.primary, 0.72))

    def _add_quote_sidebar(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        exhibit = self._exhibit(outline)
        bullets = [
            str(item)
            for item in exhibit.get("supporting_points", [])
            if str(item).strip()
        ][:4] or self._bullets(outline)[:4]
        if not bullets:
            bullets = ["Shift the operating model from ad hoc execution to managed discipline."]
        quote = (
            exhibit.get("quote")
            or exhibit.get("key_idea")
            or outline.content_json.get("summary")
            or outline.content_json.get("subheading")
            or bullets[0]
        )
        panel = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(8.4), Inches(1.48), Inches(3.75), Inches(4.85))
        panel.fill.solid()
        panel.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        panel.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_dark_text(slide, "KEY IDEA", 8.74, 1.92, 1.3, 0.25, brand, size=9, color=brand.colors.accent)
        self._add_dark_text(
            slide,
            self._truncate_phrase(str(quote), 135),
            8.74,
            2.35,
            3.0,
            1.3,
            brand,
            size=16,
            bold=True,
        )
        support = bullets[1] if len(bullets) > 1 else bullets[0]
        self._add_dark_text(
            slide,
            self._truncate_at_word(support, 105),
            8.76,
            4.25,
            2.9,
            0.9,
            brand,
            size=10,
            color=self._tint(brand.colors.primary, 0.72),
        )
        icons = self._icons(outline)
        for idx, text in enumerate(bullets[:4]):
            y = 1.55 + idx * 1.08
            self._add_icon(slide, icons[idx], 0.95, y, 0.7, brand, self._icon_fill(brand, idx))
            connector = slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT,
                Inches(7.58),
                Inches(y + 0.36),
                Inches(8.4),
                Inches(3.1),
            )
            connector.line.color.rgb = self._rgb(self._tint(brand.colors.primary, 0.58))
            connector.line.width = Pt(0.8)
            self._add_body_text(
                slide,
                self._truncate_phrase(text, 120),
                1.88,
                y + 0.02,
                5.55,
                0.72,
                brand,
                size=13,
            )

    def _add_framework_cycle(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        if self._try_add_diagram_asset(
            slide, outline, brand, 0.78, 1.36, 11.75, 5.08
        ):
            return
        exhibit = self._exhibit(outline)
        steps = exhibit.get("steps") if exhibit.get("type") == "cycle" else None
        if isinstance(steps, list) and steps:
            bullets = [
                str(step.get("label") or step.get("description") or "")
                for step in steps
                if isinstance(step, dict)
            ][:6]
        else:
            bullets = self._bullets(outline)[:6]
        if len(bullets) < 4:
            bullets = (
                bullets
                + [
                    "Load context",
                    "Plan the work",
                    "Execute changes",
                    "Review evidence",
                    "Update memory",
                    "Reset cleanly",
                ]
            )[:6]
        center_x, center_y = 6.65, 3.85
        center = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(center_x - 0.78), Inches(center_y - 0.78), Inches(1.56), Inches(1.56))
        center.fill.solid()
        center.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        center.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_text_in_shape(
            center,
            self._truncate_at_word(str(exhibit.get("center_label") or "CYCLE"), 24),
            brand,
            size=13,
            bold=True,
            color=brand.colors.text_light,
            center=True,
        )
        icons = self._icons(outline)
        points: list[tuple[float, float]] = []
        for idx, text in enumerate(bullets):
            angle = -math.pi / 2 + idx * (2 * math.pi / len(bullets))
            x = center_x + math.cos(angle) * 3.65
            y = center_y + math.sin(angle) * 2.0
            points.append((x, y))
            self._add_card(slide, x - 1.3, y - 0.45, 2.6, 0.9, "FFFFFF", brand.colors.background_light)
            self._add_icon(slide, icons[idx % len(icons)], x - 1.14, y - 0.31, 0.52, brand, self._icon_fill(brand, idx))
            self._add_body_text(
                slide,
                self._truncate_at_word(text, 42),
                x - 0.46,
                y - 0.28,
                1.55,
                0.45,
                brand,
                size=10,
            )
        for idx, (x1, y1) in enumerate(points):
            x2, y2 = points[(idx + 1) % len(points)]
            self._add_arrow(slide, x1, y1, x2, y2, brand.colors.secondary, width=1.8)
            mid_x = (x1 + x2) / 2
            mid_y = (y1 + y2) / 2
            self._add_arrowhead(slide, mid_x, mid_y, x2 - x1, y2 - y1, brand.colors.secondary)

    def _add_dependency_map(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        if self._try_add_diagram_asset(
            slide, outline, brand, 0.78, 1.38, 11.75, 5.05
        ):
            return
        exhibit = self._exhibit(outline)
        middle_nodes = [
            str(item)
            for item in exhibit.get("middle_nodes", [])
            if str(item).strip()
        ][:3]
        bullets = self._bullets(outline)[:5]
        while len(middle_nodes) < 3:
            fallback = bullets[len(middle_nodes)] if len(middle_nodes) < len(bullets) else ""
            middle_nodes.append(fallback or ["Product context", "System patterns", "Active decisions"][len(middle_nodes)])
        left_label = str(exhibit.get("left_node") or "Source context")
        right_label = str(exhibit.get("right_outcome") or "Reliable next session")
        connector_labels = [
            str(item)
            for item in exhibit.get("connector_labels", [])
            if str(item).strip()
        ]
        left = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.78), Inches(3.0), Inches(2.55), Inches(0.88))
        left.fill.solid()
        left.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        left.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_text_in_shape(
            left,
            self._truncate_at_word(left_label, 42),
            brand,
            size=10,
            bold=True,
            color=brand.colors.text_light,
            center=True,
        )
        mid_positions = [(4.15, 1.95), (4.15, 3.22), (4.15, 4.49)]
        for idx, (x, y) in enumerate(mid_positions):
            self._add_card(slide, x, y, 2.9, 0.92, "FFFFFF", brand.colors.secondary)
            self._add_body_text(
                slide,
                self._truncate_phrase(middle_nodes[idx], 48),
                x + 0.22,
                y + 0.2,
                2.45,
                0.36,
                brand,
                size=10,
            )
            self._add_arrow(slide, 3.36, 3.44, x - 0.05, y + 0.46, brand.colors.secondary, width=2.0)
            if idx < len(connector_labels):
                self._add_body_text(
                    slide,
                    connector_labels[idx],
                    3.42,
                    y + 0.06,
                    0.62,
                    0.24,
                    brand,
                    center=True,
                    size=7,
                )
        right = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(8.25), Inches(2.96), Inches(3.55), Inches(0.96))
        right.fill.solid()
        right.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.accent, 0.84))
        right.line.color.rgb = self._rgb(brand.colors.accent)
        self._add_body_text(
            slide,
            self._truncate_phrase(right_label, 58),
            8.46,
            3.18,
            3.1,
            0.42,
            brand,
            size=10,
            center=True,
        )
        for _idx, (_x, y) in enumerate(mid_positions):
            self._add_arrow(slide, 7.08, y + 0.46, 8.18, 3.44, brand.colors.accent, width=2.0)

    def _add_checklist(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        exhibit = self._exhibit(outline)
        items = exhibit.get("items") if exhibit.get("type") == "checklist" else None
        if isinstance(items, list) and items:
            bullets = [
                str(item.get("action") or "")
                for item in items
                if isinstance(item, dict) and str(item.get("action") or "").strip()
            ][:6]
            owners = [
                str(item.get("owner") or "")
                for item in items
                if isinstance(item, dict)
            ][:6]
            timings = [
                str(item.get("timing") or "")
                for item in items
                if isinstance(item, dict)
            ][:6]
        else:
            bullets = self._bullets(outline)[:6]
            owners = []
            timings = []
        bullets = self._complete_operating_rules(outline, bullets, minimum=4)[:6]
        if not bullets:
            bullets = self._complete_operating_rules(outline, [], minimum=4)[:4]
        for idx, text in enumerate(bullets[:6]):
            y = 1.5 + idx * 0.76
            badge = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.98), Inches(y), Inches(0.38), Inches(0.38))
            badge.fill.solid()
            badge.fill.fore_color.rgb = self._rgb(self._icon_fill(brand, idx))
            badge.line.color.rgb = badge.fill.fore_color.rgb
            self._add_text_in_shape(
                badge,
                str(idx + 1),
                brand,
                size=8,
                bold=True,
                color=brand.colors.text_light,
                center=True,
            )
            detail = ""
            if idx < len(owners) and owners[idx]:
                detail = owners[idx]
            if idx < len(timings) and timings[idx]:
                detail = f"{detail} / {timings[idx]}".strip(" /")
            body = text if not detail else f"{text.rstrip('.')} ({detail})"
            self._add_body_text(
                slide,
                self._truncate_at_word(body, 118),
                1.58,
                y - 0.03,
                6.2,
                0.43,
                brand,
                size=12,
            )
        panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(8.45), Inches(1.62), Inches(3.55), Inches(3.92))
        panel.fill.solid()
        panel.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        panel.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_dark_text(slide, "NEXT 30 DAYS", 8.82, 2.0, 1.8, 0.28, brand, size=10, color=brand.colors.accent)
        self._add_dark_text(slide, "Turn the checklist into operating cadence, not a one-time cleanup.", 8.82, 2.52, 2.8, 1.0, brand, size=16, bold=True)
        self._add_dark_text(slide, "Review the evidence and update the shared record before scaling.", 8.84, 4.15, 2.8, 0.62, brand, size=9, color=self._tint(brand.colors.primary, 0.72))

    def _add_code_panel(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        exhibit = self._exhibit(outline)
        artifact_title = str(exhibit.get("title") or "operating-rules.md")
        artifact_label = self._truncate_at_word(artifact_title.rsplit("/", 1)[-1], 28)
        lines = [
            str(item)
            for item in exhibit.get("lines", [])
            if str(item).strip()
        ][:5]
        bullets = lines[:4] or self._bullets(outline)[:4]
        bullets = self._complete_operating_rules(outline, bullets, minimum=3)[:4]
        if not bullets:
            bullets = self._complete_operating_rules(outline, [], minimum=3)[:3]
        self._add_label(slide, "OPERATING RULES", 0.94, 1.45, 2.5, brand, bold=True)
        for idx, text in enumerate(bullets[:3]):
            y = 1.82 + idx * 1.04
            self._add_card(slide, 0.88, y, 5.68, 0.82, "FFFFFF", brand.colors.background_light)
            self._add_badge(slide, str(idx + 1), 1.12, y + 0.2, 0.42, brand, self._icon_fill(brand, idx))
            self._add_body_text(
                slide,
                self._truncate_at_word(text, 112),
                1.72,
                y + 0.18,
                4.45,
                0.38,
                brand,
                size=11,
            )
        key_rule = bullets[0]
        self._add_card(slide, 0.88, 5.12, 5.68, 0.74, self._tint(brand.colors.accent, 0.86), self._tint(brand.colors.accent, 0.7))
        self._add_body_text(slide, "OPERATING RULE", 1.16, 5.28, 1.65, 0.24, brand, size=8)
        self._add_body_text(
            slide,
            self._truncate_at_word(key_rule, 92),
            2.82,
            5.24,
            3.32,
            0.3,
            brand,
            size=10,
        )

        panel = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(7.02), Inches(1.5), Inches(5.18), Inches(4.18))
        panel.fill.solid()
        panel.fill.fore_color.rgb = self._rgb("111827")
        panel.line.color.rgb = self._rgb("111827")
        header = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(7.02), Inches(1.5), Inches(5.18), Inches(0.52))
        header.fill.solid()
        header.fill.fore_color.rgb = self._rgb("1F2937")
        header.line.color.rgb = header.fill.fore_color.rgb
        self._add_dark_text(
            slide,
            "REFERENCE ARTIFACT",
            7.28,
            1.66,
            1.75,
            0.2,
            brand,
            size=8,
            color=brand.colors.accent,
        )
        self._add_dark_text(
            slide,
            self._truncate_at_word(artifact_title, 42),
            9.1,
            1.66,
            2.55,
            0.22,
            brand,
            size=8,
            color=self._tint("111827", 0.74),
        )
        code_lines = [f"# {artifact_title}"] + [
            "- " + self._truncate_at_word(str(bullet), 52) for bullet in bullets[:5]
        ]
        self._add_code_text(slide, code_lines, 7.34, 2.22, 4.34, 2.5, brand)

        chip_specs = [
            ("ARTIFACT", artifact_label),
            ("REVIEW GATE", "Evidence check"),
            ("UPDATE TRIGGER", "Material change"),
        ]
        for idx, (label, value) in enumerate(chip_specs):
            x = 7.18 + idx * 1.62
            chip = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(x),
                Inches(4.88),
                Inches(1.42),
                Inches(0.52),
            )
            chip.fill.solid()
            chip.fill.fore_color.rgb = self._rgb("1F2937")
            chip.line.color.rgb = self._rgb(self._tint("111827", 0.22))
            self._add_dark_text(slide, label, x + 0.12, 4.97, 1.02, 0.14, brand, size=6, color=brand.colors.accent)
            self._add_dark_text(slide, value, x + 0.12, 5.13, 1.16, 0.16, brand, size=7, color=self._tint("111827", 0.78))

    def _complete_operating_rules(
        self,
        outline: SlideOutline,
        rules: list[str],
        minimum: int,
    ) -> list[str]:
        completed: list[str] = []
        seen: set[str] = set()
        for rule in rules:
            cleaned = self._clean_display_text(str(rule)).rstrip(".")
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            completed.append(cleaned + ".")
        if len(completed) >= minimum:
            return completed
        intent = " ".join(
            str(value)
            for value in [
                outline.label,
                outline.content_json.get("action_title", ""),
                outline.content_json.get("subheading", ""),
                outline.content_json.get("summary", ""),
                outline.layout_json.get("layout", ""),
            ]
        ).lower()
        if any(token in intent for token in ("memory", "context", "external brain")):
            candidates = [
                "Update active context after material changes.",
                "Record decisions before starting the next session.",
                "Keep progress notes synchronized with implementation status.",
                "Refresh rules when ownership, risk, or scope changes.",
            ]
        elif any(token in intent for token in ("spec", "acceptance", "criteria")):
            candidates = [
                "Write acceptance criteria before generation begins.",
                "Attach source evidence to each material claim.",
                "Review output against the defined test before approval.",
                "Revise the specification when assumptions change.",
            ]
        elif any(token in intent for token in ("cycle", "loop", "workflow", "reset")):
            candidates = [
                "Load source context before planning the work.",
                "Verify output against the acceptance test.",
                "Update the shared record before resetting context.",
                "Repeat the loop only after evidence is captured.",
            ]
        else:
            candidates = [
                "State the decision before execution begins.",
                "Attach source context to the working artifact.",
                "Run review before expanding the workflow.",
                "Name the owner for the next operating step.",
            ]
        for candidate in candidates:
            key = candidate.rstrip(".").casefold()
            if key in seen:
                continue
            seen.add(key)
            completed.append(candidate)
            if len(completed) >= minimum:
                break
        return completed

    def _add_anti_patterns(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        exhibit = self._exhibit(outline)
        patterns = exhibit.get("patterns") if exhibit.get("type") == "anti_patterns" else None
        if not isinstance(patterns, list) or not patterns:
            bullets = self._bullets(outline)[:4]
            patterns = [
                {
                    "name": self._truncate_at_word(text, 28),
                    "symptom": text,
                    "consequence": "Reliability drops.",
                    "better_behavior": "Add a durable rule.",
                }
                for text in bullets
            ]
        if not patterns:
            patterns = [
                {"name": "Chat drift", "symptom": "Relying on chat history", "better_behavior": "Persist context"},
                {"name": "Thin sourcing", "symptom": "Skipping source checks", "better_behavior": "Cite evidence"},
                {"name": "Blind accept", "symptom": "Accepting code blindly", "better_behavior": "Run QA gates"},
            ]
        icons = self._icons(outline)
        count = min(len(patterns), 4)
        card_w = 11.4 / count - 0.24
        for idx, pattern in enumerate(patterns[:4]):
            if not isinstance(pattern, dict):
                continue
            x = 0.86 + idx * (card_w + 0.32)
            self._add_card(slide, x, 1.72, card_w, 3.85, "FFFFFF", brand.colors.background_light)
            self._add_icon(slide, icons[idx], x + 0.22, 1.98, 0.68, brand, self._icon_fill(brand, idx))
            self._add_label(
                slide,
                self._truncate_at_word(str(pattern.get("name") or f"Risk {idx + 1}"), 26),
                x + 1.02,
                2.14,
                card_w - 1.22,
                brand,
                bold=True,
            )
            symptom = self._truncate_phrase(str(pattern.get("symptom") or ""), 76)
            behavior = self._truncate_phrase(str(pattern.get("better_behavior") or ""), 74)
            body_parts = []
            if symptom:
                body_parts.append(f"Symptom: {symptom}")
            if behavior:
                body_parts.append(f"Better move: {behavior}")
            body = "\n".join(body_parts)
            self._add_body_text(slide, body, x + 0.32, 2.88, card_w - 0.58, 1.72, brand, size=10)

    def _add_grid(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        bullets = self._bullets(outline)[:4]
        if not bullets:
            bullets = ["Clarify the implication and required management action."]
        icons = self._icons(outline)
        if len(bullets) == 1:
            self._add_card(slide, 1.1, 2.0, 11.2, 2.5, brand.colors.background_light, brand.colors.secondary)
            self._add_icon(slide, icons[0], 1.48, 2.42, 1.05, brand, brand.colors.primary)
            self._add_body_text(slide, bullets[0], 2.78, 2.7, 8.45, 1.0, brand, center=False, size=16)
            return
        if len(bullets) in {2, 3}:
            card_w = 5.35 if len(bullets) == 2 else 3.55
            gap = 0.55
            total_w = len(bullets) * card_w + (len(bullets) - 1) * gap
            start_x = (SLIDE_W - total_w) / 2
            for idx, text in enumerate(bullets):
                x = start_x + idx * (card_w + gap)
                self._add_card(slide, x, 1.85, card_w, 3.55, "FFFFFF", brand.colors.background_light)
                self._add_icon(slide, icons[idx], x + 0.34, 2.04, 0.98, brand, self._icon_fill(brand, idx))
                self._add_body_text(slide, text, x + 0.4, 3.22, card_w - 0.8, 1.24, brand, center=False, size=14)
            return
        for idx, text in enumerate(bullets):
            row = idx // 2
            col = idx % 2
            x = 0.9 + col * 6.0
            y = 1.55 + row * 2.25
            self._add_card(slide, x, y, 5.25, 1.85, "FFFFFF", brand.colors.background_light)
            self._add_icon(slide, icons[idx], x + 0.28, y + 0.25, 0.86, brand, self._icon_fill(brand, idx))
            self._add_body_text(slide, text, x + 1.34, y + 0.36, 3.52, 1.0, brand, size=13)

    def _add_icon_rows(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        bullets = self._bullets(outline)[:4]
        if not bullets:
            bullets = ["Clarify the implication and required management action."]
        icons = self._icons(outline)
        for idx, text in enumerate(bullets[:4]):
            y = 1.45 + idx * 1.25
            self._add_card(slide, 0.9, y, 11.7, 0.98, "FFFFFF", brand.colors.background_light)
            self._add_icon(
                slide,
                icons[idx],
                1.2,
                y + 0.12,
                0.82,
                brand,
                self._icon_fill(brand, idx),
            )
            self._add_body_text(slide, text, 2.24, y + 0.25, 9.55, 0.48, brand, size=14)

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
        frame.word_wrap = True
        frame.clear()
        run = frame.paragraphs[0].add_run()
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
        frame.word_wrap = True
        frame.clear()
        for idx, line in enumerate(lines[:8]):
            para = frame.paragraphs[0] if idx == 0 else frame.add_paragraph()
            run = para.add_run()
            run.text = line
            run.font.name = "Courier New"
            run.font.size = Pt(10)
            run.font.color.rgb = self._rgb(brand.colors.text_light)
            para.space_after = Pt(4)

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
        run.font.color.rgb = self._rgb(brand.colors.text_light)

    def _add_icon(
        self,
        slide,
        icon_name: str,
        x: float,
        y: float,
        size: float,
        brand: BrandDNA,
        fill: str,
    ) -> None:
        halo = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            Inches(x),
            Inches(y),
            Inches(size),
            Inches(size),
        )
        halo.fill.solid()
        halo.fill.fore_color.rgb = self._rgb(self._tint(fill, 0.84))
        halo.line.color.rgb = self._rgb(self._tint(fill, 0.62))
        inner_inset = size * 0.08
        badge = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            Inches(x + inner_inset),
            Inches(y + inner_inset),
            Inches(size - inner_inset * 2),
            Inches(size - inner_inset * 2),
        )
        badge.fill.solid()
        badge.fill.fore_color.rgb = self._rgb(fill)
        badge.line.color.rgb = self._rgb(fill)
        icon_size = size * 0.43
        inset = (size - icon_size) / 2
        icon_path = self._icon_image_path(icon_name, "FFFFFF")
        slide.shapes.add_picture(
            icon_path.as_posix(),
            Inches(x + inset),
            Inches(y + inset),
            Inches(icon_size),
            Inches(icon_size),
        )

    def _icon_fill(self, brand: BrandDNA, index: int) -> str:
        palette = [brand.colors.primary, brand.colors.secondary, brand.colors.accent]
        return palette[index % len(palette)]

    def _icon_image_path(self, icon_name: str, color: str) -> Path:
        safe_name = re.sub(r"[^a-z0-9]+", "-", icon_name.lower()).strip("-") or "default"
        safe_color = self._clean_hex(color).lower()
        path = self._icon_cache_dir / f"{safe_name}-{safe_color}.png"
        if not path.exists():
            if not self._draw_icon_with_node(icon_name, color, path):
                self._draw_icon_png(icon_name, color, path)
        return path

    def _draw_icon_with_node(self, icon_name: str, color: str, path: Path) -> bool:
        script_path = Path(__file__).resolve().parents[1] / "workers" / "icon_renderer.js"
        if shutil.which("node") is None or not script_path.exists():
            return False
        try:
            result = subprocess.run(
                [
                    "node",
                    script_path.as_posix(),
                    icon_name,
                    self._clean_hex(color),
                    path.as_posix(),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and path.exists() and path.stat().st_size > 0

    def _draw_icon_png(self, icon_name: str, color: str, path: Path) -> None:
        normalized = icon_name.lower()
        size = 128 * ICON_SCALE
        image = Image.new("RGBA", (size, size), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        stroke = self._rgba(color)
        width = 8
        if "chart" in normalized or "growth" in normalized:
            self._draw_chart_icon(draw, stroke, width)
        elif "risk" in normalized or "exclamation" in normalized:
            self._draw_warning_icon(draw, stroke, width)
        elif (
            "database" in normalized
            or "data" in normalized
            or "brain" in normalized
            or "book" in normalized
            or "file" in normalized
        ):
            self._draw_database_icon(draw, stroke, width)
        elif "users" in normalized or "customer" in normalized or "comments" in normalized or "usertie" in normalized:
            self._draw_users_icon(draw, stroke, width)
        elif (
            "shield" in normalized
            or "security" in normalized
            or "clipboard" in normalized
            or "tasks" in normalized
            or "check" in normalized
        ):
            self._draw_shield_icon(draw, stroke, width)
        elif (
            "timeline" in normalized
            or "project" in normalized
            or "robot" in normalized
            or "code" in normalized
            or "sitemap" in normalized
            or "tools" in normalized
        ):
            self._draw_process_icon(draw, stroke, width)
        elif "finance" in normalized or "dollar" in normalized:
            self._draw_finance_icon(draw, stroke, width)
        elif "strategy" in normalized or "chess" in normalized:
            self._draw_strategy_icon(draw, stroke, width)
        elif "status" in normalized or "tachometer" in normalized:
            self._draw_status_icon(draw, stroke, width)
        else:
            self._draw_lightbulb_icon(draw, stroke, width)
        image.save(path)

    def _draw_chart_icon(self, draw: ImageDraw.ImageDraw, color, width: int) -> None:
        self._line(draw, [(24, 96), (24, 30)], color, width)
        self._line(draw, [(24, 96), (104, 96)], color, width)
        self._line(draw, [(36, 78), (54, 58), (72, 66), (100, 34)], color, width)
        self._dot(draw, 36, 78, 4.5, color)
        self._dot(draw, 54, 58, 4.5, color)
        self._dot(draw, 72, 66, 4.5, color)
        self._polygon(draw, [(100, 34), (86, 38), (96, 50)], fill=color)

    def _draw_warning_icon(self, draw: ImageDraw.ImageDraw, color, width: int) -> None:
        self._line(draw, [(64, 22), (108, 100), (20, 100), (64, 22)], color, width, rounded=False)
        self._line(draw, [(64, 48), (64, 76)], color, width)
        self._dot(draw, 64, 92, 5.5, color)

    def _draw_database_icon(self, draw: ImageDraw.ImageDraw, color, width: int) -> None:
        self._ellipse(draw, (26, 22, 102, 50), outline=color, width=width)
        self._line(draw, [(26, 36), (26, 92)], color, width)
        self._line(draw, [(102, 36), (102, 92)], color, width)
        self._arc(draw, (26, 48, 102, 76), 0, 180, color, width)
        self._arc(draw, (26, 68, 102, 96), 0, 180, color, width)
        self._arc(draw, (26, 78, 102, 106), 0, 180, color, width)

    def _draw_users_icon(self, draw: ImageDraw.ImageDraw, color, width: int) -> None:
        self._ellipse(draw, (46, 22, 82, 58), outline=color, width=width)
        self._arc(draw, (34, 54, 94, 116), 205, 335, color, width)
        self._ellipse(draw, (18, 40, 48, 70), outline=color, width=max(6, width - 2))
        self._ellipse(draw, (80, 40, 110, 70), outline=color, width=max(6, width - 2))
        self._arc(draw, (12, 66, 58, 116), 210, 320, color, max(5, width - 3))
        self._arc(draw, (70, 66, 116, 116), 220, 330, color, max(5, width - 3))

    def _draw_shield_icon(self, draw: ImageDraw.ImageDraw, color, width: int) -> None:
        points = [(64, 18), (104, 34), (98, 76), (64, 108), (30, 76), (24, 34)]
        self._line(draw, points + [points[0]], color, width, rounded=False)
        self._line(draw, [(48, 64), (60, 76), (86, 48)], color, width)

    def _draw_process_icon(self, draw: ImageDraw.ImageDraw, color, width: int) -> None:
        self._line(draw, [(42, 42), (86, 42)], color, max(5, width - 2))
        self._line(draw, [(64, 58), (64, 82)], color, max(5, width - 2))
        self._line(draw, [(42, 92), (86, 92)], color, max(5, width - 2))
        self._rounded_rectangle(draw, (18, 24, 50, 60), outline=color, width=width, radius=7)
        self._rounded_rectangle(draw, (78, 24, 110, 60), outline=color, width=width, radius=7)
        self._rounded_rectangle(draw, (48, 76, 80, 112), outline=color, width=width, radius=7)
        self._dot(draw, 34, 42, 3.5, color)
        self._dot(draw, 94, 42, 3.5, color)
        self._dot(draw, 64, 94, 3.5, color)

    def _draw_finance_icon(self, draw: ImageDraw.ImageDraw, color, width: int) -> None:
        self._ellipse(draw, (26, 20, 102, 100), outline=color, width=width)
        self._line(draw, [(64, 34), (64, 90)], color, width)
        self._arc(draw, (44, 36, 82, 68), 90, 270, color, width)
        self._arc(draw, (46, 58, 84, 90), 270, 90, color, width)

    def _draw_strategy_icon(self, draw: ImageDraw.ImageDraw, color, width: int) -> None:
        self._ellipse(draw, (30, 30, 98, 98), outline=color, width=width)
        self._ellipse(draw, (48, 48, 80, 80), outline=color, width=max(5, width - 2))
        self._line(draw, [(64, 18), (64, 42)], color, max(5, width - 2))
        self._line(draw, [(64, 86), (64, 110)], color, max(5, width - 2))
        self._line(draw, [(18, 64), (42, 64)], color, max(5, width - 2))
        self._line(draw, [(86, 64), (110, 64)], color, max(5, width - 2))
        self._line(draw, [(68, 60), (102, 26)], color, width)
        self._polygon(draw, [(102, 26), (92, 28), (100, 38)], fill=color)

    def _draw_status_icon(self, draw: ImageDraw.ImageDraw, color, width: int) -> None:
        self._arc(draw, (22, 26, 106, 110), 200, 340, color, width)
        self._line(draw, [(38, 82), (30, 90)], color, max(5, width - 2))
        self._line(draw, [(90, 82), (100, 90)], color, max(5, width - 2))
        self._line(draw, [(64, 76), (90, 50)], color, width)
        self._dot(draw, 64, 76, 7, color)

    def _draw_lightbulb_icon(self, draw: ImageDraw.ImageDraw, color, width: int) -> None:
        self._ellipse(draw, (40, 22, 88, 76), outline=color, width=width)
        self._line(draw, [(50, 78), (78, 78)], color, width)
        self._line(draw, [(54, 92), (74, 92)], color, width)
        self._line(draw, [(58, 106), (70, 106)], color, width)
        self._line(draw, [(64, 12), (64, 4)], color, max(5, width - 2))
        self._line(draw, [(32, 28), (24, 20)], color, max(5, width - 2))
        self._line(draw, [(96, 28), (104, 20)], color, max(5, width - 2))

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
        frame.word_wrap = True
        frame.clear()
        para = frame.paragraphs[0]
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
        frame.word_wrap = True
        frame.clear()
        for idx, bullet in enumerate(bullets[:4]):
            para = frame.paragraphs[0] if idx == 0 else frame.add_paragraph()
            para.level = 0
            para.text = f"• {self._truncate_at_word(bullet, 175)}"
            para.font.name = brand.fonts.body
            para.font.size = Pt(13)
            para.font.color.rgb = self._rgb(brand.colors.text_dark)
            para.space_after = Pt(7)

    def _add_big_number(self, slide, text: str, x: float, y: float, w: float, brand: BrandDNA) -> None:
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(0.8))
        frame = box.text_frame
        frame.clear()
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
        frame.word_wrap = True
        frame.clear()
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
        run.font.color.rgb = self._rgb(color or brand.colors.text_dark)

    def _set_table_cell(
        self,
        cell,
        text: str,
        brand: BrandDNA,
        size: int = 9,
        bold: bool = False,
        color: str | None = None,
        fill: str = "FFFFFF",
        center: bool = False,
    ) -> None:
        cell.fill.solid()
        cell.fill.fore_color.rgb = self._rgb(fill)
        cell.margin_left = Inches(0.08)
        cell.margin_right = Inches(0.08)
        cell.margin_top = Inches(0.05)
        cell.margin_bottom = Inches(0.04)
        frame = cell.text_frame
        frame.word_wrap = True
        frame.clear()
        paragraph = frame.paragraphs[0]
        if center:
            paragraph.alignment = 1
        run = paragraph.add_run()
        run.text = text
        run.font.name = brand.fonts.body
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = self._rgb(color or brand.colors.text_dark)

    def _exhibit(self, outline: SlideOutline) -> dict[str, Any]:
        exhibit = outline.content_json.get("exhibit_spec")
        if isinstance(exhibit, dict):
            return exhibit
        return {}

    def _comparison_rows(
        self, exhibit: dict[str, Any], outline: SlideOutline
    ) -> tuple[list[str], list[list[str]]]:
        columns = exhibit.get("columns")
        rows = exhibit.get("rows")
        if isinstance(columns, list) and isinstance(rows, list) and rows:
            normalized_rows: list[list[str]] = []
            for row in rows:
                if isinstance(row, dict):
                    normalized_rows.append(
                        [
                            self._table_cell_text(row.get("label", "")),
                            *[self._table_cell_text(value) for value in row.get("values", [])],
                        ]
                    )
                elif isinstance(row, list):
                    normalized_rows.append([self._table_cell_text(value) for value in row])
            if normalized_rows:
                return [self._table_header_text(value) for value in columns], normalized_rows
        table_rows = self._table_rows(outline)
        if len(table_rows) >= 2:
            return [str(value) for value in table_rows[0]], [
                [str(value) for value in row] for row in table_rows[1:]
            ]
        bullets = self._bullets(outline)[:3]
        return ["Dimension", "Current state", "Target state"], [
            [f"Area {idx + 1}", bullet, "Managed behavior"]
            for idx, bullet in enumerate(bullets or ["Context", "Review", "Cadence"])
        ]

    def _reference_rows(
        self, exhibit: dict[str, Any], outline: SlideOutline
    ) -> tuple[list[str], list[list[str]]]:
        columns = exhibit.get("columns")
        rows = exhibit.get("rows")
        if isinstance(columns, list) and isinstance(rows, list) and rows:
            return [self._table_header_text(value) for value in columns], [
                [self._table_cell_text(value) for value in row]
                if isinstance(row, list)
                else [self._table_cell_text(row)]
                for row in rows
            ]
        table_rows = self._table_rows(outline)
        if len(table_rows) >= 2:
            return [str(value) for value in table_rows[0]], [
                [str(value) for value in row] for row in table_rows[1:]
            ]
        bullets = self._bullets(outline)[:5]
        return ["Item", "Implication"], [[self._truncate_at_word(item, 28), item] for item in bullets]

    def _table_header_text(self, value: Any) -> str:
        if isinstance(value, dict):
            for key in ("name", "label", "title", "header"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return ""
        return self._table_cell_text(value)

    def _table_cell_text(self, value: Any) -> str:
        if isinstance(value, dict):
            for key in ("text", "label", "name", "value"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return ""
        return str(value)

    def _column_widths(self, total_width: float, count: int) -> list[float]:
        if count <= 1:
            return [total_width]
        if count == 2:
            return [total_width * 0.34, total_width * 0.66]
        first = total_width * 0.26
        remaining = (total_width - first) / (count - 1)
        return [first] + [remaining] * (count - 1)

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

    def _table_rows(self, outline: SlideOutline) -> list[list[Any]]:
        blocks = outline.content_json.get("content_blocks") or []
        for block in blocks:
            if block.get("type") == "table" and isinstance(block.get("body"), list):
                rows = [row for row in block["body"] if isinstance(row, list)]
                if rows:
                    return rows
        bullets = self._bullets(outline)[:5]
        if bullets:
            return [["Step", "Action"]] + [
                [str(index + 1), bullet] for index, bullet in enumerate(bullets)
            ]
        return [["Action", "Owner", "Timing"], ["Align", "Sponsor", "Week 1"], ["Execute", "Team", "Week 2"]]

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
