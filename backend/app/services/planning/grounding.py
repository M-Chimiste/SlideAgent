# ruff: noqa: F401
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.document import DocumentBundle, DocumentMetric, DocumentSection
from app.models.generation import ContentBlock, DeckBlueprint, DeckSpec, GeneratedSlideSpec
from app.models.outline import SlideOutline
from app.models.template import SlideSpec, TemplateProfile
from app.services.planning.constants import (
    PLANNER_SYSTEM_PROMPT,
    SOURCE_NEEDED_LABEL,
    UPLOADED_SOURCE_LABEL,
)


class SourceGroundingMixin:
    def _normalize_source_labels(
        self, deck: DeckSpec, bundle: DocumentBundle
    ) -> list[dict[str, Any]]:
        has_source_material = self._has_uploaded_source_material(bundle)
        fallback_label = (
            UPLOADED_SOURCE_LABEL if has_source_material else SOURCE_NEEDED_LABEL
        )
        warnings: list[dict[str, Any]] = []
        for slide in deck.slides:
            original_sources = list(slide.sources)
            normalized: list[str] = []
            invalid_sources: list[str] = []
            for source in original_sources:
                label = str(source).strip()
                canonical = self._canonical_source_label(label, has_source_material)
                if canonical:
                    normalized.append(canonical)
                elif label:
                    invalid_sources.append(label)

            if invalid_sources and fallback_label not in normalized:
                normalized.append(fallback_label)
            if not normalized:
                normalized.append(fallback_label)

            slide.sources = self._dedupe_preserving_order(normalized)
            if slide.sources == original_sources and not invalid_sources:
                continue

            invalid_summary = ", ".join(invalid_sources[:3])
            if invalid_summary:
                message = (
                    "Unverified source labels were replaced with "
                    f"{fallback_label}: {invalid_summary}"
                )
            else:
                message = f"Missing source labels were set to {fallback_label}."
            slide.qa.issues.append({"category": "source_label", "message": message})
            warnings.append(
                {
                    "slide_index": slide.slide_number - 1,
                    "field": "source_label",
                    "message": message,
                }
            )
        return warnings

    def _has_uploaded_source_material(self, bundle: DocumentBundle) -> bool:
        return bool(
            bundle.sections
            or bundle.tables
            or bundle.metrics
            or bundle.content_inventory
        )

    def _canonical_source_label(
        self, label: str, allow_uploaded_source: bool
    ) -> str | None:
        normalized = label.strip().casefold()
        if allow_uploaded_source and normalized == UPLOADED_SOURCE_LABEL.casefold():
            return UPLOADED_SOURCE_LABEL
        if normalized == SOURCE_NEEDED_LABEL.casefold():
            return SOURCE_NEEDED_LABEL
        return None

    def _dedupe_preserving_order(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped

    def _ground_numeric_claims(
        self, deck: DeckSpec, bundle: DocumentBundle
    ) -> list[dict[str, Any]]:
        supported_numbers = self._supported_numeric_tokens(bundle)
        warnings: list[dict[str, Any]] = []
        for slide in deck.slides:
            unsupported = sorted(
                token
                for token in self._numeric_tokens(self._slide_claim_text(slide))
                if token not in supported_numbers
            )
            if not unsupported:
                continue
            self._mark_unsupported_numeric_claims(slide, unsupported)
            if SOURCE_NEEDED_LABEL not in slide.sources:
                slide.sources.append(SOURCE_NEEDED_LABEL)
            issue = {
                "category": "source_coverage",
                "message": (
                    "Unsupported quantitative claim needs a source: "
                    + ", ".join(unsupported[:5])
                ),
            }
            slide.qa.issues.append(issue)
            warnings.append(
                {
                    "slide_index": slide.slide_number - 1,
                    "field": "source_coverage",
                    "message": issue["message"],
                }
            )
        return warnings

    def _supported_numeric_tokens(self, bundle: DocumentBundle) -> set[str]:
        source_text = " ".join(
            [f"{section.title} {section.content}" for section in bundle.sections]
            + [str(metric.value) for metric in bundle.metrics]
            + [inventory for inventory in bundle.content_inventory]
        )
        tokens = self._numeric_tokens(source_text)
        for token in list(tokens):
            if token.endswith("%"):
                tokens.add(token[:-1])
        for metric in bundle.metrics:
            tokens.add(self._normalize_numeric_token(str(metric.value)))
            if metric.unit:
                tokens.add(self._normalize_numeric_token(f"{metric.value}{metric.unit}"))
        return tokens

    def _slide_claim_text(self, slide: GeneratedSlideSpec) -> str:
        parts: list[str] = [slide.action_title, slide.subheading]
        for block in slide.content_blocks:
            parts.extend(self._claim_text_from_value(item) for item in block.body)
            parts.extend(block.annotations)
            parts.extend(block.callouts)
        if slide.chart_spec:
            parts.append(self._claim_text_from_value(slide.chart_spec))
        if slide.exhibit_spec:
            parts.append(self._claim_text_from_value(slide.exhibit_spec))
        return " ".join(parts)

    def _claim_text_from_value(self, value: Any, key: str = "") -> str:
        if key.lower() in self._visual_metadata_keys():
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            return " ".join(self._claim_text_from_value(item) for item in value)
        if isinstance(value, dict):
            return " ".join(
                self._claim_text_from_value(item, str(item_key))
                for item_key, item in value.items()
            )
        return ""

    def _mark_unsupported_numeric_claims(
        self, slide: GeneratedSlideSpec, unsupported: list[str]
    ) -> None:
        unsupported_set = set(unsupported)
        for block in slide.content_blocks:
            block.body = [
                self._mark_value_if_unsupported_number(item, unsupported_set)
                for item in block.body
            ]
            block.annotations = [
                self._mark_text_if_unsupported_number(item, unsupported_set)
                for item in block.annotations
            ]
            block.callouts = [
                self._mark_text_if_unsupported_number(item, unsupported_set)
                for item in block.callouts
            ]
        if slide.exhibit_spec:
            slide.exhibit_spec = self._mark_unsupported_numbers_in_value(
                slide.exhibit_spec,
                unsupported_set,
            )

    def _mark_unsupported_numbers_in_value(self, value: Any, unsupported: set[str]) -> Any:
        if isinstance(value, str):
            return self._mark_text_if_unsupported_number(value, unsupported)
        if isinstance(value, list):
            return [
                self._mark_unsupported_numbers_in_value(item, unsupported)
                for item in value
            ]
        if isinstance(value, dict):
            return {
                key: item
                if str(key).lower() in self._visual_metadata_keys()
                else self._mark_unsupported_numbers_in_value(item, unsupported)
                for key, item in value.items()
            }
        return value

    def _visual_metadata_keys(self) -> set[str]:
        return {
            "width",
            "height",
            "x",
            "y",
            "left",
            "right",
            "top",
            "bottom",
            "fill",
            "color",
            "accent",
        }

    def _mark_value_if_unsupported_number(
        self, value: Any, unsupported: set[str]
    ) -> Any:
        if isinstance(value, str):
            return self._mark_text_if_unsupported_number(value, unsupported)
        if isinstance(value, list):
            return [
                self._mark_text_if_unsupported_number(item, unsupported)
                if isinstance(item, str)
                else item
                for item in value
            ]
        return value

    def _mark_text_if_unsupported_number(self, text: str, unsupported: set[str]) -> str:
        if "[source needed]" in text:
            return text
        if self._numeric_tokens(text) & unsupported:
            return f"{text} [source needed]"
        return text

    def _numeric_tokens(self, text: str) -> set[str]:
        return {
            self._normalize_numeric_token(match.group(0))
            for match in re.finditer(
                r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)%?(?!\w)",
                text,
            )
        }

    def _normalize_numeric_token(self, token: str) -> str:
        cleaned = token.strip().replace(",", "")
        if cleaned.endswith(".0"):
            cleaned = cleaned[:-2]
        return cleaned

    def _body_to_bullets(self, slide: GeneratedSlideSpec) -> list[str]:
        bullets: list[str] = []
        for block in slide.content_blocks:
            for item in block.body:
                if isinstance(item, str):
                    cleaned = self._clean_generated_visual_placeholder(item)
                    if cleaned:
                        bullets.append(cleaned)
                elif isinstance(item, list):
                    cleaned = self._clean_generated_visual_placeholder(
                        " | ".join(str(value) for value in item)
                    )
                    if cleaned:
                        bullets.append(cleaned)
        return bullets[:5]

    def _clean_generated_visual_placeholder(self, text: str) -> str:
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
        return self._repair_dangling_fragment(" ".join(cleaned.split()).strip(" -:;"))

    def _metrics_from_slide(self, slide: GeneratedSlideSpec) -> list[dict[str, Any]]:
        if isinstance(slide.exhibit_spec, dict):
            exhibit_type = str(slide.exhibit_spec.get("type") or "").lower().replace("-", "_")
            exhibit_metrics = slide.exhibit_spec.get("metrics", [])
            if exhibit_type == "metric_chart" and isinstance(exhibit_metrics, list):
                metrics = self._normalized_metric_dicts(exhibit_metrics)
                if metrics:
                    return metrics
        metrics = self._metrics_from_chart_spec(slide.chart_spec)
        if metrics:
            return metrics
        chart_signal = (
            slide.slide_type == "chart"
            or any(
                token in slide.action_title.lower()
                for token in ("quantify", "visualize", "measure", "adoption")
            )
        )
        if not chart_signal:
            return []
        extracted: list[dict[str, Any]] = []
        for bullet in self._body_to_bullets(slide):
            candidates: list[dict[str, Any]] = []
            for match in re.finditer(
                r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
                r"\s*(%|million\s+tokens?|tokens?)?(?!\w)",
                bullet,
                flags=re.IGNORECASE,
            ):
                value = self._parse_metric_value(match.group(1), match.group(2) or "")
                unit = self._normalize_metric_unit(match.group(2) or "")
                if self._looks_like_date_metric(value, unit, bullet, match.start(), match.end()):
                    continue
                candidates.append(
                    {
                        "label": self._metric_label_from_text(
                            bullet, match.start(), match.end()
                        ),
                        "value": value,
                        "unit": unit,
                    }
                )
            candidates.sort(key=self._metric_dict_priority)
            extracted.extend(candidates[:1])
        return extracted[:5]

    def _metric_label_from_text(
        self, text: str, number_start: int, number_end: int | None = None
    ) -> str:
        prefix = text[:number_start].strip(" :,-")
        suffix = text[number_end or number_start :].strip(" :,-")
        suffix = re.sub(r"^(?:of|for)\s+", "", suffix, flags=re.IGNORECASE)
        suffix = re.split(
            r"[,.;]|\b(?:by|during|as of)\b",
            suffix,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        if prefix and not self._looks_like_date_label(prefix):
            return self._truncate_at_word(prefix, 48).removesuffix("...")
        return self._truncate_at_word(suffix, 48).removesuffix("...") or "Metric"

    def _metrics_from_chart_spec(
        self, chart_spec: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        if not chart_spec:
            return []
        metrics = chart_spec.get("metrics", [])
        if isinstance(metrics, list) and metrics:
            return [
                metric
                for metric in metrics
                if isinstance(metric, dict) and self._is_chartable_metric_dict(metric)
            ]
        data_points = chart_spec.get("data_points", [])
        if isinstance(data_points, list) and data_points:
            normalized: list[dict[str, Any]] = []
            for point in data_points:
                if not isinstance(point, dict):
                    continue
                label = point.get("label") or point.get("name") or "Metric"
                value = point.get("value")
                if value is None:
                    continue
                normalized.append(
                    {
                        "label": label,
                        "value": value,
                        "unit": point.get("unit"),
                    }
                )
            return [
                metric
                for metric in normalized
                if self._is_chartable_metric_dict(metric)
            ]
        return []

    def _parse_metric_value(self, number_text: str, unit_text: str) -> float | int:
        value = float(number_text.replace(",", ""))
        if unit_text.lower().startswith("million"):
            value *= 1_000_000
        return int(value) if value.is_integer() else value

    def _normalize_metric_unit(self, unit_text: str) -> str | None:
        unit = unit_text.strip().lower()
        if not unit:
            return None
        if unit == "%":
            return "%"
        if "token" in unit:
            return "tokens"
        return unit_text.strip()

    def _metric_dict_priority(self, metric: dict[str, Any]) -> tuple[int, str]:
        unit = str(metric.get("unit") or "").lower()
        if unit == "%":
            return (0, str(metric.get("label") or ""))
        if unit == "tokens":
            return (1, str(metric.get("label") or ""))
        if unit:
            return (2, str(metric.get("label") or ""))
        return (3, str(metric.get("label") or ""))

    def _is_chartable_metric_dict(self, metric: dict[str, Any]) -> bool:
        value = metric.get("value")
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return False
        unit = self._normalize_metric_unit(str(metric.get("unit") or ""))
        label = str(metric.get("label") or "")
        return not self._looks_like_date_metric(numeric_value, unit, label, 0, len(label))

    def _looks_like_date_metric(
        self,
        value: float | int,
        unit: str | None,
        text: str,
        number_start: int,
        number_end: int,
    ) -> bool:
        if unit:
            return False
        if 1900 <= float(value) <= 2099:
            return True
        window = text[max(0, number_start - 24) : number_end + 24].lower()
        if float(value) <= 31 and self._contains_month_or_season(window):
            return True
        if re.search(r"\b(?:section|chapter|phase|step|slide)\s*$", text[:number_start], re.I):
            return True
        return False

    def _looks_like_date_label(self, text: str) -> bool:
        cleaned = text.lower()
        return bool(
            re.search(r"\b(?:19|20)\d{2}\b", cleaned)
            or self._contains_month_or_season(cleaned)
        )

    def _contains_month_or_season(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:january|february|march|april|may|june|july|august|"
                r"september|october|november|december|winter|spring|summer|fall|autumn)\b",
                text,
            )
        )

    def _layout_for_slide(self, slide: GeneratedSlideSpec) -> str:
        intent_text = self._slide_intent_text(slide)
        archetype = self._normalize_archetype(slide.archetype or "")
        archetype_layouts = {
            "cover": "cover",
            "executive_summary": "executive_summary",
            "section_divider": "section_divider",
            "comparison_table": "comparison_table",
            "dependency_map": "dependency_map",
            "framework_cycle": "framework_cycle",
            "code_panel": "code_panel",
            "checklist": "checklist",
            "quote_sidebar": "quote_sidebar",
            "anti_patterns": "anti_patterns",
            "metric_chart": "chart",
            "table_reference": "table_reference",
            "closing_recommendation": "closing_recommendation",
            "reference": "code_panel",
        }
        if archetype in archetype_layouts:
            if archetype == "metric_chart" and not self._metrics_from_slide(slide):
                return "table_reference"
            return archetype_layouts[archetype]
        if slide.chart_spec or (
            slide.slide_type == "chart" and self._metrics_from_slide(slide)
        ):
            return "chart"
        if slide.slide_type in {"section", "divider"}:
            return "section_divider"
        if slide.slide_type == "executive_summary" and slide.slide_number == 1:
            return "executive_summary"
        if slide.slide_type in {"anti_pattern", "anti-pattern"} or any(
            token in intent_text
            for token in ("anti-pattern", "anti pattern", "stop doing", "failure mode", "fails")
        ):
            return "anti_patterns"
        if any(
            token in intent_text
            for token in ("external brain", "memory bank", "hierarchy", "dependency graph")
        ):
            return "dependency_map"
        if slide.slide_type == "checklist" or any(
            token in intent_text
            for token in ("checklist", "quick-start", "quick start", "adopt it", "execute the transition", "standardize")
        ):
            return "checklist"
        if slide.slide_type == "quote" or any(
            token in intent_text
            for token in (
                "developer role",
                "product manager",
                "product-manager",
                "ai manager",
                "manager of ai",
                "employee management",
                "managed team member",
                "team member",
                "mental model",
                "reviewer mode",
            )
        ):
            return "quote_sidebar"
        if slide.slide_type in {"reference", "code"} or any(
            token in intent_text
            for token in ("markdown", "rules file", "rules files", "code", "github", "tool-agnostic", "tool agnostic")
        ):
            return "code_panel"
        if slide.slide_type in {"framework", "cycle"} or any(
            token in intent_text
            for token in ("cycle", "workflow", "six phases", "phase", "operating model")
        ):
            return "framework_cycle"
        block_types = {block.type for block in slide.content_blocks}
        if "table" in block_types:
            return "process"
        if "callout" in block_types:
            return "callouts"
        if slide.slide_type in {"matrix", "comparison"}:
            return "icon_grid"
        return "two_column"

    def _layout_with_variety(
        self,
        slide: GeneratedSlideSpec,
        preferred_layout: str,
        last_layout: str | None,
        slide_index: int,
    ) -> str:
        fixed_layouts = {
            "cover",
            "executive_summary",
            "section_divider",
            "comparison_table",
            "chart",
            "process",
            "quote_sidebar",
            "framework_cycle",
            "dependency_map",
            "checklist",
            "code_panel",
            "anti_patterns",
            "table_reference",
            "closing_recommendation",
        }
        if preferred_layout in fixed_layouts:
            if preferred_layout != last_layout:
                return preferred_layout
        cycle = ["two_column", "icon_grid", "quote_sidebar", "callouts", "checklist"]
        if preferred_layout == "two_column":
            layout = cycle[slide_index % len(cycle)]
        else:
            layout = preferred_layout if preferred_layout in cycle else cycle[slide_index % len(cycle)]
        if layout == last_layout:
            layout = cycle[(cycle.index(layout) + 1) % len(cycle)]
        return layout

    def _visual_elements_for_layout(self, layout: str) -> list[str]:
        if layout == "cover":
            return ["hero_typography", "section_marker"]
        if layout == "section_divider":
            return ["section_marker", "typography"]
        if layout == "comparison_table":
            return ["tables", "comparison"]
        if layout == "chart":
            return ["charts", "callouts"]
        if layout == "callouts":
            return ["callouts"]
        if layout == "process":
            return ["tables"]
        if layout == "quote_sidebar":
            return ["quote", "sidebar"]
        if layout == "framework_cycle":
            return ["cycle", "process"]
        if layout == "dependency_map":
            return ["diagram", "connectors"]
        if layout == "checklist":
            return ["checklist", "steps"]
        if layout == "code_panel":
            return ["reference_panel", "code"]
        if layout == "anti_patterns":
            return ["anti_pattern_cards", "icons"]
        if layout == "table_reference":
            return ["tables", "reference"]
        if layout == "closing_recommendation":
            return ["recommendation", "checklist"]
        return ["structured_text", "shapes"]

    def _slide_intent_text(self, slide: GeneratedSlideSpec) -> str:
        parts: list[str] = [
            slide.slide_type,
            slide.action_title,
            slide.subheading,
            slide.archetype or "",
            slide.narrative_role or "",
            slide.design_intent or "",
            str(slide.exhibit_spec or ""),
        ]
        for block in slide.content_blocks:
            parts.append(block.type)
            parts.extend(str(item) for item in block.body)
            parts.extend(block.annotations)
            parts.extend(block.callouts)
        return " ".join(parts).lower()

    def _next_layout(self, last_layout: str | None) -> str:
        for layout in self.layouts:
            if layout != last_layout:
                return layout
        return self.layouts[0]

    def _summarize(self, content: str) -> str:
        sentences = re.split(r"[.!?]\s+", content)
        summary = sentences[0] if sentences else content
        return self._truncate_at_word(summary, 160)

    def _truncate_at_word(self, text: str, limit: int) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= limit:
            return cleaned
        truncated = cleaned[: limit - 3].rsplit(" ", 1)[0].rstrip(".,;:")
        return f"{truncated}..."

    def _to_bullets(self, content: str) -> list[str]:
        lines = [line.strip("-• ") for line in content.splitlines() if line.strip()]
        bullets = [line for line in lines if len(line.split()) > 3]
        return bullets[:4] if bullets else lines[:4]

    def _pick_metrics(
        self, metrics: list[DocumentMetric], count: int
    ) -> list[dict[str, Any]]:
        selected = [
            metric
            for metric in metrics
            if self._is_chartable_metric_dict(
                {"label": metric.label, "value": metric.value, "unit": metric.unit}
            )
        ]
        selected.sort(
            key=lambda metric: self._metric_dict_priority(
                {"label": metric.label, "value": metric.value, "unit": metric.unit}
            )
        )
        selected = selected[:count]
        return [
            {
                "label": self._truncate_at_word(metric.label, 42).removesuffix("..."),
                "value": int(metric.value) if float(metric.value).is_integer() else metric.value,
                "unit": self._normalize_metric_unit(metric.unit or ""),
            }
            for metric in selected
        ]

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

