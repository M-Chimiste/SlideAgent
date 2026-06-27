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
from app.services.presentation_styles import get_style


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
            f"Create a {blueprint.target_slide_count}-slide {get_style(self._presentation_style).label} deck plan as strict JSON. "
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
            "For list exhibits, fill exhibit_spec.points as objects {title, body}: title an optional 2-5 word bold lead, body ONE complete sentence (not a fragment). "
            "Dependency, cycle, checklist, code, anti-pattern, and quote exhibits need structured arrays, not prose blobs. "
            "Every content point must be a complete thought grounded in the source — no sentence fragments, trailing clauses, placeholder text, or generic filler; "
            "a slide with one finished idea beats a slide padded with thin bullets. "
            "For dependency_map and framework/cycle slides, include diagram_spec with kind dependency_flow or cycle when useful; otherwise use null. "
            "Action titles must avoid the word 'and'; split the idea instead. "
            "Only use numeric claims that appear in the allowed numeric tokens. "
            "If an unsupported numeric claim is necessary, write [source needed] beside it. "
            "Use source_refs for exact source packet ids. Sources may only be Uploaded source, a short label copied from source_refs, or [source needed]. "
            "Do not invent document names, reports, URLs, people, companies, or dates as sources. "
            "Do not include markdown, comments, reasoning, or text outside the JSON. "
            f"Generation mode: {mode}. Quality profile: {quality_profile}. Presentation style: {get_style(self._presentation_style).label}. "
            f"Instructions: {instructions or 'No extra instructions.'}\n"
            f"Blueprint: {blueprint.model_dump()}\n"
            f"Story map: {story_map.model_dump() if story_map else {}}\n"
            f"Source compression: {source_compression.model_dump() if source_compression else {}}\n"
            f"Allowed numeric tokens: {allowed_numbers or ['none']}\n"
            f"Source packet: {json.dumps(source_packet, ensure_ascii=True)}\n"
            f"Metrics: {json.dumps(metrics, ensure_ascii=True)}"
        )
        system_prompt = build_planner_system_prompt(quality_profile, self._presentation_style)
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
            return self._complete_partial_llm_deck(
                deck,
                bundle,
                instructions,
                mode,
                blueprint,
                story_map,
            )
        if self._should_skip_schema_repair_retry():
            return None
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
        deck = self._validate_deck_payload(
            payload,
            blueprint,
            require_exact_slide_count=require_exact_slide_count,
        )
        if deck is None:
            return None
        return self._complete_partial_llm_deck(
            deck,
            bundle,
            instructions,
            mode,
            blueprint,
            story_map,
        )

    # ------------------------------------------------------------------ #
    # Decomposed generation (batched for fast profile, per-slide for deep)
    # ------------------------------------------------------------------ #
    def _generate_deck_slides(
        self,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
        *,
        blueprint: DeckBlueprint,
        quality_profile: str,
        source_compression: SourceCompression | None = None,
        story_map: StoryMap | None = None,
    ) -> DeckSpec | None:
        """Author the deck, choosing batched/per-slide generation by strategy.

        Falls back to the monolithic single-call planner when decomposition is
        disabled, there are no story beats to scaffold from, or the decomposed
        attempt yields nothing usable. Returning None preserves the caller's
        existing deterministic-fallback / no-fallback behavior.
        """
        if self.llm_client is None:
            return None
        beats = list(story_map.beats) if story_map and story_map.beats else []
        if getattr(self, "decompose", True) and beats:
            try:
                batch_size = 1 if getattr(self, "slide_generation_strategy", "batched") == "per_slide" else 4
                deck = self._plan_with_llm_batched(
                    bundle,
                    instructions,
                    mode,
                    blueprint=blueprint,
                    quality_profile=quality_profile,
                    source_compression=source_compression,
                    story_map=story_map,
                    batch_size=batch_size,
                )
            except Exception as exc:  # never let decomposition hard-fail the job
                self._last_planning_error = (
                    f"decomposed planning error: {type(exc).__name__}: {exc}"
                )
                deck = None
            if deck is not None and deck.slides:
                return deck
        return self._plan_with_llm(
            bundle,
            instructions,
            mode,
            blueprint=blueprint,
            quality_profile=quality_profile,
            source_compression=source_compression,
            story_map=story_map,
        )

    def _plan_with_llm_per_slide(self, *args, **kwargs) -> DeckSpec | None:
        kwargs["batch_size"] = 1
        return self._plan_with_llm_batched(*args, **kwargs)

    def _plan_with_llm_batched(
        self,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
        *,
        blueprint: DeckBlueprint,
        quality_profile: str,
        source_compression: SourceCompression | None = None,
        story_map: StoryMap | None = None,
        batch_size: int = 4,
    ) -> DeckSpec | None:
        beats = list(story_map.beats) if story_map and story_map.beats else []
        if not beats:
            return None
        allowed_numbers = sorted(self._supported_numeric_tokens(bundle))[:40]
        step = max(1, batch_size)
        slides: list[GeneratedSlideSpec] = []
        for start in range(0, len(beats), step):
            subset = beats[start : start + step]
            batch = self._generate_slide_batch(
                subset,
                slides,
                bundle,
                blueprint,
                quality_profile,
                story_map,
                allowed_numbers,
                start_number=start + 1,
            )
            if batch is None:
                # The model returned a whole-deck response instead of a batch;
                # let the monolithic handler process it.
                return None
            slides.extend(batch)
        if not slides:
            return None
        deck = DeckSpec(
            deck_title=blueprint.deck_title,
            audience=blueprint.audience,
            goal=(story_map.recommendation if story_map else "")
            or "Communicate a clear recommendation.",
            narrative_arc=(story_map.narrative_arc if story_map else "")
            or "Situation -> Complication -> Resolution",
            slides=slides,
            blueprint=blueprint,
        )
        # Honor the requested deck length even if the story map returned fewer
        # beats than the blueprint target (fills the remainder deterministically).
        target_count = max(len(beats), blueprint.target_slide_count)
        deck = self._fill_deck_to_target(
            deck, target_count, bundle, instructions, mode, blueprint, story_map
        )
        for index, slide in enumerate(deck.slides, start=1):
            slide.slide_number = index
        self._repair_model_titles(deck)
        return deck

    def _generate_slide_batch(
        self,
        subset: list[Any],
        prior_slides: list[GeneratedSlideSpec],
        bundle: DocumentBundle,
        blueprint: DeckBlueprint,
        quality_profile: str,
        story_map: StoryMap | None,
        allowed_numbers: list[str],
        *,
        start_number: int,
    ) -> list[GeneratedSlideSpec] | None:
        prior_titles = [s.action_title for s in prior_slides if s.action_title][-12:]
        prior_archetypes = [s.archetype for s in prior_slides if getattr(s, "archetype", None)][-12:]
        beats_payload = [
            {
                "slide_number": start_number + offset,
                "role": beat.role,
                "claim": beat.claim,
                "preferred_exhibit": beat.preferred_exhibit,
                "source_refs": beat.source_refs,
                "rationale": beat.rationale,
                # Bound substantive source points + the per-slide authoring contract
                # (density floor + per-element char budget) so the model writes
                # finished, on-budget content instead of sparse fragments.
                "evidence": list(beat.evidence)[:6] if getattr(beat, "evidence", None) else [],
                "authoring_contract": self._beat_authoring_contract(beat),
            }
            for offset, beat in enumerate(subset)
        ]
        section_context = self._beat_source_context(subset, bundle)
        thesis = story_map.thesis if story_map else ""
        count = len(subset)
        user_prompt = (
            f"Author exactly {count} {get_style(self._presentation_style).label} slide object(s) as strict JSON, one per beat below, in order. "
            'Return exactly this shape: {"slides":[ <one slide object per beat> ]}. '
            "Each slide object uses exactly this shape: " + self._slide_schema_block() + ". "
            "Each action_title must be a complete sentence with a verb, 15 words or fewer, avoid the word 'and', "
            "and must not repeat any prior slide title. "
            "Every non-cover slide needs exactly one primary exhibit_spec matching the beat's preferred_exhibit. "
            "Comparison exhibits need clear columns and row labels; checklist, cycle, and dependency exhibits need structured arrays, not prose. "
            "For list exhibits (callouts, icon_rows, two_column, checklist) fill exhibit_spec.points as objects {title, body}: title is an optional 2-5 word bold lead, body is ONE complete sentence of evidence (not a fragment). "
            "Honor each beat's authoring_contract: produce at least its min_points substantive content points (never fewer) and at most max_points; "
            "keep each bold lead within lead_chars characters and each supporting line within body_chars characters. "
            "Write complete thoughts grounded in the beat's evidence — no sentence fragments, trailing clauses, placeholder text, or generic filler. "
            "Only use numbers that appear in the allowed numeric tokens; otherwise write [source needed] beside the number. "
            "Use the beat's source_refs as source_refs. Sources may only be 'Uploaded source', a label copied from source_refs, or '[source needed]'. "
            "Do not invent document names, people, companies, dates, or URLs. No markdown, comments, reasoning, or text outside the JSON.\n"
            f"Deck thesis: {thesis}\nAudience: {blueprint.audience}\n"
            f"Prior slide titles (do not repeat): {prior_titles or ['none']}\n"
            f"Prior slide archetypes used (vary from these; avoid repeating an archetype on adjacent slides): {prior_archetypes or ['none']}\n"
            f"Beats: {json.dumps(beats_payload, ensure_ascii=True)}\n"
            f"Allowed numeric tokens: {allowed_numbers or ['none']}\n"
            f"Source sections: {json.dumps(section_context, ensure_ascii=True)}"
        )
        system_prompt = build_planner_system_prompt(quality_profile, self._presentation_style)
        # Headroom so a batch of dense {title, body} slides rarely truncates mid-JSON
        # on a local model (truncation was the root of mid-sentence body fragments).
        max_tokens = min(16000, 3000 + count * 1800)
        try:
            payload = self.llm_client.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=0.2,
            )
        except Exception as exc:
            self._last_planning_error = f"batch generation error: {type(exc).__name__}: {exc}"
            return []
        if not isinstance(payload, dict):
            return []
        # A response carrying whole-deck fields is not a batch — signal the
        # caller to abort decomposition and use the monolithic handler instead.
        if "deck_title" in payload or "narrative_arc" in payload:
            return None
        raw_slides = payload.get("slides")
        if not isinstance(raw_slides, list):
            raw_slides = [payload] if payload.get("action_title") else []
        specs: list[GeneratedSlideSpec] = []
        for offset, raw in enumerate(raw_slides[:count]):
            normalized = self._normalize_llm_slide_payload(raw)
            try:
                spec = GeneratedSlideSpec.model_validate(normalized)
            except Exception:
                continue
            spec.slide_number = start_number + offset
            specs.append(spec)
        return specs

    def _beat_authoring_contract(self, beat: Any) -> dict[str, Any]:
        """The per-slide density floor + per-element char budget the model must hit,
        derived from the beat's preferred exhibit via the slide-type catalog and the
        single fit-budget table (so the prompt, the spec gate, and the renderer all
        target the same numbers)."""
        from app.services import slide_types
        from app.services.slide_design import fit

        stype = slide_types.get_slide_type(
            slide_types.slide_type_for_archetype(getattr(beat, "preferred_exhibit", "") or "")
        )
        cap = fit.budget_for(
            stype.primitive, getattr(self, "_design_language", "editorial_serif")
        )
        return {
            "slide_type": stype.key,
            "min_points": stype.min_points,
            "max_points": stype.max_points,
            "lead_chars": cap.lead.authoring_chars(),
            "body_chars": cap.body.authoring_chars(),
        }

    def _beat_source_context(
        self, subset: list[Any], bundle: DocumentBundle, char_limit: int = 900
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for beat in subset:
            for ref in beat.source_refs or []:
                ref_str = str(ref)
                if ref_str in seen or "source needed" in ref_str.lower():
                    continue
                seen.add(ref_str)
                section = self._section_for_source_ref(ref_str, bundle)
                if section is None:
                    continue
                out.append(
                    {
                        "id": ref_str,
                        "title": section.title,
                        "content": self._source_excerpt(section.content, char_limit),
                    }
                )
        return out

    def _fill_deck_to_target(
        self,
        deck: DeckSpec,
        target_count: int,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
        blueprint: DeckBlueprint,
        story_map: StoryMap | None,
    ) -> DeckSpec:
        if len(deck.slides) >= target_count:
            return deck
        fallback = self._fallback_deck(bundle, instructions, mode, blueprint, story_map=story_map)
        existing = {" ".join(s.action_title.lower().split()) for s in deck.slides}
        for fb_slide in fallback.slides:
            if len(deck.slides) >= target_count:
                break
            key = " ".join(fb_slide.action_title.lower().split())
            if key in existing:
                continue
            deck.slides.append(
                fb_slide.model_copy(update={"slide_number": len(deck.slides) + 1}, deep=True)
            )
            existing.add(key)
        return deck

    def _slide_schema_block(self) -> str:
        return (
            '{"slide_number":1,"slide_type":"cover|executive_summary|content|chart|comparison|process|framework|reference|checklist|anti_pattern|quote|decision|closing",'
            '"action_title":"complete sentence with a verb, 15 words or fewer",'
            '"subheading":"evidence context",'
            '"content_blocks":[{"type":"bullets|chart|table|callout|text","body":["one complete evidence sentence"],"annotations":[],"callouts":[]}],'
            '"chart_spec":null,"sources":["Uploaded source"],'
            '"archetype":"cover|section_divider|comparison_table|dependency_map|cycle|code_panel|checklist|quote_sidebar|anti_patterns|metric_chart|executive_summary|table_reference|matrix_2x2|callouts|icon_rows|two_column|closing_recommendation",'
            '"narrative_role":"cover|executive_summary|problem|evidence|framework|implementation|reference|decision|closing",'
            '"exhibit_spec":{"type":"comparison_table|dependency_map|cycle|checklist|code_panel|anti_patterns|quote_sidebar|metric_chart|reference_table|matrix_2x2|callouts|icon_rows|two_column|recommendation",'
            '"points":[{"title":"2-5 word bold lead","body":"one complete supporting sentence"}]},'
            '"diagram_spec":null,"design_intent":"short renderer guidance",'
            '"source_refs":["a source id or [source needed]"],'
            '"speaker_notes":"short presenter note","qa":{"consulting_status":"pending","visual_status":"pending","issues":[]}}'
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
        if self._uses_small_model_harness():
            return False
        module = client.__class__.__module__
        if module.startswith("app.clients."):
            return True
        model = str(getattr(client, "model", "") or "").lower()
        return bool(model)

    def _should_skip_schema_repair_retry(self) -> bool:
        # Small local models DO get one schema-repair retry now — a truncated/invalid
        # first response is re-prompted rather than dropped to the deterministic deck.
        return False

    def _uses_small_model_harness(self) -> bool:
        model = str(getattr(self.llm_client, "model", "") or "").lower()
        return any(marker in model for marker in ["qwen3.6", "qwen3-6", "qwen3.5", "qwen3-5"])

    def _complete_partial_llm_deck(
        self,
        deck: DeckSpec,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
        blueprint: DeckBlueprint,
        story_map: StoryMap | None,
    ) -> DeckSpec:
        if not self._uses_small_model_harness():
            return deck
        if len(deck.slides) >= blueprint.target_slide_count:
            return deck
        fallback = self._fallback_deck(
            bundle,
            instructions,
            mode,
            blueprint,
            story_map=story_map,
        )
        existing_titles = {
            " ".join(slide.action_title.lower().split()) for slide in deck.slides
        }
        for fallback_slide in fallback.slides:
            if len(deck.slides) >= blueprint.target_slide_count:
                break
            normalized_title = " ".join(fallback_slide.action_title.lower().split())
            if normalized_title in existing_titles:
                continue
            deck.slides.append(
                fallback_slide.model_copy(
                    update={"slide_number": len(deck.slides) + 1},
                    deep=True,
                )
            )
            existing_titles.add(normalized_title)
        return deck

    def _normalize_llm_payload(
        self, payload: dict[str, Any], blueprint: DeckBlueprint
    ) -> dict[str, Any]:
        normalized = dict(payload)
        normalized["blueprint"] = blueprint.model_dump()
        slides = normalized.get("slides")
        if isinstance(slides, list):
            normalized["slides"] = [
                self._normalize_llm_slide_payload(slide) for slide in slides
            ]
        return normalized

    def _normalize_llm_slide_payload(self, slide: Any) -> Any:
        if not isinstance(slide, dict):
            return slide
        normalized = dict(slide)
        blocks = normalized.get("content_blocks")
        if isinstance(blocks, list):
            normalized["content_blocks"] = [
                self._normalize_llm_content_block(block) for block in blocks
            ]
        return normalized

    def _normalize_llm_content_block(self, block: Any) -> Any:
        if not isinstance(block, dict):
            return block
        normalized = dict(block)
        for key in ("annotations", "callouts"):
            values = normalized.get(key)
            if isinstance(values, list):
                normalized[key] = [self._stringify_llm_list_item(item) for item in values]
        return normalized

    def _stringify_llm_list_item(self, item: Any) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            title = str(
                item.get("title")
                or item.get("label")
                or item.get("name")
                or ""
            ).strip()
            detail = str(
                item.get("detail")
                or item.get("description")
                or item.get("body")
                or item.get("text")
                or item.get("value")
                or ""
            ).strip()
            if title and detail:
                return f"{title}: {detail}"
            if title or detail:
                return title or detail
            return json.dumps(item, ensure_ascii=True, sort_keys=True)
        return str(item)

    def _planner_max_tokens(self, quality_profile: str, target_slide_count: int) -> int:
        if quality_profile == "fast":
            # Headroom so the full deck JSON rarely truncates on a local model;
            # extract_json salvages anything that still overflows.
            return max(9000, min(16000, target_slide_count * 1400))
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
        """Excerpt whole sentences up to ``char_limit`` — never start or end on a
        mid-sentence fragment. If the first sentence alone exceeds the budget, keep
        it whole (a complete long sentence beats a truncated one for LLM context)."""
        cleaned = " ".join(str(content).split())
        if len(cleaned) <= char_limit:
            return cleaned
        out = ""
        for sentence in self._split_sentences(cleaned):
            if out and len(out) + 1 + len(sentence) > char_limit:
                break
            out = f"{out} {sentence}".strip()
        if not out:
            sentences = self._split_sentences(cleaned)
            out = sentences[0] if sentences else cleaned
        return out

    def _source_key_points(self, content: str) -> list[str]:
        points: list[str] = []
        for item in self._to_bullets(content):
            phrase = self._repair_dangling_fragment(" ".join(str(item).split()))
            if phrase and phrase not in points:
                points.append(phrase)
            if len(points) >= 6:
                break
        return points
