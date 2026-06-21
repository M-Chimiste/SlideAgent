# ruff: noqa: F401
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.document import DocumentBundle, DocumentMetric, DocumentSection
from app.models.generation import ContentBlock, DeckBlueprint, DeckSpec, GeneratedSlideSpec
from app.models.outline import SlideOutline
from app.models.planning import StoryBeat, StoryMap
from app.models.template import SlideSpec, TemplateProfile
from app.services.planning.constants import (
    PLANNER_SYSTEM_PROMPT,
    SOURCE_NEEDED_LABEL,
    UPLOADED_SOURCE_LABEL,
)


class ExhibitSelectionMixin:
    def _apply_exhibit_selection(
        self,
        deck: DeckSpec,
        bundle: DocumentBundle,
        story_map: StoryMap | None = None,
    ) -> None:
        used_metric_ids: set[str] = set()
        for slide in deck.slides:
            archetype = self._normalize_archetype(slide.archetype or "")
            if archetype in {"cover", "executive_summary", "closing_recommendation"}:
                continue
            beat = self._story_beat_for_slide(story_map, slide.slide_number) if story_map else None
            section = self._section_for_slide_sources(slide, bundle)
            if (
                beat is None
                and archetype
                and archetype not in {"two_column", "callouts", "icon_rows"}
                and not self._exhibit_is_incomplete(slide)
                and not (
                    self._claim_has_metric_signal(self._selection_text(slide, section, beat))
                    and bundle.metrics
                )
                and not bundle.tables
            ):
                continue
            desired = self._select_exhibit_archetype(slide, section, bundle, beat)
            if not desired:
                continue
            current_exhibit_type = str((slide.exhibit_spec or {}).get("type") or "")
            desired_exhibit_type = self._expected_exhibit_type(desired)
            should_refresh = (
                desired != archetype
                or self._exhibit_is_incomplete(slide)
                or (
                    desired_exhibit_type
                    and current_exhibit_type
                    and current_exhibit_type != desired_exhibit_type
                    and not (
                        desired == "framework_cycle" and current_exhibit_type == "cycle"
                    )
                )
            )
            if not should_refresh:
                continue
            self._apply_selected_exhibit(slide, desired, section, bundle, used_metric_ids)

    def _select_exhibit_archetype(
        self,
        slide: GeneratedSlideSpec,
        section: DocumentSection | None,
        bundle: DocumentBundle,
        beat: StoryBeat | None = None,
    ) -> str:
        text = self._selection_text(slide, section, beat)
        preferred = self._normalize_archetype(beat.preferred_exhibit) if beat else ""
        if preferred == "cycle":
            preferred = "framework_cycle"
        if preferred in {"cover", "executive_summary", "closing_recommendation"}:
            return self._normalize_archetype(slide.archetype or "") or "two_column"
        if self._claim_has_metric_signal(text) and bundle.metrics:
            return "metric_chart"
        if bundle.tables:
            if self._claim_has_comparison_signal(text) or self._tables_have_comparison_shape(bundle):
                return "comparison_table"
            if self._claim_has_reference_signal(text):
                return "table_reference"
        if preferred in {
            "comparison_table",
            "dependency_map",
            "framework_cycle",
            "checklist",
            "code_panel",
            "anti_patterns",
            "metric_chart",
            "table_reference",
            "matrix_2x2",
            "callouts",
            "icon_rows",
            "two_column",
        }:
            return preferred
        if self._claim_has_ordered_signal(text):
            return "checklist"
        if self._claim_has_tradeoff_signal(text):
            return "matrix_2x2"
        if self._claim_has_dependency_signal(text):
            return "dependency_map"
        if self._claim_has_cycle_signal(text):
            return "framework_cycle"
        if self._claim_has_reference_signal(text):
            return "code_panel"
        if self._claim_has_mindset_signal(text):
            return "quote_sidebar"
        current = self._normalize_archetype(slide.archetype or "")
        return current if current in {"callouts", "icon_rows", "two_column"} else "callouts"

    def _apply_selected_exhibit(
        self,
        slide: GeneratedSlideSpec,
        archetype: str,
        section: DocumentSection | None,
        bundle: DocumentBundle,
        used_metric_ids: set[str] | None = None,
    ) -> None:
        if section is None and bundle.sections:
            section = bundle.sections[min(slide.slide_number - 1, len(bundle.sections) - 1)]
        if section is None:
            section = DocumentSection(
                title=slide.action_title,
                level=1,
                content=slide.subheading or slide.action_title,
                source_doc_id="generated",
            )
        if used_metric_ids:
            available_metrics = [
                metric
                for metric in bundle.metrics
                if self._metric_key(metric.label, metric.value, metric.unit)
                not in used_metric_ids
            ]
        else:
            available_metrics = bundle.metrics
        metrics = self._pick_metrics(available_metrics, count=5, exclude_ids=used_metric_ids)
        exhibit = self._exhibit_for_archetype(
            archetype,
            section,
            bundle.sections or [section],
            metrics,
            bundle.tables,
            available_metrics,
        )
        slide.archetype = archetype
        slide.slide_type = self._slide_type_for_archetype(archetype)
        slide.exhibit_spec = exhibit
        # Mark metrics consumed by a chart exhibit so later slides pick fresh ones
        # instead of repeating the same KPI block.
        if used_metric_ids is not None and str(exhibit.get("type") or "") in {
            "metric_chart",
            "line_chart",
        }:
            for metric in exhibit.get("metrics", []):
                if isinstance(metric, dict):
                    used_metric_ids.add(
                        self._metric_key(
                            metric.get("label"), metric.get("value"), metric.get("unit")
                        )
                    )
        slide.content_blocks = self._content_blocks_from_exhibit(archetype, exhibit, section)
        chart_spec = self.exhibit_compiler.chart_spec(exhibit)
        if chart_spec:
            slide.chart_spec = chart_spec
        elif archetype != "metric_chart":
            slide.chart_spec = None
        slide.design_intent = self._design_intent(archetype)
        self._sync_diagram_spec(slide)

    def _section_for_slide_sources(
        self,
        slide: GeneratedSlideSpec,
        bundle: DocumentBundle,
    ) -> DocumentSection | None:
        refs = [
            str(ref)
            for ref in slide.source_refs
            if str(ref).strip() and "source needed" not in str(ref).lower()
        ]
        for ref in refs:
            for section in bundle.sections:
                if getattr(section, "source_id", "") == ref or self._legacy_source_ref(section) == ref:
                    return section
            entry = bundle.source_index.get(ref)
            if not entry:
                continue
            doc_id = entry.get("source_doc_id", "")
            title = str(entry.get("title") or entry.get("section") or "").casefold()
            for section in bundle.sections:
                if section.source_doc_id == doc_id and (
                    not title or self._clean_section_title(section.title).casefold() == title
                ):
                    return section
        if bundle.sections:
            return bundle.sections[min(max(slide.slide_number - 1, 0), len(bundle.sections) - 1)]
        return None

    def _selection_text(
        self,
        slide: GeneratedSlideSpec,
        section: DocumentSection | None,
        beat: StoryBeat | None,
    ) -> str:
        parts = [
            slide.action_title,
            slide.subheading,
            slide.slide_type,
            slide.archetype or "",
            slide.narrative_role or "",
            beat.claim if beat else "",
            beat.preferred_exhibit if beat else "",
            section.title if section else "",
            section.content if section else "",
        ]
        for block in slide.content_blocks:
            parts.extend(str(item) for item in block.body)
            parts.extend(block.annotations)
            parts.extend(block.callouts)
        return " ".join(parts).lower()

    def _expected_exhibit_type(self, archetype: str) -> str:
        return {
            "comparison_table": "comparison_table",
            "dependency_map": "dependency_map",
            "framework_cycle": "cycle",
            "checklist": "checklist",
            "code_panel": "code_panel",
            "anti_patterns": "anti_patterns",
            "quote_sidebar": "quote_sidebar",
            "metric_chart": "metric_chart",
            "table_reference": "reference_table",
            "matrix_2x2": "matrix_2x2",
            "callouts": "callouts",
            "icon_rows": "icon_rows",
            "two_column": "two_column",
        }.get(archetype, "")

    def _claim_has_metric_signal(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b(metric|quantify|quantitative|kpi|percent|percentage|%|revenue|cost|growth|adoption|tokens?|window|rate|number|measure)\b",
                text,
            )
        )

    def _claim_has_comparison_signal(self, text: str) -> bool:
        return bool(re.search(r"\b(compare|contrast|versus|vs\.?|current state|target state|before|after)\b", text))

    def _claim_has_reference_signal(self, text: str) -> bool:
        return bool(re.search(r"\b(reference|artifact|standard|rule|rules|code|file|table|catalog|inventory)\b", text))

    def _claim_has_ordered_signal(self, text: str) -> bool:
        return bool(re.search(r"\b(first|then|next|finally|step|steps|checklist|sequence|timing|implementation plan)\b", text))

    def _claim_has_tradeoff_signal(self, text: str) -> bool:
        return bool(re.search(r"\b(trade[- ]?off|priorit|impact|readiness|matrix|quadrant|low|high)\b", text))

    def _claim_has_dependency_signal(self, text: str) -> bool:
        return bool(re.search(r"\b(depend|driver|flow|feed|constraint|cause|map|relationship|link)\b", text))

    def _claim_has_cycle_signal(self, text: str) -> bool:
        return bool(re.search(r"\b(cycle|loop|workflow|phase|operating model|cadence|iterate)\b", text))

    def _claim_has_mindset_signal(self, text: str) -> bool:
        return bool(re.search(r"\b(mindset|reframe|role|belief|quote|mental model|manager|teammate)\b", text))

    def _tables_have_comparison_shape(self, bundle: DocumentBundle) -> bool:
        return any(len(table.headers) >= 3 and len(table.rows) >= 2 for table in bundle.tables[:3])
