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


class LLMPlanningMixin:
    def _plan_with_llm(
        self,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
        blueprint: DeckBlueprint,
        quality_profile: str,
    ) -> DeckSpec | None:
        if self.llm_client is None:
            return None
        source_packet = self._planner_source_packet(bundle, blueprint, quality_profile)
        metrics = [
            {"label": metric.label, "value": metric.value, "unit": metric.unit}
            for metric in bundle.metrics[:8]
        ]
        allowed_numbers = sorted(self._supported_numeric_tokens(bundle))[:50]
        user_prompt = (
            f"Create a {blueprint.target_slide_count}-slide consulting deck plan as strict JSON. "
            "Use the supplied blueprint as the deck plan, but improve wording and exhibit details from the source. "
            "Use distinct slide archetypes across the deck: cover, executive summary, section divider, "
            "comparison table, dependency map, framework/cycle, code/reference panel, checklist, "
            "anti-pattern cards, quote/sidebar, metric chart, table/reference, or closing recommendation. "
            "Avoid repeating the same slide type on adjacent slides. "
            "Use exactly this shape: "
            "{\"deck_title\":\"string\",\"audience\":\"string\",\"goal\":\"string\","
            "\"narrative_arc\":\"Situation -> Complication -> Resolution\","
            "\"blueprint\":{\"deck_title\":\"string\",\"audience\":\"string\",\"core_thesis\":\"string\","
            "\"target_slide_count\":8,\"story_beats\":[],\"section_plan\":[],"
            "\"archetype_sequence\":[],\"source_coverage_map\":{}},"
            "\"slides\":[{\"slide_number\":1,\"slide_type\":\"cover|executive_summary|content|chart|comparison|process|framework|reference|checklist|anti_pattern|quote|decision|closing\","
            "\"action_title\":\"complete sentence with a verb, 15 words or fewer\","
            "\"subheading\":\"evidence context\","
            "\"content_blocks\":[{\"type\":\"bullets|chart|table|callout|text\","
            "\"body\":[\"short evidence point\"],\"annotations\":[],\"callouts\":[]}],"
            "\"chart_spec\":null,\"sources\":[\"Uploaded source\"],"
            "\"archetype\":\"cover|section_divider|comparison_table|dependency_map|cycle|code_panel|checklist|quote_sidebar|anti_patterns|metric_chart|executive_summary|table_reference|closing_recommendation\","
            "\"narrative_role\":\"cover|executive_summary|problem|evidence|framework|implementation|reference|decision|closing\","
            "\"exhibit_spec\":{\"type\":\"comparison_table|dependency_map|cycle|checklist|code_panel|anti_patterns|quote_sidebar|metric_chart|reference_table|recommendation\"},"
            "\"diagram_spec\":null,"
            "\"design_intent\":\"short renderer guidance\","
            "\"source_refs\":[\"stable source section id or Uploaded source\"],"
            "\"speaker_notes\":\"short presenter note\",\"qa\":{\"consulting_status\":\"pending\","
            "\"visual_status\":\"pending\",\"issues\":[]}}]}. "
            "Every non-cover slide should have exactly one primary exhibit_spec. "
            "Comparison exhibits need clear columns and row labels. "
            "Dependency, cycle, checklist, code, anti-pattern, and quote exhibits need structured arrays, not prose blobs. "
            "For dependency_map and framework/cycle slides, include diagram_spec with kind dependency_flow or cycle when useful; otherwise use null. "
            "Action titles must avoid the word 'and'; split the idea instead. "
            "Only use numeric claims that appear in the allowed numeric tokens. "
            "If an unsupported numeric claim is necessary, write [source needed] beside it. "
            "Sources may only be Uploaded source or [source needed]. "
            "Do not invent document names, reports, URLs, people, companies, or dates as sources. "
            "Do not include markdown, comments, reasoning, or text outside the JSON. "
            f"Generation mode: {mode}. Quality profile: {quality_profile}. "
            f"Instructions: {instructions or 'No extra instructions.'}\n"
            f"Blueprint: {blueprint.model_dump()}\n"
            f"Allowed numeric tokens: {allowed_numbers or ['none']}\n"
            f"Source packet: {json.dumps(source_packet, ensure_ascii=True)}\n"
            f"Metrics: {json.dumps(metrics, ensure_ascii=True)}"
        )
        try:
            payload = self.llm_client.complete_json(
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=self._planner_max_tokens(
                    quality_profile, blueprint.target_slide_count
                ),
                temperature=0.2,
            )
        except Exception as exc:
            self._last_planning_error = f"{type(exc).__name__}: {exc}"
            return None
        if payload is None:
            self._last_planning_error = "model response did not contain a JSON object"
            return None
        payload = self._normalize_llm_payload(payload, blueprint)
        try:
            deck = DeckSpec.model_validate(payload)
            self._repair_model_titles(deck)
            return deck
        except Exception as exc:
            self._last_planning_error = f"DeckSpec validation failed: {exc}"
            return None

    def _normalize_llm_payload(
        self, payload: dict[str, Any], blueprint: DeckBlueprint
    ) -> dict[str, Any]:
        normalized = dict(payload)
        normalized["blueprint"] = blueprint.model_dump()
        return normalized

    def _planner_max_tokens(self, quality_profile: str, target_slide_count: int) -> int:
        if quality_profile == "fast":
            return max(12000, min(16000, target_slide_count * 1000))
        if quality_profile == "showcase":
            return max(32000, min(40000, target_slide_count * 2600))
        return max(24000, min(32000, target_slide_count * 1800))

    def _planner_source_packet(
        self,
        bundle: DocumentBundle,
        blueprint: DeckBlueprint,
        quality_profile: str,
    ) -> dict[str, Any]:
        section_limit = self._planner_section_limit(quality_profile, blueprint)
        char_limit = self._planner_section_char_limit(quality_profile)
        sections = [
            self._planner_section_payload(section, index, char_limit)
            for index, section in enumerate(bundle.sections[:section_limit])
        ]
        return {
            "metadata": bundle.metadata.model_dump(),
            "section_count": len(bundle.sections),
            "included_section_count": len(sections),
            "sections": sections,
            "content_inventory": bundle.content_inventory[:24],
            "tables": [
                {
                    "title": table.title or "Untitled table",
                    "headers": table.headers[:8],
                    "row_count": len(table.rows),
                    "sample_rows": table.rows[:3],
                    "source_doc_id": table.source_doc_id,
                }
                for table in bundle.tables[:6]
            ],
        }

    def _planner_section_limit(
        self, quality_profile: str, blueprint: DeckBlueprint
    ) -> int:
        if quality_profile == "fast":
            return min(10, max(8, blueprint.target_slide_count))
        if quality_profile == "showcase":
            return min(24, max(18, blueprint.target_slide_count + 6))
        return min(18, max(12, blueprint.target_slide_count + 3))

    def _planner_section_char_limit(self, quality_profile: str) -> int:
        if quality_profile == "fast":
            return 1200
        if quality_profile == "showcase":
            return 4000
        return 2200

    def _planner_section_payload(
        self,
        section: DocumentSection,
        index: int,
        char_limit: int,
    ) -> dict[str, Any]:
        content = self._source_excerpt(section.content, char_limit)
        return {
            "id": self._source_ref(section, index),
            "title": section.title,
            "level": section.level,
            "source_doc_id": section.source_doc_id,
            "word_count": len(section.content.split()),
            "content": content,
            "key_points": self._source_key_points(section.content),
        }

    def _source_excerpt(self, content: str, char_limit: int) -> str:
        cleaned = " ".join(str(content).split())
        if len(cleaned) <= char_limit:
            return cleaned
        excerpt = cleaned[:char_limit].rsplit(" ", 1)[0].rstrip(" ,;:")
        sentence_end = max(excerpt.rfind("."), excerpt.rfind("!"), excerpt.rfind("?"))
        if sentence_end >= max(240, int(char_limit * 0.55)):
            excerpt = excerpt[: sentence_end + 1]
        return self._repair_dangling_fragment(excerpt)

    def _source_key_points(self, content: str) -> list[str]:
        points: list[str] = []
        for item in self._to_bullets(content):
            phrase = self._phrase(item, "", limit=135)
            if phrase and phrase not in points:
                points.append(phrase)
            if len(points) >= 4:
                break
        return points

