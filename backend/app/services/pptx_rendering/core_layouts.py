# ruff: noqa: F401
from pathlib import Path
import math
import re
import shutil
import subprocess
from typing import Any

from PIL import Image, ImageDraw
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.util import Inches, Pt

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.services.concept_diagram_renderer import ConceptDiagramRenderer, DiagramRenderError
from app.services.pptx_rendering.constants import ICON_SCALE, SLIDE_H, SLIDE_W


class CoreLayoutRenderingMixin:
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
        if not metrics and exhibit.get("type") == "line_chart":
            metrics = exhibit.get("metrics") or []
        metrics = [metric for metric in metrics if isinstance(metric, dict)]
        if not metrics:
            self._add_two_column(slide, outline, brand)
            return
        chart_type = str((outline.content_json.get("chart_spec") or {}).get("type") or exhibit.get("type") or "")
        if chart_type == "line" or exhibit.get("type") == "line_chart":
            series = self._line_series(metrics[:8])
            if series:
                self._add_native_line_chart(slide, outline, brand, series)
                return
        series = self._chart_series(metrics[:6])
        if series:
            self._add_native_bar_chart(slide, outline, brand, series)
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

    def _chart_series(
        self, metrics: list[dict[str, Any]]
    ) -> list[tuple[str, float, str]] | None:
        """Return a chartable (label, value, unit) series, or None.

        A native bar chart is only meaningful when at least three values share a
        single unit; mixed-unit KPIs (e.g. 95% next to 1M tokens) stay as cards.
        """
        series: list[tuple[str, float, str]] = []
        for metric in metrics:
            text = str(metric.get("value", "")).strip()
            had_pct = text.endswith("%")
            try:
                value = float(text.replace(",", "").rstrip("%").strip())
            except (TypeError, ValueError):
                return None
            label = self._metric_label_text(metric.get("label", "")) or "Item"
            unit = str(metric.get("unit") or "").strip() or ("%" if had_pct else "")
            series.append((label, value, unit))
        if len(series) < 3:
            return None
        if len({unit.lower() for _, _, unit in series}) != 1:
            return None
        return series

    def _line_series(
        self, metrics: list[dict[str, Any]]
    ) -> list[tuple[str, float, str]] | None:
        series: list[tuple[str, float, str]] = []
        for index, metric in enumerate(metrics):
            try:
                value = float(str(metric.get("value", "")).replace(",", "").rstrip("%"))
            except (TypeError, ValueError):
                continue
            label = self._metric_label_text(metric.get("label", "")) or f"Point {index + 1}"
            unit = str(metric.get("unit") or "")
            series.append((label, value, unit))
        if len(series) < 3:
            return None
        units = {unit.lower() for _, _, unit in series if unit}
        if len(units) > 1:
            return None
        return series

    def _add_native_line_chart(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        series: list[tuple[str, float, str]],
    ) -> None:
        labels = [self._truncate_at_word(label, 20) for label, _, _ in series]
        values = [value for _, value, _ in series]
        unit = series[0][2]
        self._add_label(slide, "TREND SIGNAL", 0.9, 1.45, 3.0, brand, bold=True)
        chart_data = CategoryChartData()
        chart_data.categories = labels
        chart_data.add_series("trend", tuple(values))
        frame = slide.shapes.add_chart(
            XL_CHART_TYPE.LINE_MARKERS,
            Inches(0.9),
            Inches(1.9),
            Inches(11.35),
            Inches(3.6),
            chart_data,
        )
        chart = frame.chart
        chart.has_legend = False
        chart.has_title = False
        plot = chart.plots[0]
        plot.has_data_labels = True
        data_labels = plot.data_labels
        data_labels.number_format = '0"%"' if unit == "%" else "#,##0"
        data_labels.number_format_is_linked = False
        data_labels.position = XL_LABEL_POSITION.ABOVE
        data_labels.font.size = Pt(10)
        data_labels.font.bold = True
        data_labels.font.name = brand.fonts.body
        data_labels.font.color.rgb = self._rgb(brand.colors.text_dark)
        line_series = plot.series[0]
        line_series.format.line.color.rgb = self._rgb(brand.colors.accent)
        line_series.format.line.width = Pt(2.25)
        value_axis = chart.value_axis
        value_axis.has_major_gridlines = True
        value_axis.major_gridlines.format.line.color.rgb = self._rgb(
            self._tint(brand.colors.secondary, 0.78)
        )
        value_axis.tick_labels.font.size = Pt(9)
        category_axis = chart.category_axis
        category_axis.tick_labels.font.size = Pt(10)
        category_axis.tick_labels.font.name = brand.fonts.body
        category_axis.tick_labels.font.color.rgb = self._rgb(brand.colors.text_dark)
        insight = self._metric_insight(
            outline,
            [{"label": label, "value": value, "unit": unit} for label, value, unit in series],
        )
        self._add_card(
            slide,
            1.2,
            5.74,
            10.9,
            0.74,
            brand.colors.background_light,
            brand.colors.background_light,
        )
        self._add_body_text(
            slide, insight, 1.52, 5.92, 10.25, 0.4, brand, center=True, size=13
        )

    def _add_native_bar_chart(
        self,
        slide,
        outline: SlideOutline,
        brand: BrandDNA,
        series: list[tuple[str, float, str]],
    ) -> None:
        labels = [self._truncate_at_word(label, 22) for label, _, _ in series]
        values = [value for _, value, _ in series]
        unit = series[0][2]
        self._add_label(slide, "SOURCED SIGNALS", 0.9, 1.45, 3.0, brand, bold=True)

        chart_data = CategoryChartData()
        chart_data.categories = labels
        chart_data.add_series("signal", tuple(values))
        frame = slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED,
            Inches(0.9),
            Inches(1.98),
            Inches(11.5),
            Inches(3.5),
            chart_data,
        )
        chart = frame.chart
        chart.has_legend = False
        chart.has_title = False

        plot = chart.plots[0]
        plot.gap_width = 80
        plot.has_data_labels = True
        data_labels = plot.data_labels
        data_labels.number_format = '0"%"' if unit == "%" else "#,##0"
        data_labels.number_format_is_linked = False
        data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
        data_labels.font.size = Pt(12)
        data_labels.font.bold = True
        data_labels.font.name = brand.fonts.body
        data_labels.font.color.rgb = self._rgb(brand.colors.text_dark)

        # One accent bar carries the message; the rest stay a neutral gray.
        highlight = max(range(len(values)), key=lambda index: values[index])
        muted = self._tint(brand.colors.secondary, 0.5)
        bar_series = plot.series[0]
        for index, point in enumerate(bar_series.points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = self._rgb(
                brand.colors.accent if index == highlight else muted
            )

        value_axis = chart.value_axis
        value_axis.has_major_gridlines = False
        value_axis.visible = False
        value_axis.minimum_scale = 0
        value_axis.maximum_scale = max(values) * 1.18 if values else 1
        category_axis = chart.category_axis
        category_axis.has_major_gridlines = False
        category_axis.tick_labels.font.size = Pt(11)
        category_axis.tick_labels.font.name = brand.fonts.body
        category_axis.tick_labels.font.color.rgb = self._rgb(brand.colors.text_dark)

        insight = self._metric_insight(
            outline,
            [{"label": label, "value": value, "unit": unit} for label, value, unit in series],
        )
        self._add_card(
            slide, 1.2, 5.74, 10.9, 0.74, brand.colors.background_light, brand.colors.background_light
        )
        self._add_body_text(slide, insight, 1.52, 5.92, 10.25, 0.4, brand, center=True, size=13)
