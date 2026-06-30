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
        from app.services.slide_types import LIST_TYPES, get_slide_type

        bullet_layouts = {"two_column", "icon_rows", "icon_grid", "callouts"}

        outlines = []
        last_layout: str | None = None
        section_number = 0
        prev_section_label: str | None = None
        for slide in deck.slides:
            content = slide.model_dump()
            # Pin the planned slide-type's render primitive + composition family so
            # the build/render layers honor the planned *kind* instead of
            # re-deriving it from already-uniform content.
            stype = get_slide_type(slide.slide_type)
            content["pinned_primitive"] = stype.primitive
            content["pinned_family"] = stype.composition_family
            is_cover = self._normalize_archetype(slide.archetype or "") == "cover"
            display_title = deck.deck_title if is_cover else slide.action_title
            content["action_title"] = display_title
            content["title"] = display_title
            content["summary"] = slide.subheading
            content["bullets"] = self._body_to_bullets(slide)
            content["metrics"] = self._metrics_from_slide(slide)
            content["source_labels"] = list(slide.sources)
            preferred_layout = self._layout_for_slide(slide)
            layout = self._layout_with_variety(
                slide, preferred_layout, last_layout, len(outlines)
            )
            # Keep the QA-visible layout/archetype consistent with the pinned
            # non-list primitive: a slide the renderer draws as a statement/stat
            # (density gate or variety controller) must not still report a
            # bullet-card layout, which would misreport variety and trip
            # bullet_card_usage / narrative_rhythm against what was rendered.
            non_list_override = (
                slide.slide_type not in LIST_TYPES and layout in bullet_layouts
            )
            if non_list_override:
                layout = "chart" if self._metrics_from_slide(slide) else "quote_sidebar"
            last_layout = layout
            archetype = layout if non_list_override else (slide.archetype or layout)
            # Assign a monotonic section number that only advances when the section
            # label changes, so kickers read 01 -> 0N in order instead of jumping
            # around by per-slide archetype (the cover carries no section kicker).
            if is_cover:
                section_marker, section_label = "", ""
                content["deck_title"] = deck.deck_title
            else:
                section_label = self._section_label_for(slide.narrative_role, archetype)
                if section_label != prev_section_label:
                    section_number += 1
                    prev_section_label = section_label
                section_marker = f"{section_number:02d}"
            outlines.append(
                SlideOutline(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    slide_index=slide.slide_number - 1,
                    mode="flexible",
                    label=display_title,
                    content_json=content,
                    layout_json={
                        "layout": layout,
                        "visual_elements": self._visual_elements_for_layout(layout),
                        "generation_mode": mode,
                        "archetype": archetype,
                        "narrative_role": slide.narrative_role,
                        "design_intent": slide.design_intent,
                        "section_number": section_marker,
                        "section_label": section_label,
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

    def _section_label_for(self, role: str | None, archetype: str) -> str:
        """Section label for a slide's kicker, derived from its narrative role
        (preferred) or archetype. Numbering is assigned sequentially by the caller."""
        from app.services.presentation_styles import get_style

        role_key = str(role or "").lower()
        style_labels = get_style(getattr(self, "_presentation_style", "consulting")).section_labels
        if role_key in style_labels:
            return style_labels[role_key].upper()
        role_labels = {
            "executive_summary": "EXECUTIVE SUMMARY",
            "problem": "DIAGNOSIS",
            "evidence": "EVIDENCE",
            "framework": "OPERATING MODEL",
            "reference": "REFERENCE SYSTEM",
            "implementation": "IMPLEMENTATION",
            "decision": "DECISION",
            "closing": "RECOMMENDATION",
        }
        role_key = str(role or "").lower()
        if role_key in role_labels:
            return role_labels[role_key]
        archetype_labels = {
            "executive_summary": "EXECUTIVE SUMMARY",
            "anti_patterns": "DIAGNOSIS",
            "dependency_map": "EVIDENCE",
            "chart": "EVIDENCE",
            "metric_chart": "EVIDENCE",
            "comparison_table": "EVIDENCE",
            "framework_cycle": "OPERATING MODEL",
            "code_panel": "REFERENCE SYSTEM",
            "table_reference": "REFERENCE SYSTEM",
            "checklist": "IMPLEMENTATION",
            "quote_sidebar": "DECISION",
            "closing_recommendation": "RECOMMENDATION",
        }
        return archetype_labels.get(self._normalize_archetype(archetype or ""), "ANALYSIS")

    def _pick_sections(self, sections: list[DocumentSection]) -> list[DocumentSection]:
        skipped = {"overview", "executive summary", "introduction", "background"}
        primary = [
            section
            for section in sections
            if section.level <= 2 and section.title.strip().lower() not in skipped
        ]
        return primary[:12] if primary else sections[:8]

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
        first_sentence = re.sub(r"^\s*Pattern:\s*", "", first_sentence, flags=re.IGNORECASE)
        # Prefer a real claim from the source over any template. Accept a slightly
        # wider window and a leading verb, so the title reads as a conclusion.
        words = first_sentence.split()
        if 5 <= len(words) <= 18 and self._reads_as_claim(first_sentence):
            return first_sentence.rstrip(".")[:110]
        base = self._clean_section_title(title)
        if not base:
            base = "this work"
        subject = base[0].lower() + base[1:] if base[:1].isupper() and base[1:2].islower() else base
        return self._themed_action_title(subject, f"{title} {content}".lower())[:110]

    def _reads_as_claim(self, sentence: str) -> bool:
        """A usable action title is a clause, not a fragment or a heading echo."""
        lowered = sentence.lower().strip()
        if not lowered or lowered.endswith(":"):
            return False
        if lowered.split()[0] in {"the", "a", "an", "this", "these", "section", "chapter"}:
            # Headings/fragments tend to start like this; only keep if a verb-ish
            # token follows soon (kept simple: presence of a common verb cue).
            return bool(re.search(r"\b(is|are|makes?|creates?|drives?|requires?|reduces?|"
                                  r"improves?|turns?|keeps?|gives?|prevents?|shifts?|"
                                  r"replaces?|breaks?|enables?)\b", lowered))
        return True

    def _themed_action_title(self, subject: str, theme_text: str) -> str:
        frames = [
            (("executive summary", "saturation", "labeling cost"),
             "Current benchmarks need harnesses that discover operational truth"),
            (("introduction", "static benchmark", "frontier model", "leaderboard"),
             "Static benchmarks need operational validity beyond leaderboards"),
            (("future directions", "data catalog", "confidence calibration"),
             "Data catalogs shape benchmark governance through confidence calibration"),
            (("conclusion", "closing remarks", "deployment", "real use cases"),
             "Build evaluation systems around real use cases"),
            (("harness-centric", "harness centric", "harness-centric view"),
             "Harness-centric design turns existing workflows into evaluation evidence"),
            (("synthetic benchmark", "synthetic data"),
             "Use source-grounded harnesses instead of synthetic benchmark shortcuts"),
            (("implicit ground truth", "validated truth", "ground truth discovery"),
             "Implicit ground truth discovery makes benchmark creation scalable"),
            (("model contract", "contract question", "contract must answer"),
             "Model contracts make evaluation expectations explicit"),
            (("harness interface", "benchmark harness"),
             "Harness interfaces turn contracts into repeatable tests"),
            (("benchmark", "evaluation", "ground truth"),
             f"Make {subject} measurable through the harness"),
            (("risk", "failure", "anti", "pitfall", "trap", "rot"),
             f"Eliminate {subject} before it undermines reliability"),
            (("spec", "acceptance", "criteria", "requirement", "authentication", "feature"),
             f"Specify {subject} before delegating it to the agent"),
            (("review", "plan", "verify", "evidence", "quality", "test"),
             f"Review {subject} before trusting the generated output"),
            (("cycle", "loop", "workflow", "phase", "cadence", "reset"),
             f"Run {subject} as a repeatable operating loop"),
            (("rule", "prompt", "markdown", "constraint", "standard"),
             f"Codify {subject} into rules the team can reuse"),
            (("memory", "context", "external brain", "documentation", "stale"),
             f"Keep {subject} current across context resets"),
        ]
        for cues, framed in frames:
            if any(cue in theme_text for cue in cues):
                return framed
        return f"Ground the next decision in {self._clean_title_subject(subject)}"

    def _clean_section_title(self, title: str) -> str:
        cleaned = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", title).strip()
        cleaned = cleaned.split(":", 1)[0].strip()
        cleaned = re.sub(r"[^A-Za-z0-9\s%-]", "", cleaned)
        return " ".join(cleaned.split())

    def _keyword_action_title(self, title: str, content: str) -> str | None:
        combined = f"{title} {content}".lower()
        rules = [
            (
                "why not simply generate synthetic benchmarks",
                "Synthetic benchmarks cannot substitute for validated operating evidence",
            ),
            (
                "implicit ground truth discovery",
                "Implicit ground truth discovery makes benchmark creation scalable",
            ),
            (
                "questions the model contract must answer",
                "Six contract questions keep every benchmark operational",
            ),
            (
                "the model contract",
                "Model contracts make evaluation expectations explicit",
            ),
            (
                "the harness interface",
                "Harness interfaces turn contracts into repeatable tests",
            ),
            (
                "conclusion and future directions",
                "Govern agent-assisted benchmark discovery before deployment",
            ),
            (
                "harness-centric view",
                "Harness-centric design turns existing workflows into evaluation evidence",
            ),
            (
                "bootstrapping strategies",
                "Bootstrapping strategies should map to reusable evidence patterns",
            ),
            (
                "architecture overview",
                "Five harness layers connect contracts, data, execution, and review",
            ),
            (
                "future directions",
                "Enterprise data catalogs make benchmark discovery scalable",
            ),
            (
                "closing remarks",
                "Make benchmark governance a managed operating capability",
            ),
            (
                "executive summary",
                "Current benchmarks need harnesses that discover operational truth",
            ),
            (
                "when and how to update",
                "Update memory after meaningful changes",
            ),
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
            (
                "accept-all reflex",
                "Review generated changes before accepting them",
            ),
        ]
        for keyword, action_title in rules:
            if keyword in combined:
                return action_title
        return None
