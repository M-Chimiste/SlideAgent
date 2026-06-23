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
        used_exhibit_fingerprints: set[str] = set()
        exhibit_type_counts: dict[str, int] = {}
        metric_slide_count = 0
        # The same KPI block on three slides is the most visible repetition tell.
        # Allow a single dedicated metric slide for a thin metric set, two when the
        # source is metric-rich; every other "metric signal" slide gets a distinct
        # non-metric exhibit instead.
        metric_slide_budget = 2 if len(bundle.metrics) >= 6 else 1
        for slide in deck.slides:
            archetype = self._normalize_archetype(slide.archetype or "")
            if archetype in {"cover", "executive_summary", "closing_recommendation"}:
                continue
            beat = self._story_beat_for_slide(story_map, slide.slide_number) if story_map else None
            section = self._section_for_slide_sources(slide, bundle)
            current_exhibit_type = str((slide.exhibit_spec or {}).get("type") or "")
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
                if not self._exhibit_repeats(
                    slide,
                    used_exhibit_fingerprints,
                    exhibit_type_counts,
                    bundle,
                ):
                    if current_exhibit_type in {"metric_chart", "line_chart"}:
                        self._register_used_metrics(slide, used_metric_ids)
                        metric_slide_count += 1
                    self._register_exhibit_usage(
                        slide,
                        used_exhibit_fingerprints,
                        exhibit_type_counts,
                    )
                    continue
            desired = self._select_exhibit_archetype(slide, section, bundle, beat)
            if not desired:
                continue
            # Steer metric slides away from repetition: switch to a distinct
            # exhibit once the metric budget is spent or no fresh metrics remain.
            if desired == "metric_chart":
                fresh = self._fresh_metrics(bundle, used_metric_ids)
                first_metric_slide = metric_slide_count == 0
                enough = len(fresh) >= 2 or (first_metric_slide and len(bundle.metrics) >= 2)
                if metric_slide_count >= metric_slide_budget or not enough:
                    desired = self._nonmetric_alternative(slide, section, bundle, beat)
            if self._exhibit_type_over_budget(
                self._expected_exhibit_type(desired),
                exhibit_type_counts,
                bundle,
            ):
                desired = self._nonmetric_alternative(
                    slide,
                    section,
                    bundle,
                    beat,
                    avoid={desired, self._expected_exhibit_type(desired)},
                )
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
            current_repeats = self._exhibit_repeats(
                slide,
                used_exhibit_fingerprints,
                exhibit_type_counts,
                bundle,
            )
            if current_repeats:
                desired = self._nonmetric_alternative(
                    slide,
                    section,
                    bundle,
                    beat,
                    avoid={archetype, current_exhibit_type},
                )
                should_refresh = True
            # A kept metric exhibit that re-uses already-shown numbers, or that
            # blows the metric budget, must be reworked rather than silently
            # repeating the prior KPI block.
            if not should_refresh and current_exhibit_type in {"metric_chart", "line_chart"}:
                if (
                    metric_slide_count >= metric_slide_budget
                    or self._exhibit_metrics_mostly_used(slide, used_metric_ids)
                ):
                    desired = (
                        "metric_chart"
                        if metric_slide_count < metric_slide_budget
                        and len(self._fresh_metrics(bundle, used_metric_ids)) >= 2
                        else self._nonmetric_alternative(slide, section, bundle, beat)
                    )
                    should_refresh = True
            if not should_refresh:
                if current_exhibit_type in {"metric_chart", "line_chart"}:
                    self._register_used_metrics(slide, used_metric_ids)
                    metric_slide_count += 1
                self._register_exhibit_usage(
                    slide,
                    used_exhibit_fingerprints,
                    exhibit_type_counts,
                )
                continue
            self._apply_selected_exhibit(slide, desired, section, bundle, used_metric_ids)
            if str((slide.exhibit_spec or {}).get("type") or "") in {"metric_chart", "line_chart"}:
                metric_slide_count += 1
            self._register_exhibit_usage(
                slide,
                used_exhibit_fingerprints,
                exhibit_type_counts,
            )

    def _fresh_metrics(
        self, bundle: DocumentBundle, used_metric_ids: set[str]
    ) -> list[Any]:
        return [
            metric
            for metric in bundle.metrics
            if self._metric_key(metric.label, metric.value, metric.unit) not in used_metric_ids
        ]

    def _register_used_metrics(
        self, slide: GeneratedSlideSpec, used_metric_ids: set[str]
    ) -> None:
        exhibit = slide.exhibit_spec if isinstance(slide.exhibit_spec, dict) else {}
        for metric in exhibit.get("metrics", []):
            if isinstance(metric, dict):
                used_metric_ids.add(
                    self._metric_key(
                        metric.get("label"), metric.get("value"), metric.get("unit")
                    )
                )

    def _exhibit_metrics_mostly_used(
        self, slide: GeneratedSlideSpec, used_metric_ids: set[str]
    ) -> bool:
        exhibit = slide.exhibit_spec if isinstance(slide.exhibit_spec, dict) else {}
        metrics = [m for m in exhibit.get("metrics", []) if isinstance(m, dict)]
        if not metrics:
            return False
        used = sum(
            1
            for metric in metrics
            if self._metric_key(metric.get("label"), metric.get("value"), metric.get("unit"))
            in used_metric_ids
        )
        return used >= max(1, len(metrics) - 1)

    def _nonmetric_alternative(
        self,
        slide: GeneratedSlideSpec,
        section: DocumentSection | None,
        bundle: DocumentBundle,
        beat: StoryBeat | None,
        avoid: set[str] | None = None,
    ) -> str:
        avoid_keys = {
            self._normalize_archetype(item)
            for item in (avoid or set())
            if str(item).strip()
        }
        avoid_keys.update(
            self._archetypes_for_exhibit_type(item)
            for item in (avoid or set())
            if str(item).strip()
        )
        text = self._selection_text(slide, section, beat)
        candidates: list[str] = []
        if bundle.tables and (
            self._claim_has_comparison_signal(text)
            or self._tables_have_comparison_shape(bundle)
        ):
            candidates.append("comparison_table")
        if self._claim_has_ordered_signal(text):
            candidates.append("checklist")
        if self._claim_has_strong_reference_signal(text):
            candidates.append("table_reference")
        if self._claim_has_dependency_signal(text):
            candidates.append("dependency_map")
        if self._claim_has_cycle_signal(text):
            candidates.append("framework_cycle")
        if self._claim_has_tradeoff_signal(text):
            candidates.append("matrix_2x2")
        if self._claim_has_mindset_signal(text):
            candidates.append("quote_sidebar")
        if bundle.tables and self._claim_has_reference_signal(text):
            candidates.append("table_reference")
        candidates.extend(
            [
                "comparison_table",
                "checklist",
                "quote_sidebar",
                "matrix_2x2",
                "icon_rows",
                "two_column",
                "callouts",
            ]
        )
        for candidate in candidates:
            if self._normalize_archetype(candidate) not in avoid_keys:
                return candidate
        return "two_column"

    def _exhibit_repeats(
        self,
        slide: GeneratedSlideSpec,
        used_fingerprints: set[str],
        type_counts: dict[str, int],
        bundle: DocumentBundle,
    ) -> bool:
        exhibit = slide.exhibit_spec if isinstance(slide.exhibit_spec, dict) else {}
        exhibit_type = str(exhibit.get("type") or "")
        if not exhibit_type:
            return False
        fingerprint = self._exhibit_fingerprint(slide)
        if fingerprint and fingerprint in used_fingerprints:
            return True
        return self._exhibit_type_over_budget(exhibit_type, type_counts, bundle)

    def _register_exhibit_usage(
        self,
        slide: GeneratedSlideSpec,
        used_fingerprints: set[str],
        type_counts: dict[str, int],
    ) -> None:
        exhibit = slide.exhibit_spec if isinstance(slide.exhibit_spec, dict) else {}
        exhibit_type = str(exhibit.get("type") or "")
        if exhibit_type:
            type_counts[exhibit_type] = type_counts.get(exhibit_type, 0) + 1
        fingerprint = self._exhibit_fingerprint(slide)
        if fingerprint:
            used_fingerprints.add(fingerprint)

    def _exhibit_type_over_budget(
        self,
        exhibit_type: str,
        type_counts: dict[str, int],
        bundle: DocumentBundle,
    ) -> bool:
        if not exhibit_type:
            return False
        budgets = {
            "dependency_map": 2,
            "cycle": 1,
            "code_panel": 1,
            "matrix_2x2": 1,
            "anti_patterns": 1,
            "quote_sidebar": 2,
            "checklist": 2,
            "reference_table": 2 if bundle.tables else 1,
            "comparison_table": 2 if bundle.tables else 1,
            "callouts": 1,
        }
        budget = budgets.get(exhibit_type)
        return budget is not None and type_counts.get(exhibit_type, 0) >= budget

    def _exhibit_fingerprint(self, slide: GeneratedSlideSpec) -> str:
        exhibit = slide.exhibit_spec if isinstance(slide.exhibit_spec, dict) else {}
        exhibit_type = str(exhibit.get("type") or "")
        if not exhibit_type:
            return ""
        parts = [exhibit_type]
        if exhibit_type == "dependency_map":
            parts.extend(
                [
                    str(exhibit.get("left_node") or ""),
                    str(exhibit.get("right_outcome") or ""),
                    *[str(item) for item in exhibit.get("middle_nodes", [])],
                ]
            )
        elif exhibit_type == "cycle":
            parts.append(str(exhibit.get("center_label") or ""))
            parts.extend(
                str(step.get("label") or step.get("description") or "")
                for step in exhibit.get("steps", [])
                if isinstance(step, dict)
            )
        elif exhibit_type in {"reference_table", "comparison_table"}:
            parts.extend(str(column) for column in exhibit.get("columns", []))
            for row in exhibit.get("rows", [])[:6]:
                if isinstance(row, dict):
                    parts.append(str(row.get("label") or ""))
                    parts.extend(str(value) for value in row.get("values", []))
                elif isinstance(row, list):
                    parts.extend(str(value) for value in row)
        elif exhibit_type == "code_panel":
            parts.extend(str(line) for line in exhibit.get("lines", []))
        elif exhibit_type == "metric_chart":
            parts.extend(
                self._metric_key(metric.get("label"), metric.get("value"), metric.get("unit"))
                for metric in exhibit.get("metrics", [])
                if isinstance(metric, dict)
            )
        else:
            parts.extend(
                self._flatten_exhibit_value(value)
                for key, value in sorted(exhibit.items())
                if key != "type"
            )
        tokens = re.sub(r"[^a-z0-9]+", " ", " ".join(parts).lower()).split()
        meaningful = [
            token
            for token in tokens
            if len(token) > 2
            and token
            not in {
                "the",
                "and",
                "for",
                "with",
                "source",
                "context",
                "review",
                "next",
            }
        ]
        return " ".join(meaningful[:36])

    def _flatten_exhibit_value(self, value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(self._flatten_exhibit_value(item) for item in value.values())
        if isinstance(value, list):
            return " ".join(self._flatten_exhibit_value(item) for item in value)
        return str(value)

    def _archetypes_for_exhibit_type(self, exhibit_type: str) -> str:
        mapping = {
            "cycle": "framework_cycle",
            "reference_table": "table_reference",
            "metric_chart": "metric_chart",
            "line_chart": "metric_chart",
            "dependency_map": "dependency_map",
            "comparison_table": "comparison_table",
            "code_panel": "code_panel",
            "matrix_2x2": "matrix_2x2",
            "quote_sidebar": "quote_sidebar",
            "checklist": "checklist",
            "callouts": "callouts",
            "icon_rows": "icon_rows",
            "two_column": "two_column",
        }
        return mapping.get(exhibit_type, self._normalize_archetype(exhibit_type))

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
        if (
            slide.slide_type == "executive_summary"
            and slide.slide_number != 1
            and self._normalize_archetype(slide.archetype or "") == "callouts"
        ):
            return "callouts"
        if preferred in {"cover", "executive_summary", "closing_recommendation"}:
            return self._normalize_archetype(slide.archetype or "") or "two_column"
        if self._claim_has_strong_reference_signal(text):
            return "table_reference"
        if self._claim_has_strong_dependency_signal(text):
            return "dependency_map"
        if self._claim_has_cycle_signal(text):
            return "framework_cycle"
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

    def _claim_has_strong_dependency_signal(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b(directed dependency graph|dependency graph|file hierarchy|hierarchy|"
                r"dependencies|dependent|feeds into|relationship map|system map)\b",
                text,
            )
        )

    def _claim_has_cycle_signal(self, text: str) -> bool:
        return bool(re.search(r"\b(cycle|loop|workflow|phase|operating model|cadence|iterate)\b", text))

    def _claim_has_strong_reference_signal(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b(six core files|core files|reference table|rules file|rules files|"
                r"specification files|memory bank files|file catalog|artifact catalog)\b",
                text,
            )
        )

    def _claim_has_mindset_signal(self, text: str) -> bool:
        return bool(re.search(r"\b(mindset|reframe|role|belief|quote|mental model|manager|teammate)\b", text))

    def _tables_have_comparison_shape(self, bundle: DocumentBundle) -> bool:
        return any(len(table.headers) >= 3 and len(table.rows) >= 2 for table in bundle.tables[:3])
