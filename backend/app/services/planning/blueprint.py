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
from app.services.presentation_styles import get_style


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
        archetype_sequence = self._archetype_sequence(target_slide_count, bundle)
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
        style = get_style(getattr(self, "_presentation_style", "consulting"))
        (label1, purpose1), (label2, purpose2), (label3, purpose3) = style.section_plan_labels
        section_plan = [
            {
                "label": label1,
                "start_slide": 1,
                "end_slide": min(thirds, target_slide_count),
                "purpose": purpose1,
            },
            {
                "label": label2,
                "start_slide": min(thirds + 1, target_slide_count),
                "end_slide": min(thirds * 2, target_slide_count),
                "purpose": purpose2,
            },
            {
                "label": label3,
                "start_slide": min(thirds * 2 + 1, target_slide_count),
                "end_slide": target_slide_count,
                "purpose": purpose3,
            },
        ]
        return DeckBlueprint(
            deck_title=title,
            audience=style.audience,
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
        # Length tiers give the UI control real range: concise=low, expanded=high.
        # Thinner sources cap lower so Expanded does not pad an empty deck.
        if not has_source:
            low, high = 5, 11
        elif source_rich:
            low, high = 7, 22
        else:
            low, high = 6, 16

        if length_strategy == "concise":
            target = low
        elif length_strategy == "expanded":
            target = high
        else:  # auto: a balanced middle of the range
            target = min(high, max(low, 12 if source_rich else 10 if has_source else 7))

        if quality_profile == "showcase" and has_source:
            target = min(high, target + 2)
        # Cap the toggle by how much distinct material the source actually has,
        # so Expanded does not pad a thin source with filler: roughly one slide
        # per section plus a structural slide and a bounded exhibit contribution.
        # Prompt-only decks are generative (uncapped); an explicit brief count
        # below is honored as-is — the user asked for an exact size.
        if has_source:
            supportable = section_count + 1 + min(len(bundle.tables) + len(bundle.metrics), 4)
            target = min(target, max(low, supportable))
        # An explicit count in the brief ("make a 6-slide deck", "20 slides")
        # overrides the toggle; clamped to a sane 3-30.
        match = re.search(r"\b(\d{1,2})\s+slides?\b", instructions.lower())
        if match:
            return max(3, min(30, int(match.group(1))))
        return min(target, high)

    def _archetype_sequence(
        self, target_slide_count: int, bundle: DocumentBundle | None = None
    ) -> list[str]:
        has_source = bool(
            bundle
            and (
                bundle.sections
                or bundle.tables
                or bundle.metrics
                or bundle.content_inventory
            )
        )
        has_tables = bool(bundle and bundle.tables)
        has_metrics = bool(bundle and bundle.metrics)
        has_inventory = bool(bundle and bundle.content_inventory)
        sequence = ["cover", "executive_summary"]
        if not has_source:
            candidates = [
                "comparison_table",
                "checklist",
                "quote_sidebar",
                "table_reference",
                "closing_recommendation",
            ]
        else:
            candidates = ["anti_patterns"]
            if has_tables:
                candidates.extend(["comparison_table", "table_reference"])
            elif has_inventory:
                candidates.extend(["table_reference", "callouts"])
            if has_metrics:
                candidates.append("metric_chart")
            candidates.extend(
                [
                    "checklist",
                    "quote_sidebar",
                    "callouts",
                    "icon_rows",
                    "comparison_table" if not has_tables else "table_reference",
                    "two_column",
                    "checklist",
                    "callouts",
                    "icon_rows",
                ]
            )
        for archetype in candidates:
            if len(sequence) >= max(target_slide_count - 1, 1):
                break
            sequence.append(archetype)
        while len(sequence) < max(target_slide_count - 1, 1):
            sequence.append(["comparison_table", "checklist", "table_reference"][len(sequence) % 3])
        if target_slide_count == 1:
            return ["cover"]
        return sequence[: target_slide_count - 1] + ["closing_recommendation"]

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
            "matrix_2x2": "decision",
            "callouts": "evidence",
            "icon_rows": "implementation",
            "two_column": "evidence",
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
        representative_sections = self._representative_source_sections(
            sections,
            target_slide_count,
        )
        for index in range(target_slide_count):
            section = representative_sections[
                min(index, len(representative_sections) - 1)
            ]
            source_map[str(index + 1)] = [self._source_ref(section, index)]
        return source_map

    def _representative_source_sections(
        self,
        sections: list[DocumentSection],
        target_slide_count: int,
    ) -> list[DocumentSection]:
        if target_slide_count <= 0:
            return []
        if len(sections) <= target_slide_count:
            return sections

        mandatory_indices = self._representative_document_start_indices(
            sections,
            target_slide_count,
        )
        selected: set[int] = set(mandatory_indices)
        for index in self._evenly_spaced_indices(len(sections), target_slide_count):
            selected.add(index)
            if len(selected) >= target_slide_count:
                break
        if len(selected) < target_slide_count:
            for index in range(len(sections)):
                selected.add(index)
                if len(selected) >= target_slide_count:
                    break
        return [sections[index] for index in sorted(selected)[:target_slide_count]]

    def _representative_document_start_indices(
        self,
        sections: list[DocumentSection],
        target_slide_count: int,
    ) -> list[int]:
        first_indices: list[int] = []
        seen_docs: set[str] = set()
        for index, section in enumerate(sections):
            doc_id = section.source_doc_id or "__unknown__"
            if doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)
            first_indices.append(index)
        if len(first_indices) <= 1:
            return []
        if len(first_indices) <= target_slide_count:
            return first_indices
        return [
            first_indices[index]
            for index in self._evenly_spaced_indices(
                len(first_indices),
                target_slide_count,
            )
        ]

    def _evenly_spaced_indices(self, total: int, count: int) -> list[int]:
        if total <= 0 or count <= 0:
            return []
        if count >= total:
            return list(range(total))
        if count == 1:
            return [0]
        return [
            round(index * (total - 1) / (count - 1))
            for index in range(count)
        ]

    def _representative_source_section(
        self,
        sections: list[DocumentSection],
        slide_index: int,
        target_slide_count: int,
    ) -> DocumentSection:
        if len(sections) <= target_slide_count or target_slide_count <= 1:
            return sections[min(slide_index, len(sections) - 1)]
        section_index = round(
            slide_index * (len(sections) - 1) / max(target_slide_count - 1, 1)
        )
        return sections[min(max(section_index, 0), len(sections) - 1)]

    def _source_ref(self, section: DocumentSection, index: int) -> str:
        if getattr(section, "source_id", ""):
            return section.source_id
        title = self._clean_section_title(section.title) or f"Section {index + 1}"
        source = section.source_doc_id or "source"
        return f"{source}:{title}"

    def _beat_message(self, archetype: str, title: str) -> str:
        messages = {
            "cover": f"Introduce {title} as a leadership decision.",
            "executive_summary": "Summarize the thesis, risks, and recommendation.",
            "anti_patterns": "Show the failure modes that put the decision at risk.",
            "dependency_map": "Map the dependencies that determine the outcome.",
            "framework_cycle": "Give leaders an operating cycle they can manage.",
            "section_divider": "Reset attention before the implementation half of the story.",
            "comparison_table": "Contrast the current state with the target state.",
            "code_panel": "Translate the recommendation into reusable operating rules.",
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
