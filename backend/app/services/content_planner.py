import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.models.document import DocumentBundle, DocumentMetric, DocumentSection
from app.models.generation import (
    ContentBlock,
    DeckBlueprint,
    DeckSpec,
    GeneratedSlideSpec,
    GenerationMode,
)
from app.models.outline import SlideOutline
from app.models.template import SlideSpec, TemplateProfile
from app.services.consulting_qa import ConsultingQA


PLANNER_SYSTEM_PROMPT = """You are a senior engagement manager creating consulting-quality decks.
Follow the style guide rules: SCR/Pyramid structure, action titles, one message per slide,
MECE grouping, source discipline, and concise evidence. Return strict JSON only."""

UPLOADED_SOURCE_LABEL = "Uploaded source"
SOURCE_NEEDED_LABEL = "[source needed]"


class ContentPlanner:
    def __init__(self, llm_client: Optional[OpenAICompatibleClient] = None) -> None:
        self.llm_client = llm_client
        self._last_planning_error: str | None = None
        self.qa = ConsultingQA()
        self.layouts = [
            "cover",
            "executive_summary",
            "section_divider",
            "comparison_table",
            "icon_rows",
            "two_column",
            "callouts",
            "chart",
            "icon_grid",
            "process",
            "quote_sidebar",
            "framework_cycle",
            "dependency_map",
            "checklist",
            "code_panel",
            "anti_patterns",
            "table_reference",
            "closing_recommendation",
        ]

    def plan(
        self,
        template: TemplateProfile,
        bundle: DocumentBundle,
        instructions: str = "",
        generation_mode: str | None = None,
        quality_profile: str = "balanced",
        length_strategy: str = "auto",
    ) -> tuple[list[SlideOutline], list[dict[str, Any]]]:
        mode = generation_mode or template.type
        if mode in {GenerationMode.freeform.value, GenerationMode.brand.value}:
            deck, warnings = self._plan_generated_deck(
                template,
                bundle,
                instructions,
                mode,
                quality_profile=quality_profile,
                length_strategy=length_strategy,
            )
            return self._deck_to_outlines(deck, bundle.job_id, mode), warnings

        warnings: list[dict[str, Any]] = []
        outlines: list[SlideOutline] = []
        last_layout: str | None = None
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

    def _plan_generated_deck(
        self,
        template: TemplateProfile,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
        quality_profile: str = "balanced",
        length_strategy: str = "auto",
    ) -> tuple[DeckSpec, list[dict[str, Any]]]:
        warnings: list[dict[str, Any]] = []
        blueprint = self._build_blueprint(
            bundle,
            instructions,
            mode,
            quality_profile=quality_profile,
            length_strategy=length_strategy,
        )
        self._last_planning_error = None
        deck = self._plan_with_llm(
            bundle,
            instructions,
            mode,
            blueprint=blueprint,
            quality_profile=quality_profile,
        )
        if deck is None:
            message = (
                "LLM planner was not configured; used deterministic fallback."
                if self.llm_client is None
                else "LLM planning was unavailable or malformed; used deterministic fallback."
            )
            if self._last_planning_error:
                message = f"{message} Reason: {self._last_planning_error}"
            warnings.append(
                {
                    "slide_index": None,
                    "field": "llm_planning",
                    "message": message,
                }
            )
            deck = self._fallback_deck(bundle, instructions, mode, blueprint)
        if deck.blueprint is None:
            deck.blueprint = blueprint
        self._enrich_deck_specs(deck, blueprint, bundle)
        self._repair_model_titles(deck)
        self._repair_repeated_action_titles(deck)
        warnings.extend(self._normalize_source_labels(deck, bundle))
        warnings.extend(self._ground_numeric_claims(deck, bundle))
        deck, qa_warnings = self.qa.inspect(deck)
        warnings.extend(qa_warnings)
        return deck, warnings

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

    def _fallback_deck(
        self,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
        blueprint: DeckBlueprint,
    ) -> DeckSpec:
        title = bundle.metadata.title or self._title_from_instructions(instructions)
        source_label = UPLOADED_SOURCE_LABEL if bundle.sections else SOURCE_NEEDED_LABEL
        sections = self._pick_sections(bundle.sections)
        if not sections:
            sections = self._sections_from_instructions(instructions)
        metrics = self._pick_metrics(bundle.metrics, count=3)
        roles = self._narrative_roles_for_sequence(blueprint.archetype_sequence)
        slides: list[GeneratedSlideSpec] = []
        for index, archetype in enumerate(blueprint.archetype_sequence):
            role = roles[index] if index < len(roles) else "evidence"
            section = self._section_for_blueprint_slot(index, sections, blueprint)
            slide = self._fallback_slide_for_archetype(
                index=index,
                archetype=archetype,
                role=role,
                title=title,
                section=section,
                sections=sections,
                metrics=metrics,
                source_label=source_label,
                blueprint=blueprint,
            )
            slides.append(slide)
        return DeckSpec(
            deck_title=title,
            audience="Executive audience",
            goal=instructions or "Create an executive-ready recommendation deck.",
            narrative_arc="Situation -> Complication -> Resolution",
            slides=slides,
            blueprint=blueprint,
        )

    def _section_for_blueprint_slot(
        self,
        index: int,
        sections: list[DocumentSection],
        blueprint: DeckBlueprint,
    ) -> DocumentSection:
        fallback = sections[min(max(index - 1, 0), len(sections) - 1)]
        source_refs = blueprint.source_coverage_map.get(str(index + 1), [])
        for source_ref in source_refs:
            title = str(source_ref).split(":", 1)[-1]
            normalized_title = self._clean_section_title(title).casefold()
            if not normalized_title:
                continue
            for section in sections:
                if self._clean_section_title(section.title).casefold() == normalized_title:
                    return section
        return fallback

    def _fallback_slide_for_archetype(
        self,
        index: int,
        archetype: str,
        role: str,
        title: str,
        section: DocumentSection,
        sections: list[DocumentSection],
        metrics: list[dict[str, Any]],
        source_label: str,
        blueprint: DeckBlueprint,
    ) -> GeneratedSlideSpec:
        exhibit_spec = self._exhibit_for_archetype(archetype, section, sections, metrics)
        content_blocks = self._content_blocks_from_exhibit(archetype, exhibit_spec, section)
        action_title = self._fallback_action_title(archetype, title, section)
        source_refs = blueprint.source_coverage_map.get(str(index + 1), [source_label])
        return GeneratedSlideSpec(
            slide_number=index + 1,
            slide_type=self._slide_type_for_archetype(archetype),
            action_title=action_title,
            subheading=self._subheading_for_archetype(archetype, section),
            content_blocks=content_blocks,
            chart_spec={"type": "bar", "metrics": metrics[:5]}
            if archetype == "metric_chart" and metrics
            else None,
            sources=[source_label],
            speaker_notes=self._beat_message(archetype, title),
            archetype=archetype,
            narrative_role=role,
            exhibit_spec=exhibit_spec,
            diagram_spec=self._diagram_spec_for_exhibit(
                archetype,
                exhibit_spec,
                action_title,
            ),
            design_intent=self._design_intent(archetype),
            source_refs=source_refs,
        )

    def _exhibit_for_archetype(
        self,
        archetype: str,
        section: DocumentSection,
        sections: list[DocumentSection],
        metrics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        bullets = self._section_phrases(section, 4)
        if archetype == "cover":
            return {
                "type": "cover",
                "thesis": self._phrase(section.content, "A managed operating model improves AI work."),
                "signals": [self._clean_section_title(item.title) for item in sections[:3]],
            }
        if archetype == "executive_summary":
            return {
                "type": "executive_summary",
                "messages": [
                    {"label": "Situation", "text": bullets[0]},
                    {
                        "label": "Complication",
                        "text": bullets[1] if len(bullets) > 1 else "AI speed exposes review gaps.",
                    },
                    {
                        "label": "Resolution",
                        "text": bullets[2]
                        if len(bullets) > 2
                        else "Move from intent to explicit owners, evidence, and review gates.",
                    },
                ],
                "proof_points": self._executive_summary_proof_points(metrics),
            }
        if archetype == "anti_patterns":
            pattern_bullets = bullets[:3]
            while len(pattern_bullets) < 3:
                pattern_bullets.append(self._default_pattern(len(pattern_bullets)))
            return {
                "type": "anti_patterns",
                "patterns": [
                    {
                        "name": self._anti_pattern_name(pattern_bullets[idx]),
                        "symptom": pattern_bullets[idx],
                        "consequence": [
                            "Execution quality degrades as assumptions stay implicit.",
                            "Teams spend review time resolving avoidable ambiguity.",
                            "Decisions become hard to trace when conditions change.",
                        ][idx],
                        "better_behavior": [
                            "Make the operating context explicit.",
                            "Require source-backed acceptance criteria.",
                            "Record decisions and next actions in the workflow.",
                        ][idx],
                    }
                    for idx in range(3)
                ],
            }
        if archetype == "dependency_map":
            middle = [
                self._clean_section_title(item.title) or f"Context {idx + 1}"
                for idx, item in enumerate(sections[:3])
            ]
            while len(middle) < 3:
                middle.append(["Decision context", "Operating rules", "Review evidence"][len(middle)])
            return {
                "type": "dependency_map",
                "left_node": "Source evidence",
                "middle_nodes": middle[:3],
                "right_outcome": "Confident decision",
                "connector_labels": ["feeds", "constrains", "verifies"],
            }
        if archetype == "framework_cycle":
            return {
                "type": "cycle",
                "center_label": "Operating loop",
                "steps": [
                    {"label": "Frame", "description": "Write the decision and success criteria."},
                    {"label": "Ground", "description": "Load the source context and constraints."},
                    {"label": "Build", "description": "Draft the work against the evidence."},
                    {"label": "Review", "description": "Check output against the decision standard."},
                    {"label": "Update", "description": "Record what changed before the next cycle."},
                ],
                "reset_label": "Update the shared record before the next task.",
            }
        if archetype == "comparison_table":
            return {
                "type": "comparison_table",
                "columns": ["Dimension", "Current model", "Target model"],
                "rows": [
                    {
                        "label": "Context",
                        "values": ["Fragmented inputs", "Shared source of truth"],
                        "indicator": "green",
                    },
                    {
                        "label": "Control",
                        "values": ["Implicit judgment", "Explicit operating rules"],
                        "indicator": "green",
                    },
                    {
                        "label": "Review",
                        "values": ["Late cleanup", "Built-in quality gates"],
                        "indicator": "green",
                    },
                ],
            }
        if archetype in {"code_panel", "reference"}:
            return self._code_panel_spec_for_section(section)
        if archetype == "checklist":
            return {
                "type": "checklist",
                "items": [
                    {"action": "Name the decision and success criteria", "owner": "Sponsor", "timing": "Now"},
                    {"action": "Assign evidence and review owners", "owner": "Lead", "timing": "Next"},
                    {"action": "Pilot the operating loop on one workflow", "owner": "Team", "timing": "Pilot"},
                    {"action": "Codify lessons before scaling", "owner": "Owner", "timing": "Scale"},
                ],
            }
        if archetype == "quote_sidebar":
            return {
                "type": "quote_sidebar",
                "key_idea": "The work shifts from isolated output to managed operating discipline.",
                "supporting_points": bullets[:3],
                "quote": "Make the standard explicit before asking the team to move faster.",
            }
        if archetype == "table_reference":
            return self._reference_spec_for_section(section, bullets)
        if archetype == "metric_chart":
            return {"type": "metric_chart", "metrics": metrics[:5]}
        if archetype == "closing_recommendation":
            return {
                "type": "recommendation",
                "recommendation": self._phrase(
                    section.content,
                    "Adopt the target operating model as the default way of working.",
                ),
                "next_steps": [
                    "Pick one source-rich workflow.",
                    "Define owners, evidence, and review gates.",
                    "Use lessons from the pilot before expanding.",
                ],
                "decision_ask": "Approve a time-boxed pilot with named owners.",
            }
        return {"type": "text_exhibit", "points": bullets}

    def _code_panel_spec_for_section(self, section: DocumentSection) -> dict[str, Any]:
        section_text = f"{section.title} {section.content}".lower()
        section_title = section.title.lower()
        if any(token in section_title for token in ("update", "stale", "reset")):
            return {
                "type": "code_panel",
                "title": "memory-bank/update-protocol.md",
                "lines": [
                    "Refresh activeContext.md after changes.",
                    "Record decisions before the next session.",
                    "Sync progress.md when status changes.",
                    "Load latest memory files before restart.",
                ],
            }
        if any(token in section_text for token in ("employee", "product manager", "manager")):
            return {
                "type": "code_panel",
                "title": "agent-brief.md",
                "lines": [
                    "State the outcome before assigning work.",
                    "Describe constraints the agent must preserve.",
                    "Name review gates before implementation.",
                    "Close the loop with recorded decisions.",
                ],
            }
        if any(token in section_text for token in ("cycle", "loop", "phase", "workflow")):
            return {
                "type": "code_panel",
                "title": "agentic-cycle.md",
                "lines": [
                    "Frame the request with an explicit outcome.",
                    "Prime the agent with memory and constraints.",
                    "Generate bounded changes from the spec.",
                    "Review output before updating memory.",
                ],
            }
        if any(token in section_text for token in ("update", "stale", "reset")):
            return {
                "type": "code_panel",
                "title": "memory-bank/update-protocol.md",
                "lines": [
                    "Refresh activeContext.md after meaningful changes.",
                    "Record decisions before starting the next session.",
                    "Sync progress.md when status or risk changes.",
                    "Restart with the latest memory files loaded.",
                ],
            }
        if any(token in section_text for token in ("markdown", "specification", "rules file", "rules files")):
            return {
                "type": "code_panel",
                "title": "rules.md",
                "lines": [
                    "Write acceptance criteria before generation.",
                    "Keep constraints in markdown beside code.",
                    "Treat examples as executable review cases.",
                    "Revise rules after QA findings.",
                ],
            }
        if any(token in section_text for token in ("memory bank", "external brain", "persistent context")):
            return {
                "type": "code_panel",
                "title": "memory-bank/README.md",
                "lines": [
                    "Create core files before the first agent run.",
                    "Load projectbrief.md and activeContext.md at session start.",
                    "Persist decisions as memory updates.",
                    "Use progress.md to resume work safely.",
                ],
            }
        return {
            "type": "code_panel",
            "title": "operating-rules.md",
            "lines": [
                "Define the decision before drafting.",
                "Keep source context attached to the work.",
                "Require evidence before approval.",
                "Record accepted decisions after review.",
            ],
        }

    def _reference_spec_for_section(
        self, section: DocumentSection, bullets: list[str]
    ) -> dict[str, Any]:
        if self._is_memory_text(f"{section.title} {section.content}"):
            return self._memory_bank_reference_spec()
        reference_rows = [
            [
                "Decision owner",
                "Names who can approve the recommendation",
                "Owner or mandate changes",
            ],
            [
                "Evidence base",
                "Keeps the sources used for the slide traceable",
                "New data or source challenge",
            ],
            [
                "Operating rule",
                "Turns the recommendation into repeatable behavior",
                "Process or risk changes",
            ],
            [
                "Review gate",
                "Defines the quality check before wider rollout",
                "Pilot or launch milestone",
            ],
        ]
        if bullets:
            reference_rows = [
                [self._short_label(bullet), bullet, "When conditions change"]
                for bullet in bullets[:4]
            ]
        return {
            "type": "reference_table",
            "columns": ["Artifact", "Purpose", "Update trigger"],
            "rows": reference_rows,
        }

    def _content_blocks_from_exhibit(
        self, archetype: str, exhibit_spec: dict[str, Any], section: DocumentSection
    ) -> list[ContentBlock]:
        if archetype in {"comparison_table", "table_reference"}:
            columns = exhibit_spec.get("columns", [])
            rows = exhibit_spec.get("rows", [])
            body = [columns] if isinstance(columns, list) else []
            for row in rows:
                if isinstance(row, dict):
                    body.append([row.get("label", ""), *row.get("values", [])])
                elif isinstance(row, list):
                    body.append(row)
            return [ContentBlock(type="table", body=body)]
        if archetype == "metric_chart":
            return [ContentBlock(type="chart", body=exhibit_spec.get("metrics", []))]
        if archetype == "executive_summary":
            messages = exhibit_spec.get("messages", [])
            return [
                ContentBlock(
                    type="bullets",
                    body=[
                        item.get("text", "")
                        for item in messages
                        if isinstance(item, dict) and item.get("text")
                    ],
                )
            ]
        if archetype == "checklist":
            return [
                ContentBlock(
                    type="table",
                    body=[
                        ["Action", "Owner", "Timing"],
                        *[
                            [item.get("action", ""), item.get("owner", ""), item.get("timing", "")]
                            for item in exhibit_spec.get("items", [])
                            if isinstance(item, dict)
                        ],
                    ],
                )
            ]
        if archetype == "anti_patterns":
            return [
                ContentBlock(
                    type="bullets",
                    body=[
                        f"{item.get('name')}: {item.get('better_behavior')}"
                        for item in exhibit_spec.get("patterns", [])
                        if isinstance(item, dict)
                    ],
                )
            ]
        if archetype in {"code_panel", "reference"}:
            return [ContentBlock(type="bullets", body=exhibit_spec.get("lines", []))]
        if archetype == "quote_sidebar":
            return [ContentBlock(type="bullets", body=exhibit_spec.get("supporting_points", []))]
        return [ContentBlock(type="bullets", body=self._section_phrases(section, 4))]

    def _fallback_action_title(
        self, archetype: str, title: str, section: DocumentSection
    ) -> str:
        title_phrase = title.lower()
        section_text = f"{section.title} {section.content}".lower()
        keyword_title = self._keyword_action_title(section.title, section.content)
        if keyword_title and archetype not in {"cover", "section_divider"}:
            return self._truncate_title(keyword_title)
        if archetype == "dependency_map":
            if any(token in section_text for token in ("update", "stale", "protocol")):
                return "Map context updates to preserve workflow reliability"
            if self._is_memory_text(section_text):
                return "Use memory systems to make AI work reproducible"
        if archetype == "comparison_table":
            if any(token in section_text for token in ("cycle", "loop", "phase")):
                return "Contrast the operating loop with ad hoc execution"
            if any(token in section_text for token in ("chatbot", "employee", "manager")):
                return "Contrast chatbot prompting with managed AI teammates"
        if archetype in {"code_panel", "reference"}:
            section_title = section.title.lower()
            if any(token in section_title for token in ("update", "stale", "reset")):
                return "Codify memory updates before context goes stale"
            if any(token in section_text for token in ("agent", "ai", "chatbot")) and any(
                token in section_text for token in ("employee", "product manager", "manager")
            ):
                return "Define agent briefs before assigning AI work"
            if any(token in section_text for token in ("cycle", "loop", "phase", "workflow")):
                return "Codify the operating cycle as reusable rules"
            if any(token in section_text for token in ("markdown", "specification", "rules file")):
                return "Codify markdown rules where teams already work"
            if self._is_memory_text(section_text):
                return "Codify memory-bank rules where teams already work"
        titles = {
            "cover": f"Translate {title_phrase} into an executive decision",
            "executive_summary": "Focus the story on decision, risk, and recommended action",
            "anti_patterns": "Stop three failure modes before execution scales",
            "dependency_map": "Map the dependencies that determine the outcome",
            "framework_cycle": "Run the work through a reviewable operating cycle",
            "section_divider": "Shift from diagnosis to execution",
            "comparison_table": "Compare the current model with the target operating model",
            "code_panel": "Codify operating rules where teams already work",
            "checklist": "Adopt the transition through a short operating checklist",
            "quote_sidebar": "Reframe the mindset shift behind the recommendation",
            "table_reference": "Standardize responsibilities across the operating workflow",
            "metric_chart": "Quantify the signal before making the decision",
            "closing_recommendation": "Commit to the next operating decision",
        }
        if archetype in titles:
            return self._truncate_title(titles[archetype])
        return self._action_title(section.title, section.content)

    def _slide_type_for_archetype(self, archetype: str) -> str:
        mapping = {
            "cover": "cover",
            "executive_summary": "executive_summary",
            "anti_patterns": "anti_pattern",
            "dependency_map": "framework",
            "framework_cycle": "framework",
            "section_divider": "section",
            "comparison_table": "comparison",
            "code_panel": "reference",
            "reference": "reference",
            "checklist": "checklist",
            "quote_sidebar": "quote",
            "table_reference": "reference",
            "metric_chart": "chart",
            "closing_recommendation": "closing",
        }
        return mapping.get(archetype, "content")

    def _subheading_for_archetype(self, archetype: str, section: DocumentSection) -> str:
        if archetype == "cover":
            return "A practical operating model for reliable AI-assisted software work"
        if archetype == "section_divider":
            return "The second half of the story turns diagnosis into repeatable execution."
        return f"Evidence from {section.title}"

    def _design_intent(self, archetype: str) -> str:
        intents = {
            "cover": "dark editorial cover with a clear thesis",
            "executive_summary": "three-part situation-complication-resolution summary",
            "anti_patterns": "named failure-mode cards with concise consequences",
            "dependency_map": "left-to-right dependency flow with thick connectors",
            "framework_cycle": "directional cycle around a center operating model",
            "section_divider": "dark editorial divider",
            "comparison_table": "compact comparison table with clear axes",
            "code_panel": "compact reference block with slide-specific rules",
            "reference": "compact reference block with slide-specific rules",
            "checklist": "quick-start reference checklist",
            "quote_sidebar": "quote sidebar visually tied to supporting points",
            "table_reference": "compact reference table",
            "metric_chart": "simple metric chart using sourced values",
            "closing_recommendation": "closing recommendation with decision ask",
        }
        return intents.get(archetype, "structured exhibit with concise body text")

    def _section_phrases(self, section: DocumentSection, count: int) -> list[str]:
        phrases = [
            self._phrase(line, "")
            for line in self._to_bullets(section.content)
            if self._phrase(line, "")
        ]
        if not phrases:
            phrases = [self._phrase(section.content or section.title, section.title)]
        while len(phrases) < count:
            phrases.append(
                [
                    "Preserve context before work begins.",
                    "Make review criteria explicit before execution.",
                    "Keep decisions traceable across handoffs.",
                    "Turn lessons into durable operating rules.",
                ][len(phrases) % 4]
            )
        return phrases[:count]

    def _phrase(self, text: str, fallback: str, limit: int = 105) -> str:
        cleaned = self._clean_generated_visual_placeholder(text or fallback)
        cleaned = re.split(r"[.!?]\s+", cleaned)[0] if cleaned else fallback
        cleaned = " ".join(cleaned.split())
        cleaned = self._repair_dangling_fragment(cleaned)
        if len(cleaned) <= limit:
            return cleaned
        return self._repair_dangling_fragment(
            cleaned[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
        )

    def _repair_dangling_fragment(self, text: str) -> str:
        cleaned = " ".join(str(text).split()).strip(" -:;")
        if not cleaned:
            return ""
        clause_match = re.search(
            r",\s+(?:which|that|where|while|because|as)\b[^,.;:]*$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if clause_match and self._ends_with_dangling_token(cleaned[clause_match.start() :]):
            cleaned = cleaned[: clause_match.start()].rstrip(" ,;:")
        words = cleaned.split()
        while len(words) > 4 and self._is_dangling_token(words[-1]):
            words.pop()
        cleaned = " ".join(words).rstrip(" ,;:")
        return cleaned

    def _ends_with_dangling_token(self, text: str) -> bool:
        words = str(text).split()
        return bool(words and self._is_dangling_token(words[-1]))

    def _is_dangling_token(self, token: str) -> bool:
        cleaned = re.sub(r"[^A-Za-z]", "", token).lower()
        return cleaned in {
            "a",
            "an",
            "the",
            "as",
            "of",
            "to",
            "for",
            "from",
            "with",
            "without",
            "into",
            "onto",
            "in",
            "on",
            "at",
            "by",
            "and",
            "or",
            "but",
            "which",
            "that",
            "where",
            "when",
            "while",
            "because",
            "than",
        }

    def _truncate_title(self, title: str) -> str:
        words = title.rstrip(".").split()
        if len(words) <= 15:
            return " ".join(words)
        return " ".join(words[:15]).rstrip(".,;:")

    def _default_pattern(self, index: int) -> str:
        return [
            "Important context disappears between handoffs.",
            "Recommendations look plausible before evidence is checked.",
            "Teams cannot reproduce the reasoning behind decisions.",
        ][index]

    def _enrich_deck_specs(
        self, deck: DeckSpec, blueprint: DeckBlueprint, bundle: DocumentBundle
    ) -> None:
        sequence = blueprint.archetype_sequence or []
        roles = self._narrative_roles_for_sequence(sequence)
        source_metrics = self._pick_metrics(bundle.metrics, count=4)
        for index, slide in enumerate(deck.slides):
            if not slide.archetype:
                slide.archetype = self._archetype_from_layout(self._layout_for_slide(slide))
            slide.archetype = self._normalize_archetype(slide.archetype)
            if not slide.narrative_role:
                slide.narrative_role = (
                    self._role_for_archetype(slide.archetype)
                    or (roles[index] if index < len(roles) else "evidence")
                )
            if not slide.source_refs:
                slide.source_refs = blueprint.source_coverage_map.get(
                    str(index + 1),
                    slide.sources or [UPLOADED_SOURCE_LABEL],
                )
            if not slide.design_intent:
                slide.design_intent = self._design_intent(slide.archetype)
            if not slide.exhibit_spec or self._exhibit_is_incomplete(slide):
                slide.exhibit_spec = self._derive_exhibit_spec(slide)
            self._remove_placeholder_text(slide)
            self._repair_underfilled_exhibit(slide, source_metrics)
            self._sync_diagram_spec(slide)
            self._sync_content_blocks_from_exhibit(slide)

    def _normalize_archetype(self, archetype: str) -> str:
        normalized = archetype.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "cycle": "framework_cycle",
            "process": "framework_cycle",
            "reference_table": "table_reference",
            "table": "comparison_table",
            "comparison": "comparison_table",
            "metric": "metric_chart",
            "chart": "metric_chart",
            "anti_pattern": "anti_patterns",
            "quote": "quote_sidebar",
            "closing": "closing_recommendation",
            "recommendation": "closing_recommendation",
        }
        return aliases.get(normalized, normalized or "two_column")

    def _archetype_from_layout(self, layout: str) -> str:
        mapping = {
            "chart": "metric_chart",
            "process": "table_reference",
            "two_column": "two_column",
            "icon_grid": "two_column",
            "icon_rows": "two_column",
        }
        return mapping.get(layout, layout)

    def _role_for_archetype(self, archetype: str) -> str | None:
        role_map = dict(
            zip(
                self._archetype_sequence(16),
                self._narrative_roles_for_sequence(self._archetype_sequence(16)),
            )
        )
        return role_map.get(archetype)

    def _derive_exhibit_spec(self, slide: GeneratedSlideSpec) -> dict[str, Any]:
        bullets = self._body_to_bullets(slide)
        archetype = self._normalize_archetype(slide.archetype or "")
        if archetype == "comparison_table":
            table_rows = self._first_table_block(slide)
            if table_rows:
                columns = [str(cell) for cell in table_rows[0]]
                rows = [
                    {"label": str(row[0]), "values": [str(cell) for cell in row[1:]]}
                    for row in table_rows[1:5]
                    if row
                ]
                return {"type": "comparison_table", "columns": columns, "rows": rows}
            return {
                "type": "comparison_table",
                "columns": ["Dimension", "Current state", "Target state"],
                "rows": self._fallback_comparison_rows(slide, bullets),
            }
        if archetype == "dependency_map":
            middle = bullets[:3] or ["Context", "Rules", "Review"]
            return {
                "type": "dependency_map",
                "left_node": "Source context",
                "middle_nodes": middle[:3],
                "right_outcome": slide.action_title,
                "connector_labels": ["feeds", "guides", "validates"],
            }
        if archetype == "framework_cycle":
            steps = bullets[:5] or ["Frame", "Prime", "Generate", "Review", "Persist"]
            return {
                "type": "cycle",
                "center_label": "Operating loop",
                "steps": [{"label": self._short_label(step), "description": step} for step in steps],
            }
        if archetype == "checklist":
            checklist_items = bullets[:5]
            defaults = [
                "Name the decision and success criteria",
                "Define acceptance criteria",
                "Assign evidence and review owners",
                "Codify lessons after review",
            ]
            while len(checklist_items) < 3:
                checklist_items.append(defaults[len(checklist_items)])
            return {
                "type": "checklist",
                "items": [
                    {"action": bullet, "owner": "Owner", "timing": "Next"}
                    for bullet in checklist_items
                ],
            }
        if archetype == "code_panel":
            return {"type": "code_panel", "title": "rules.md", "lines": bullets[:5]}
        if archetype == "anti_patterns":
            pattern_bullets = bullets[:4]
            while len(pattern_bullets) < 3:
                pattern_bullets.append(self._default_pattern(len(pattern_bullets)))
            better_behaviors = [
                "Persist context in a shared record.",
                "Verify claims against the source.",
                "Record decisions beside the workflow.",
                "Refresh the record after material changes.",
            ]
            return {
                "type": "anti_patterns",
                "patterns": [
                    {
                        "name": self._anti_pattern_name(bullet),
                        "symptom": bullet,
                        "consequence": "The team loses reliability.",
                        "better_behavior": better_behaviors[idx % len(better_behaviors)],
                    }
                    for idx, bullet in enumerate(pattern_bullets[:4])
                ],
            }
        if archetype == "quote_sidebar":
            return {
                "type": "quote_sidebar",
                "key_idea": slide.subheading or slide.action_title,
                "supporting_points": bullets[:4],
            }
        if archetype == "table_reference":
            if self._is_memory_reference_intent(slide):
                return self._memory_bank_reference_spec()
            return {
                "type": "reference_table",
                "columns": ["Item", "Implication"],
                "rows": [[self._short_label(bullet), bullet] for bullet in bullets[:5]],
            }
        if archetype == "metric_chart":
            return {"type": "metric_chart", "metrics": self._metrics_from_slide(slide)}
        if archetype == "closing_recommendation":
            return {
                "type": "recommendation",
                "recommendation": slide.action_title,
                "next_steps": bullets[:3],
                "decision_ask": "Confirm ownership and timing.",
            }
        return {"type": archetype or "text_exhibit", "points": bullets}

    def _sync_diagram_spec(self, slide: GeneratedSlideSpec) -> None:
        archetype = self._normalize_archetype(slide.archetype or "")
        if isinstance(slide.diagram_spec, dict):
            slide.diagram_spec = self._clean_placeholders_in_value(slide.diagram_spec)
        if archetype not in {"dependency_map", "framework_cycle"}:
            return
        if not isinstance(slide.exhibit_spec, dict):
            return
        if self._diagram_spec_is_usable(archetype, slide.diagram_spec):
            return
        slide.diagram_spec = self._diagram_spec_for_exhibit(
            archetype,
            slide.exhibit_spec,
            slide.action_title,
        )

    def _diagram_spec_is_usable(self, archetype: str, diagram_spec) -> bool:
        if not isinstance(diagram_spec, dict):
            return False
        kind = str(diagram_spec.get("kind") or "").lower()
        if archetype == "dependency_map":
            nodes = diagram_spec.get("middle_nodes") or diagram_spec.get("nodes")
            return kind == "dependency_flow" and isinstance(nodes, list) and len(nodes) >= 2
        if archetype == "framework_cycle":
            steps = diagram_spec.get("steps")
            return kind == "cycle" and isinstance(steps, list) and len(steps) >= 4
        return False

    def _diagram_spec_for_exhibit(
        self,
        archetype: str,
        exhibit_spec: dict[str, Any],
        fallback_title: str,
    ) -> dict[str, Any] | None:
        normalized = self._normalize_archetype(archetype)
        if normalized == "dependency_map":
            middle_nodes = [
                self._clean_generated_visual_placeholder(str(item))
                for item in exhibit_spec.get("middle_nodes", [])
                if self._clean_generated_visual_placeholder(str(item))
            ][:4]
            while len(middle_nodes) < 2:
                middle_nodes.append(["Context", "Rules", "Review"][len(middle_nodes)])
            return {
                "kind": "dependency_flow",
                "title": fallback_title,
                "left_node": self._clean_generated_visual_placeholder(
                    str(exhibit_spec.get("left_node") or "Source context")
                ),
                "middle_nodes": middle_nodes,
                "right_outcome": self._clean_generated_visual_placeholder(
                    str(exhibit_spec.get("right_outcome") or fallback_title)
                ),
                "connector_labels": [
                    self._clean_generated_visual_placeholder(str(item))
                    for item in exhibit_spec.get("connector_labels", [])
                    if self._clean_generated_visual_placeholder(str(item))
                ][:4],
            }
        if normalized == "framework_cycle":
            raw_steps = exhibit_spec.get("steps")
            steps = raw_steps if isinstance(raw_steps, list) else []
            labels = [
                self._clean_generated_visual_placeholder(
                    str(step.get("label") or step.get("description") or "")
                )
                for step in steps
                if isinstance(step, dict)
                and self._clean_generated_visual_placeholder(
                    str(step.get("label") or step.get("description") or "")
                )
            ][:6]
            while len(labels) < 4:
                labels.append(["Frame", "Ground", "Build", "Review", "Update", "Reset"][len(labels)])
            return {
                "kind": "cycle",
                "title": fallback_title,
                "center_label": self._clean_generated_visual_placeholder(
                    str(exhibit_spec.get("center_label") or "Operating loop")
                ),
                "steps": [{"label": label} for label in labels[:6]],
            }
        return None

    def _fallback_comparison_rows(
        self, slide: GeneratedSlideSpec, bullets: list[str]
    ) -> list[dict[str, Any]]:
        intent = self._slide_intent_text(slide)
        if "chatbot" in intent or "employee" in intent or "ai teammate" in intent:
            return [
                {
                    "label": "Context",
                    "values": ["Conversation history", "Persistent external memory"],
                },
                {
                    "label": "Specification",
                    "values": ["Implicit prompt intent", "Explicit acceptance criteria"],
                },
                {
                    "label": "Review",
                    "values": ["Manual cleanup", "Evidence-backed QA gates"],
                },
            ]
        labels = ["Context", "Control", "Review"]
        defaults = [
            ["Fragmented inputs", "Shared source of truth"],
            ["Implicit judgment", "Explicit operating rules"],
            ["Late cleanup", "Built-in quality gates"],
        ]
        rows: list[dict[str, Any]] = []
        for idx, label in enumerate(labels):
            target = bullets[idx] if idx < len(bullets) else defaults[idx][1]
            rows.append({"label": label, "values": [defaults[idx][0], target]})
        return rows

    def _memory_bank_reference_spec(self) -> dict[str, Any]:
        return {
            "type": "reference_table",
            "columns": ["File", "Role", "Update trigger"],
            "rows": [
                [
                    "projectbrief.md",
                    "Defines purpose, scope, and success criteria",
                    "Scope or objective changes",
                ],
                [
                    "productContext.md",
                    "Captures user problem, experience goals, and value",
                    "User or market insight changes",
                ],
                [
                    "systemPatterns.md",
                    "Records architecture, patterns, and constraints",
                    "Design or integration changes",
                ],
                [
                    "activeContext.md",
                    "Tracks current focus, decisions, and next actions",
                    "Each meaningful work session",
                ],
                [
                    "progress.md",
                    "Shows what is done, open, and at risk",
                    "Milestone or status change",
                ],
            ],
        }

    def _is_memory_reference_intent(self, slide: GeneratedSlideSpec) -> bool:
        intent = self._slide_intent_text(slide)
        return self._is_memory_text(intent)

    def _is_memory_text(self, text: str) -> bool:
        intent = text.lower()
        return any(
            token in intent
            for token in (
                "memory bank",
                "core file",
                "persistent context",
                "external brain",
                "hierarchical context",
                "root-level",
            )
        )

    def _is_generic_reference_table(self, exhibit: dict[str, Any]) -> bool:
        columns = [str(column).strip().lower() for column in exhibit.get("columns", [])]
        row_text = " ".join(
            " ".join(str(value).lower() for value in row)
            for row in exhibit.get("rows", [])
            if isinstance(row, list)
        )
        if len(columns) <= 2:
            return True
        if columns[:2] in (["item", "implication"], ["artifact", "purpose"]):
            return True
        return "projectbrief.md" not in row_text and "activecontext.md" not in row_text

    def _exhibit_is_incomplete(self, slide: GeneratedSlideSpec) -> bool:
        exhibit = slide.exhibit_spec
        if not isinstance(exhibit, dict):
            return True
        exhibit_type = str(exhibit.get("type") or "").lower().replace("-", "_")
        checks = {
            "comparison_table": lambda item: not self._comparison_exhibit_is_sparse(item),
            "dependency_map": lambda item: len(item.get("middle_nodes", [])) >= 2,
            "cycle": lambda item: len(item.get("steps", [])) >= 3,
            "checklist": lambda item: len(item.get("items", [])) >= 3,
            "code_panel": lambda item: bool(item.get("lines")),
            "anti_patterns": lambda item: not self._anti_patterns_exhibit_is_sparse(item),
            "quote_sidebar": lambda item: bool(item.get("supporting_points") or item.get("key_idea")),
            "reference_table": lambda item: bool(item.get("columns") and item.get("rows")),
            "recommendation": lambda item: bool(item.get("next_steps") or item.get("recommendation")),
            "metric_chart": lambda item: bool(item.get("metrics")),
        }
        checker = checks.get(exhibit_type)
        if checker and not checker(exhibit):
            return True
        if exhibit_type == "reference_table" and self._is_memory_reference_intent(slide):
            return self._is_generic_reference_table(exhibit)
        return False

    def _repair_underfilled_exhibit(
        self, slide: GeneratedSlideSpec, source_metrics: list[dict[str, Any]]
    ) -> None:
        if not isinstance(slide.exhibit_spec, dict):
            return
        archetype = self._normalize_archetype(slide.archetype or "")
        if archetype == "comparison_table" and self._comparison_exhibit_is_sparse(
            slide.exhibit_spec
        ):
            slide.exhibit_spec = {
                "type": "comparison_table",
                "columns": ["Dimension", "Current state", "Target state"],
                "rows": self._fallback_comparison_rows(slide, self._body_to_bullets(slide)),
            }
        if archetype == "metric_chart":
            existing_metrics = self._normalized_metric_dicts(
                slide.exhibit_spec.get("metrics", [])
            )
            enriched_metrics = self._merge_metric_dicts(existing_metrics, source_metrics)
            if source_metrics and len(enriched_metrics) < min(3, len(source_metrics)):
                enriched_metrics = source_metrics
            if enriched_metrics:
                slide.exhibit_spec = {
                    **slide.exhibit_spec,
                    "type": "metric_chart",
                    "metrics": enriched_metrics[:4],
                }
        if archetype == "anti_patterns" and self._anti_patterns_exhibit_is_sparse(
            slide.exhibit_spec
        ):
            slide.exhibit_spec = self._derive_exhibit_spec(slide)
        if archetype == "executive_summary":
            proof_points = slide.exhibit_spec.get("proof_points", [])
            if source_metrics and (
                not isinstance(proof_points, list) or len(proof_points) < 2
            ):
                slide.exhibit_spec = {
                    **slide.exhibit_spec,
                    "type": "executive_summary",
                    "proof_points": self._executive_summary_proof_points(source_metrics),
                }

    def _sync_content_blocks_from_exhibit(self, slide: GeneratedSlideSpec) -> None:
        if not isinstance(slide.exhibit_spec, dict):
            return
        archetype = self._normalize_archetype(slide.archetype or "")
        if archetype == "comparison_table":
            columns = slide.exhibit_spec.get("columns", [])
            rows = slide.exhibit_spec.get("rows", [])
            body = [columns] if isinstance(columns, list) else []
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict):
                    body.append([row.get("label", ""), *row.get("values", [])])
                elif isinstance(row, list):
                    body.append(row)
            if len(body) >= 2:
                slide.content_blocks = [ContentBlock(type="table", body=body)]
        if archetype == "metric_chart":
            metrics = slide.exhibit_spec.get("metrics", [])
            if isinstance(metrics, list) and metrics:
                slide.content_blocks = [ContentBlock(type="chart", body=metrics)]

    def _comparison_exhibit_is_sparse(self, exhibit: dict[str, Any]) -> bool:
        columns = exhibit.get("columns", [])
        rows = exhibit.get("rows", [])
        if not isinstance(columns, list) or len(columns) < 3:
            return True
        normalized_columns = [self._display_cell_text(column) for column in columns[:3]]
        if any(not self._has_meaningful_cell_text(column) for column in normalized_columns):
            return True
        if not isinstance(rows, list):
            return True
        usable_rows = 0
        for row in rows:
            cells = self._comparison_row_cells(row)
            if len(cells) < 3:
                continue
            if all(self._has_meaningful_cell_text(cell) for cell in cells[:3]):
                usable_rows += 1
        return usable_rows < 3

    def _anti_patterns_exhibit_is_sparse(self, exhibit: dict[str, Any]) -> bool:
        patterns = exhibit.get("patterns", [])
        if not isinstance(patterns, list):
            return True
        usable = 0
        for pattern in patterns:
            if not isinstance(pattern, dict):
                continue
            if (
                self._has_meaningful_cell_text(pattern.get("name", ""))
                and self._has_meaningful_cell_text(pattern.get("symptom", ""))
                and self._has_meaningful_cell_text(pattern.get("better_behavior", ""))
            ):
                usable += 1
        return usable < 3

    def _comparison_row_cells(self, row: Any) -> list[str]:
        if isinstance(row, dict):
            values = row.get("values", [])
            if not isinstance(values, list):
                values = [values]
            return [self._display_cell_text(row.get("label", ""))] + [
                self._display_cell_text(value) for value in values
            ]
        if isinstance(row, list):
            return [self._display_cell_text(value) for value in row]
        return []

    def _display_cell_text(self, value: Any) -> str:
        if isinstance(value, dict):
            for key in ("text", "label", "name", "value", "title"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return ""
        return str(value or "").strip()

    def _has_meaningful_cell_text(self, value: Any) -> bool:
        text = self._clean_generated_visual_placeholder(self._display_cell_text(value))
        text = re.sub(r"\[source needed\]", "", text, flags=re.IGNORECASE).strip()
        if not text:
            return False
        if text.lower() in {"n/a", "na", "none", "tbd", "todo", "placeholder"}:
            return False
        return bool(re.search(r"[A-Za-z0-9]", text))

    def _normalized_metric_dicts(self, metrics: Any) -> list[dict[str, Any]]:
        if not isinstance(metrics, list):
            return []
        normalized: list[dict[str, Any]] = []
        for metric in metrics:
            if not isinstance(metric, dict) or not self._is_chartable_metric_dict(metric):
                continue
            value = metric.get("value")
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            normalized.append(
                {
                    "label": self._truncate_at_word(str(metric.get("label") or "Metric"), 42)
                    .removesuffix("..."),
                    "value": int(numeric_value)
                    if numeric_value.is_integer()
                    else numeric_value,
                    "unit": self._normalize_metric_unit(str(metric.get("unit") or "")),
                }
            )
        normalized.sort(key=self._metric_dict_priority)
        return normalized

    def _merge_metric_dicts(
        self, primary: list[dict[str, Any]], secondary: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, float, str]] = set()
        for metric in [*primary, *secondary]:
            value = metric.get("value")
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            unit = self._normalize_metric_unit(str(metric.get("unit") or "")) or ""
            key = (round(numeric_value, 4), unit)
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    "label": self._truncate_at_word(str(metric.get("label") or "Metric"), 42)
                    .removesuffix("..."),
                    "value": int(numeric_value)
                    if numeric_value.is_integer()
                    else numeric_value,
                    "unit": unit or None,
                }
            )
        merged.sort(key=self._metric_dict_priority)
        return merged

    def _executive_summary_proof_points(
        self, metrics: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        normalized = self._normalized_metric_dicts(metrics)[:3]
        if normalized:
            return [
                {
                    "label": metric["label"],
                    "value": metric["value"],
                    "unit": metric.get("unit"),
                    "detail": self._metric_detail(metric),
                }
                for metric in normalized
            ]
        return [
            {
                "label": "Context",
                "value": "1",
                "unit": None,
                "detail": "Persistent memory makes AI work reproducible.",
            },
            {
                "label": "Rules",
                "value": "2",
                "unit": None,
                "detail": "Acceptance criteria constrain generation.",
            },
            {
                "label": "Review",
                "value": "3",
                "unit": None,
                "detail": "Evidence gates protect delivery quality.",
            },
        ]

    def _metric_detail(self, metric: dict[str, Any]) -> str:
        label = str(metric.get("label") or "Sourced signal")
        unit = self._normalize_metric_unit(str(metric.get("unit") or ""))
        if unit == "%":
            return f"{label} show adoption pressure."
        if unit == "tokens":
            return f"{label} signals context capacity pressure."
        return f"{label} is a sourced signal."

    def _first_table_block(self, slide: GeneratedSlideSpec) -> list[list[Any]]:
        for block in slide.content_blocks:
            if block.type != "table":
                continue
            rows = [item for item in block.body if isinstance(item, list)]
            if rows:
                return rows
        return []

    def _remove_placeholder_text(self, slide: GeneratedSlideSpec) -> None:
        for block in slide.content_blocks:
            block.body = [
                self._clean_generated_visual_placeholder(str(item))
                if isinstance(item, str)
                else item
                for item in block.body
            ]
        if isinstance(slide.exhibit_spec, dict):
            slide.exhibit_spec = self._clean_placeholders_in_value(slide.exhibit_spec)

    def _clean_placeholders_in_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._clean_generated_visual_placeholder(value)
        if isinstance(value, list):
            return [self._clean_placeholders_in_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: self._clean_placeholders_in_value(item)
                for key, item in value.items()
            }
        return value

    def _short_label(self, text: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9\s-]", "", str(text)).strip()
        words = cleaned.split()
        return " ".join(words[:3]) or "Item"

    def _anti_pattern_name(self, text: str) -> str:
        before_colon = str(text).split(":", 1)[0]
        cleaned = re.sub(r"[^A-Za-z0-9\s-]", "", before_colon).strip()
        words = cleaned.split()
        if len(words) >= 2:
            return " ".join(words[:3])
        return self._short_label(text)

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

    def _repair_model_titles(self, deck: DeckSpec) -> None:
        for slide in deck.slides:
            title = " ".join(slide.action_title.split())
            title = title.rstrip(".")
            title = self._strip_meta_title_text(title)
            compound = re.match(
                r"^(Identify|Recognize|Address|Explain|Describe)\s+(.+?)\s+and\s+(.+?)\s+as\s+(.+)$",
                title,
                flags=re.IGNORECASE,
            )
            if compound:
                title = f"{compound.group(1)} {compound.group(4)}"
            compound_action = re.match(
                r"^(Mitigate|Reduce|Address|Eliminate|Manage|Prevent|Quantify)\s+"
                r"(.+?)\s+and\s+(.+)$",
                title,
                flags=re.IGNORECASE,
            )
            if compound_action:
                title = f"{compound_action.group(1)} {compound_action.group(3)}"
            if " and " in title.lower():
                title = title.split(" and ", 1)[0]
            if len(title.split()) > 16:
                title = " ".join(title.split()[:16]).rstrip(".,;:")
            title = self._repair_weak_action_title(slide, title)
            slide.action_title = self._clean_action_title_candidate(title)

    def _repair_repeated_action_titles(self, deck: DeckSpec) -> None:
        seen: set[str] = set()
        for slide in deck.slides:
            key = slide.action_title.strip().casefold()
            if key not in seen:
                seen.add(key)
                continue
            replacement = self._unique_action_title(slide, seen)
            slide.action_title = self._truncate_title(replacement)
            seen.add(slide.action_title.casefold())

    def _unique_action_title(
        self, slide: GeneratedSlideSpec, seen: set[str]
    ) -> str:
        for candidate in self._action_title_candidates(slide):
            replacement = self._clean_action_title_candidate(candidate)
            if replacement and replacement.casefold() not in seen:
                return replacement
        archetype = self._normalize_archetype(slide.archetype or "")
        role = (slide.narrative_role or archetype or "decision").replace("_", " ")
        return self._clean_action_title_candidate(
            f"Translate the {role} into a clear operating decision"
        )

    def _action_title_candidates(self, slide: GeneratedSlideSpec) -> list[str]:
        candidates = self._alternate_action_titles(slide)
        candidates.extend(
            [
                self._repair_weak_action_title(slide, self._distinct_action_title(slide)),
                self._distinct_action_title(slide),
            ]
        )
        return candidates

    def _clean_action_title_candidate(self, title: str) -> str:
        cleaned = self._strip_meta_title_text(title).strip()
        cleaned = cleaned.replace("...", " ").replace("…", " ")
        cleaned = " ".join(cleaned.split())
        if " and " in cleaned.lower():
            cleaned = cleaned.split(" and ", 1)[0]
        return self._truncate_title(cleaned)

    def _alternate_action_titles(self, slide: GeneratedSlideSpec) -> list[str]:
        archetype = self._normalize_archetype(slide.archetype or "")
        intent = self._slide_intent_text(slide)
        context = self._slide_context_label(slide)
        candidates: list[str] = []
        if any(token in intent for token in ("acceptance criteria", "specification")):
            candidates.extend(self._acceptance_criteria_titles(archetype))
        if any(
            token in intent
            for token in ("context window", "token", "finite", "limit", "memory")
        ):
            candidates.extend(
                self._context_limit_titles(archetype)
            )
        if self._is_memory_text(intent):
            candidates.extend(self._memory_action_titles(archetype))
        candidates.extend(
            {
                "checklist": [
                    "Convert next steps into an executable transition checklist",
                    "Make implementation gates explicit before work starts",
                ],
                "code_panel": [
                    "Codify the operating rule where teams already work",
                    "Translate source evidence into reusable team rules",
                ],
                "table_reference": [
                    "Standardize core artifacts for persistent context",
                    "Standardize recurring decisions as a reusable reference",
                ],
                "comparison_table": [
                    "Compare the current model with the target operating model",
                    "Show why managed execution beats ad hoc prompting",
                ],
                "dependency_map": [
                    "Map the dependencies that determine reliable output",
                    "Expose context handoffs before the workflow breaks",
                ],
                "framework_cycle": [
                    "Run the operating cycle with explicit review gates",
                    "Reset the workflow before context begins to drift",
                ],
                "section_divider": [
                    "Shift From Prompting to Management",
                    "Shift From Diagnosis to Execution",
                ],
                "quote_sidebar": [
                    "Reframe the operating model around persistent context",
                    "Translate the mindset shift into management behavior",
                ],
                "closing_recommendation": [
                    "Commit to the recommendation with named ownership",
                    "Move from pilot enthusiasm to an operating mandate",
                ],
                "metric_chart": [
                    "Quantify context-window limits before relying on model memory",
                    "Use context limits to justify persistent memory",
                ],
                "chart": [
                    "Quantify context-window limits before relying on model memory",
                    "Use context limits to justify persistent memory",
                ],
            }.get(archetype, [])
        )
        if context:
            candidates.append(
                f"Translate {context.lower()} into a distinct operating decision"
            )
        candidates.append("Translate source evidence into an explicit operating decision")
        return candidates

    def _acceptance_criteria_titles(self, archetype: str) -> list[str]:
        by_archetype = {
            "checklist": [
                "Convert acceptance criteria into pre-execution review gates",
                "Use acceptance criteria to make work reviewable before execution",
            ],
            "code_panel": [
                "Codify acceptance criteria as reusable team rules",
                "Translate specifications into rules the agent can follow",
            ],
            "table_reference": [
                "Standardize acceptance criteria as a reusable reference",
            ],
            "comparison_table": [
                "Compare implicit prompts with explicit acceptance criteria",
            ],
        }
        return by_archetype.get(
            archetype,
            [
                "Define acceptance criteria before execution begins",
                "Use acceptance criteria to make work reviewable before execution",
                "Translate specifications into rules the agent can follow",
            ],
        )

    def _memory_action_titles(self, archetype: str) -> list[str]:
        by_archetype = {
            "checklist": [
                "Implement memory-bank upkeep through a short checklist",
                "Keep context current through explicit update gates",
            ],
            "code_panel": [
                "Codify memory-bank upkeep where teams already work",
                "Translate memory rules into reusable team instructions",
            ],
            "table_reference": [
                "Standardize memory-bank files around update triggers",
            ],
            "dependency_map": [
                "Map memory handoffs before context begins to decay",
            ],
        }
        return by_archetype.get(
            archetype,
            ["Use memory bank files so teams inherit context"],
        )

    def _context_limit_titles(self, archetype: str) -> list[str]:
        by_archetype = {
            "chart": [
                "Quantify context-window limits before relying on model memory",
                "Use context limits to justify persistent memory",
            ],
            "metric_chart": [
                "Quantify context-window limits before relying on model memory",
                "Use context limits to justify persistent memory",
            ],
            "comparison_table": [
                "Compare finite model context with persistent team memory",
            ],
            "code_panel": [
                "Codify memory rules before model context expires",
            ],
        }
        return by_archetype.get(
            archetype,
            ["Use finite context limits to justify persistent memory"],
        )

    def _distinct_action_title(self, slide: GeneratedSlideSpec) -> str:
        archetype = self._normalize_archetype(slide.archetype or "")
        intent = self._slide_intent_text(slide)
        context = self._slide_context_label(slide)
        if archetype in {"code_panel", "reference"}:
            if any(token in intent for token in ("cycle", "loop", "phase", "workflow")):
                return "Codify the operating cycle as reusable rules"
            if any(token in intent for token in ("update", "stale", "reset")):
                return "Codify memory updates before context goes stale"
            if any(token in intent for token in ("markdown", "specification", "rules file")):
                return "Codify markdown rules where teams already work"
            if context:
                return f"Codify {context.lower()} into reusable operating rules"
            return "Codify the next reference artifact for the team"
        if archetype == "dependency_map":
            if any(token in intent for token in ("update", "stale", "protocol")):
                return "Map context updates to preserve workflow reliability"
            if context:
                return f"Map {context.lower()} into context dependencies"
        if archetype == "comparison_table":
            if any(token in intent for token in ("cycle", "loop", "phase")):
                return "Contrast the operating loop with ad hoc execution"
            if context:
                return f"Contrast {context.lower()} with the target operating model"
        if archetype == "section_divider":
            return self._section_divider_title(intent)
        if archetype == "table_reference":
            if self._is_memory_text(intent):
                return "Standardize Memory Bank files as a reusable reference"
            if context:
                return f"Standardize {context.lower()} as a reusable reference"
        if archetype in {"chart", "metric_chart"}:
            if any(
                token in intent
                for token in ("context window", "token", "finite", "limit", "memory")
            ):
                return "Quantify context-window limits before relying on model memory"
            return "Quantify the operating signal before scaling AI work"
        if context:
            return f"Translate {context.lower()} into an explicit operating decision"
        return "Translate the source evidence into an explicit operating decision"

    def _slide_context_label(self, slide: GeneratedSlideSpec) -> str:
        candidates = [slide.subheading, slide.design_intent or ""]
        for candidate in candidates:
            cleaned = re.sub(r"^evidence\s+from\s+", "", candidate, flags=re.IGNORECASE)
            cleaned = self._clean_section_title(cleaned)
            if cleaned and cleaned.lower() not in {"uploaded source", "source"}:
                return self._truncate_at_word(cleaned, 42).removesuffix("...")
        return ""

    def _repair_weak_action_title(self, slide: GeneratedSlideSpec, title: str) -> str:
        normalized = self._strip_meta_title_text(title).strip()
        intent = f"{normalized} {self._slide_intent_text(slide)}"
        intent_lower = intent.lower()
        word_count = len(normalized.split())
        archetype = self._normalize_archetype(slide.archetype or "")
        section_divider_needs_repair = archetype == "section_divider" and (
            word_count > 6
            or bool(
                re.match(
                    r"^(translate|turn|explain)\s+why\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
        )
        table_reference_needs_repair = archetype == "table_reference" and bool(
            re.search(
                r"\b(?:core files|six[- ]file|six core|memory bank)\b"
                r".*\b(?:as|hierarchy|reference)\b",
                normalized,
                flags=re.IGNORECASE,
            )
        )
        closing_needs_repair = archetype == "closing_recommendation" and not bool(
            re.match(
                r"^(commit|adopt|approve|launch|move|recommend)\b",
                normalized,
                flags=re.IGNORECASE,
            )
        )
        generic = (
            self._title_contains_meta_instruction(normalized)
            or word_count <= 4
            or "..." in normalized
            or section_divider_needs_repair
            or table_reference_needs_repair
            or closing_needs_repair
            or bool(re.match(r"^use\s+.*\bguide\b", normalized, flags=re.IGNORECASE))
            or bool(
                re.match(
                    r"^(turn\s+reference|reference)\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
            or self._has_embedded_clause_title(normalized)
            or bool(
                re.match(
                    r"^(provide|support|end|name|make|detail)\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
            or bool(
                re.match(
                    r"^(define|quantify|enforce|structure|create|build|show|explain|"
                    r"execute|operationalize|reference|use)\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
                and not re.search(
                    r"\b(to|so|because|with|before|after|through|into|against|across)\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
        )
        if not generic and not normalized.lower().endswith((" for reliable", " for scalable")):
            return normalized
        if archetype == "section_divider":
            return self._section_divider_title(intent_lower)
        if archetype == "closing_recommendation":
            if normalized.lower().startswith("end with"):
                return "Commit to the recommendation with named ownership"
            return self._closing_recommendation_title(intent_lower)
        if archetype == "table_reference" and self._is_memory_text(intent_lower):
            return "Standardize Memory Bank files as a reusable reference"
        if self._has_embedded_clause_title(normalized):
            replacement = self._distinct_action_title(slide)
            if replacement.casefold() != normalized.casefold():
                return self._truncate_title(replacement)
        if archetype == "table_reference":
            context = self._slide_context_label(slide)
            if context:
                return f"Standardize {context.lower()} as a reusable reference"
        if "specification" in intent_lower or "acceptance criteria" in intent_lower:
            return "Define acceptance criteria before execution begins"
        if archetype in {"code_panel", "reference"} and (
            self._is_memory_text(intent_lower)
        ):
            return "Codify memory rules where teams already work"
        if archetype in {"code_panel", "reference"} and (
            "cycle" in intent_lower or "loop" in intent_lower or "phase" in intent_lower
        ):
            return "Codify the operating cycle as reusable rules"
        if "agentic cycle" in intent_lower or "operating cycle" in intent_lower:
            return "Run the operating cycle with explicit review gates"
        if archetype == "framework_cycle":
            return "Run the operating cycle with explicit review gates"
        if archetype == "checklist" and (
            self._is_memory_text(intent_lower)
        ):
            return "Implement the memory bank through a short operating checklist"
        if archetype == "checklist":
            return "Implement next steps through a short operating checklist"
        if archetype == "code_panel":
            return "Codify operating rules where teams already work"
        if archetype == "quote_sidebar":
            return "Reframe the operating model around persistent context"
        if archetype == "table_reference" and self._is_memory_text(intent_lower):
            return "Standardize Memory Bank roles through refresh-triggered files"
        if self._is_memory_text(intent_lower):
            return "Use memory bank files so teams inherit context"
        if "industry shift" in intent_lower or "adoption" in intent_lower:
            return "Quantify adoption pressure before redesigning delivery"
        if archetype == "comparison_table":
            return "Compare the current model with the target operating model"
        if archetype == "table_reference":
            return "Standardize core artifacts for persistent context"
        if archetype == "closing_recommendation":
            return "Commit to the recommendation with named ownership"
        replacement = self._distinct_action_title(slide)
        if replacement.casefold() != normalized.casefold():
            return self._truncate_title(replacement)
        return "Translate source evidence into an explicit operating decision"

    def _section_divider_title(self, intent: str) -> str:
        intent_lower = intent.lower()
        if any(token in intent_lower for token in ("chatbot", "employee", "manager")):
            return "Shift From Prompting to Management"
        if any(
            token in intent_lower
            for token in ("ephemeral", "conversation", "reproducibility")
        ):
            return "Shift From Ephemeral Chat to Persistent Context"
        if any(token in intent_lower for token in ("execution", "implementation")):
            return "Shift From Diagnosis to Execution"
        return "Shift From Insight to Operating Model"

    def _closing_recommendation_title(self, intent: str) -> str:
        intent_lower = intent.lower()
        if any(token in intent_lower for token in ("memory", "context", "external brain")):
            return "Commit to persistent context as the operating default"
        if any(token in intent_lower for token in ("cycle", "loop", "reset")):
            return "Commit to the agentic cycle for reliable delivery"
        if "agentic coding" in intent_lower:
            return "Commit to Agentic Coding for production-grade reliability"
        return "Commit to the recommendation with named ownership"

    def _has_embedded_clause_title(self, title: str) -> bool:
        return bool(
            re.search(
                r"\b(?:turn|translate|convert|standardize)\s+.+\b"
                r"(?:is|are|was|were|has|have|can|should|must|consists?|arranged)\b"
                r".+\b(?:into|as)\b",
                title,
                flags=re.IGNORECASE,
            )
        )

    def _strip_meta_title_text(self, title: str) -> str:
        cleaned = re.sub(
            r"\s+(?:as|for)\s+(?:a\s+)?(?:distinct|primary|structured)\s+exhibit\b.*$",
            "",
            title,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b(?:distinct|primary|structured)\s+exhibit\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = " ".join(cleaned.split()).strip(" -:;,.")
        return cleaned or title

    def _title_contains_meta_instruction(self, title: str) -> bool:
        return bool(
            re.search(
                r"\b(?:distinct|primary|structured)\s+exhibit\b"
                r"|\badvance\s+the\s+storyline\b"
                r"|\bsource[-\s]+grounded\s+evidence\b"
                r"|\bsource[-\s]+backed\s+exhibit\b"
                r"|\bevidence\s+from\s+uploaded\s+source\b"
                r"|\bfocused\s+recommendation\b",
                title,
                flags=re.IGNORECASE,
            )
        )

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
