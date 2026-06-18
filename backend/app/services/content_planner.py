from typing import Any, Optional

from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.models.document import DocumentBundle
from app.models.generation import DeckSpec, GenerationMode
from app.models.outline import SlideOutline
from app.models.template import TemplateProfile
from app.services.consulting_qa import ConsultingQA
from app.services.planning.blueprint import BlueprintPlanningMixin
from app.services.planning import constants as planning_constants
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
