import re
from typing import Any, Optional

from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.models.document import DocumentBundle, DocumentSection
from app.models.generation import ContentBlock, DeckSpec, GeneratedSlideSpec, GenerationMode
from app.models.outline import SlideOutline
from app.models.qa import QAIssue
from app.models.template import TemplateProfile
from app.services.consulting_qa import ConsultingQA
from app.services.planning.blueprint import BlueprintPlanningMixin
from app.services.planning import constants as planning_constants
from app.services.planning.context import ContextPlanningMixin
from app.services.planning.exhibit_selection import ExhibitSelectionMixin
from app.services.planning.exhibits import ExhibitCompiler
from app.services.planning.grounding import SourceGroundingMixin
from app.services.planning.llm import LLMPlanningMixin
from app.services.planning.narrative import NarrativeEditorMixin
from app.services.planning.outlines import OutlinePlanningMixin
from app.services.planning.repairs import PlanningRepairMixin
from app.services.planning.specs import SlideSpecPlanningMixin
from app.services.planning.spec_gate import SpecGateMixin


PLANNER_SYSTEM_PROMPT = planning_constants.PLANNER_SYSTEM_PROMPT
UPLOADED_SOURCE_LABEL = planning_constants.UPLOADED_SOURCE_LABEL
SOURCE_NEEDED_LABEL = planning_constants.SOURCE_NEEDED_LABEL


class PlanningFailedError(RuntimeError):
    """Raised when a configured planner cannot produce an agent-authored plan."""


class ContentPlanner(
    ContextPlanningMixin,
    ExhibitSelectionMixin,
    SpecGateMixin,
    LLMPlanningMixin,
    NarrativeEditorMixin,
    BlueprintPlanningMixin,
    SlideSpecPlanningMixin,
    OutlinePlanningMixin,
    PlanningRepairMixin,
    SourceGroundingMixin,
):
    def __init__(
        self,
        llm_client: Optional[OpenAICompatibleClient] = None,
        slide_generation_strategy: str = "batched",
        decompose: bool = True,
    ) -> None:
        self.llm_client = llm_client
        # How the LLM authors slides: "batched" (small chunks, fast profile) or
        # "per_slide" (one focused call per slide, deep profile). `decompose` is
        # the kill-switch back to the single monolithic deck-JSON call.
        self.slide_generation_strategy = (slide_generation_strategy or "batched").strip().lower()
        self.decompose = decompose
        self._last_planning_error: str | None = None
        self._last_story_map_error: str | None = None
        # Presentation style for the current plan() pass (stashed because plan()
        # runs fully synchronously; read by the prompt/blueprint/label mixins).
        self._presentation_style: str = "consulting"
        self.last_planning_artifacts: dict[str, Any] = {}
        self.qa = ConsultingQA()
        self.exhibit_compiler = ExhibitCompiler()
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
            "matrix_2x2",
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
        presentation_style: str = "consulting",
    ) -> tuple[list[SlideOutline], list[dict[str, Any]]]:
        self._presentation_style = (presentation_style or "consulting").strip().lower()
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
        self.last_planning_artifacts = {}
        blueprint = self._build_blueprint(
            bundle,
            instructions,
            mode,
            quality_profile=quality_profile,
            length_strategy=length_strategy,
        )
        source_compression = self._build_source_compression(bundle, quality_profile)
        story_map = self._build_story_map(
            bundle,
            instructions,
            blueprint,
            source_compression,
            quality_profile,
        )
        blueprint.story_beats = [beat.model_dump() for beat in story_map.beats]
        self.last_planning_artifacts = {
            "source-compression": source_compression.model_dump(),
            "story-map": story_map.model_dump(),
        }
        self._last_planning_error = None
        used_deck_fallback = False
        deck = self._generate_deck_slides(
            bundle,
            instructions,
            mode,
            blueprint=blueprint,
            quality_profile=quality_profile,
            source_compression=source_compression,
            story_map=story_map,
        )
        if deck is None:
            if self.llm_client is not None:
                message = (
                    "LLM planning failed and deterministic planning fallback is "
                    "disabled for configured planners."
                )
                if self._last_planning_error:
                    message = f"{message} Reason: {self._last_planning_error}"
                raise PlanningFailedError(message)
            message = (
                "LLM planner was not configured; used deterministic fallback."
            )
            warnings.append(
                {
                    "slide_index": None,
                    "field": "llm_planning",
                    "message": message,
                }
            )
            deck = self._fallback_deck(
                bundle,
                instructions,
                mode,
                blueprint,
                story_map=story_map,
            )
            used_deck_fallback = True
        if deck.blueprint is None:
            deck.blueprint = blueprint
        selection_story_map = (
            story_map
            if story_map.status == "llm" or used_deck_fallback
            else None
        )
        self._enrich_deck_specs(deck, blueprint, bundle)
        self._apply_exhibit_selection(deck, bundle, selection_story_map)
        self._ensure_core_exhibit_mix(deck, bundle)
        self._repair_model_titles(deck)
        self._repair_repeated_action_titles(deck)
        warnings.extend(self._normalize_source_labels(deck, bundle))
        warnings.extend(self._ground_numeric_claims(deck, bundle))
        spec_gate_report = self._run_spec_gate(
            deck,
            bundle,
            source_compression,
            selection_story_map or story_map,
        )
        self.last_planning_artifacts["spec-gate"] = spec_gate_report.model_dump()
        warnings.extend(self._spec_gate_warnings(spec_gate_report))
        self._repair_repeated_action_titles(deck)
        self._polish_source_action_titles(deck, bundle)
        self._repair_repeated_action_titles(deck)
        self._polish_source_action_titles(deck, bundle)
        self._repair_weak_source_claims(deck, bundle)
        self._rewrite_title_ladder_for_narrative(deck, story_map, bundle)
        self._finalize_action_titles(deck)
        deck, qa_warnings = self.qa.inspect(deck)
        warnings.extend(qa_warnings)
        return deck, warnings

    def _ensure_core_exhibit_mix(self, deck: DeckSpec, bundle: DocumentBundle) -> None:
        if len(deck.slides) < 6 or not bundle.sections:
            return
        # Force only resilient editorial/table shapes into the mix. Code panels,
        # diagrams, and 2x2 matrices must be selected by source evidence; when
        # injected as variety filler they are the most visible source of generic
        # "benchmark factory" slides. The required set is the presentation
        # style's exhibit emphasis, filtered to the safe-to-inject shapes.
        from app.services.presentation_styles import SAFE_FILLER_EXHIBITS, get_style

        style = get_style(getattr(self, "_presentation_style", "consulting"))
        safe = set(SAFE_FILLER_EXHIBITS)
        if bundle.metrics:
            safe.add("metric_chart")
        required = [a for a in style.exhibit_emphasis if a in safe] or [
            "comparison_table",
            "icon_rows",
            "callouts",
        ]
        for required_archetype in required:
            archetypes = [
                self._normalize_archetype(slide.archetype or "")
                for slide in deck.slides
            ]
            if required_archetype in archetypes:
                continue
            lightweight_counts = {
                archetype: archetypes.count(archetype)
                for archetype in {"callouts", "checklist", "icon_rows", "two_column"}
            }
            candidates = [
                slide
                for slide in deck.slides[2:-1]
                if self._normalize_archetype(slide.archetype or "") in lightweight_counts
                and lightweight_counts[self._normalize_archetype(slide.archetype or "")] > 1
            ]
            if not candidates:
                return
            slide = candidates[min(len(candidates) // 2, len(candidates) - 1)]
            section = self._section_for_slide_sources(slide, bundle)
            self._apply_selected_exhibit(slide, required_archetype, section, bundle)
            if section is not None:
                slide.action_title = self._clean_action_title_candidate(
                    self._fallback_action_title(required_archetype, section.title, section)
                )

    def _polish_source_action_titles(
        self,
        deck: DeckSpec,
        bundle: DocumentBundle,
    ) -> None:
        seen_titles: set[str] = set()
        for slide in deck.slides:
            title = " ".join(str(slide.action_title or "").split())
            corrected = title.replace("scanable", "scannable")
            section = self._section_for_slide_sources(slide, bundle)
            context_parts = [
                corrected,
                slide.subheading,
                slide.speaker_notes,
                slide.design_intent or "",
                " ".join(str(source) for source in slide.sources),
                self._flatten_exhibit_value(slide.exhibit_spec),
            ]
            if section is not None:
                context_parts.extend([section.title, section.content[:1200]])
            context = " ".join(context_parts).lower()
            replacement = ""
            if self._weak_source_action_title(corrected):
                replacement = self._benchmark_title_repair(context)
                if not replacement and section is not None:
                    subject = self._clean_section_title(section.title).lower()
                    replacement = self._themed_action_title(subject, context)
            if replacement:
                corrected = self._clean_action_title_candidate(replacement)
            corrected = self._unique_polished_action_title(
                corrected,
                section,
                context,
                seen_titles,
            )
            if corrected and corrected != title:
                slide.action_title = self._truncate_title(corrected)
            if slide.action_title:
                seen_titles.add(str(slide.action_title).casefold())

    def _unique_polished_action_title(
        self,
        title: str,
        section: DocumentSection | None,
        context: str,
        seen_titles: set[str],
    ) -> str:
        cleaned = self._truncate_title(title)
        if cleaned.casefold() not in seen_titles:
            return cleaned
        for candidate in self._source_title_alternatives(section, context):
            cleaned = self._clean_action_title_candidate(candidate)
            if cleaned and cleaned.casefold() not in seen_titles:
                return cleaned
        return cleaned

    def _source_title_alternatives(
        self,
        section: DocumentSection | None,
        context: str,
    ) -> list[str]:
        alternatives: list[str] = []
        if section is not None:
            alternatives.extend(self._section_claim_fallbacks(section))
            subject = self._clean_section_title(section.title).lower()
            if subject:
                alternatives.append(self._themed_action_title(subject, context))
        alternatives.extend(
            [
                self._benchmark_title_repair(context),
                "Use source evidence to choose the next operating move",
            ]
        )
        return [item for item in alternatives if item]

    def _weak_source_action_title(self, title: str) -> bool:
        lowered = " ".join(str(title).lower().split())
        return bool(
            re.match(
                r"^use\s+(?:the\s+)?(?:harness-centric view|harness centric view|"
                r"introduction|source evidence|conclusion|future directions|"
                r"executive summary)\b",
                lowered,
            )
        )

    def _repair_weak_source_claims(
        self,
        deck: DeckSpec,
        bundle: DocumentBundle,
    ) -> None:
        if not self._has_uploaded_source_material(bundle):
            return
        for slide in deck.slides:
            archetype = self._normalize_archetype(slide.archetype or "")
            if archetype in {"cover", "section_divider"}:
                continue
            section = self._section_for_slide_sources(slide, bundle)
            if section is None:
                continue
            if not self._has_source_claim_fallback(section) and not self._value_has_bad_source_fragment(
                slide.exhibit_spec
            ):
                continue
            if not self._slide_claims_need_repair(slide):
                continue
            claims = self._source_rewrite_bullets(
                section,
                4,
                prefer_claim_fallbacks=True,
            )
            claims = [
                claim
                for claim in claims
                if self._source_claim_is_display_safe(claim)
            ]
            if not claims:
                continue
            self._apply_source_claims_to_slide(slide, claims)

    def _slide_claims_need_repair(self, slide: GeneratedSlideSpec) -> bool:
        archetype = self._normalize_archetype(slide.archetype or "")
        if archetype in {"comparison_table", "table_reference", "metric_chart"}:
            # Tables/charts have their own structure checks; avoid flattening a
            # good exhibit just because one row is terse.
            return self._value_has_bad_source_fragment(slide.exhibit_spec)
        body = self._body_to_bullets(slide)
        exhibit_text = self._flatten_exhibit_value(slide.exhibit_spec)
        if self._value_has_bad_source_fragment(exhibit_text):
            return True
        safe_claims = [
            item for item in body if self._source_claim_is_display_safe(item)
        ]
        if len(body) >= 2 and len(safe_claims) < min(3, len(body)):
            return True
        if len(body) <= 1 and archetype not in {"closing_recommendation"}:
            return True
        return any(not self._source_claim_is_display_safe(item) for item in body)

    def _source_claim_is_display_safe(self, text: str) -> bool:
        cleaned = " ".join(str(text).split()).strip(" -:;,.")
        if not cleaned:
            return False
        if self._looks_like_bad_slide_fragment(cleaned):
            return False
        lowered = cleaned.lower()
        if lowered in {
            "architecture overview",
            "closing remarks",
            "executive summary",
            "introduction",
            "the model contract",
            "the problem",
            "the solution",
        }:
            return False
        words = re.findall(r"[A-Za-z][A-Za-z'-]*", cleaned)
        if len(words) < 5:
            return False
        if re.search(r"\b(?:cannot|can|make|makes|around|through|from|to)\s+is\b", lowered):
            return False
        verb_like = {
            "acts",
            "addresses",
            "allows",
            "becomes",
            "build",
            "builds",
            "can",
            "captures",
            "clarifies",
            "connects",
            "coordinates",
            "creates",
            "defines",
            "discovers",
            "enables",
            "ensures",
            "evaluate",
            "evaluates",
            "exists",
            "gives",
            "helps",
            "improves",
            "links",
            "make",
            "makes",
            "matters",
            "must",
            "need",
            "needs",
            "reflect",
            "reflects",
            "requires",
            "scales",
            "shift",
            "shifts",
            "should",
            "specifies",
            "standardize",
            "standardizes",
            "treats",
            "turn",
            "turns",
            "uses",
        }
        return any(word.lower() in verb_like for word in words)

    def _value_has_bad_source_fragment(self, value: Any) -> bool:
        flattened = self._flatten_exhibit_value(value)
        if not flattened:
            return False
        return bool(
            re.search(
                r"\btie the claim\b.{0,80}\bsource-backed evaluation artifact\b|"
                r"\bconnect\b.{0,80}\bexplicit review gate\b|"
                r"\bmake\b.{0,80}\bvisible before execution starts\b|"
                r"\bname the review gate before expanding the benchmark\b|"
                r"\bupdate the benchmark when source evidence changes\b|"
                r"\b(?:left|right)\s+column\s*:\s*(?:the problem|the solution)\b|"
                r"\b(?:prediction|predictions)\b",
                flattened,
                flags=re.IGNORECASE,
            )
        )

    def _apply_source_claims_to_slide(
        self,
        slide: GeneratedSlideSpec,
        claims: list[str],
    ) -> None:
        archetype = self._normalize_archetype(slide.archetype or "")
        slide.content_blocks = [ContentBlock(type="bullets", body=claims[:4])]
        if archetype == "executive_summary":
            slide.exhibit_spec = {
                "type": "executive_summary",
                "points": claims[:3],
                "proof_points": [],
            }
            return
        if archetype == "checklist":
            slide.exhibit_spec = {
                "type": "checklist",
                "items": [{"action": claim} for claim in claims[:4]],
            }
            return
        if archetype == "quote_sidebar":
            slide.exhibit_spec = {
                "type": "quote_sidebar",
                "quote": claims[0],
                "key_idea": claims[0],
                "supporting_points": claims[1:4] or claims[:1],
            }
            return
        if archetype == "two_column":
            split = max(1, len(claims[:4]) // 2)
            slide.exhibit_spec = {
                "type": "two_column",
                "left": claims[:split],
                "right": claims[split:4] or claims[:1],
            }
            return
        if archetype == "closing_recommendation":
            existing = slide.exhibit_spec if isinstance(slide.exhibit_spec, dict) else {}
            slide.exhibit_spec = {
                **existing,
                "type": "recommendation",
                "recommendation": existing.get("recommendation") or claims[0],
                "decision_ask": existing.get("decision_ask") or "Approve the recommended pilot with named owners and a review date.",
                "next_steps": claims[:3],
            }
            return
        if archetype == "icon_rows":
            slide.exhibit_spec = {"type": "icon_rows", "items": claims[:4]}
            return
        slide.exhibit_spec = {"type": "callouts", "points": claims[:4]}

    def repair_weak_outline_claims(
        self,
        outlines: list[SlideOutline],
        bundle: DocumentBundle,
    ) -> list[SlideOutline]:
        if not self._has_uploaded_source_material(bundle):
            return outlines
        repaired: list[SlideOutline] = []
        seen_bullets: set[str] = set()
        for outline in outlines:
            if outline.mode != "flexible":
                repaired.append(outline)
                continue
            section = self._source_section_for_outline(outline, bundle)
            if (
                section is None
                or (
                    not self._has_source_claim_fallback(section)
                    and not self._value_has_bad_source_fragment(
                        outline.content_json.get("exhibit_spec")
                    )
                )
                or not self._outline_claims_need_repair(outline)
            ):
                self._track_outline_bullets(outline, seen_bullets)
                repaired.append(outline)
                continue
            revised = outline.model_copy(deep=True)
            claims = self._source_rewrite_bullets(
                section,
                4,
                prefer_claim_fallbacks=True,
            )
            claims = [
                claim
                for claim in claims
                if self._source_claim_is_display_safe(claim)
            ]
            if not claims:
                self._track_outline_bullets(outline, seen_bullets)
                repaired.append(outline)
                continue
            unique_claims: list[str] = []
            for claim in claims:
                key = self._qa_key(claim)
                if key and key in seen_bullets:
                    continue
                unique_claims.append(claim)
                if key:
                    seen_bullets.add(key)
            self._apply_source_claims_to_outline(revised, unique_claims or claims)
            self._restore_outline_sources(revised, section, bundle)
            repaired.append(revised)
        return repaired

    def _outline_claims_need_repair(self, outline: SlideOutline) -> bool:
        archetype = str(
            outline.content_json.get("archetype")
            or outline.layout_json.get("archetype")
            or outline.layout_json.get("layout")
            or ""
        ).lower().replace("-", "_")
        if archetype in {"cover", "section_divider"}:
            return False
        exhibit = outline.content_json.get("exhibit_spec")
        if archetype in {"comparison_table", "table_reference", "metric_chart"}:
            return self._value_has_bad_source_fragment(exhibit)
        body = self._outline_bullets(outline)
        if self._value_has_bad_source_fragment(exhibit):
            return True
        safe_claims = [
            item for item in body if self._source_claim_is_display_safe(item)
        ]
        if len(body) >= 2 and len(safe_claims) < min(3, len(body)):
            return True
        if len(body) <= 1 and archetype not in {"closing_recommendation"}:
            return True
        return any(not self._source_claim_is_display_safe(item) for item in body)

    def _apply_source_claims_to_outline(
        self,
        outline: SlideOutline,
        claims: list[str],
    ) -> None:
        archetype = str(
            outline.content_json.get("archetype")
            or outline.layout_json.get("archetype")
            or outline.layout_json.get("layout")
            or ""
        ).lower().replace("-", "_")
        claims = claims[:4]
        outline.content_json["bullets"] = claims
        outline.content_json["content_blocks"] = [
            {"type": "bullets", "body": claims, "annotations": [], "callouts": []}
        ]
        if archetype == "executive_summary":
            exhibit = {
                "type": "executive_summary",
                "points": claims[:3],
                "proof_points": [],
            }
        elif archetype == "checklist":
            exhibit = {
                "type": "checklist",
                "items": [{"action": claim} for claim in claims],
            }
        elif archetype == "quote_sidebar":
            exhibit = {
                "type": "quote_sidebar",
                "quote": claims[0],
                "key_idea": claims[0],
                "supporting_points": claims[1:4] or claims[:1],
            }
        elif archetype == "two_column":
            split = max(1, len(claims) // 2)
            exhibit = {
                "type": "two_column",
                "left": claims[:split],
                "right": claims[split:4] or claims[:1],
                "points": claims,
            }
        elif archetype == "closing_recommendation":
            current = outline.content_json.get("exhibit_spec")
            existing = current if isinstance(current, dict) else {}
            exhibit = {
                **existing,
                "type": "recommendation",
                "recommendation": existing.get("recommendation") or claims[0],
                "decision_ask": existing.get("decision_ask")
                or "Approve the recommended pilot with named owners and a review date.",
                "next_steps": claims[:3],
            }
        elif archetype == "icon_rows":
            exhibit = {"type": "icon_rows", "items": claims}
        else:
            exhibit = {"type": "callouts", "points": claims}
            outline.content_json["archetype"] = "callouts"
            outline.layout_json["archetype"] = "callouts"
            outline.layout_json["layout"] = "callouts"
        outline.content_json["exhibit_spec"] = exhibit
        outline.layout_json["exhibit_type"] = str(exhibit.get("type") or "")

    def _spec_gate_warnings(self, report) -> list[dict[str, Any]]:
        if not getattr(report, "unresolved_count", 0):
            return []
        return [
            {
                "slide_index": issue.slide_number - 1
                if issue.slide_number is not None
                else None,
                "field": "spec_gate",
                "message": issue.message,
            }
            for issue in report.issues
            if not issue.repaired
        ]

    def consulting_issues_for_outlines(
        self, outlines: list[SlideOutline], bundle: DocumentBundle
    ) -> list[QAIssue]:
        return self.qa.inspect_outlines(
            outlines,
            has_source_material=self._has_uploaded_source_material(bundle),
        )

    def repair_outlines_for_consulting(
        self,
        outlines: list[SlideOutline],
        issues: list[QAIssue],
        bundle: DocumentBundle,
    ) -> list[SlideOutline]:
        issues_by_slide: dict[int, list[QAIssue]] = {}
        deck_level_issue = False
        for issue in issues:
            if issue.slide_index is None:
                deck_level_issue = True
                continue
            issues_by_slide.setdefault(issue.slide_index, []).append(issue)
        repaired: list[SlideOutline] = []
        seen_titles: set[str] = set()
        seen_prefixes: set[str] = set()
        seen_bullets: set[str] = set()
        seen_source_refs: set[str] = set()
        for outline in outlines:
            if outline.mode != "flexible":
                repaired.append(outline)
                continue
            revised = outline.model_copy(deep=True)
            slide_issues = issues_by_slide.get(outline.slide_index, [])
            section = self._source_section_for_outline(revised, bundle)
            issue_categories = {
                str(issue.category or "") for issue in slide_issues
            }
            prior_seen_bullets = set(seen_bullets)
            if issue_categories & {"duplicate_slide", "repeated_bullet"}:
                section = self._alternate_source_section(
                    section,
                    bundle,
                    seen_source_refs,
                    outline.slide_index,
                )
            current_title = str(
                revised.content_json.get("action_title")
                or revised.content_json.get("title")
                or revised.label
            )
            direct_title_applied = False
            direct_benchmark_title = self._direct_benchmark_outline_title(
                revised,
                current_title,
            )
            if direct_benchmark_title:
                current_title = self._unique_consulting_title(
                    direct_benchmark_title,
                    section,
                    seen_titles,
                    seen_prefixes,
                )
                revised.label = current_title
                revised.content_json["action_title"] = current_title
                revised.content_json["title"] = current_title
                direct_title_applied = True
            title_keys = self._title_seen_keys(current_title)
            current_prefix = self._title_subject_prefix(current_title)
            if (
                not direct_title_applied
                and (
                    deck_level_issue
                    or bool(title_keys & seen_titles)
                    or bool(current_prefix and current_prefix in seen_prefixes)
                    or issue_categories
                    & {
                        "action_title",
                        "duplicate_slide",
                        "horizontal_flow",
                        "one_message",
                        "title_body_support",
                    }
                )
            ):
                title = self._consulting_title_for_section(section, revised)
                title = self._unique_consulting_title(title, section, seen_titles, seen_prefixes)
                revised.label = title
                revised.content_json["action_title"] = title
                revised.content_json["title"] = title
            elif not direct_title_applied:
                seen_titles.update(title_keys)
                if current_prefix:
                    seen_prefixes.add(current_prefix)
            if issue_categories & {
                    "duplicate_slide",
                    "content_quality",
                    "generic_filler",
                    "repeated_bullet",
                    "sparse_content",
                "title_body_support",
            }:
                self._replace_outline_bullets_from_source(
                    revised,
                    section,
                    seen_bullets,
                    prefer_claim_fallbacks=bool(
                        issue_categories
                        & {
                            "content_quality",
                            "generic_filler",
                            "sparse_content",
                            "title_body_support",
                        }
                    ),
                )
            else:
                self._track_outline_bullets(revised, seen_bullets)
            if (
                issue_categories
                & {
                    "duplicate_slide",
                    "content_quality",
                    "exhibit_structure",
                    "generic_filler",
                    "missing_exhibit",
                    "repeated_bullet",
                    "sparse_content",
                    "source_refs",
                    "title_body_support",
                }
            ):
                if "exhibit_structure" in issue_categories:
                    self._repair_outline_archetype_for_exhibit_issue(revised)
                self._restore_outline_sources(revised, section, bundle)
                self._rebuild_outline_exhibit(revised, section, bundle)
                if "repeated_bullet" in issue_categories:
                    self._dedupe_rebuilt_outline_exhibit(
                        revised,
                        section,
                        prior_seen_bullets,
                        seen_bullets,
                    )
            elif issue_categories & {"source_refs"}:
                self._restore_outline_sources(revised, section, bundle)
            self._track_outline_source_refs(revised, section, seen_source_refs)
            repaired.append(revised)
        return repaired

    def repair_outlines_for_visual_qa(
        self,
        outlines: list[SlideOutline],
        issues: list[QAIssue],
        bundle: DocumentBundle,
    ) -> list[SlideOutline]:
        issues_by_slide: dict[int, list[QAIssue]] = {}
        for issue in issues:
            if issue.slide_index is None:
                continue
            if not self._visual_qa_needs_source_rewrite([issue]):
                continue
            issues_by_slide.setdefault(issue.slide_index, []).append(issue)
        if not issues_by_slide:
            return outlines

        repaired: list[SlideOutline] = []
        seen_bullets: set[str] = set()
        seen_source_refs: set[str] = set()
        for outline in outlines:
            if outline.mode != "flexible":
                repaired.append(outline)
                continue
            slide_issues = issues_by_slide.get(outline.slide_index, [])
            if not self._visual_qa_needs_source_rewrite(slide_issues):
                self._track_outline_bullets(outline, seen_bullets)
                repaired.append(outline)
                continue
            revised = outline.model_copy(deep=True)
            section = self._source_section_for_outline(revised, bundle)
            if section is not None:
                section_key = getattr(section, "source_id", "") or self._source_ref(
                    section,
                    outline.slide_index,
                )
                if section_key in seen_source_refs:
                    section = self._alternate_source_section(
                        section,
                        bundle,
                        seen_source_refs,
                        outline.slide_index,
                    )
            safe_archetype = self._safe_visual_repair_archetype(revised, slide_issues)
            self._set_outline_archetype(revised, safe_archetype)
            self._replace_outline_bullets_from_source(
                revised,
                section,
                seen_bullets,
                prefer_claim_fallbacks=True,
            )
            self._restore_outline_sources(revised, section, bundle)
            repair_section = self._repair_section_from_outline(section, revised)
            self._rebuild_outline_exhibit(revised, repair_section, bundle)
            revised.content_json.pop("diagram_spec", None)
            revised.content_json["visual_qa_source_repair"] = True
            self._track_outline_source_refs(revised, section, seen_source_refs)
            repaired.append(revised)
        return repaired

    def _visual_qa_needs_source_rewrite(self, issues: list[QAIssue]) -> bool:
        content_categories = {
            "content_quality",
            "cut_off_text",
            "cut-off_text",
            "cut-off text",
            "diagram_semantic_fit",
            "incomplete_content",
            "nonsensical_copy",
            "placeholder_text",
            "raw_artifact",
            "semantic_visual_fit",
            "source_fragment",
        }
        content_tokens = (
            "boilerplate",
            "cut off",
            "cut-off",
            "dangling",
            "generic fallback",
            "grammar",
            "incomplete",
            "markdown delimiter",
            "nonsensical",
            "placeholder",
            "raw table",
            "source fragment",
            "source-fragment",
            "truncated",
        )
        for issue in issues:
            if issue.severity not in {"CRITICAL", "WARNING"}:
                continue
            category = str(issue.category or "").strip().lower()
            normalized_category = category.replace("-", "_").replace(" ", "_")
            message = str(issue.message or "").lower()
            if category in content_categories or normalized_category in content_categories:
                return True
            if any(token in message for token in content_tokens):
                return True
        return False

    def _safe_visual_repair_archetype(
        self,
        outline: SlideOutline,
        issues: list[QAIssue],
    ) -> str:
        text = " ".join(
            [
                str(outline.content_json.get("action_title") or outline.label),
                str(outline.content_json.get("subheading") or ""),
                " ".join(f"{issue.category or ''} {issue.message}" for issue in issues),
            ]
        ).lower()
        current = str(
            outline.content_json.get("archetype")
            or outline.layout_json.get("archetype")
            or outline.layout_json.get("layout")
            or ""
        ).lower().replace("-", "_")
        if current in {"dependency_map", "framework_cycle", "code_panel", "table_reference", "matrix_2x2"}:
            return "callouts"
        if current in {
            "callouts",
            "checklist",
            "comparison_table",
            "cover",
            "executive_summary",
            "icon_grid",
            "icon_rows",
            "process",
            "quote_sidebar",
            "two_column",
        }:
            return current
        if "checklist" in text or "questions" in text:
            return "checklist"
        if current in {"comparison_table", "checklist"} and (
            "nonsensical" in text or "repeated identically" in text or "purely tabular" in text
        ):
            return "callouts"
        return "icon_rows" if outline.slide_index % 2 else "callouts"

    def _set_outline_archetype(self, outline: SlideOutline, archetype: str) -> None:
        layout = "chart" if archetype == "metric_chart" else archetype
        outline.content_json["archetype"] = archetype
        outline.layout_json["archetype"] = archetype
        outline.layout_json["layout"] = layout
        outline.layout_json["visual_elements"] = self._visual_elements_for_layout(layout)

    def _repair_section_from_outline(
        self,
        section: DocumentSection | None,
        outline: SlideOutline,
    ) -> DocumentSection | None:
        if section is None:
            return None
        bullets = [
            str(item)
            for item in outline.content_json.get("bullets", [])
            if str(item).strip()
        ]
        if not bullets:
            return section
        return DocumentSection(
            title=section.title,
            level=section.level,
            content="\n".join(bullets),
            source_doc_id=section.source_doc_id,
            source_id=getattr(section, "source_id", ""),
        )

    def _direct_benchmark_outline_title(self, outline: SlideOutline, title: str) -> str:
        normalized = " ".join(str(title).split())
        lowered = normalized.lower()
        if not lowered:
            return ""
        context = " ".join(
            [
                lowered,
                str(outline.content_json.get("subheading") or ""),
                str(outline.content_json.get("speaker_notes") or ""),
                " ".join(str(item) for item in outline.content_json.get("sources", [])),
                self._flatten_exhibit_value(outline.content_json.get("exhibit_spec")),
                " ".join(self._outline_bullets(outline)),
            ]
        ).lower()
        generic_frame = bool(
            re.match(
                r"^(make|turn|clarify|review)\b.+\b"
                r"(explicit operating decision|before teams act|generated output|case for)\b",
                lowered,
            )
        ) or bool(
            re.match(
                r"^(translate|convert)\s+(executive summary|business case|evidence)\b",
                lowered,
            )
        ) or bool(
            re.match(
                r"^(translate|convert)\b.+\bdistinct operating decision\b",
                lowered,
            )
        ) or bool(
            re.match(
                r"^commit\s+to\s+the\s+recommendation\b",
                lowered,
            )
            and re.search(
                r"\b(benchmark|evaluation|harness|ground truth|model contract)\b",
                context,
            )
        ) or bool(
            re.match(
                r"^use\s+(?:the\s+)?(?:harness-centric view|harness centric view|"
                r"introduction|source evidence|conclusion|future directions|"
                r"executive summary)\b",
                lowered,
            )
            and re.search(
                r"\b(benchmark|evaluation|harness|ground truth|model contract)\b",
                context,
            )
        )
        source_heading_echo = any(
            phrase in lowered
            for phrase in (
                "conclusion and future directions",
                "closing remarks",
                "executive summary",
                "the harness interface",
                "why not simply generate synthetic benchmarks",
            )
        )
        if not (generic_frame or source_heading_echo):
            return ""
        return self._benchmark_title_repair(context)

    def _repair_outline_archetype_for_exhibit_issue(self, outline: SlideOutline) -> None:
        preferred = self._preferred_archetype_for_outline_text(outline)
        if not preferred:
            return
        outline.content_json["archetype"] = preferred
        outline.layout_json["archetype"] = preferred
        layout = "chart" if preferred == "metric_chart" else preferred
        outline.layout_json["layout"] = layout
        outline.layout_json["visual_elements"] = self._visual_elements_for_layout(layout)

    def _preferred_archetype_for_outline_text(self, outline: SlideOutline) -> str:
        content = outline.content_json
        parts = [
            str(content.get("action_title") or content.get("title") or outline.label),
            str(content.get("summary") or content.get("subheading") or ""),
            self._flatten_exhibit_value(content.get("exhibit_spec")),
        ]
        for bullet in self._outline_bullets(outline):
            parts.append(str(bullet))
        text = " ".join(parts).lower()
        if re.search(
            r"\b(directed dependency graph|dependency graph|file hierarchy|"
            r"dependencies|relationship map)\b",
            text,
        ):
            return "dependency_map"
        if re.search(r"\b(six[- ]phase loop|cycle|operating loop)\b", text):
            return "framework_cycle"
        if re.search(
            r"\b(six core files|core files|rules files|specification files|"
            r"reference table)\b",
            text,
        ):
            return "table_reference"
        return ""

    def _source_section_for_outline(
        self, outline: SlideOutline, bundle: DocumentBundle
    ) -> DocumentSection | None:
        refs = outline.content_json.get("source_refs")
        matches: list[DocumentSection] = []
        if isinstance(refs, list):
            for ref in refs:
                match = self._section_for_source_ref(str(ref), bundle)
                if match:
                    matches.append(match)
        if matches:
            return self._best_source_section_match(outline, matches)
        if not bundle.sections:
            return None
        index = min(max(outline.slide_index, 0), len(bundle.sections) - 1)
        candidate = bundle.sections[index]
        if self._is_low_value_source_section(candidate, outline):
            alternative = self._alternate_source_section(
                candidate,
                bundle,
                set(),
                outline.slide_index,
            )
            return alternative or candidate
        return candidate

    def _best_source_section_match(
        self,
        outline: SlideOutline,
        matches: list[DocumentSection],
    ) -> DocumentSection:
        if len(matches) == 1:
            return matches[0]
        outline_text = " ".join(
            [
                str(outline.content_json.get("action_title") or outline.label),
                str(outline.content_json.get("subheading") or ""),
                " ".join(self._outline_bullets(outline)),
            ]
        ).lower()

        def score(section: DocumentSection) -> tuple[int, int, int]:
            title = self._clean_section_title(section.title).lower()
            source_text = f"{section.title} {section.content}".lower()
            low_value = self._is_low_value_source_section(section, outline)
            overlap = len(
                {
                    token
                    for token in re.findall(r"[a-z][a-z0-9-]{3,}", title)
                    if token in outline_text
                }
            )
            domain_hits = sum(
                1
                for token in (
                    "benchmark",
                    "harness",
                    "ground truth",
                    "model contract",
                    "synthetic",
                    "data catalog",
                    "confidence",
                    "evaluation",
                )
                if token in source_text and token in outline_text
            )
            return (0 if low_value else 1, domain_hits, overlap)

        return max(matches, key=score)

    def _is_low_value_source_section(
        self,
        section: DocumentSection,
        outline: SlideOutline | None = None,
    ) -> bool:
        title = self._clean_section_title(section.title).lower()
        content = " ".join(section.content.split())
        if outline is not None:
            role = str(
                outline.content_json.get("narrative_role")
                or outline.layout_json.get("narrative_role")
                or ""
            ).lower()
            layout = str(outline.layout_json.get("layout") or "").lower()
            if role == "cover" or layout == "cover" or outline.slide_index == 0:
                return False
        if title in {"overview", "title", "agenda"} and len(content.split()) < 40:
            return True
        return title in {"contents", "table of contents"}

    def _section_for_source_ref(
        self, ref: str, bundle: DocumentBundle
    ) -> DocumentSection | None:
        if not ref:
            return None
        for section in bundle.sections:
            if getattr(section, "source_id", "") == ref:
                return section
        if ":" in ref:
            title = ref.split(":", 1)[-1].casefold()
            for section in bundle.sections:
                if self._clean_section_title(section.title).casefold() == title:
                    return section
        return None

    def _alternate_source_section(
        self,
        section: DocumentSection | None,
        bundle: DocumentBundle,
        seen_source_refs: set[str],
        slide_index: int,
    ) -> DocumentSection | None:
        candidates = bundle.sections or []
        if not candidates:
            return section
        for candidate in candidates[slide_index:] + candidates[:slide_index]:
            key = getattr(candidate, "source_id", "") or self._source_ref(
                candidate,
                slide_index,
            )
            if self._is_low_value_source_section(candidate):
                continue
            if key and key not in seen_source_refs:
                return candidate
        return section

    def _consulting_title_for_section(
        self, section: DocumentSection | None, outline: SlideOutline
    ) -> str:
        current = str(
            outline.content_json.get("action_title")
            or outline.content_json.get("title")
            or outline.label
        )
        context = " ".join(
            [
                current,
                str(outline.content_json.get("subheading") or ""),
                str(outline.content_json.get("speaker_notes") or ""),
                self._flatten_exhibit_value(outline.content_json.get("exhibit_spec")),
            ]
        ).lower()
        benchmark_title = self._benchmark_title_repair(context)
        if benchmark_title:
            return benchmark_title
        if section:
            return self._truncate_title(self._action_title(section.title, section.content))
        return self._truncate_title(self._repair_dangling_fragment(current))

    def _unique_consulting_title(
        self,
        title: str,
        section: DocumentSection | None,
        seen_titles: set[str],
        seen_prefixes: set[str] | None = None,
    ) -> str:
        seen_prefixes = seen_prefixes if seen_prefixes is not None else set()

        def _accept(text: str) -> str | None:
            cand = self._truncate_title(text)
            keys = self._title_seen_keys(cand)
            prefix = self._title_subject_prefix(cand)
            if keys & seen_titles:
                return None
            if prefix and prefix in seen_prefixes:
                return None
            seen_titles.update(keys)
            if prefix:
                seen_prefixes.add(prefix)
            return cand

        primary = _accept(title or "Clarify the next decision")
        if primary:
            return primary
        source_label = self._clean_section_title(section.title) if section else "next step"
        subject = self._clean_title_subject(source_label).lower()
        themed = (
            self._themed_action_title(subject, f"{section.title} {section.content}".lower())
            if section
            else ""
        )
        # Vary the leading verb so two slides on the same subject do not collide
        # on a shared opening phrase (and replace the old awkward "Use X to
        # sharpen the next operating choice" / "Tie X to ..." scaffolding copy).
        alternatives = [
            *self._question_subject_titles(subject),
            themed,
            f"Ground the next decision in {subject}",
            f"Turn {subject} into a repeatable operating step",
            f"Bind {subject} to source-backed evidence",
            f"Act on {subject} before scaling the work",
        ]
        for alternative in alternatives:
            if not alternative:
                continue
            accepted = _accept(alternative)
            if accepted:
                return accepted
        suffix = len(seen_titles) + 1
        candidate = self._truncate_title(f"Resolve decision path {suffix} with source evidence")
        seen_titles.update(self._title_seen_keys(candidate))
        return candidate

    def _question_subject_titles(self, subject: str) -> list[str]:
        cleaned = " ".join(str(subject).split())
        lowered = cleaned.lower()
        if "executive summary" in lowered:
            return [
                "Harness-centric discovery turns enterprise evidence into benchmark cases",
                "Current benchmarks need harnesses that discover operational truth",
            ]
        if "model contract" in lowered:
            return [
                "Model contracts bind expectations to executable benchmark rules",
                "Model contracts turn evaluation expectations into testable rules",
            ]
        if lowered.startswith("why "):
            return [f"Clarify {cleaned} before teams act"]
        if lowered.startswith("how to "):
            return [f"Define how to {cleaned[7:]} before execution begins"]
        if lowered.startswith("how "):
            return [f"Define {cleaned} before execution begins"]
        if lowered.startswith("when "):
            return [f"Set {cleaned} before execution begins"]
        if lowered.startswith("what "):
            return [f"Clarify {cleaned} before teams act"]
        return []

    def _title_seen_keys(self, title: str) -> set[str]:
        keys: set[str] = set()
        title_key = self._qa_key(title)
        if title_key:
            keys.add(f"title:{title_key}")
        frame_key = self._title_frame_key(title)
        if frame_key:
            keys.add(f"frame:{frame_key}")
        return keys

    def _title_frame_key(self, title: str) -> str:
        words = self._qa_key(title).split()
        if len(words) < 6:
            return ""
        for connector in ("so", "before", "after", "through", "with", "into", "as", "to"):
            if connector not in words:
                continue
            index = words.index(connector)
            tail = words[index + 1 :]
            if index >= 2 and len(tail) >= 3:
                return " ".join([words[0], connector, *tail])
        return ""

    def _replace_outline_bullets_from_source(
        self,
        outline: SlideOutline,
        section: DocumentSection | None,
        seen_bullets: set[str],
        prefer_claim_fallbacks: bool = False,
    ) -> None:
        bullets = (
            self._source_rewrite_bullets(
                section,
                4,
                prefer_claim_fallbacks=prefer_claim_fallbacks,
            )
            if section
            else self._outline_bullets(outline)[:4]
        )
        cleaned = []
        for bullet in bullets:
            key = self._qa_key(bullet)
            if key and key not in seen_bullets:
                cleaned.append(bullet)
                seen_bullets.add(key)
        if not cleaned:
            cleaned = bullets[:3]
        outline.content_json["bullets"] = cleaned[:4]
        blocks = outline.content_json.get("content_blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "bullets":
                    block["body"] = cleaned[:4]
                    break

    def _source_rewrite_bullets(
        self,
        section: DocumentSection | None,
        count: int,
        prefer_claim_fallbacks: bool = False,
    ) -> list[str]:
        if section is None:
            return []
        candidates = [
            self._polish_source_bullet(item)
            for item in self._section_phrases(section, count + 4)
        ]
        fallbacks = [
            self._polish_source_bullet(item)
            for item in self._section_claim_fallbacks(section)
        ]
        if self._has_source_claim_fallback(section):
            fallback_clean = [
                item
                for item in fallbacks
                if item and not self._looks_like_bad_slide_fragment(item)
            ]
            if prefer_claim_fallbacks:
                if len(fallback_clean) >= 3:
                    return fallback_clean[:count]
                candidates = [*fallbacks, *candidates]
            else:
                candidates = [*candidates, *fallbacks]
        else:
            candidates = [*candidates, *fallbacks]
        cleaned: list[str] = []
        for item in candidates:
            if not item or self._looks_like_bad_slide_fragment(item):
                continue
            if item not in cleaned:
                cleaned.append(item)
            if len(cleaned) >= count:
                return cleaned[:count]
        return cleaned[:count] or [self._polish_source_bullet(section.title)]

    def _polish_source_bullet(self, text: str) -> str:
        cleaned = self._repair_dangling_fragment(" ".join(str(text).split()))
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:;,.")
        if not cleaned:
            return ""
        if len(cleaned) > 160:
            cleaned = self._repair_dangling_fragment(
                cleaned[:160].rsplit(" ", 1)[0].rstrip(" ,;:.")
            )
        return cleaned if cleaned.endswith((".", "?", "!")) else f"{cleaned}."

    def _looks_like_bad_slide_fragment(self, text: str) -> bool:
        cleaned = " ".join(str(text).split()).strip()
        lowered = cleaned.lower().rstrip(".")
        if not lowered:
            return True
        if cleaned[0].islower() and not cleaned.startswith(("e.g.", "i.e.")):
            return True
        if cleaned.count("(") != cleaned.count(")"):
            return True
        if "..." in cleaned or "…" in cleaned:
            return True
        if re.search(r"\b(?:e\.g|i\.e)\.?$", lowered):
            return True
        if re.search(
            r"\b(?:determine|worked on|consisted|consists|contain|contains|"
            r"cannot|create|creates|define|defines|generate|make|makes|"
            r"reflect|reflects|specified|specifies|standardize|standardizes|"
            r"test|treat|requires|include|includes|"
            r"evaluate|evaluated|defined|real-world|development of|proliferation of|"
            r"instead of looking)$",
            lowered,
        ):
            return True
        if lowered in {
            "architecture overview",
            "closing remarks",
            "executive summary",
            "historically",
            "however",
            "introduction",
            "prediction",
            "predictions",
            "the model contract",
            "the problem",
            "the solution",
        }:
            return True
        if re.search(r"\b(?:cannot|can|make|makes|around|through|from|to)\s+is\b", lowered):
            return True
        if re.search(
            r"^(use this evidence to decide|review evidence for|frame the request|"
            r"prime the agent|generate bounded changes|review output before|"
            r"name the decision and success criteria|instead of looking|"
            r"this white paper has presented|the key contributions are|"
            r"a reframing of|rather than treating)",
            lowered,
        ):
            return True
        return False

    def _has_source_claim_fallback(self, section: DocumentSection) -> bool:
        text = f"{section.title} {section.content}".lower()
        return any(
            token in text
            for token in (
                "benchmark",
                "ground truth",
                "harness",
                "model contract",
                "data catalog",
                "confidence calibration",
            )
        )

    def _section_claim_fallbacks(self, section: DocumentSection) -> list[str]:
        title = self._clean_section_title(section.title).lower()
        text = f"{section.title} {section.content}".lower()
        if "harness-centric view" in title:
            return [
                "The harness-centric view treats benchmark generation as a validity problem, not a data-generation task.",
                "The agent should reason about what makes a test meaningful before it creates cases.",
                "Existing workflows become evaluation evidence when the harness captures rules, inputs, and review gates.",
            ]
        if "case for implicit ground truth" in title:
            return [
                "Implicit ground truth already exists in operational data, approved documents, replicated experiments, and decisions.",
                "Agents can discover benchmark cases by finding evidence that real processes have already validated.",
                "The discovery approach scales because it reuses enterprise evidence instead of relying on manual labeling.",
            ]
        if "questions the model contract" in title:
            return [
                "The model contract must specify inputs, outputs, success criteria, and allowed evaluation procedures.",
                "Each contract question turns ambiguous model behavior into an executable benchmark requirement.",
                "Answering the six questions gives agents enough structure to generate valid test cases.",
            ]
        if title == "the model contract" or title.endswith("model contract"):
            return [
                "Model contracts make inputs, outputs, success criteria, and evaluation rules explicit.",
                "A contract gives humans, agents, and harnesses a shared definition of what must be tested.",
                "The contract should answer the operational questions required to build valid benchmark cases.",
            ]
        if "harness interface" in title:
            return [
                "Harness interfaces standardize benchmark execution across domains.",
                "The interface turns a declarative model contract into repeatable evaluation mechanics.",
                "A lifecycle for harness execution helps teams reproduce, update, and compare benchmark runs.",
            ]
        if "closing remarks" in title:
            return [
                "Evaluation systems must shift from manual benchmark creation to systematic ground-truth discovery.",
                "Organizations need benchmarks that reflect their own consequential use cases.",
                "Human effort should move toward defining validity, reviewing evidence, and governing deployment.",
            ]
        if "future directions" in title or "conclusion" in title:
            return [
                "Data catalogs make benchmark discovery easier to scale across enterprise sources.",
                "Schema discovery and metadata extraction determine how reliably agents can find usable evidence.",
                "Confidence calibration matters because source evidence varies in certainty and review quality.",
            ]
        if "introduction" in title and "benchmark" in text:
            return [
                "Public benchmarks are saturating as frontier models learn to perform well on static tests.",
                "The benchmark problem is shifting from data scarcity to operational validity.",
                "Executives need evaluation systems that reflect real use cases rather than generic leaderboard tasks.",
            ]
        if "executive summary" in title and "benchmark" in text:
            return [
                "Current benchmarking is constrained by saturation, high labeling cost, and weak fit to enterprise use cases.",
                "Agent-assisted discovery can find implicit ground truth inside already validated organizational workflows.",
                "The recommended shift is from manual benchmark creation to governed evidence discovery.",
            ]
        if "synthetic benchmark" in text or "why not simply generate" in title:
            return [
                "Synthetic benchmarks can create circular validation loops without operational grounding.",
                "Source-grounded harnesses evaluate models against evidence that already matters to the organization.",
                "Benchmark quality improves when test cases come from real workflows rather than generated examples.",
            ]
        if "harness-centric" in text:
            return [
                "The harness-centric view treats benchmark generation as a validity problem, not a data-generation task.",
                "The agent should reason about what makes a test meaningful before it creates cases.",
                "Existing workflows become evaluation evidence when the harness captures rules, inputs, and review gates.",
            ]
        if "implicit ground truth" in text:
            return [
                "Implicit ground truth already exists in operational data, approved documents, replicated experiments, and decisions.",
                "Agents can discover benchmark cases by finding evidence that real processes have already validated.",
                "The discovery approach scales because it reuses enterprise evidence instead of relying on manual labeling.",
            ]
        if "architecture" in title or "orchestration" in text:
            return [
                "The architecture coordinates discovery, contracts, harnesses, and validation into one evaluation system.",
                "The orchestration layer decides which evidence and model contract are needed for each benchmark.",
                "Reproducibility depends on linking generated tests back to source data and harness execution.",
            ]
        if "bootstrapping" in title or "bootstrapping strategies" in text:
            return [
                "Bootstrapping strategies turn proprietary data into reusable ground-truth evidence.",
                "Extractive methods work when source documents contain verifiable claims or references.",
                "Validation strategies should match the type of enterprise evidence available.",
            ]
        if "model contract" in text:
            return [
                "Model contracts make inputs, outputs, success criteria, and evaluation rules explicit.",
                "A contract gives humans, agents, and harnesses a shared definition of what must be tested.",
                "The contract should answer the operational questions required to build valid benchmark cases.",
            ]
        if "harness interface" in text:
            return [
                "Harness interfaces standardize benchmark execution across domains.",
                "The interface turns a declarative model contract into repeatable evaluation mechanics.",
                "A lifecycle for harness execution helps teams reproduce, update, and compare benchmark runs.",
            ]
        if "data catalog" in text or "future directions" in title or "confidence calibration" in text:
            return [
                "Data catalogs make benchmark discovery easier to scale across enterprise sources.",
                "Schema discovery and metadata extraction determine how reliably agents can find usable evidence.",
                "Confidence calibration matters because source evidence varies in certainty and review quality.",
            ]
        if "closing" in title or "conclusion" in title:
            return [
                "Evaluation systems must shift from manual benchmark creation to systematic ground-truth discovery.",
                "Organizations need benchmarks that reflect their own consequential use cases.",
                "Human effort should move toward defining validity, reviewing evidence, and governing deployment.",
            ]
        return [
            self._action_title(section.title, section.content),
            f"{self._clean_section_title(section.title)} needs source-backed review before scaling.",
            f"{self._clean_section_title(section.title)} should be tied to explicit evidence and ownership.",
        ]

    def _track_outline_bullets(
        self, outline: SlideOutline, seen_bullets: set[str]
    ) -> None:
        for bullet in self._outline_bullets(outline):
            key = self._qa_key(bullet)
            if key:
                seen_bullets.add(key)

    def _track_outline_source_refs(
        self,
        outline: SlideOutline,
        section: DocumentSection | None,
        seen_source_refs: set[str],
    ) -> None:
        refs = outline.content_json.get("source_refs")
        if isinstance(refs, list):
            for ref in refs:
                if str(ref).strip():
                    seen_source_refs.add(str(ref).strip())
        if section:
            key = getattr(section, "source_id", "") or self._source_ref(
                section,
                outline.slide_index,
            )
            if key:
                seen_source_refs.add(key)

    def _outline_bullets(self, outline: SlideOutline) -> list[str]:
        bullets = outline.content_json.get("bullets")
        if isinstance(bullets, list) and bullets:
            return [str(item) for item in bullets if str(item).strip()]
        collected = []
        blocks = outline.content_json.get("content_blocks")
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                for item in block.get("body", []):
                    if isinstance(item, str) and item.strip():
                        collected.append(item)
        return collected

    def _restore_outline_sources(
        self,
        outline: SlideOutline,
        section: DocumentSection | None,
        bundle: DocumentBundle,
    ) -> None:
        if self._has_uploaded_source_material(bundle) and section:
            source_id = getattr(section, "source_id", "")
            refs = [source_id] if source_id else [self._source_ref(section, outline.slide_index)]
        elif self._has_uploaded_source_material(bundle):
            refs = [UPLOADED_SOURCE_LABEL]
        else:
            refs = [SOURCE_NEEDED_LABEL]
        outline.content_json["source_refs"] = refs
        outline.content_json["sources"] = self._source_labels_for_refs(refs, bundle) or refs

    def _rebuild_outline_exhibit(
        self,
        outline: SlideOutline,
        section: DocumentSection | None,
        bundle: DocumentBundle,
    ) -> None:
        archetype = str(
            outline.content_json.get("archetype")
            or outline.layout_json.get("archetype")
            or outline.layout_json.get("layout")
            or "reference"
        )
        role = str(outline.content_json.get("narrative_role") or "")
        tables = self._nearby_tables(section, bundle)
        metrics = self._nearby_metrics(section, bundle)
        compile_section = section
        bullets = [
            str(item)
            for item in outline.content_json.get("bullets", [])
            if str(item).strip()
        ]
        if section is not None and bullets and not tables and not metrics:
            compile_section = self._repair_section_from_outline(section, outline)
        if bullets and archetype == "callouts":
            exhibit = {"type": "callouts", "points": bullets[:4]}
        elif bullets and archetype == "icon_rows":
            exhibit = {"type": "icon_rows", "items": bullets[:4]}
        elif bullets and archetype == "two_column":
            exhibit = {
                "type": "two_column",
                "left": bullets[:2],
                "right": bullets[2:4] or bullets[:2],
                "points": bullets[:4],
            }
        else:
            exhibit = self.exhibit_compiler.compile(
                archetype,
                role,
                compile_section,
                tables,
                metrics,
            )
        outline.content_json["exhibit_spec"] = exhibit
        outline.content_json["content_blocks"] = [
            block.model_dump() for block in self.exhibit_compiler.content_blocks(exhibit)
        ]
        chart_spec = self.exhibit_compiler.chart_spec(exhibit)
        if chart_spec:
            outline.content_json["chart_spec"] = chart_spec
            outline.content_json["metrics"] = chart_spec.get("metrics", [])
        outline.layout_json["exhibit_type"] = exhibit.get("type")

    def _dedupe_rebuilt_outline_exhibit(
        self,
        outline: SlideOutline,
        section: DocumentSection | None,
        prior_seen_bullets: set[str],
        seen_bullets: set[str],
    ) -> None:
        exhibit = outline.content_json.get("exhibit_spec")
        if not isinstance(exhibit, dict):
            return
        pool = [
            *self._source_rewrite_bullets(section, 8),
            *self._section_phrases(section, 8),
            "Assign an owner before the next implementation cycle.",
            "Set the review cadence before scaling the workflow.",
            "Capture lessons in the shared operating reference.",
            "Retire stale context after each completed feature.",
        ]
        section_key = self._qa_key(self._clean_section_title(section.title)) if section else ""

        def unique_text(value: str) -> str:
            key = self._qa_key(value)
            if key and key not in prior_seen_bullets:
                prior_seen_bullets.add(key)
                seen_bullets.add(key)
                return value
            for candidate in pool:
                candidate_key = self._qa_key(candidate)
                is_section_specific = bool(
                    section_key and section_key in candidate_key
                )
                if candidate_key and (
                    candidate_key not in prior_seen_bullets or is_section_specific
                ):
                    prior_seen_bullets.add(candidate_key)
                    seen_bullets.add(candidate_key)
                    return candidate
            return value

        changed = False
        for key in ("next_steps", "supporting_points", "points"):
            values = exhibit.get(key)
            if not isinstance(values, list):
                continue
            updated = [unique_text(str(item)) for item in values if str(item).strip()]
            if updated != values:
                exhibit[key] = updated
                changed = True
        items = exhibit.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict) or not str(item.get("action") or "").strip():
                    continue
                replacement = unique_text(str(item["action"]))
                if replacement != item["action"]:
                    item["action"] = replacement
                    changed = True
        if changed:
            outline.content_json["content_blocks"] = [
                block.model_dump()
                for block in self.exhibit_compiler.content_blocks(exhibit)
            ]

    def _nearby_tables(
        self, section: DocumentSection | None, bundle: DocumentBundle
    ):
        if not bundle.tables:
            return []
        if section and getattr(section, "source_doc_id", ""):
            same_doc = [
                table
                for table in bundle.tables
                if table.source_doc_id == section.source_doc_id
            ]
            if same_doc:
                return same_doc[:2]
        return bundle.tables[:2]

    def _nearby_metrics(
        self, section: DocumentSection | None, bundle: DocumentBundle
    ):
        if not bundle.metrics:
            return []
        if section and getattr(section, "source_doc_id", ""):
            same_doc = [
                metric
                for metric in bundle.metrics
                if metric.source_doc_id == section.source_doc_id
            ]
            if same_doc:
                return same_doc[:6]
        return bundle.metrics[:6]

    def _qa_key(self, text: str) -> str:
        return " ".join(
            re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split()
        )
