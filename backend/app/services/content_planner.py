import re
import uuid
from datetime import datetime
from typing import Any

from app.models.document import DocumentBundle, DocumentMetric, DocumentSection
from app.models.outline import SlideOutline
from app.models.template import SlideSpec, TemplateProfile


class ContentPlanner:
    def __init__(self) -> None:
        self.layouts = [
            "icon_rows",
            "two_column",
            "callouts",
            "chart",
            "icon_grid",
        ]

    def plan(
        self, template: TemplateProfile, bundle: DocumentBundle
    ) -> tuple[list[SlideOutline], list[dict[str, Any]]]:
        warnings: list[dict[str, Any]] = []
        outlines: list[SlideOutline] = []
        last_layout: str | None = None
        if template.type == "brand":
            sections = self._pick_sections(bundle.sections)
            for index, section in enumerate(sections):
                layout = self._next_layout(last_layout)
                last_layout = layout
                outline = self._outline_for_section(
                    template, bundle, index, section, layout
                )
                outlines.append(outline)
        else:
            for slide_spec in template.slides:
                if slide_spec.mode == "strict":
                    outline, slide_warnings = self._outline_for_strict_slide(
                        template, bundle, slide_spec
                    )
                    outlines.append(outline)
                    warnings.extend(slide_warnings)
                else:
                    layout = self._next_layout(last_layout)
                    last_layout = layout
                    outline = self._outline_for_flexible_slide(
                        template, bundle, slide_spec, layout
                    )
                    outlines.append(outline)
        return outlines, warnings

    def _pick_sections(self, sections: list[DocumentSection]) -> list[DocumentSection]:
        primary = [section for section in sections if section.level <= 2]
        return primary[:12] if primary else sections[:8]

    def _outline_for_section(
        self,
        template: TemplateProfile,
        bundle: DocumentBundle,
        slide_index: int,
        section: DocumentSection,
        layout: str,
    ) -> SlideOutline:
        metrics = self._pick_metrics(bundle.metrics, count=3)
        content = {
            "title": section.title,
            "summary": self._summarize(section.content),
            "bullets": self._to_bullets(section.content),
            "metrics": metrics,
        }
        if metrics and layout == "chart":
            layout_json = {"layout": "chart", "visual_elements": ["charts"]}
        elif metrics and layout == "callouts":
            layout_json = {"layout": "callouts", "visual_elements": ["callouts"]}
        else:
            layout_json = {"layout": layout, "visual_elements": ["icons"]}
        return SlideOutline(
            id=str(uuid.uuid4()),
            job_id=bundle.job_id,
            slide_index=slide_index,
            mode="flexible",
            label=section.title,
            content_json=content,
            layout_json=layout_json,
            created_at=self._timestamp(),
        )

    def _outline_for_flexible_slide(
        self,
        template: TemplateProfile,
        bundle: DocumentBundle,
        slide_spec: SlideSpec,
        layout: str,
    ) -> SlideOutline:
        section = self._match_section(bundle.sections, slide_spec)
        metrics = self._pick_metrics(bundle.metrics, count=3)
        content = {
            "title": slide_spec.label,
            "summary": self._summarize(section.content if section else ""),
            "bullets": self._to_bullets(section.content if section else ""),
            "metrics": metrics,
            "intent": slide_spec.intent or slide_spec.label,
        }
        if metrics and layout == "chart":
            layout_json = {"layout": "chart", "visual_elements": ["charts"]}
        elif metrics and layout == "callouts":
            layout_json = {"layout": "callouts", "visual_elements": ["callouts"]}
        else:
            layout_json = {"layout": layout, "visual_elements": ["icons"]}
        return SlideOutline(
            id=str(uuid.uuid4()),
            job_id=bundle.job_id,
            slide_index=slide_spec.index,
            mode="flexible",
            label=slide_spec.label,
            content_json=content,
            layout_json=layout_json,
            created_at=self._timestamp(),
        )

    def _outline_for_strict_slide(
        self,
        template: TemplateProfile,
        bundle: DocumentBundle,
        slide_spec: SlideSpec,
    ) -> tuple[SlideOutline, list[dict[str, Any]]]:
        warnings: list[dict[str, Any]] = []
        field_values: dict[str, Any] = {}
        if slide_spec.schema:
            for field in slide_spec.schema.fields:
                value = self._find_field_value(field.id, field.type, bundle)
                if value is None:
                    value = "[INSERT CONTENT HERE]"
                    warnings.append(
                        {
                            "slide_index": slide_spec.index,
                            "field": field.id,
                            "message": "Missing content for strict field.",
                        }
                    )
                field_values[field.id] = value
        content = {"fields": field_values}
        layout_json = {"layout": "strict", "visual_elements": []}
        outline = SlideOutline(
            id=str(uuid.uuid4()),
            job_id=bundle.job_id,
            slide_index=slide_spec.index,
            mode="strict",
            label=slide_spec.label,
            content_json=content,
            layout_json=layout_json,
            created_at=self._timestamp(),
        )
        return outline, warnings

    def _match_section(
        self, sections: list[DocumentSection], slide_spec: SlideSpec
    ) -> DocumentSection | None:
        if not sections:
            return None
        for section in sections:
            if slide_spec.label.lower() in section.title.lower():
                return section
        return sections[0]

    def _find_field_value(
        self, field_id: str, field_type: str, bundle: DocumentBundle
    ) -> Any:
        normalized = field_id.replace("_", " ").lower()
        for section in bundle.sections:
            if normalized in section.title.lower():
                return self._summarize(section.content)
        if field_type in {"number", "enum"} and bundle.metrics:
            return bundle.metrics[0].value
        return None

    def _next_layout(self, last_layout: str | None) -> str:
        for layout in self.layouts:
            if layout != last_layout:
                return layout
        return self.layouts[0]

    def _summarize(self, content: str) -> str:
        sentences = re.split(r"[.!?]\s+", content)
        return sentences[0][:160] if sentences else content[:160]

    def _to_bullets(self, content: str) -> list[str]:
        lines = [line.strip("-• ") for line in content.splitlines() if line.strip()]
        bullets = [line for line in lines if len(line.split()) > 3]
        return bullets[:4] if bullets else lines[:4]

    def _pick_metrics(
        self, metrics: list[DocumentMetric], count: int
    ) -> list[dict[str, Any]]:
        selected = metrics[:count]
        return [
            {"label": metric.label, "value": metric.value, "unit": metric.unit}
            for metric in selected
        ]

    def _timestamp(self) -> str:
        return datetime.utcnow().isoformat() + "Z"
