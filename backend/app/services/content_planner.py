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
from app.services.planning.exhibits import ExhibitCompiler
from app.services.planning.grounding import SourceGroundingMixin
from app.services.planning.llm import LLMPlanningMixin
from app.services.planning.outlines import OutlinePlanningMixin
from app.services.planning.repairs import PlanningRepairMixin
from app.services.planning.specs import SlideSpecPlanningMixin


PLANNER_SYSTEM_PROMPT = planning_constants.PLANNER_SYSTEM_PROMPT
UPLOADED_SOURCE_LABEL = planning_constants.UPLOADED_SOURCE_LABEL
SOURCE_NEEDED_LABEL = planning_constants.SOURCE_NEEDED_LABEL


class ContentPlanner(
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
            current_title = str(
                revised.content_json.get("action_title")
                or revised.content_json.get("title")
                or revised.label
            )
            title_key = self._qa_key(current_title)
            if (
                deck_level_issue
                or title_key in seen_titles
                or issue_categories
                & {"action_title", "one_message", "horizontal_flow", "title_body_support"}
            ):
                title = self._consulting_title_for_section(section, revised)
                title = self._unique_consulting_title(title, section, seen_titles)
                revised.label = title
                revised.content_json["action_title"] = title
                revised.content_json["title"] = title
            else:
                seen_titles.add(title_key)
            if issue_categories & {"repeated_bullet", "generic_filler", "title_body_support"}:
                self._replace_outline_bullets_from_source(
                    revised, section, seen_bullets
                )
            else:
                self._track_outline_bullets(revised, seen_bullets)
            if (
                issue_categories
                & {"missing_exhibit", "exhibit_structure", "source_refs"}
            ):
                self._restore_outline_sources(revised, section, bundle)
                self._rebuild_outline_exhibit(revised, section, bundle)
            elif issue_categories & {"source_refs"}:
                self._restore_outline_sources(revised, section, bundle)
            repaired.append(revised)
        return repaired

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
        if self._qa_key(candidate) not in seen_titles:
            seen_titles.add(self._qa_key(candidate))
            return candidate
        source_label = self._clean_section_title(section.title) if section else "next step"
        alternatives = [
            f"Use {source_label.lower()} to sharpen the decision",
            f"Translate {source_label.lower()} into an owned action",
            f"Prioritize {source_label.lower()} before scaling execution",
        ]
        for alternative in alternatives:
            candidate = self._truncate_title(alternative)
            if self._qa_key(candidate) not in seen_titles:
                seen_titles.add(self._qa_key(candidate))
                return candidate
        suffix = len(seen_titles) + 1
        candidate = self._truncate_title(f"Resolve decision path {suffix} with source evidence")
        seen_titles.add(self._qa_key(candidate))
        return candidate

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
