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


SLIDE_W = 13.333
SLIDE_H = 7.5
ICON_SCALE = 4


class DeterministicPptxRenderer:
    def render(
        self,
        outlines: list[SlideOutline],
        brand: BrandDNA,
        output_path: Path,
    ) -> None:
        self._icon_cache_dir = output_path.parent / f"{output_path.stem}-icons"
        self._icon_cache_dir.mkdir(parents=True, exist_ok=True)
        prs = Presentation()
        prs.slide_width = Inches(SLIDE_W)
        prs.slide_height = Inches(SLIDE_H)
        blank_layout = prs.slide_layouts[6]
        for index, outline in enumerate(outlines):
            slide = prs.slides.add_slide(blank_layout)
            self._render_slide(slide, outline, brand, index + 1, len(outlines))
        prs.save(output_path.as_posix())

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
        if layout == "section_divider":
            self._add_section_divider(slide, outline, brand, slide_number)
            self._add_logo(slide, brand)
            return
        self._add_header(slide, title, subheading, brand)
        self._add_logo(slide, brand)
        self._add_footer(slide, outline, brand, slide_number, total_slides)

        if layout == "executive_summary":
            self._add_executive_summary(slide, outline, brand)
        elif layout == "chart":
            self._add_metric_chart(slide, outline, brand)
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
        elif layout == "icon_grid":
            self._add_grid(slide, outline, brand)
        elif layout == "icon_rows":
            self._add_icon_rows(slide, outline, brand)
        else:
            self._add_two_column(slide, outline, brand)

    def _add_header(self, slide, title: str, subheading: str, brand: BrandDNA) -> None:
        band = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0),
            Inches(0),
            Inches(SLIDE_W),
            Inches(1.12),
        )
        band.fill.solid()
        band.fill.fore_color.rgb = self._rgb(brand.colors.background_light)
        band.line.color.rgb = self._rgb(brand.colors.background_light)
        reserved_logo_width = brand.logo.size_w + 0.35 if brand.logo else 0
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
            Inches(0.6),
            Inches(0.28),
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
            sub_y = 0.83 if title_height <= 0.55 else 0.28 + title_height + 0.06
            sub_box = slide.shapes.add_textbox(Inches(0.6), Inches(sub_y), Inches(12.0), Inches(0.28))
            sub_frame = sub_box.text_frame
            sub_frame.clear()
            sub = sub_frame.paragraphs[0].add_run()
            sub.text = subheading[:180]
            sub.font.name = brand.fonts.body
            sub.font.size = Pt(11)
            sub.font.color.rgb = self._rgb(brand.colors.secondary)

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

    def _add_executive_summary(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        bullets = self._bullets(outline)
        y = 1.55
        labels = ["Situation", "Complication", "Resolution"]
        icons = self._icons(outline)
        for idx, label in enumerate(labels):
            x = 0.8 + idx * 4.15
            self._add_card(slide, x, y, 3.7, 4.6, brand.colors.background_light, brand.colors.secondary)
            self._add_icon(slide, icons[idx], x + 0.28, y + 0.24, 0.88, brand, self._icon_fill(brand, idx))
            self._add_label(slide, label, x + 1.36, y + 0.42, 2.05, brand, bold=True)
            text = bullets[idx] if idx < len(bullets) else "Define the critical implication for leadership."
            self._add_body_text(slide, text, x + 0.34, y + 1.32, 3.0, 2.38, brand, size=14)

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
        if not metrics:
            self._add_two_column(slide, outline, brand)
            return
        values = [float(metric.get("value", 0) or 0) for metric in metrics[:5]]
        max_value = max(values) if values else 1
        self._add_card(slide, 0.85, 1.5, 11.75, 4.9, "FFFFFF", brand.colors.background_light)
        for idx, metric in enumerate(metrics[:5]):
            value = values[idx]
            x = 1.25 + idx * 2.12
            height = 3.3 * (value / max_value) if max_value else 0.2
            y = 5.75 - height
            bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(1.28), Inches(height))
            bar.fill.solid()
            bar.fill.fore_color.rgb = self._rgb(brand.colors.primary if idx == 0 else brand.colors.secondary)
            bar.line.color.rgb = self._rgb(brand.colors.background_light)
            value_text = f"{metric.get('value', '')}{metric.get('unit') or ''}"
            self._add_body_text(slide, value_text, x - 0.05, y - 0.45, 1.4, 0.3, brand, center=True, size=14)
            self._add_body_text(slide, str(metric.get("label", "Metric"))[:30], x - 0.35, 5.9, 1.9, 0.42, brand, center=True, size=11)

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
        for idx, radius in enumerate([2.35, 1.7, 1.03]):
            circle = slide.shapes.add_shape(
                MSO_SHAPE.OVAL,
                Inches(9.2 - idx * 0.18),
                Inches(0.75 + idx * 0.38),
                Inches(radius),
                Inches(radius),
            )
            circle.fill.solid()
            circle.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.primary, 0.18 + idx * 0.16))
            circle.line.color.rgb = circle.fill.fore_color.rgb
        number = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(10.02), Inches(2.1), Inches(0.75), Inches(0.75))
        number.fill.solid()
        number.fill.fore_color.rgb = self._rgb(brand.colors.accent)
        number.line.color.rgb = self._rgb(brand.colors.accent)
        self._add_text_in_shape(
            number,
            f"{slide_number:02d}",
            brand,
            size=15,
            bold=True,
            color=brand.colors.text_light,
            center=True,
        )
        self._add_dark_text(slide, "Source: " + "; ".join((outline.content_json.get("sources") or ["Uploaded source"])[:1]), 0.8, 6.92, 6.0, 0.25, brand, size=8, color=self._tint(brand.colors.primary, 0.72))

    def _add_quote_sidebar(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        bullets = self._bullets(outline)[:4]
        if not bullets:
            bullets = ["Shift the operating model from ad hoc prompting to managed execution."]
        quote = outline.content_json.get("summary") or outline.content_json.get("subheading") or bullets[0]
        panel = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(8.4), Inches(1.48), Inches(3.75), Inches(4.85))
        panel.fill.solid()
        panel.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        panel.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_dark_text(slide, "KEY IDEA", 8.74, 1.92, 1.3, 0.25, brand, size=9, color=brand.colors.accent)
        self._add_dark_text(slide, quote, 8.74, 2.35, 3.0, 1.3, brand, size=17, bold=True)
        support = bullets[1] if len(bullets) > 1 else bullets[0]
        self._add_dark_text(
            slide,
            self._truncate_at_word(support, 120),
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
            self._add_body_text(slide, text, 1.88, y + 0.02, 5.95, 0.72, brand, size=13)

    def _add_framework_cycle(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        bullets = self._bullets(outline)[:6]
        if len(bullets) < 4:
            bullets = (bullets + [
                "Load context",
                "Plan the work",
                "Execute changes",
                "Review evidence",
                "Update memory",
                "Reset cleanly",
            ])[:6]
        center_x, center_y = 6.65, 3.85
        center = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(center_x - 0.78), Inches(center_y - 0.78), Inches(1.56), Inches(1.56))
        center.fill.solid()
        center.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        center.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_text_in_shape(
            center,
            "CYCLE",
            brand,
            size=13,
            bold=True,
            color=brand.colors.text_light,
            center=True,
        )
        icons = self._icons(outline)
        for idx, text in enumerate(bullets):
            angle = -math.pi / 2 + idx * (2 * math.pi / len(bullets))
            x = center_x + math.cos(angle) * 3.65
            y = center_y + math.sin(angle) * 2.0
            self._add_card(slide, x - 1.3, y - 0.45, 2.6, 0.9, "FFFFFF", brand.colors.background_light)
            self._add_icon(slide, icons[idx % len(icons)], x - 1.14, y - 0.31, 0.52, brand, self._icon_fill(brand, idx))
            self._add_body_text(slide, text, x - 0.46, y - 0.28, 1.55, 0.45, brand, size=10)

    def _add_dependency_map(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        bullets = self._bullets(outline)[:5]
        if len(bullets) < 4:
            bullets = (bullets + [
                "Capture product context",
                "Capture system patterns",
                "Capture active decisions",
                "Feed the next AI session",
            ])[:4]
        left = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.9), Inches(3.0), Inches(2.25), Inches(0.78))
        left.fill.solid()
        left.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        left.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_text_in_shape(left, "project_brief.md", brand, size=10, bold=True, color=brand.colors.text_light)
        mid_positions = [(4.1, 2.0), (4.1, 3.22), (4.1, 4.44)]
        for idx, (x, y) in enumerate(mid_positions):
            self._add_card(slide, x, y, 2.65, 0.82, "FFFFFF", brand.colors.secondary)
            self._add_body_text(slide, bullets[idx], x + 0.18, y + 0.17, 2.28, 0.36, brand, size=9)
            self._add_arrow(slide, 3.18, 3.37, x - 0.05, y + 0.41, brand.colors.secondary)
        right = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(8.1), Inches(3.0), Inches(3.3), Inches(0.88))
        right.fill.solid()
        right.fill.fore_color.rgb = self._rgb(self._tint(brand.colors.accent, 0.84))
        right.line.color.rgb = self._rgb(brand.colors.accent)
        self._add_body_text(slide, bullets[3], 8.34, 3.22, 2.75, 0.34, brand, size=10)
        for _idx, (_x, y) in enumerate(mid_positions):
            self._add_arrow(slide, 6.78, y + 0.41, 8.0, 3.44, brand.colors.accent)

    def _add_checklist(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        bullets = self._bullets(outline)[:6]
        if not bullets:
            bullets = ["Create the core context files", "Set review rules", "Run a clean session", "Update memory after changes"]
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
            self._add_body_text(slide, text, 1.58, y - 0.03, 6.2, 0.43, brand, size=12)
        panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(8.45), Inches(1.62), Inches(3.55), Inches(3.92))
        panel.fill.solid()
        panel.fill.fore_color.rgb = self._rgb(brand.colors.primary)
        panel.line.color.rgb = self._rgb(brand.colors.primary)
        self._add_dark_text(slide, "NEXT 30 DAYS", 8.82, 2.0, 1.8, 0.28, brand, size=10, color=brand.colors.accent)
        self._add_dark_text(slide, "Turn the checklist into operating cadence, not a one-time cleanup.", 8.82, 2.52, 2.8, 1.0, brand, size=16, bold=True)
        self._add_dark_text(slide, "Review the Memory Bank after each meaningful code or architecture change.", 8.84, 4.15, 2.8, 0.62, brand, size=9, color=self._tint(brand.colors.primary, 0.72))

    def _add_code_panel(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        bullets = self._bullets(outline)[:4]
        if not bullets:
            bullets = ["Store rules in version control", "Keep instructions specific", "Review outputs before merge"]
        self._add_bullets(slide, bullets, 0.95, 1.78, 5.9, 3.25, brand)
        panel = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(7.35), Inches(1.72), Inches(4.5), Inches(3.9))
        panel.fill.solid()
        panel.fill.fore_color.rgb = self._rgb("111827")
        panel.line.color.rgb = self._rgb("111827")
        header = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(7.35), Inches(1.72), Inches(4.5), Inches(0.42))
        header.fill.solid()
        header.fill.fore_color.rgb = self._rgb("1F2937")
        header.line.color.rgb = header.fill.fore_color.rgb
        self._add_dark_text(
            slide,
            "rules.md",
            7.58,
            1.85,
            1.4,
            0.2,
            brand,
            size=8,
            color=self._tint("111827", 0.72),
        )
        code_lines = ["# agent rules"] + [
            "- " + self._truncate_at_word(str(bullet), 46) for bullet in bullets[:5]
        ]
        self._add_code_text(slide, code_lines, 7.62, 2.32, 3.76, 2.48, brand)

    def _add_anti_patterns(self, slide, outline: SlideOutline, brand: BrandDNA) -> None:
        bullets = self._bullets(outline)[:4]
        if not bullets:
            bullets = ["Relying on chat history", "Skipping source checks", "Accepting generated code blindly", "Letting context go stale"]
        icons = self._icons(outline)
        card_w = 2.72
        for idx, text in enumerate(bullets[:4]):
            x = 0.86 + idx * 3.05
            self._add_card(slide, x, 1.78, card_w, 3.6, "FFFFFF", brand.colors.background_light)
            self._add_icon(slide, icons[idx], x + 0.22, 2.05, 0.72, brand, self._icon_fill(brand, idx))
            self._add_label(slide, f"Pattern {idx + 1}", x + 1.1, 2.22, 1.2, brand, bold=True)
            self._add_body_text(slide, text, x + 0.32, 3.05, card_w - 0.58, 1.5, brand, size=12)

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
    ) -> None:
        connector = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            Inches(x1),
            Inches(y1),
            Inches(x2),
            Inches(y2),
        )
        connector.line.color.rgb = self._rgb(color)
        connector.line.width = Pt(1.4)

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
            para.text = f"• {bullet[:175]}"
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
        return " ".join(cleaned.split()).strip(" -:;")

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
        return cleaned[: limit - 3].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
