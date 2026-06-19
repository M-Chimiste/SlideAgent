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


class OutlinePlanningMixin:
    def _deck_to_outlines(
        self, deck: DeckSpec, job_id: str, mode: str
    ) -> list[SlideOutline]:
        outlines = []
        last_layout: str | None = None
        for slide in deck.slides:
            content = slide.model_dump()
            content["title"] = slide.action_title
            content["summary"] = slide.subheading
            content["bullets"] = self._body_to_bullets(slide)
            content["metrics"] = self._metrics_from_slide(slide)
            content["source_labels"] = list(slide.sources)
            preferred_layout = self._layout_for_slide(slide)
            layout = self._layout_with_variety(
                slide, preferred_layout, last_layout, len(outlines)
            )
            last_layout = layout
            outlines.append(
                SlideOutline(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    slide_index=slide.slide_number - 1,
                    mode="flexible",
                    label=slide.action_title,
                    content_json=content,
                    layout_json={
                        "layout": layout,
                        "visual_elements": self._visual_elements_for_layout(layout),
                        "generation_mode": mode,
                        "archetype": slide.archetype or layout,
                        "narrative_role": slide.narrative_role,
                        "design_intent": slide.design_intent,
                        "exhibit_type": (slide.exhibit_spec or {}).get("type")
                        if slide.exhibit_spec
                        else None,
                    },
                    qa_status=slide.qa.consulting_status,
                    qa_issues_json={"issues": slide.qa.issues},
                    created_at=self._timestamp(),
                )
            )
        return outlines

    def _pick_sections(self, sections: list[DocumentSection]) -> list[DocumentSection]:
        skipped = {"overview", "executive summary", "introduction", "background"}
        primary = [
            section
            for section in sections
            if section.level <= 2 and section.title.strip().lower() not in skipped
        ]
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
        if slide_spec.slide_schema:
            for field in slide_spec.slide_schema.fields:
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
        if field_type in {"text", "date"}:
            semantic = self._semantic_field_value(normalized, bundle)
            if semantic is not None:
                return semantic
        if field_type in {"number", "enum"} and bundle.metrics:
            return bundle.metrics[0].value
        return None

    def _semantic_field_value(self, normalized_field_id: str, bundle: DocumentBundle) -> str | None:
        sections = bundle.sections
        if not sections:
            return None
        if any(token in normalized_field_id for token in ["title", "name"]):
            return bundle.metadata.title or sections[0].title
        if "summary" in normalized_field_id:
            for section in sections:
                if "executive summary" in section.title.lower():
                    return self._summarize(section.content)
            return self._summarize(sections[0].content)
        if any(token in normalized_field_id for token in ["implication", "recommendation", "message"]):
            for section in sections:
                if section.title.lower() not in {"overview", "executive summary"}:
                    return self._summarize(section.content)
            return self._summarize(sections[0].content)
        return None

    def _title_from_instructions(self, instructions: str) -> str:
        cleaned = " ".join(instructions.split())
        if not cleaned:
            return "Executive Recommendation"
        return cleaned[:70].rstrip(".,;:") or "Executive Recommendation"

    def _sections_from_instructions(self, instructions: str) -> list[DocumentSection]:
        content = instructions or "Build a concise executive recommendation deck."
        return [
            DocumentSection(
                title="Decision Context",
                level=1,
                content=content,
                source_doc_id="prompt",
            ),
            DocumentSection(
                title="Key Implications",
                level=1,
                content=content,
                source_doc_id="prompt",
            ),
            DocumentSection(
                title="Recommended Path",
                level=1,
                content=content,
                source_doc_id="prompt",
            ),
        ]

    def _action_title(self, title: str, content: str) -> str:
        keyword_title = self._keyword_action_title(title, content)
        if keyword_title:
            return keyword_title
        first_sentence = self._summarize(content)
        if 5 <= len(first_sentence.split()) <= 16:
            return first_sentence[:110]
        base = self._clean_section_title(title)
        if not base:
            base = "The analysis"
        if re.search(r"\b\d+(\.\d+)?%?\b", first_sentence):
            return f"{base} shows measurable impact that should guide the decision"[:110]
        return f"Prioritize {base.lower()} to strengthen the recommendation"[:110]

    def _clean_section_title(self, title: str) -> str:
        cleaned = re.sub(r"^\d+(\.\d+)*\s*", "", title).strip()
        cleaned = re.sub(r"[^A-Za-z0-9\s%-]", "", cleaned)
        return " ".join(cleaned.split())

    def _keyword_action_title(self, title: str, content: str) -> str | None:
        combined = f"{title} {content}".lower()
        rules = [
            (
                "context rot",
                "Context rot makes long-running work increasingly unreliable",
            ),
            (
                "hallucination",
                "Unverified claims create quality risk before evidence is checked",
            ),
            (
                "reproducibility",
                "Untracked decisions create a reproducibility gap for teams",
            ),
            (
                "chatbot to employee",
                "Treat AI agents as managed teammates to improve software outcomes",
            ),
            (
                "product manager",
                "Use product-style specifications to manage complex work",
            ),
            (
                "external brain",
                "External memory gives agents the context they need to work reliably",
            ),
            (
                "memory bank",
                "Use a memory bank to turn ad hoc work into persistent context",
            ),
        ]
        for keyword, action_title in rules:
            if keyword in combined:
                return action_title
        return None
