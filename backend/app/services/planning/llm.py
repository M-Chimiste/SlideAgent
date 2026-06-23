# ruff: noqa: F401
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.document import DocumentBundle, DocumentMetric, DocumentSection
from app.models.generation import ContentBlock, DeckBlueprint, DeckSpec, GeneratedSlideSpec
from app.models.outline import SlideOutline
from app.models.planning import SourceCompression, StoryMap
from app.models.template import SlideSpec, TemplateProfile
from app.services.planning.constants import (
    PLANNER_SYSTEM_PROMPT,
    SOURCE_NEEDED_LABEL,
    UPLOADED_SOURCE_LABEL,
    build_planner_system_prompt,
)


class LLMPlanningMixin:
    def _plan_with_llm(
        self,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
        blueprint: DeckBlueprint,
        quality_profile: str,
        source_compression: SourceCompression | None = None,
        story_map: StoryMap | None = None,
    ) -> DeckSpec | None:
        if self.llm_client is None:
            return None
        source_packet = self._planner_source_packet(bundle, blueprint, quality_profile)
        metrics = [
            {
                "id": getattr(metric, "source_id", ""),
                "label": metric.label,
                "value": metric.value,
                "unit": metric.unit,
            }
            for metric in bundle.metrics[:8]
        ]
        allowed_numbers = sorted(self._supported_numeric_tokens(bundle))[:50]
        user_prompt = (
            f"Create a {blueprint.target_slide_count}-slide consulting deck plan as strict JSON. "
            "Use the supplied blueprint as the deck plan, but improve wording and exhibit details from the source. "
            f"The slides array must contain exactly {blueprint.target_slide_count} slide objects; "
            "do not return a sample, partial deck, or cover-only deck. "
            "Use distinct slide archetypes across the deck: cover, executive summary, section divider, "
            "comparison table, dependency map, framework/cycle, code/reference panel, checklist, "
            "anti-pattern cards, quote/sidebar, metric chart, table/reference, 2x2 matrix, "
            "callouts, icon rows, two column, or closing recommendation. "
            "Avoid repeating the same slide type on adjacent slides. "
            "Do not reuse the same dependency map, framework cycle, code panel, reference table, or metric block; "
            "when a topic recurs, change the exhibit family or focus on a different source section. "
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
            "\"archetype\":\"cover|section_divider|comparison_table|dependency_map|cycle|code_panel|checklist|quote_sidebar|anti_patterns|metric_chart|executive_summary|table_reference|matrix_2x2|callouts|icon_rows|two_column|closing_recommendation\","
            "\"narrative_role\":\"cover|executive_summary|problem|evidence|framework|implementation|reference|decision|closing\","
            "\"exhibit_spec\":{\"type\":\"comparison_table|dependency_map|cycle|checklist|code_panel|anti_patterns|quote_sidebar|metric_chart|reference_table|matrix_2x2|callouts|icon_rows|two_column|recommendation\"},"
            "\"diagram_spec\":null,"
            "\"design_intent\":\"short renderer guidance\","
            "\"source_refs\":[\"one of the source packet section ids, table ids, metric ids, or [source needed]\"],"
            "\"speaker_notes\":\"short presenter note\",\"qa\":{\"consulting_status\":\"pending\","
            "\"visual_status\":\"pending\",\"issues\":[]}}]}. "
            "Every non-cover slide should have exactly one primary exhibit_spec. "
            "Rewrite source headings and subtitles into grammatical action titles; do not concatenate them. "
            "Comparison exhibits need clear columns and row labels. "
            "Dependency, cycle, checklist, code, anti-pattern, and quote exhibits need structured arrays, not prose blobs. "
            "For dependency_map and framework/cycle slides, include diagram_spec with kind dependency_flow or cycle when useful; otherwise use null. "
            "Action titles must avoid the word 'and'; split the idea instead. "
            "Only use numeric claims that appear in the allowed numeric tokens. "
            "If an unsupported numeric claim is necessary, write [source needed] beside it. "
            "Use source_refs for exact source packet ids. Sources may only be Uploaded source, a short label copied from source_refs, or [source needed]. "
            "Do not invent document names, reports, URLs, people, companies, or dates as sources. "
            "Do not include markdown, comments, reasoning, or text outside the JSON. "
            f"Generation mode: {mode}. Quality profile: {quality_profile}. "
            f"Instructions: {instructions or 'No extra instructions.'}\n"
            f"Blueprint: {blueprint.model_dump()}\n"
            f"Story map: {story_map.model_dump() if story_map else {}}\n"
            f"Source compression: {source_compression.model_dump() if source_compression else {}}\n"
            f"Allowed numeric tokens: {allowed_numbers or ['none']}\n"
            f"Source packet: {json.dumps(source_packet, ensure_ascii=True)}\n"
            f"Metrics: {json.dumps(metrics, ensure_ascii=True)}"
        )
        system_prompt = build_planner_system_prompt(quality_profile)
        max_tokens = self._planner_max_tokens(
            quality_profile, blueprint.target_slide_count
        )
        try:
            payload = self.llm_client.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=0.2,
            )
        except Exception as exc:
            self._last_planning_error = f"{type(exc).__name__}: {exc}"
            return None
        if payload is None:
            self._last_planning_error = "model response did not contain a JSON object"
            return None
        require_exact_slide_count = self._requires_complete_llm_deck()
        deck = self._validate_deck_payload(
            payload,
            blueprint,
            require_exact_slide_count=require_exact_slide_count,
        )
        if deck is not None:
            return deck
        # One schema-repair retry: re-prompt with the validation error before
        # giving up and falling back to the deterministic deck.
        repair_prompt = (
            f"{user_prompt}\n\n"
            "Your previous response did not satisfy the required schema. "
            f"Validation error: {self._last_planning_error}. "
            "Return a corrected JSON object that matches the requested shape exactly. "
            "Keep every slide action_title a complete sentence with a verb, and emit no "
            "markdown, comments, or prose outside the JSON object."
        )
        try:
            payload = self.llm_client.complete_json(
                system_prompt=system_prompt,
                user_prompt=repair_prompt,
                max_tokens=max_tokens,
                temperature=0,
            )
        except Exception as exc:
            self._last_planning_error = f"{type(exc).__name__}: {exc}"
            return None
        if payload is None:
            self._last_planning_error = (
                "model repair response did not contain a JSON object"
            )
            return None
        return self._validate_deck_payload(
            payload,
            blueprint,
            require_exact_slide_count=require_exact_slide_count,
        )

    def _validate_deck_payload(
        self,
        payload: dict[str, Any],
        blueprint: DeckBlueprint,
        require_exact_slide_count: bool = True,
    ) -> DeckSpec | None:
        payload = self._normalize_llm_payload(payload, blueprint)
        try:
            deck = DeckSpec.model_validate(payload)
        except Exception as exc:
            self._last_planning_error = f"DeckSpec validation failed: {exc}"
            return None
        if require_exact_slide_count and len(deck.slides) != blueprint.target_slide_count:
            self._last_planning_error = (
                f"Deck must contain exactly {blueprint.target_slide_count} slides; "
                f"got {len(deck.slides)}."
            )
            return None
        self._repair_model_titles(deck)
        return deck

    def _requires_complete_llm_deck(self) -> bool:
        client = self.llm_client
        if client is None:
            return False
        if getattr(client, "require_exact_slide_count", False):
            return True
        module = client.__class__.__module__
        if module.startswith("app.clients."):
            return True
        model = str(getattr(client, "model", "") or "").lower()
        return bool(model)

    def _normalize_llm_payload(
        self, payload: dict[str, Any], blueprint: DeckBlueprint
    ) -> dict[str, Any]:
        normalized = dict(payload)
        normalized["blueprint"] = blueprint.model_dump()
        return normalized

    def _planner_max_tokens(self, quality_profile: str, target_slide_count: int) -> int:
        if quality_profile == "fast":
            return max(6000, min(9000, target_slide_count * 800))
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
        detailed_sections = self._planner_detailed_sections(
            bundle,
            blueprint,
            section_limit,
        )
        sections = [
            self._planner_section_payload(section, index, char_limit)
            for index, section in enumerate(detailed_sections)
        ]
        document_outline = self._planner_document_outline(bundle, quality_profile)
        source_index = self._planner_source_index(bundle, sections, document_outline)
        return {
            "metadata": bundle.metadata.model_dump(),
            "section_count": len(bundle.sections),
            "included_section_count": len(sections),
            "document_outline": document_outline,
            "sections": sections,
            "content_inventory": bundle.content_inventory[:24],
            "tables": [
                {
                    "id": getattr(table, "source_id", ""),
                    "title": table.title or "Untitled table",
                    "headers": table.headers[:8],
                    "row_count": len(table.rows),
                    "sample_rows": table.rows[:3],
                    "source_doc_id": table.source_doc_id,
                }
                for table in bundle.tables[:6]
            ],
            "source_index": source_index,
        }

    def _planner_detailed_sections(
        self,
        bundle: DocumentBundle,
        blueprint: DeckBlueprint,
        section_limit: int,
    ) -> list[DocumentSection]:
        selected: list[DocumentSection] = []
        seen: set[str] = set()

        def add(section: DocumentSection | None) -> None:
            if section is None:
                return
            key = (
                getattr(section, "source_id", "")
                or f"{section.source_doc_id}:{section.title}"
            )
            if key in seen:
                return
            seen.add(key)
            selected.append(section)

        for slide_number in sorted(
            blueprint.source_coverage_map,
            key=lambda value: int(value) if str(value).isdigit() else 9999,
        ):
            for source_ref in blueprint.source_coverage_map.get(slide_number, []):
                add(self._section_for_source_ref(str(source_ref), bundle))
                if len(selected) >= section_limit:
                    return selected

        for section in self._planner_outline_sections(bundle.sections, section_limit):
            add(section)
            if len(selected) >= section_limit:
                return selected

        for section in bundle.sections:
            add(section)
            if len(selected) >= section_limit:
                break
        return selected

    def _planner_document_outline(
        self,
        bundle: DocumentBundle,
        quality_profile: str,
    ) -> dict[str, Any]:
        summary_limit = self._planner_outline_summary_limit(quality_profile)
        outline_sections = self._planner_outline_sections(
            bundle.sections,
            self._planner_outline_section_budget(quality_profile),
        )
        sections = [
            {
                "id": self._source_ref(section, index),
                "title": section.title,
                "level": section.level,
                "source_doc_id": section.source_doc_id,
                "word_count": len(section.content.split()),
                "summary": self._source_excerpt(section.content, summary_limit),
                "key_points": self._source_key_points(section.content)[:2],
            }
            for index, section in enumerate(outline_sections)
        ]
        return {
            "section_count": len(bundle.sections),
            "included_section_count": len(sections),
            "omitted_section_count": max(0, len(bundle.sections) - len(sections)),
            "coverage": "full" if len(sections) == len(bundle.sections) else "representative",
            "documents": self._planner_document_manifest(bundle),
            "sections": sections,
        }

    def _planner_outline_sections(
        self,
        sections: list[DocumentSection],
        budget: int,
    ) -> list[DocumentSection]:
        return self._representative_source_sections(sections, budget)

    def _planner_document_manifest(self, bundle: DocumentBundle) -> list[dict[str, Any]]:
        docs: dict[str, dict[str, Any]] = {}
        filenames = self._planner_filenames_by_doc_id(bundle)
        for section in bundle.sections:
            doc_id = section.source_doc_id or "__unknown__"
            entry = docs.setdefault(
                doc_id,
                {
                    "source_doc_id": doc_id,
                    "filename": filenames.get(doc_id, doc_id),
                    "section_count": 0,
                    "word_count": 0,
                    "first_section": section.title,
                    "last_section": section.title,
                },
            )
            entry["section_count"] += 1
            entry["word_count"] += len(section.content.split())
            entry["last_section"] = section.title
        return list(docs.values())

    def _planner_filenames_by_doc_id(self, bundle: DocumentBundle) -> dict[str, str]:
        filenames: dict[str, str] = {}
        for entry in bundle.source_index.values():
            doc_id = entry.get("source_doc_id")
            filename = entry.get("filename")
            if doc_id and filename:
                filenames.setdefault(doc_id, filename)
        return filenames

    def _planner_source_index(
        self,
        bundle: DocumentBundle,
        sections: list[dict[str, Any]],
        document_outline: dict[str, Any],
    ) -> dict[str, dict[str, str]]:
        included_ids = {
            str(section.get("id"))
            for section in sections
            if section.get("id")
        }
        included_ids.update(
            str(section.get("id"))
            for section in document_outline.get("sections", [])
            if section.get("id")
        )
        included_ids.update(
            getattr(table, "source_id", "")
            for table in bundle.tables[:6]
            if getattr(table, "source_id", "")
        )
        included_ids.update(
            getattr(metric, "source_id", "")
            for metric in bundle.metrics[:8]
            if getattr(metric, "source_id", "")
        )
        return {
            source_id: entry
            for source_id, entry in bundle.source_index.items()
            if source_id in included_ids
        }

    def _planner_outline_section_budget(self, quality_profile: str) -> int:
        if quality_profile == "fast":
            return 40
        if quality_profile == "showcase":
            return 120
        return 80

    def _planner_outline_summary_limit(self, quality_profile: str) -> int:
        if quality_profile == "fast":
            return 180
        if quality_profile == "showcase":
            return 360
        return 260

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
