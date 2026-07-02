from datetime import UTC, datetime
from typing import Any

import pytest

from app.models.brand import BrandDNA
from app.models.document import DocumentBundle, DocumentMetadata, DocumentSection
from app.models.outline import SlideOutline
from app.models.template import TemplateProfile
from app.services import content_planner as content_planner_module
from app.services.content_planner import ContentPlanner
from app.services.planning import constants as planning_constants
from app.services.pptx_renderer import DeterministicPptxRenderer
from app.services.visual_qa import constants as visual_qa_constants
from app.services.visual_qa_agent import QA_SYSTEM_PROMPT, VisualQAAgent


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _template(template_type: str = "freeform") -> TemplateProfile:
    return TemplateProfile(
        id=f"{template_type}-template",
        name=f"{template_type.title()} Template",
        type=template_type,
        brand=BrandDNA(),
        slides=[],
        source_file="",
        created_at=_timestamp(),
        updated_at=_timestamp(),
    )


def _bundle() -> DocumentBundle:
    return DocumentBundle(
        job_id="job-refactor",
        sections=[
            DocumentSection(
                title="Operating Model",
                level=1,
                content="Persistent context and explicit acceptance criteria improve agentic work.",
                source_doc_id="doc-1",
            )
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Refactor Boundary Test"),
        content_inventory=[],
    )


def _outline(layout: str) -> SlideOutline:
    return SlideOutline(
        id=f"outline-{layout}",
        job_id="job-refactor",
        slide_index=0,
        mode="flexible",
        label="Persistent context improves agentic delivery",
        content_json={
            "action_title": "Persistent context improves agentic delivery",
            "subheading": "Evidence from uploaded source",
            "bullets": ["External memory keeps work reproducible."],
            "sources": ["Uploaded source"],
        },
        layout_json={"layout": layout, "visual_elements": []},
        created_at="2026-01-01T00:00:00Z",
    )


def test_content_planner_facade_reexports_public_prompt_constants() -> None:
    assert content_planner_module.PLANNER_SYSTEM_PROMPT == planning_constants.PLANNER_SYSTEM_PROMPT
    assert content_planner_module.UPLOADED_SOURCE_LABEL == planning_constants.UPLOADED_SOURCE_LABEL
    assert content_planner_module.SOURCE_NEEDED_LABEL == planning_constants.SOURCE_NEEDED_LABEL


def test_content_planner_facade_delegates_generated_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    planner = ContentPlanner()
    sentinel_deck = object()
    calls: dict[str, Any] = {}
    returned_outline = _outline("two_column")

    def fake_plan_generated_deck(
        template: TemplateProfile,
        bundle: DocumentBundle,
        instructions: str,
        mode: str,
        quality_profile: str = "balanced",
        length_strategy: str = "auto",
    ) -> tuple[object, list[dict[str, str]]]:
        calls["generated"] = {
            "template": template,
            "bundle": bundle,
            "instructions": instructions,
            "mode": mode,
            "quality_profile": quality_profile,
            "length_strategy": length_strategy,
        }
        return sentinel_deck, [{"field": "llm_planning", "message": "kept"}]

    def fake_deck_to_outlines(deck: object, job_id: str, mode: str) -> list[SlideOutline]:
        calls["outlines"] = {"deck": deck, "job_id": job_id, "mode": mode}
        return [returned_outline]

    monkeypatch.setattr(planner, "_plan_generated_deck", fake_plan_generated_deck)
    monkeypatch.setattr(planner, "_deck_to_outlines", fake_deck_to_outlines)

    outlines, warnings = planner.plan(
        _template("brand"),
        _bundle(),
        instructions="Create the deck.",
        generation_mode="brand",
        quality_profile="showcase",
        length_strategy="expanded",
    )

    assert outlines == [returned_outline]
    assert warnings == [{"field": "llm_planning", "message": "kept"}]
    assert calls["generated"]["mode"] == "brand"
    assert calls["generated"]["quality_profile"] == "showcase"
    assert calls["generated"]["length_strategy"] == "expanded"
    assert calls["outlines"] == {
        "deck": sentinel_deck,
        "job_id": "job-refactor",
        "mode": "brand",
    }


@pytest.mark.parametrize(
    ("layout", "expected"),
    [
        ("cover", ["_add_cover", "_add_logo"]),
        ("section_divider", ["_add_section_divider", "_add_logo"]),
        ("framework_cycle", ["_add_framework_cycle_immersive", "_add_logo"]),
        ("quote_sidebar", ["_add_quote_sidebar_immersive", "_add_logo"]),
        ("closing_recommendation", ["_add_closing_recommendation_immersive", "_add_logo"]),
        ("executive_summary", ["_add_header", "_add_logo", "_add_footer", "_add_executive_summary"]),
        ("chart", ["_add_header", "_add_logo", "_add_footer", "_add_metric_chart"]),
        ("comparison_table", ["_add_header", "_add_logo", "_add_footer", "_add_comparison_table"]),
        ("callouts", ["_add_header", "_add_logo", "_add_footer", "_add_callouts"]),
        ("process", ["_add_header", "_add_logo", "_add_footer", "_add_table_or_process"]),
        ("dependency_map", ["_add_header", "_add_logo", "_add_footer", "_add_dependency_map"]),
        ("checklist", ["_add_header", "_add_logo", "_add_footer", "_add_checklist"]),
        ("code_panel", ["_add_header", "_add_logo", "_add_footer", "_add_code_panel"]),
        ("anti_patterns", ["_add_header", "_add_logo", "_add_footer", "_add_anti_patterns"]),
        ("table_reference", ["_add_header", "_add_logo", "_add_footer", "_add_reference_table"]),
        ("icon_grid", ["_add_header", "_add_logo", "_add_footer", "_add_grid"]),
        ("icon_rows", ["_add_header", "_add_logo", "_add_footer", "_add_icon_rows"]),
        ("unknown", ["_add_header", "_add_logo", "_add_footer", "_add_two_column"]),
    ],
)
def test_renderer_facade_dispatches_layouts(
    monkeypatch: pytest.MonkeyPatch,
    layout: str,
    expected: list[str],
) -> None:
    renderer = DeterministicPptxRenderer()
    calls: list[str] = []
    method_names = {
        "_add_cover",
        "_add_logo",
        "_add_section_divider",
        "_add_framework_cycle_immersive",
        "_add_quote_sidebar_immersive",
        "_add_closing_recommendation_immersive",
        "_add_header",
        "_add_footer",
        "_add_executive_summary",
        "_add_metric_chart",
        "_add_comparison_table",
        "_add_callouts",
        "_add_table_or_process",
        "_add_dependency_map",
        "_add_checklist",
        "_add_code_panel",
        "_add_anti_patterns",
        "_add_reference_table",
        "_add_grid",
        "_add_icon_rows",
        "_add_two_column",
    }

    for method_name in method_names:
        monkeypatch.setattr(
            renderer,
            method_name,
            lambda *args, _method_name=method_name, **kwargs: calls.append(_method_name),
        )

    renderer._render_slide(object(), _outline(layout), BrandDNA(), slide_number=1, total_slides=3)

    assert calls == expected


def test_visual_qa_facade_reexports_prompt_and_keeps_public_method() -> None:
    assert QA_SYSTEM_PROMPT == visual_qa_constants.QA_SYSTEM_PROMPT
    assert callable(VisualQAAgent().inspect_deck)
