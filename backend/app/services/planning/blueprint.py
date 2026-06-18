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


class BlueprintPlanningMixin:
    def _build_blueprint(
        self,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
        quality_profile: str,
        length_strategy: str,
    ) -> DeckBlueprint:
        title = bundle.metadata.title or self._title_from_instructions(instructions)
        target_slide_count = self._adaptive_slide_count(
            bundle,
            instructions,
            quality_profile=quality_profile,
            length_strategy=length_strategy,
        )
        archetype_sequence = self._archetype_sequence(target_slide_count)
        if not bundle.metrics:
            archetype_sequence = [
                "table_reference" if archetype == "metric_chart" else archetype
                for archetype in archetype_sequence
            ]
        roles = self._narrative_roles_for_sequence(archetype_sequence)
        source_map = self._source_coverage_map(bundle, target_slide_count)
        story_beats = [
            {
                "slide_number": index + 1,
                "narrative_role": roles[index],
                "archetype": archetype,
                "message": self._beat_message(archetype, title),
                "source_refs": source_map.get(str(index + 1), []),
            }
            for index, archetype in enumerate(archetype_sequence)
        ]
        thirds = max(target_slide_count // 3, 1)
        section_plan = [
            {
                "label": "Frame the decision",
                "start_slide": 1,
                "end_slide": min(thirds, target_slide_count),
                "purpose": "Establish thesis, stakes, and leadership question.",
            },
            {
                "label": "Prove the shift",
                "start_slide": min(thirds + 1, target_slide_count),
                "end_slide": min(thirds * 2, target_slide_count),
                "purpose": "Use evidence and exhibits to show why the old model breaks.",
            },
            {
                "label": "Commit to execution",
                "start_slide": min(thirds * 2 + 1, target_slide_count),
                "end_slide": target_slide_count,
                "purpose": "Translate the answer into operating choices and next steps.",
            },
        ]
        return DeckBlueprint(
            deck_title=title,
            audience="Engineering and product leaders",
            core_thesis=self._core_thesis(title, instructions, bundle),
            target_slide_count=target_slide_count,
            story_beats=story_beats,
            section_plan=section_plan,
            archetype_sequence=archetype_sequence,
            source_coverage_map=source_map,
        )

    def _adaptive_slide_count(
        self,
        bundle: DocumentBundle,
        instructions: str,
        quality_profile: str,
        length_strategy: str,
    ) -> int:
        section_count = len(bundle.sections)
        evidence_count = len(bundle.tables) + len(bundle.metrics) + len(bundle.content_inventory)
        word_count = sum(len(section.content.split()) for section in bundle.sections)
        has_source = self._has_uploaded_source_material(bundle)
        source_rich = section_count >= 8 or evidence_count >= 4 or word_count >= 2500
        if not has_source:
            low, high = 5, 8
        elif source_rich:
            low, high = 12, 16
        else:
            low, high = 8, 12

        if length_strategy == "concise":
            target = low
        elif length_strategy == "expanded":
            target = high
        else:
            target = min(high, max(low, 14 if source_rich else 9 if has_source else 6))

        if quality_profile == "showcase" and has_source:
            target = min(high, target + 2)
        if re.search(r"\b(\d{2,})\s+slides?\b", instructions.lower()):
            requested = int(re.search(r"\b(\d{2,})\s+slides?\b", instructions.lower()).group(1))
            return max(1, requested)
        return min(target, 16)

    def _archetype_sequence(self, target_slide_count: int) -> list[str]:
        source = [
            "cover",
            "executive_summary",
            "anti_patterns",
            "dependency_map",
            "framework_cycle",
            "section_divider",
            "comparison_table",
            "code_panel",
            "checklist",
            "quote_sidebar",
            "table_reference",
            "metric_chart",
            "code_panel",
            "comparison_table",
            "reference",
            "quote_sidebar",
            "code_panel",
        ]
        if target_slide_count <= 8:
            compact = [
                "cover",
                "executive_summary",
                "anti_patterns",
                "dependency_map",
                "framework_cycle",
                "checklist",
                "quote_sidebar",
                "closing_recommendation",
            ]
            return compact[:target_slide_count]
        return source[: max(target_slide_count - 1, 1)] + ["closing_recommendation"]

    def _narrative_roles_for_sequence(self, archetypes: list[str]) -> list[str]:
        role_map = {
            "cover": "cover",
            "executive_summary": "executive_summary",
            "anti_patterns": "problem",
            "dependency_map": "evidence",
            "framework_cycle": "framework",
            "section_divider": "framework",
            "comparison_table": "evidence",
            "code_panel": "reference",
            "checklist": "implementation",
            "quote_sidebar": "decision",
            "table_reference": "reference",
            "metric_chart": "evidence",
            "closing_recommendation": "closing",
            "reference": "reference",
        }
        roles = [role_map.get(archetype, "evidence") for archetype in archetypes]
        if roles and roles[-1] not in {"closing", "decision"}:
            roles[-1] = "closing"
        return roles

    def _source_coverage_map(
        self, bundle: DocumentBundle, target_slide_count: int
    ) -> dict[str, list[str]]:
        sections = bundle.sections or []
        source_map: dict[str, list[str]] = {}
        if not sections:
            return {str(index + 1): [SOURCE_NEEDED_LABEL] for index in range(target_slide_count)}
        for index in range(target_slide_count):
            section = sections[min(index, len(sections) - 1)]
            source_map[str(index + 1)] = [self._source_ref(section, index)]
        return source_map

    def _source_ref(self, section: DocumentSection, index: int) -> str:
        title = self._clean_section_title(section.title) or f"Section {index + 1}"
        source = section.source_doc_id or "source"
        return f"{source}:{title}"

    def _beat_message(self, archetype: str, title: str) -> str:
        messages = {
            "cover": f"Introduce {title} as a leadership decision.",
            "executive_summary": "Summarize the thesis, risks, and recommendation.",
            "anti_patterns": "Show the failure modes that make ad hoc work fragile.",
            "dependency_map": "Map the context dependencies that determine reliability.",
            "framework_cycle": "Give leaders an operating cycle they can manage.",
            "section_divider": "Reset attention before the implementation half of the story.",
            "comparison_table": "Contrast the old behavior with the target operating model.",
            "code_panel": "Translate principles into durable rules and reference artifacts.",
            "checklist": "Make the next steps executable.",
            "quote_sidebar": "Name the mental model shift for the audience.",
            "table_reference": "Provide a compact reference leaders can reuse.",
            "metric_chart": "Quantify the pressure or adoption signal when sourced.",
            "closing_recommendation": "End with a clear recommendation and decision ask.",
        }
        return messages.get(archetype, "Support the decision with a source-backed exhibit.")

    def _core_thesis(
        self, title: str, instructions: str, bundle: DocumentBundle
    ) -> str:
        if bundle.sections:
            return self._summarize(bundle.sections[0].content)
        return instructions or "Leaders should move from broad intent to a specific operating decision."

