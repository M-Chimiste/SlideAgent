import re
from typing import Any, Optional

from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.models.document import DocumentBundle, DocumentSection
from app.models.generation import DeckSpec, GenerationMode
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
from app.services.planning.outlines import OutlinePlanningMixin
from app.services.planning.repairs import PlanningRepairMixin
from app.services.planning.specs import SlideSpecPlanningMixin
from app.services.planning.spec_gate import SpecGateMixin


PLANNER_SYSTEM_PROMPT = planning_constants.PLANNER_SYSTEM_PROMPT
UPLOADED_SOURCE_LABEL = planning_constants.UPLOADED_SOURCE_LABEL
SOURCE_NEEDED_LABEL = planning_constants.SOURCE_NEEDED_LABEL


class ContentPlanner(
    ContextPlanningMixin,
    ExhibitSelectionMixin,
    SpecGateMixin,
    LLMPlanningMixin,
    BlueprintPlanningMixin,
    SlideSpecPlanningMixin,
    OutlinePlanningMixin,
    PlanningRepairMixin,
    SourceGroundingMixin,
):
    def __init__(self, llm_client: Optional[OpenAICompatibleClient] = None) -> None:
        self.llm_client = llm_client
        self._last_planning_error: str | None = None
        self._last_story_map_error: str | None = None
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
        deck = self._plan_with_llm(
            bundle,
            instructions,
            mode,
            blueprint=blueprint,
            quality_profile=quality_profile,
            source_compression=source_compression,
            story_map=story_map,
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
        deck, qa_warnings = self.qa.inspect(deck)
        warnings.extend(qa_warnings)
        return deck, warnings

    def _ensure_core_exhibit_mix(self, deck: DeckSpec, bundle: DocumentBundle) -> None:
        if len(deck.slides) < 6 or not bundle.sections:
            return
        required = ["comparison_table", "code_panel", "matrix_2x2", "icon_rows"]
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
            if "duplicate_slide" in issue_categories:
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
            title_keys = self._title_seen_keys(current_title)
            if (
                deck_level_issue
                or bool(title_keys & seen_titles)
                or issue_categories
                & {
                    "action_title",
                    "duplicate_slide",
                    "horizontal_flow",
                    "one_message",
                    "title_body_support",
                }
            ):
                title = self._consulting_title_for_section(section, revised)
                title = self._unique_consulting_title(title, section, seen_titles)
                revised.label = title
                revised.content_json["action_title"] = title
                revised.content_json["title"] = title
            else:
                seen_titles.update(title_keys)
            if issue_categories & {
                "duplicate_slide",
                "generic_filler",
                "repeated_bullet",
                "title_body_support",
            }:
                self._replace_outline_bullets_from_source(
                    revised, section, seen_bullets
                )
            else:
                self._track_outline_bullets(revised, seen_bullets)
            if (
                issue_categories
                & {
                    "duplicate_slide",
                    "exhibit_structure",
                    "generic_filler",
                    "missing_exhibit",
                    "repeated_bullet",
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
        if isinstance(refs, list):
            for ref in refs:
                match = self._section_for_source_ref(str(ref), bundle)
                if match:
                    return match
        if not bundle.sections:
            return None
        index = min(max(outline.slide_index, 0), len(bundle.sections) - 1)
        return bundle.sections[index]

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
            if key and key not in seen_source_refs:
                return candidate
        return section

    def _consulting_title_for_section(
        self, section: DocumentSection | None, outline: SlideOutline
    ) -> str:
        if section:
            return self._truncate_title(self._action_title(section.title, section.content))
        current = str(
            outline.content_json.get("action_title")
            or outline.content_json.get("title")
            or outline.label
        )
        return self._truncate_title(self._repair_dangling_fragment(current))

    def _unique_consulting_title(
        self,
        title: str,
        section: DocumentSection | None,
        seen_titles: set[str],
    ) -> str:
        candidate = self._truncate_title(title or "Clarify the next decision")
        candidate_keys = self._title_seen_keys(candidate)
        if not (candidate_keys & seen_titles):
            seen_titles.update(candidate_keys)
            return candidate
        source_label = self._clean_section_title(section.title) if section else "next step"
        subject = source_label.lower()
        themed = (
            self._themed_action_title(subject, f"{section.title} {section.content}".lower())
            if section
            else ""
        )
        alternatives = [
            *self._question_subject_titles(subject),
            themed,
            f"Make {subject} an explicit operating decision",
            f"Translate {subject} into an owned next step",
            f"Address {subject} before it shapes delivery",
        ]
        alternatives = [alternative for alternative in alternatives if alternative]
        for alternative in alternatives:
            candidate = self._truncate_title(alternative)
            candidate_keys = self._title_seen_keys(candidate)
            if not (candidate_keys & seen_titles):
                seen_titles.update(candidate_keys)
                return candidate
        suffix = len(seen_titles) + 1
        candidate = self._truncate_title(f"Resolve decision path {suffix} with source evidence")
        seen_titles.update(self._title_seen_keys(candidate))
        return candidate

    def _question_subject_titles(self, subject: str) -> list[str]:
        cleaned = " ".join(str(subject).split())
        lowered = cleaned.lower()
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
    ) -> None:
        bullets = (
            self._section_phrases(section, 4)
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
        exhibit = self.exhibit_compiler.compile(
            archetype,
            role,
            section,
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
            *self._section_phrases(section, 8),
            "Assign an owner before the next implementation cycle.",
            "Set the review cadence before scaling the workflow.",
            "Capture lessons in the shared operating reference.",
            "Retire stale context after each completed feature.",
        ]

        def unique_text(value: str) -> str:
            key = self._qa_key(value)
            if key and key not in prior_seen_bullets:
                prior_seen_bullets.add(key)
                seen_bullets.add(key)
                return value
            for candidate in pool:
                candidate_key = self._qa_key(candidate)
                if candidate_key and candidate_key not in prior_seen_bullets:
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
