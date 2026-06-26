import json
import re
import zipfile
from io import BytesIO
from datetime import UTC, datetime
from pathlib import Path

import pytest
from lxml import etree
from openpyxl import load_workbook
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches

from app.config import Settings
from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.models.brand import BrandDNA
from app.models.document import DocumentBundle, DocumentMetadata, DocumentMetric, DocumentSection
from app.models.generation import ContentBlock, DeckBlueprint, DeckSpec, GeneratedSlideSpec
from app.models.outline import SlideOutline
from app.models.planning import StoryMap
from app.models.qa import QAIssue
from app.models.template import SlideField, SlideSchema, SlideSpec, TemplateProfile
from app.services.content_planner import ContentPlanner, PlanningFailedError
from app.services.design_agent import DesignAgent
from app.services.document_ingester import DocumentIngester
from app.services.authored_pptx_renderer import AuthoredPptxRenderer
from app.services.generation_editing_contract import GenerationEditingContract
from app.services.planning.exhibits import ExhibitCompiler
from app.services.pptx_builder import PptxBuilder
from app.services.pptx_renderer import DeterministicPptxRenderer
from app.services.rendered_slide_audit import RenderedSlideAudit
from app.services.strict_injector import StrictSlideInjector
from app.services.template_analyzer import TemplateAnalyzer


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _template(template_type: str = "freeform", source_file: str = "") -> TemplateProfile:
    return TemplateProfile(
        id=f"{template_type}-template",
        name=f"{template_type.title()} Template",
        type=template_type,
        brand=BrandDNA(),
        slides=[],
        source_file=source_file,
        created_at=_timestamp(),
        updated_at=_timestamp(),
    )


def _bundle(job_id: str = "job-1") -> DocumentBundle:
    return DocumentBundle(
        job_id=job_id,
        sections=[
            DocumentSection(
                title="Developer Productivity",
                level=1,
                content=(
                    "Engineering teams are using AI coding assistants broadly, "
                    "but review discipline and architecture judgment remain uneven."
                ),
                source_doc_id="doc-1",
            ),
            DocumentSection(
                title="Quality Risk",
                level=1,
                content=(
                    "Fast code generation can increase defects unless teams add "
                    "testing, architectural review, and acceptance criteria."
                ),
                source_doc_id="doc-1",
            ),
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[],
    )


def test_visual_qa_repair_rewrites_bad_rendered_fragments_from_source() -> None:
    source_id = "doc-1:section:why-not-synthetic"
    bundle = DocumentBundle(
        job_id="job-visual-repair",
        sections=[
            DocumentSection(
                title="Why Not Simply Generate Synthetic Benchmarks?",
                level=1,
                content=(
                    "Synthetic benchmark generation creates circular validation loops "
                    "without grounding in operational reality. Source-grounded harnesses "
                    "evaluate models against evidence that already matters to the organization."
                ),
                source_doc_id="doc-1",
                source_id=source_id,
            )
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Bootstrapping Benchmarks"),
        content_inventory=[],
        source_index={
            source_id: {
                "label": "Bootstrapping Benchmarks > Why Not Simply Generate Synthetic Benchmarks?",
                "type": "section",
            }
        },
    )
    outline = SlideOutline(
        id="slide-1",
        job_id=bundle.job_id,
        slide_index=0,
        mode="flexible",
        label="Harness-centric design turns existing workflows into evaluation evidence",
        content_json={
            "action_title": "Harness-centric design turns existing workflows into evaluation evidence",
            "subheading": "Source-backed repair case",
            "archetype": "table_reference",
            "source_refs": [source_id],
            "sources": ["Uploaded source"],
            "bullets": [
                "Instead of looking",
                "Connect the harness-centric",
                "Make the harness-centric",
            ],
            "content_blocks": [
                {
                    "type": "table",
                    "body": [
                        ["Artifact", "Purpose", "Update trigger"],
                        ["Instead of looking", "Instead of looking at using models", "When conditions change"],
                    ],
                }
            ],
            "exhibit_spec": {
                "type": "reference_table",
                "columns": ["Artifact", "Purpose", "Update trigger"],
                "rows": [
                    ["Instead of looking", "Instead of looking at using models", "When conditions change"],
                ],
            },
        },
        layout_json={"layout": "table_reference", "archetype": "table_reference"},
        created_at=_timestamp(),
    )
    issues = [
        QAIssue(
            severity="CRITICAL",
            category="nonsensical copy",
            message="The table content is nonsensical and incomplete.",
            slide_index=0,
        ),
        QAIssue(
            severity="CRITICAL",
            category="cut-off text",
            message="Text is cut off in multiple columns.",
            slide_index=0,
        ),
    ]

    repaired = ContentPlanner().repair_outlines_for_visual_qa([outline], issues, bundle)

    content = json.dumps(repaired[0].content_json).lower()
    assert repaired[0].layout_json["layout"] == "callouts"
    assert "synthetic benchmarks can create circular validation loops" in content
    assert "source-grounded harnesses evaluate models" in content
    assert "instead of looking" not in content
    assert "when conditions change" not in content
    assert "review evidence for" not in content
    assert "diagram_spec" not in repaired[0].content_json


def test_visual_qa_repair_ignores_visual_only_warnings() -> None:
    source_id = "doc-1:section:visual-only"
    bundle = DocumentBundle(
        job_id="job-visual-only",
        sections=[
            DocumentSection(
                title="Harness Interface",
                level=1,
                content=(
                    "The harness interface standardizes execution, records evidence, "
                    "and keeps benchmark runs comparable across domains."
                ),
                source_doc_id="doc-1",
                source_id=source_id,
            )
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Bootstrapping Benchmarks"),
        content_inventory=[],
        source_index={
            source_id: {
                "label": "Bootstrapping Benchmarks > Harness Interface",
                "type": "section",
            }
        },
    )
    outline = SlideOutline(
        id="slide-visual-only",
        job_id=bundle.job_id,
        slide_index=0,
        mode="flexible",
        label="Harness interfaces standardize benchmark execution across domains",
        content_json={
            "action_title": "Harness interfaces standardize benchmark execution across domains",
            "subheading": "Operational execution",
            "narrative_role": "evidence",
            "archetype": "checklist",
            "source_refs": [source_id],
            "sources": ["Uploaded source"],
            "bullets": [
                "Standardize execution across domains.",
                "Record evidence beside benchmark runs.",
                "Keep repeated runs comparable.",
            ],
            "exhibit_spec": {
                "type": "checklist",
                "items": [
                    {"action": "Standardize execution across domains."},
                    {"action": "Record evidence beside benchmark runs."},
                    {"action": "Keep repeated runs comparable."},
                ],
            },
        },
        layout_json={"layout": "checklist", "archetype": "checklist"},
        created_at=_timestamp(),
    )
    issues = [
        QAIssue(
            severity="WARNING",
            category="spacing",
            message="The slide has generous spacing and could use stronger visual balance.",
            slide_index=0,
        ),
        QAIssue(
            severity="INFO",
            category="nonsensical_copy",
            message="The phrase is a little vague but still readable.",
            slide_index=0,
        ),
    ]

    repaired = ContentPlanner().repair_outlines_for_visual_qa([outline], issues, bundle)

    assert repaired[0].content_json["bullets"] == outline.content_json["bullets"]
    assert repaired[0].layout_json["layout"] == "checklist"
    assert "visual_qa_source_repair" not in repaired[0].content_json


def test_visual_qa_repair_prefers_real_evidence_over_overview_section() -> None:
    overview_ref = "doc-1:section:overview"
    summary_ref = "doc-1:section:executive-summary"
    bundle = DocumentBundle(
        job_id="job-overview-repair",
        sections=[
            DocumentSection(
                title="Overview",
                level=1,
                content="Bootstrapping the Creation of Testing Benchmarks",
                source_doc_id="doc-1",
                source_id=overview_ref,
            ),
            DocumentSection(
                title="Executive Summary",
                level=1,
                content=(
                    "Current benchmarking is constrained by saturation, high labeling cost, "
                    "and weak fit to enterprise use cases. Agent-assisted discovery can find "
                    "implicit ground truth inside already validated organizational workflows."
                ),
                source_doc_id="doc-1",
                source_id=summary_ref,
            ),
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Bootstrapping Benchmarks"),
        content_inventory=[],
        source_index={
            overview_ref: {"label": "Bootstrapping Benchmarks > Overview", "type": "section"},
            summary_ref: {"label": "Bootstrapping Benchmarks > Executive Summary", "type": "section"},
        },
    )
    outline = SlideOutline(
        id="slide-overview",
        job_id=bundle.job_id,
        slide_index=4,
        mode="flexible",
        label="Use real use-case benchmarks instead of generic public evaluations",
        content_json={
            "action_title": "Use real use-case benchmarks instead of generic public evaluations",
            "subheading": "Evidence repair case",
            "narrative_role": "evidence",
            "archetype": "callouts",
            "source_refs": [overview_ref, summary_ref],
            "sources": ["Uploaded source"],
            "bullets": ["Bootstrapping the Creation"],
            "exhibit_spec": {"type": "callouts", "points": ["Bootstrapping the Creation"]},
        },
        layout_json={"layout": "callouts", "archetype": "callouts"},
        created_at=_timestamp(),
    )
    issues = [
        QAIssue(
            severity="CRITICAL",
            category="content_quality",
            message="Rendered slide contains source-fragment text instead of authored copy.",
            slide_index=4,
        )
    ]

    repaired = ContentPlanner().repair_outlines_for_visual_qa([outline], issues, bundle)

    content = json.dumps(repaired[0].content_json).lower()
    assert repaired[0].content_json["source_refs"] == [summary_ref]
    assert "current benchmarking is constrained" in content
    assert "bootstrapping the creation" not in content


def test_authored_renderer_keeps_source_repair_slides_out_of_fake_anti_patterns(tmp_path) -> None:
    outline = SlideOutline(
        id="slide-source-repair",
        job_id="job-render-repair",
        slide_index=2,
        mode="flexible",
        label="Use source-grounded harnesses instead of synthetic benchmark shortcuts",
        content_json={
            "action_title": "Use source-grounded harnesses instead of synthetic benchmark shortcuts",
            "subheading": "Source-backed repair case",
            "narrative_role": "problem",
            "archetype": "callouts",
            "visual_qa_source_repair": True,
            "bullets": [
                "Synthetic benchmarks can create circular validation loops without operational grounding.",
                "Source-grounded harnesses evaluate models against evidence that already matters.",
                "Benchmark quality improves when test cases come from real workflows.",
            ],
            "exhibit_spec": {
                "type": "callouts",
                "points": [
                    "Synthetic benchmarks can create circular validation loops without operational grounding.",
                    "Source-grounded harnesses evaluate models against evidence that already matters.",
                    "Benchmark quality improves when test cases come from real workflows.",
                ],
            },
            "source_refs": ["doc-1:section:synthetic"],
            "sources": ["Bootstrapping Benchmarks > Synthetic Benchmarks"],
        },
        layout_json={"layout": "callouts", "archetype": "callouts"},
        created_at=_timestamp(),
    )
    pptx_path = tmp_path / "source-repair.pptx"

    authored = AuthoredPptxRenderer().author_outlines([outline])
    AuthoredPptxRenderer().render([outline], BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, authored)

    visible = " ".join(" ".join(slide["text"]) for slide in payload["slides"]).lower()
    assert authored[0].layout_json["composition_family"] != "source_repair_cards"
    assert "better move" not in visible
    assert "symptom:" not in visible
    assert "synthetic benchmarks can create circular validation loops" in visible
    assert not issues


def test_anti_pattern_renderer_rejects_truncated_benchmark_fragments(tmp_path) -> None:
    outline = SlideOutline(
        id="anti-pattern-fragments",
        job_id="job-render-fragments",
        slide_index=0,
        mode="flexible",
        label="Synthetic benchmarks cannot substitute for validated operating evidence",
        content_json={
            "action_title": "Synthetic benchmarks cannot substitute for validated operating evidence",
            "subheading": "Show the failure modes that put benchmark quality at risk.",
            "narrative_role": "problem",
            "archetype": "anti_patterns",
            "bullets": [
                "Synthetic benchmarks can create circular validation loops without operational grounding.",
                "Source-grounded harnesses evaluate models against evidence that already matters.",
                "Benchmark quality improves when test cases come from real workflows.",
            ],
            "exhibit_spec": {
                "type": "anti_patterns",
                "patterns": [
                    {
                        "name": "Synthetic benchmarks can",
                        "symptom": "Synthetic benchmarks can create circular validation loops without",
                        "better_behavior": "Add a durable rule.",
                    },
                    {
                        "name": "Source-grounded harnesses",
                        "symptom": "Source-grounded harnesses evaluate models against evidence that already",
                        "better_behavior": "Add a durable rule.",
                    },
                    {
                        "name": "Benchmark quality improves",
                        "symptom": "Benchmark quality improves when test cases come from real workflows rather",
                        "better_behavior": "Add a durable rule.",
                    },
                ],
            },
            "source_refs": ["doc-1:section:synthetic"],
            "sources": ["Bootstrapping Benchmarks > Synthetic Benchmarks"],
        },
        layout_json={"layout": "anti_patterns", "archetype": "anti_patterns"},
        created_at=_timestamp(),
    )
    pptx_path = tmp_path / "anti-pattern-fragments.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, [outline])

    visible = " ".join(" ".join(slide["text"]) for slide in payload["slides"])
    assert "without Better move" not in visible
    assert "already Better move" not in visible
    assert "rather Better move" not in visible
    assert "Synthetic benchmarks can\n" not in visible
    assert not [issue for issue in issues if issue.category == "incomplete_content"]


def test_evidence_wall_renderer_removes_short_duplicate_cards(tmp_path) -> None:
    outline = _authored_card_outline(0, layout="icon_rows")
    outline.content_json.update(
        {
            "action_title": "Implicit ground truth discovery makes benchmark creation scalable",
            "subheading": "Use evidence that already exists in real workflows.",
            "narrative_role": "evidence",
            "bullets": [
                "Implicit ground truth already exists in operational data, approved documents, replicated experiments, and decisions.",
                "Agents can discover benchmark cases by finding evidence that real processes have already validated.",
                "The discovery approach scales because it reuses enterprise evidence instead of relying on manual labeling.",
                "Implicit ground truth",
                "Agents",
            ],
            "exhibit_spec": {
                "type": "icon_rows",
                "items": [
                    "Implicit ground truth already exists in operational data, approved documents, replicated experiments, and decisions.",
                    "Agents can discover benchmark cases by finding evidence that real processes have already validated.",
                    "The discovery approach scales because it reuses enterprise evidence instead of relying on manual labeling.",
                    "Implicit ground truth",
                    "Agents",
                ],
            },
            "sources": ["Bootstrapping Benchmarks > The Case for Implicit Ground Truth Discovery"],
        }
    )
    outline.layout_json["composition_family"] = "evidence_wall"
    outline.layout_json["composition_signature"] = "evidence_wall|0|evidence|icon_rows"
    pptx_path = tmp_path / "evidence-wall-clean.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, [outline])

    visible = " ".join(" ".join(slide["text"]) for slide in payload["slides"])
    assert visible.count("Implicit ground truth") <= 2
    assert visible.count("Agents") <= 2
    assert "Can discover benchmark cases by finding evidence that real processes have already validated." in visible
    assert not [issue for issue in issues if issue.category in {"cut-off-text", "incomplete_content"}]


def test_closing_renderer_uses_action_steps_instead_of_source_excerpts(tmp_path) -> None:
    outline = _authored_card_outline(0, layout="closing_recommendation")
    outline.content_json.update(
        {
            "action_title": "Commit to models are only as trustworthy as our ability to evaluate them, necessitating benchmarks",
            "subheading": "Move from benchmark theory to a governed operating pilot.",
            "narrative_role": "closing",
            "bullets": [
                "Benchmarks have been a core foundation of data science and model development to help determine",
                "histopathology segmentation) and the benchmarks themselves consisted of a training set",
                "With the proliferation of large language models (LLMs) there has been a desire to test these",
            ],
            "exhibit_spec": {
                "type": "recommendation",
                "recommendation": "Benchmarks have been a core foundation of data science and model development to help determine",
                "decision_ask": "Approve the first governed benchmark pilot.",
                "next_steps": [
                    "Historically, model development worked on specialized tasks in a single domain.",
                    "histopathology segmentation) and the benchmarks themselves consisted of a training set",
                    "With the proliferation of large language models (LLMs) there has been a desire to test these",
                ],
            },
            "sources": ["Bootstrapping Benchmarks > Closing Remarks"],
        }
    )
    outline.layout_json["layout"] = "closing_recommendation"
    outline.layout_json["archetype"] = "closing_recommendation"
    pptx_path = tmp_path / "closing-clean.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, [outline])

    visible = " ".join(" ".join(slide["text"]) for slide in payload["slides"])
    assert "help determine" not in visible
    assert "histopathology segmentation" not in visible
    assert "desire to test these" not in visible
    assert "Commit to a governed benchmark pilot" in visible
    assert "Launch a governed benchmark pilot tied to validated source evidence." in visible
    assert "Select one consequential internal benchmark pilot." in visible
    assert "Bind test cases to validated source evidence." in visible
    assert "Review failures before expanding coverage." in visible
    assert not [issue for issue in issues if issue.category == "incomplete_content"]


def test_reframe_comparison_renderer_avoids_generic_filler_copy(tmp_path) -> None:
    outline = _authored_card_outline(0, layout="comparison_table")
    outline.content_json.update(
        {
            "action_title": "Benchmark governance needs source-specific decision rules",
            "subheading": "Compare evidence signals against the workflow change they require.",
            "narrative_role": "implementation",
            "bullets": [
                "Evaluation claims need evidence tests before scaling.",
                "Owners need documented evidence before rollout.",
                "Benchmarks should refresh when source evidence changes.",
            ],
            "exhibit_spec": {
                "type": "comparison_table",
                "columns": ["Dimension", "Current state", "Target state"],
                "rows": [
                    ["Evidence", "Current readout", "Target move"],
                    ["Ownership", "Source claim", "Managed behavior"],
                    ["Refresh", "Operating implication", "Managed behavior"],
                ],
            },
            "sources": ["Bootstrapping Benchmarks > The Questions the Model Contract Must Answer"],
        }
    )
    outline.layout_json["composition_family"] = "reframe_comparison"
    outline.layout_json["composition_signature"] = "reframe_comparison|0|implementation|comparison_table"
    pptx_path = tmp_path / "reframe-no-filler.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, [outline])

    visible = " ".join(" ".join(slide["text"]) for slide in payload["slides"])
    assert "operating move" not in visible.lower()
    assert "Managed behavior" not in visible
    assert "Show how each source signal changes the benchmark workflow." in visible
    assert not [issue for issue in issues if issue.category == "renderer_filler_copy"]


def test_authored_renderer_preserves_variety_for_source_rewritten_slides() -> None:
    renderer = AuthoredPptxRenderer()
    outlines = []
    for index, layout in enumerate(
        ["callouts", "checklist", "icon_rows", "quote_sidebar", "comparison_table", "process"],
        start=1,
    ):
        outline = _authored_card_outline(index, layout=layout)
        outline.content_json["visual_qa_source_repair"] = True
        outlines.append(outline)

    authored = renderer.author_outlines(outlines)
    families = [outline.layout_json["composition_family"] for outline in authored]

    assert "source_repair_cards" not in families
    assert len(set(families)) >= 4


def _authored_card_outline(index: int, layout: str = "icon_rows") -> SlideOutline:
    return SlideOutline(
        id=f"authored-card-{index}",
        job_id="job-authored-cards",
        slide_index=index,
        mode="flexible",
        label=f"Operating discipline slide {index}",
        content_json={
            "action_title": f"Operating discipline slide {index}",
            "subheading": "Use source evidence, review gates, and ownership to make AI work reliable.",
            "narrative_role": "evidence",
            "archetype": layout,
            "bullets": [
                "Persist source context before starting a new generation session.",
                "Define acceptance criteria before asking the model to produce changes.",
                "Review output against evidence before updating project memory.",
                "Name the owner who will keep the workflow current.",
            ],
            "exhibit_spec": {
                "type": "callouts",
                "points": [
                    "Persist source context before starting a new generation session.",
                    "Define acceptance criteria before asking the model to produce changes.",
                    "Review output against evidence before updating project memory.",
                    "Name the owner who will keep the workflow current.",
                ],
            },
        },
        layout_json={"layout": layout, "archetype": layout},
        created_at=_timestamp(),
    )


def test_authored_renderer_assigns_distinct_card_composition_families() -> None:
    renderer = AuthoredPptxRenderer()

    authored = renderer.author_outlines(
        [_authored_card_outline(index) for index in range(1, 5)]
    )
    families = [outline.layout_json["composition_family"] for outline in authored]

    assert "why_it_matters_cards" in families
    assert "challenge_cards" in families
    assert "evidence_wall" in families
    assert "toolkit_grid" in families
    assert len(set(families)) == 4
    assert len({outline.layout_json["composition_signature"] for outline in authored}) == 4


def test_authored_renderer_repairs_repeated_challenge_rhythm() -> None:
    outlines = []
    for index in range(8):
        outline = _authored_card_outline(index, layout="callouts")
        outline.content_json["narrative_role"] = "problem"
        outlines.append(outline)

    authored = AuthoredPptxRenderer().author_outlines(outlines)
    families = [outline.layout_json["composition_family"] for outline in authored]
    card_count = sum(
        1
        for family in families
        if family in AuthoredPptxRenderer().card_like_families
    )
    contract = GenerationEditingContract().build(_template("freeform"), authored)
    requirement_status = {
        item["id"]: item["status"] for item in contract["requirements"]
    }

    assert not any(left == right for left, right in zip(families, families[1:]))
    assert card_count / len(families) <= 0.46
    assert any(outline.layout_json.get("rhythm_repair", {}).get("applied") for outline in authored)
    assert requirement_status["avoid_adjacent_repetition"] == "pass"
    assert requirement_status["avoid_card_composition_default"] == "pass"


def test_pptx_builder_prepares_authored_outline_metadata_for_ui() -> None:
    builder = PptxBuilder(node_runner=object(), renderer_engine="authored")
    outlines = [_authored_card_outline(index) for index in range(1, 5)]

    prepared = builder.prepare_outlines(_template("freeform"), outlines)

    assert all(outline.layout_json.get("render_engine") == "authored" for outline in prepared)
    assert all(outline.layout_json.get("composition_family") for outline in prepared)
    assert all(outline.content_json.get("visual_intent") for outline in prepared)
    assert not any(outline.layout_json.get("composition_family") for outline in outlines)


def test_authored_renderer_uses_composition_specific_native_routes(tmp_path) -> None:
    outlines = [_authored_card_outline(index) for index in range(6)]
    pptx_path = tmp_path / "authored-compositions.pptx"

    AuthoredPptxRenderer().render(outlines, BrandDNA(), pptx_path)

    prs = Presentation(pptx_path.as_posix())
    visible = "\n".join(
        shape.text
        for slide in prs.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert "PROOF" not in visible
    route_markers = {
        marker
        for marker in (
            "OPERATING KIT",
            "TENSION",
            "EVIDENCE WALL",
            "DECISION POINT",
            "OPERATING SHIFT",
            "STATEMENT",
            "CALLOUT",
            "NUMBER SIGNAL",
        )
        if marker in visible
    }
    assert {"EVIDENCE WALL", "TENSION", "DECISION POINT", "OPERATING SHIFT"}.issubset(
        route_markers
    )
    assert len(route_markers) >= 4


def test_authored_renderer_routes_metric_slides_to_number_signal(tmp_path) -> None:
    outline = _authored_card_outline(1, layout="chart")
    outline.content_json["metrics"] = [
        {"label": "Agent handoffs with explicit criteria", "value": 82, "unit": "%"},
        {"label": "Manual review cycles removed", "value": 14, "unit": "hours"},
        {"label": "Context window budget", "value": 128000, "unit": "tokens"},
    ]
    outline.content_json["exhibit_spec"] = {
        "type": "metric_chart",
        "metrics": outline.content_json["metrics"],
    }
    authored = AuthoredPptxRenderer().author_outlines([outline])
    pptx_path = tmp_path / "metric-signal.pptx"

    AuthoredPptxRenderer().render([outline], BrandDNA(), pptx_path)

    visible = "\n".join(
        shape.text
        for slide in Presentation(pptx_path.as_posix()).slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert authored[0].layout_json["composition_family"] == "metric_signal"
    assert "NUMBER SIGNAL" in visible
    assert "82%" in visible
    assert "SUPPORTING SIGNALS" in visible


def test_authored_renderer_does_not_promote_incidental_callout_metrics() -> None:
    outline = _authored_card_outline(1, layout="callouts")
    outline.content_json["narrative_role"] = "evidence"
    outline.content_json["exhibit_spec"] = {
        "type": "callouts",
        "points": ["Connect the harness-centric view to an explicit review gate."],
        "metrics": [{"label": "Predictions", "value": 1.0, "unit": "%"}],
    }

    authored = AuthoredPptxRenderer().author_outlines([outline])

    assert authored[0].layout_json["composition_family"] != "metric_signal"
    assert authored[0].layout_json["layout"] != "chart"

    metric_outline = _authored_card_outline(2, layout="chart")
    metric_outline.content_json["exhibit_spec"] = {
        "type": "metric_chart",
        "metrics": [{"label": "Predictions", "value": 1.0, "unit": "%"}],
    }
    metric_outline.content_json["chart_spec"] = {
        "type": "bar",
        "metrics": [{"label": "Predictions", "value": 1.0, "unit": "%"}],
    }
    metric_outline.content_json["metrics"] = [
        {"label": "Predictions", "value": 1.0, "unit": "%"}
    ]
    metric_outline.layout_json["layout"] = "chart"
    metric_outline.layout_json["archetype"] = "metric_chart"

    authored_metric = AuthoredPptxRenderer().author_outlines([metric_outline])

    assert authored_metric[0].layout_json["composition_family"] != "metric_signal"
    assert authored_metric[0].layout_json["layout"] != "chart"


def test_authored_renderer_routes_decision_slides_to_spotlight_callout(tmp_path) -> None:
    outline = _authored_card_outline(1, layout="quote_sidebar")
    outline.content_json["narrative_role"] = "decision"
    outline.content_json["action_title"] = "Make the benchmark contract the review gate"
    authored = AuthoredPptxRenderer().author_outlines([outline])
    pptx_path = tmp_path / "spotlight-callout.pptx"

    AuthoredPptxRenderer().render([outline], BrandDNA(), pptx_path)

    visible = "\n".join(
        shape.text
        for slide in Presentation(pptx_path.as_posix()).slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert authored[0].layout_json["composition_family"] == "spotlight_quote"
    assert "CALLOUT" in visible
    assert "WHAT CHANGES" in visible
    assert "Make the benchmark contract" in visible


def test_authored_renderer_varies_structured_composition_families() -> None:
    outlines: list[SlideOutline] = [_authored_card_outline(0, layout="cover")]
    for index in range(1, 7):
        outline = _authored_card_outline(index, layout="comparison_table")
        outline.content_json["archetype"] = "comparison_table"
        outline.content_json["exhibit_spec"] = {
            "type": "comparison_table",
            "columns": ["Signal", "Current readout", "Target move"],
            "rows": [
                ["Grounding", "Generic public checks", "Use source-backed harnesses"],
                ["Execution", "Ad hoc prompting", "Run a managed benchmark workflow"],
            ],
        }
        outline.layout_json["archetype"] = "comparison_table"
        outlines.append(outline)
    for index, layout in enumerate(
        ["checklist", "checklist", "table_reference", "table_reference"], start=7
    ):
        outline = _authored_card_outline(index, layout=layout)
        outline.content_json["archetype"] = layout
        outline.content_json["exhibit_spec"] = {
            "type": "reference_table" if layout == "table_reference" else "checklist",
            "items": [
                {"label": "Contract", "text": "Make success explicit"},
                {"label": "Harness", "text": "Run the workflow repeatedly"},
            ],
            "rows": [
                ["Contract", "Defines what counts as success"],
                ["Harness", "Executes benchmark evidence"],
            ],
        }
        outline.layout_json["archetype"] = layout
        outlines.append(outline)
    outlines.append(_authored_card_outline(10, layout="closing_recommendation"))

    authored = AuthoredPptxRenderer().author_outlines(outlines)
    families = [outline.layout_json["composition_family"] for outline in authored]

    assert "reframe_comparison" in families
    assert "evidence_wall" in families
    assert "statement_canvas" in families
    assert "operating_map" in families or "decision_ladder" in families
    assert families.count("lifecycle_timeline") <= 1
    assert "architecture_layers" in families
    assert len({outline.layout_json["composition_signature"] for outline in authored}) >= 6


def test_authored_renderer_uses_full_canvas_structured_routes(tmp_path) -> None:
    outlines: list[SlideOutline] = [_authored_card_outline(0, layout="cover")]
    comparison = _authored_card_outline(1, layout="comparison_table")
    comparison.content_json["exhibit_spec"] = {
        "type": "comparison_table",
        "columns": ["Signal", "Current readout", "Target move"],
        "rows": [
            ["Grounding", "Synthetic examples drift", "Anchor to real workflow evidence"],
            ["Review", "Manual inspection comes late", "Gate each run with acceptance tests"],
        ],
    }
    outlines.append(comparison)
    second_comparison = _authored_card_outline(2, layout="comparison_table")
    second_comparison.content_json["exhibit_spec"] = comparison.content_json["exhibit_spec"]
    outlines.append(second_comparison)
    checklist = _authored_card_outline(2, layout="checklist")
    checklist.content_json["exhibit_spec"] = {
        "type": "checklist",
        "items": [
            {"text": "Name the decision and success criteria"},
            {"text": "Run the harness against source-backed cases"},
            {"text": "Record the review result before scaling"},
        ],
    }
    outlines.append(checklist)
    reference = _authored_card_outline(4, layout="table_reference")
    reference.content_json["exhibit_spec"] = {
        "type": "reference_table",
        "rows": [
            ["Contract", "Declares the evaluation target"],
            ["Harness", "Executes the benchmark workflow"],
            ["Evidence", "Keeps cases grounded in reality"],
        ],
    }
    outlines.append(reference)
    outlines.append(_authored_card_outline(5, layout="closing_recommendation"))
    pptx_path = tmp_path / "authored-structured-routes.pptx"

    AuthoredPptxRenderer().render(outlines, BrandDNA(), pptx_path)

    prs = Presentation(pptx_path.as_posix())
    visible = "\n".join(
        shape.text
        for slide in prs.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert "EVIDENCE WALL" in visible
    assert "REFRAME" in visible
    assert "OPERATING MAP" in visible
    assert "ARCHITECTURE" in visible
    assert "COMPARISON LENS" not in visible


def test_rendered_slide_audit_flags_repetitive_card_visual_rhythm(tmp_path) -> None:
    outlines = [_authored_card_outline(index) for index in range(10)]
    for outline in outlines:
        outline.layout_json["composition_family"] = "proof_strip"
        outline.layout_json["composition_signature"] = (
            f"proof_strip|{outline.slide_index}|evidence|callouts"
        )
    pptx_path = tmp_path / "repetitive-proof-strip.pptx"

    DeterministicPptxRenderer().render(outlines, BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, outlines, tmp_path)

    assert payload["visual_rhythm"]["card_like_ratio"] == 1
    assert any(issue.category == "visual_rhythm" for issue in issues)


def test_rendered_slide_audit_counts_evidence_wall_as_card_like(tmp_path) -> None:
    outlines = [_authored_card_outline(index) for index in range(8)]
    for outline in outlines:
        outline.layout_json["composition_family"] = "evidence_wall"
        outline.layout_json["composition_signature"] = (
            f"evidence_wall|{outline.slide_index}|evidence|callouts"
        )
    pptx_path = tmp_path / "repetitive-evidence-wall.pptx"

    DeterministicPptxRenderer().render(outlines, BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, outlines, tmp_path)

    assert payload["visual_rhythm"]["card_like_ratio"] == 1
    assert any(issue.category == "visual_rhythm" for issue in issues)


def test_rendered_slide_audit_flags_repeated_process_visual_rhythm(tmp_path) -> None:
    families = [
        "editorial_spread",
        "challenge_cards",
        "lifecycle_timeline",
        "why_it_matters_cards",
        "lifecycle_timeline",
        "decision_ladder",
        "reframe_split",
        "evidence_wall",
        "lifecycle_timeline",
        "proof_strip",
        "architecture_layers",
        "reframe_comparison",
        "decision_ladder",
        "decision_ladder",
        "lifecycle_timeline",
        "challenge_cards",
    ]
    outlines = [_authored_card_outline(index) for index, _family in enumerate(families)]
    for outline, family in zip(outlines, families):
        outline.layout_json["composition_family"] = family
        outline.layout_json["composition_signature"] = (
            f"{family}|{outline.slide_index}|evidence|callouts"
        )
    pptx_path = tmp_path / "repetitive-process-rhythm.pptx"

    DeterministicPptxRenderer().render(outlines, BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, outlines, tmp_path)

    assert payload["visual_rhythm"]["family_counts"]["lifecycle_timeline"] == 4
    assert any(
        issue.category == "visual_rhythm" and "process-like" in issue.message
        for issue in issues
    )


def test_renderer_uses_native_bullet_paragraphs_without_literal_bullet_text(
    tmp_path,
) -> None:
    outline = _authored_card_outline(1, layout="two_column")
    pptx_path = tmp_path / "native-bullets.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), pptx_path)

    prs = Presentation(pptx_path.as_posix())
    visible_text = "\n".join(
        shape.text
        for slide in prs.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )
    with zipfile.ZipFile(pptx_path) as package:
        slide_xml = package.read("ppt/slides/slide1.xml").decode("utf-8")
    text_nodes = re.findall(r"<a:t>(.*?)</a:t>", slide_xml)

    assert "\u2022" not in visible_text
    assert "buChar" in slide_xml
    assert not any(text.startswith("\u2022") for text in text_nodes)


def test_renderer_splits_concatenated_step_text_into_separate_paragraphs(
    tmp_path,
) -> None:
    outline = _authored_card_outline(1, layout="two_column")
    outline.content_json["bullets"] = [
        "Step 1: Frame the request with evidence. Step 2: Review the output before memory updates. Step 3: Record the decision owner."
    ]
    outline.content_json["content_blocks"] = [
        {"type": "bullets", "body": outline.content_json["bullets"]}
    ]
    pptx_path = tmp_path / "split-steps.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), pptx_path)

    prs = Presentation(pptx_path.as_posix())
    paragraphs = [
        paragraph.text
        for slide in prs.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
        for paragraph in shape.text_frame.paragraphs
        if paragraph.text.strip()
    ]
    step_paragraphs = [text for text in paragraphs if text.startswith("Step ")]
    _payload, issues = RenderedSlideAudit().inspect(pptx_path, [outline])

    assert len(step_paragraphs) == 3
    assert not any("Step 1" in text and "Step 2" in text for text in step_paragraphs)
    assert not any(issue.category == "multi_item_concatenation" for issue in issues)


def test_rendered_slide_audit_flags_concatenated_numbered_paragraph(
    tmp_path,
) -> None:
    pptx_path = tmp_path / "bad-multi-item.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(10), Inches(2))
    box.text = "Step 1: Do the first thing. Step 2: Do the second thing."
    prs.save(pptx_path.as_posix())

    _payload, issues = RenderedSlideAudit().inspect(pptx_path, [])

    assert any(issue.category == "multi_item_concatenation" for issue in issues)


def test_authored_renderer_degrades_weak_matrix_before_rendering(tmp_path) -> None:
    outline = _authored_card_outline(1, layout="matrix_2x2")
    outline.content_json["archetype"] = "matrix_2x2"
    outline.content_json["exhibit_spec"] = {
        "type": "matrix_2x2",
        "quadrants": [
            {"label": "High impact / high readiness", "description": "Generic fallback"},
            {"label": "High impact / low readiness", "description": "Generic fallback"},
            {"label": "Low impact / high readiness", "description": "Generic fallback"},
            {"label": "Low impact / low readiness", "description": "Generic fallback"},
        ],
    }
    outline.layout_json["layout"] = "matrix_2x2"
    outline.layout_json["archetype"] = "matrix_2x2"
    cover = _authored_card_outline(0, layout="cover")
    cover.content_json["narrative_role"] = "cover"
    cover.layout_json["layout"] = "cover"
    close = _authored_card_outline(2, layout="closing_recommendation")
    close.content_json["narrative_role"] = "closing"
    close.layout_json["layout"] = "closing_recommendation"
    pptx_path = tmp_path / "degraded-matrix.pptx"

    authored_outlines = AuthoredPptxRenderer().author_outlines([cover, outline, close])
    authored = authored_outlines[1]
    AuthoredPptxRenderer().render([cover, outline, close], BrandDNA(), pptx_path)
    audit_payload, audit_issues = RenderedSlideAudit().inspect(pptx_path, authored_outlines)
    prs = Presentation(pptx_path.as_posix())
    visible = "\n".join(
        shape.text
        for slide in prs.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )

    assert authored.layout_json["layout"] == "callouts"
    assert authored.layout_json["composition_family"] in {
        "evidence_wall",
        "proof_strip",
        "statement_canvas",
        "spotlight_quote",
        "reframe_split",
        "why_it_matters_cards",
        "architecture_layers",
    }
    assert authored.content_json["visual_degradation"]["from"] == "decision_matrix"
    assert authored.content_json["visual_degradation"]["original_exhibit_type"] == "matrix_2x2"
    assert authored.content_json["exhibit_spec"]["type"] == "callouts"
    assert audit_payload["slides"][1]["visual_degradation"]["from"] == "decision_matrix"
    assert not audit_issues
    assert "PROOF" not in visible
    assert "High impact / high readiness" not in visible
    assert "Low impact / low readiness" not in visible


def test_authored_renderer_degrades_bad_code_panel_before_rendering(tmp_path) -> None:
    outline = _authored_card_outline(1, layout="code_panel")
    outline.content_json["archetype"] = "code_panel"
    outline.content_json["exhibit_spec"] = {
        "type": "code_panel",
        "title": "operating-rules.md",
        "lines": [
            "Artifact | Purpose | Update trigger",
            "Convert the framework consists of five layers into an owned action",
            "Make the harness-centric view visible before execution",
        ],
    }
    outline.content_json["content_blocks"] = [
        {
            "type": "bullets",
            "body": [
                "Artifact | Purpose | Update trigger",
                "Convert the framework consists of five layers into an owned action",
            ],
        }
    ]
    outline.layout_json["layout"] = "code_panel"
    outline.layout_json["archetype"] = "code_panel"
    cover = _authored_card_outline(0, layout="cover")
    cover.content_json["narrative_role"] = "cover"
    cover.layout_json["layout"] = "cover"
    close = _authored_card_outline(2, layout="closing_recommendation")
    close.content_json["narrative_role"] = "closing"
    close.layout_json["layout"] = "closing_recommendation"
    pptx_path = tmp_path / "degraded-code-panel.pptx"

    authored_outlines = AuthoredPptxRenderer().author_outlines([cover, outline, close])
    authored = authored_outlines[1]
    AuthoredPptxRenderer().render([cover, outline, close], BrandDNA(), pptx_path)
    prs = Presentation(pptx_path.as_posix())
    visible = "\n".join(
        shape.text
        for slide in prs.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )

    assert authored.layout_json["layout"] == "callouts"
    assert authored.layout_json["composition_family"] in {
        "evidence_wall",
        "proof_strip",
        "statement_canvas",
        "spotlight_quote",
        "reframe_split",
        "why_it_matters_cards",
        "architecture_layers",
    }
    assert authored.content_json["visual_degradation"]["from"] == "code_panel"
    assert "Artifact | Purpose" not in visible
    assert "Convert " not in visible


def test_authored_architecture_layers_do_not_occlude_title(tmp_path) -> None:
    outline = _authored_card_outline(1, layout="callouts")
    outline.content_json["action_title"] = (
        "Govern agent-assisted benchmark discovery before deployment"
    )
    outline.content_json["subheading"] = (
        "Layer each source control so benchmark evidence remains inspectable."
    )
    outline.content_json["exhibit_spec"] = {
        "type": "reference_table",
        "rows": [
            ["Data catalog", "Scale benchmark discovery across enterprise sources"],
            ["Schema metadata", "Show where usable evaluation evidence lives"],
            ["Confidence score", "Separate reviewed facts from uncertain signals"],
            ["Review gate", "Block deployment until evidence quality is accepted"],
        ],
    }
    outline.layout_json["layout"] = "callouts"
    outline.layout_json["composition_family"] = "architecture_layers"
    outline.layout_json["composition_variant"] = "architecture_layers-0"
    outline.layout_json["composition_signature"] = "architecture_layers|test"
    pptx_path = tmp_path / "architecture-layers.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), pptx_path)
    _payload, issues = RenderedSlideAudit().inspect(pptx_path, [outline])
    categories = {issue.category for issue in issues}

    assert "occluded_text" not in categories
    assert "overlap" not in categories
    assert "cut-off-text" not in categories
    assert "renderer_filler_copy" not in categories


def test_authored_architecture_layers_preserve_complete_contract_clauses(tmp_path) -> None:
    outline = _authored_card_outline(8, layout="comparison_table")
    outline.content_json["action_title"] = (
        "Model contracts bind expectations to executable benchmark rules"
    )
    outline.content_json["subheading"] = "The Model Contract is our central abstraction."
    outline.content_json["exhibit_spec"] = {
        "type": "comparison_table",
        "rows": [
            [
                "Model contracts",
                "Make inputs, outputs, success criteria, and evaluation rules explicit.",
            ],
            [
                "A contract",
                "Gives humans, agents, and harnesses a shared definition of what must be tested.",
            ],
            [
                "The contract",
                "Should answer the operational questions required to build valid benchmark cases.",
            ],
        ],
    }
    outline.layout_json["layout"] = "comparison_table"
    outline.layout_json["composition_family"] = "architecture_layers"
    outline.layout_json["composition_variant"] = "architecture_layers-0"
    outline.layout_json["composition_signature"] = "architecture_layers|contract"
    pptx_path = tmp_path / "architecture-contract-clauses.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, [outline])

    visible = " ".join(" ".join(slide["text"]) for slide in payload["slides"])
    assert "what must be tested" in visible
    assert "build valid benchmark cases" in visible
    assert "what must " not in visible.replace("what must be tested", "")
    assert "build valid" not in visible.replace("build valid benchmark cases", "")
    categories = {issue.category for issue in issues}
    assert "incomplete_content" not in categories
    assert "renderer_filler_copy" not in categories
    assert "cut-off-text" not in categories


def test_authored_architecture_layers_rewrites_generic_risk_labels(tmp_path) -> None:
    outline = _authored_card_outline(3, layout="table_reference")
    outline.content_json["action_title"] = (
        "Reframe benchmarking from data generation to harness-centric discovery"
    )
    outline.content_json["subheading"] = (
        "Compare synthetic generation with harness-centric discovery."
    )
    outline.content_json["sources"] = ["Bootstrapping Benchmarks > The Harness-Centric View"]
    outline.content_json["exhibit_spec"] = {
        "type": "reference_table",
        "rows": [
            ["Synthetic Generation LLM", "Creates cases without operational validation."],
            ["Circular Validation Risk", "Benchmark evidence validates itself."],
            ["Distribution Coverage Narrow", "Cases miss enterprise workflow coverage."],
        ],
    }
    outline.layout_json["layout"] = "table_reference"
    outline.layout_json["composition_family"] = "architecture_layers"
    outline.layout_json["composition_variant"] = "architecture_layers-0"
    outline.layout_json["composition_signature"] = "architecture_layers|harness"
    pptx_path = tmp_path / "architecture-risk-labels.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, [outline])

    visible = " ".join(" ".join(slide["text"]) for slide in payload["slides"])
    assert "Validation Risk" not in visible
    assert "Harness reasoning shift" in visible
    assert not [issue for issue in issues if issue.category == "renderer_filler_copy"]


def test_spotlight_callout_expands_sparse_executive_summary_points(tmp_path) -> None:
    outline = _authored_card_outline(13, layout="two_column")
    outline.content_json["action_title"] = (
        "Harness-centric discovery turns enterprise evidence into benchmark cases"
    )
    outline.content_json["subheading"] = "Executive summary"
    outline.content_json["sources"] = ["Bootstrapping Benchmarks > Executive Summary"]
    outline.content_json["source_labels"] = [
        "Bootstrapping Benchmarks > Executive Summary"
    ]
    outline.content_json["bullets"] = [
        "Current benchmarking is constrained by saturation, high labeling cost, and weak fit to enterprise use cases."
    ]
    outline.content_json["exhibit_spec"] = {
        "type": "callouts",
        "points": [
            "Current benchmarking is constrained by saturation and weak fit to enterprise use cases."
        ],
    }
    outline.layout_json["layout"] = "two_column"
    outline.layout_json["composition_family"] = "spotlight_quote"
    outline.layout_json["composition_variant"] = "spotlight_quote-0"
    outline.layout_json["composition_signature"] = "spotlight_quote|executive-summary"
    outline = DesignAgent().apply_design([outline])[0]
    pptx_path = tmp_path / "spotlight-executive-summary.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, [outline])

    visible = " ".join(" ".join(slide["text"]) for slide in payload["slides"])
    assert "next operating choice" not in visible.lower()
    assert len(outline.content_json["exhibit_spec"]["points"]) >= 3
    assert "enterprise workflows" in visible
    assert "Harness-centric discovery" in visible
    assert "Current benchmarking" in visible
    assert not [issue for issue in issues if issue.category == "renderer_filler_copy"]


def test_authored_decision_ladder_uses_readable_source_specific_sequence(tmp_path) -> None:
    outline = _authored_card_outline(1, layout="checklist")
    outline.content_json["action_title"] = (
        "Harness interfaces standardize benchmark execution across domains"
    )
    outline.content_json["subheading"] = (
        "Use interface boundaries to make every benchmark run repeatable."
    )
    outline.content_json["exhibit_spec"] = {
        "type": "checklist",
        "items": [
            {
                "action": "Declare the model contract before running the harness.",
                "owner": "Contract owner",
                "timing": "Define",
            },
            {
                "action": "Bind each test case to traceable proprietary evidence.",
                "owner": "Evidence lead",
                "timing": "Build",
            },
            {
                "action": "Run the same harness protocol across each model family.",
                "owner": "Harness lead",
                "timing": "Execute",
            },
            {
                "action": "Record review findings before approving deployment.",
                "owner": "Review lead",
                "timing": "Review",
            },
        ],
    }
    outline.layout_json["layout"] = "checklist"
    outline.layout_json["composition_family"] = "decision_ladder"
    outline.layout_json["composition_variant"] = "decision_ladder-0"
    outline.layout_json["composition_signature"] = "decision_ladder|test"
    pptx_path = tmp_path / "decision-ladder.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(pptx_path, [outline])
    visible = "\n".join(
        text
        for slide in payload["slides"]
        for text in slide["text"]
    )
    categories = {issue.category for issue in issues}

    assert "small_text" not in categories
    assert "renderer_filler_copy" not in categories
    assert "Tie the claim" not in visible
    assert "source-backed evaluation artifact" not in visible
    assert "Declare the model contract" in visible


def test_renderer_degrades_weak_visual_exhibits_without_generic_labels(tmp_path) -> None:
    matrix = _authored_card_outline(1, layout="matrix_2x2")
    matrix.content_json["exhibit_spec"] = {"type": "matrix_2x2", "quadrants": []}
    matrix.layout_json["layout"] = "matrix_2x2"
    dependency = _authored_card_outline(2, layout="dependency_map")
    dependency.content_json["exhibit_spec"] = {
        "type": "dependency_map",
        "left_node": "Source context",
        "middle_nodes": ["Rules"],
        "right_outcome": "Reliable next session",
    }
    dependency.layout_json["layout"] = "dependency_map"
    cycle = _authored_card_outline(3, layout="framework_cycle")
    cycle.content_json["exhibit_spec"] = {
        "type": "cycle",
        "center_label": "Operating loop",
        "steps": [
            {"label": "Frame"},
            {"label": "Prime"},
            {"label": "Review"},
        ],
    }
    cycle.layout_json["layout"] = "framework_cycle"
    pptx_path = tmp_path / "weak-exhibits.pptx"

    DeterministicPptxRenderer().render([matrix, dependency, cycle], BrandDNA(), pptx_path)

    prs = Presentation(pptx_path.as_posix())
    visible = "\n".join(
        shape.text
        for slide in prs.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )
    assert visible.count("PROOF") == 0
    assert "High impact / high readiness" not in visible
    assert "Source context" not in visible
    assert "Reliable next session" not in visible
    assert "Operating loop" not in visible
    assert "Frame" not in visible
    assert "Prime" not in visible


def _rich_bundle(job_id: str = "job-rich") -> DocumentBundle:
    sections = [
        DocumentSection(
            title=f"Chapter {idx}: Agentic Engineering Practice",
            level=1,
            content=(
                "Vibe coding works for early exploration, but teams need persistent "
                "context, explicit acceptance criteria, source-backed review, and "
                "repeatable workflow memory before using AI agents on production code. "
                "The operating model should define ownership, rules, review gates, "
                "and update triggers so the next session inherits the right context."
            ),
            source_doc_id="beyond-vibe",
        )
        for idx in range(1, 16)
    ]
    return DocumentBundle(
        job_id=job_id,
        sections=sections,
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[
            "Memory bank hierarchy",
            "Rules files",
            "Review gates",
            "Decision log",
        ],
    )


def test_exhibit_fallbacks_do_not_generate_placeholder_or_convert_copy() -> None:
    section = DocumentSection(
        title="Architecture Overview",
        level=1,
        content=(
            "The framework consists of five primary layers that work together to enable benchmark creation and execution. "
            "Orchestration Layer: Top-level agent that reasons about which models need evaluation. "
            "Model Contract Registry: A repository of model contracts that describe known model types."
        ),
        source_doc_id="doc-1",
    )
    compiler = ExhibitCompiler()

    comparison = compiler.compile("comparison_table", "framework", section, [], [])
    checklist = compiler.compile("checklist", "implementation", section, [], [])
    matrix = compiler.compile("matrix_2x2", "decision", section, [], [])
    rendered = json.dumps([comparison, checklist, matrix])

    assert "Convert " not in rendered
    assert "Owner" not in rendered
    assert "Owner / Next" not in rendered
    assert "High impact / high readiness" not in rendered
    assert "development of" not in rendered


def test_exhibit_compiler_cleans_table_and_owner_artifacts() -> None:
    section = DocumentSection(
        title="Harness-Centric View",
        level=1,
        content=(
            "Artifact | Purpose | Update trigger\n"
            "Convert the framework consists of five layers into an owned action (Owner / Next)\n"
            "Harness interfaces standardize benchmark execution across domains."
        ),
        source_doc_id="doc-1",
    )

    compiler = ExhibitCompiler()
    reference = compiler.compile("table_reference", "reference", section, [], [])
    checklist = compiler.compile("checklist", "implementation", section, [], [])
    rendered = json.dumps([reference, checklist])

    assert "Artifact | Purpose" not in rendered
    assert "Convert " not in rendered
    assert "Owner / Next" not in rendered
    assert "the framework consists of five layers" in rendered
    assert "Harness interfaces standardize benchmark execution" in rendered


def test_exhibit_compiler_varies_checklist_owner_and_timing() -> None:
    section = DocumentSection(
        title="Model Contract Questions",
        level=1,
        content=(
            "A model contract defines what goes in and how success is measured. "
            "The harness executes benchmark workflows against source-backed evidence. "
            "Review findings should be validated before production deployment."
        ),
        source_doc_id="doc-1",
    )

    checklist = ExhibitCompiler().compile("checklist", "implementation", section, [], [])
    pairs = {
        (item["owner"], item["timing"])
        for item in checklist["items"]
        if isinstance(item, dict)
    }

    assert len(pairs) >= 3
    assert ("Lead", "Review gate") not in pairs


def test_exhibit_compiler_avoids_prefix_duplicate_comparison_cells() -> None:
    section = DocumentSection(
        title="Closing Remarks",
        level=1,
        content=(
            "The proliferation of AI models across enterprise applications has outpaced the development of evaluation. "
            "Organizations deploying models for consequential decisions need benchmarks that reflect actual use. "
            "By shifting from manual benchmark creation to systematic discovery of implicit ground truth, teams can scale evaluation."
        ),
        source_doc_id="doc-1",
    )

    comparison = ExhibitCompiler().compile("comparison_table", "evidence", section, [], [])

    assert comparison["columns"] == [
        "Evidence signal",
        "Unmanaged pattern",
        "Harness move",
    ]
    for row in comparison["rows"]:
        label = row["label"].lower()
        values = [str(value).lower() for value in row["values"]]
        assert not any(value.startswith(label) for value in values)


def test_authored_items_do_not_pad_sparse_slides_with_fragments() -> None:
    outline = _authored_card_outline(1, layout="callouts")
    outline.content_json["bullets"] = ["Model contracts make expectations explicit."]
    outline.content_json["exhibit_spec"] = {
        "type": "callouts",
        "points": ["Model contracts make expectations explicit."],
    }

    items = DeterministicPptxRenderer()._authored_items(outline, limit=4)

    assert len(items) == 1
    assert len(set(items)) == len(items)
    assert items[0] == "Model contracts make expectations explicit."
    visible = " ".join(items).lower()
    assert "tie the claim" not in visible
    assert "make the operating implication explicit" not in visible
    assert "model contracts make is" not in visible


def test_authored_renderer_routes_sparse_slides_to_sparse_compositions() -> None:
    one_item = _authored_card_outline(1, layout="callouts")
    one_item.content_json["bullets"] = ["Model contracts make expectations explicit."]
    one_item.content_json["exhibit_spec"] = {
        "type": "callouts",
        "points": ["Model contracts make expectations explicit."],
    }
    two_item = _authored_card_outline(2, layout="checklist")
    two_item.content_json["bullets"] = [
        "Harnesses standardize benchmark execution.",
        "Source evidence keeps test cases auditable.",
    ]
    two_item.content_json["exhibit_spec"] = {
        "type": "checklist",
        "items": [
            {"action": "Harnesses standardize benchmark execution."},
            {"action": "Source evidence keeps test cases auditable."},
        ],
    }

    authored = AuthoredPptxRenderer().author_outlines([one_item, two_item])
    families = [outline.layout_json["composition_family"] for outline in authored]

    assert families[0] in {"statement_canvas", "spotlight_quote", "reframe_split"}
    assert families[1] in {"statement_canvas", "spotlight_quote", "reframe_split"}
    assert "challenge_cards" not in families
    assert "toolkit_grid" not in families
    assert "decision_ladder" not in families


def test_authored_renderer_routes_long_checklists_to_readable_compositions() -> None:
    outline = _authored_card_outline(3, layout="checklist")
    long_items = [
        "Implicit ground truth already exists in operational data, approved documents, replicated experiments, and decisions.",
        "Agents can discover benchmark cases by finding evidence that real processes have already validated.",
        "The discovery approach scales because it reuses enterprise evidence instead of relying on manual labeling.",
    ]
    outline.content_json["bullets"] = long_items
    outline.content_json["exhibit_spec"] = {
        "type": "checklist",
        "items": [{"action": item} for item in long_items],
    }

    authored = AuthoredPptxRenderer().author_outlines([outline])
    family = authored[0].layout_json["composition_family"]

    assert family in {
        "proof_strip",
        "evidence_wall",
        "statement_canvas",
        "reframe_split",
        "why_it_matters_cards",
    }
    assert family not in {"operating_map", "toolkit_grid", "decision_ladder"}


def test_authored_renderer_degrades_question_prompt_diagrams() -> None:
    outline = _authored_card_outline(10, layout="framework_cycle")
    outline.content_json["diagram_spec"] = {
        "kind": "cycle",
        "steps": [
            {"label": "What goes in"},
            {"label": "The Questions"},
            {"label": "What comes out"},
            {"label": "Beyond output format"},
        ],
    }
    outline.content_json["exhibit_spec"] = {
        "type": "cycle",
        "steps": [
            {"label": "What goes in"},
            {"label": "The Questions"},
            {"label": "What comes out"},
            {"label": "Beyond output format"},
        ],
    }

    authored = AuthoredPptxRenderer().author_outlines([outline])

    assert authored[0].layout_json["composition_family"] != "source_backed_diagram"
    assert authored[0].content_json["visual_degradation"]["from"] == "framework_cycle"
    assert authored[0].content_json["exhibit_spec"]["type"] == "callouts"


def test_authored_display_items_reject_dangling_source_fragments() -> None:
    renderer = DeterministicPptxRenderer()

    assert renderer._complete_display_item("Organizations deploying models for") == ""
    assert (
        renderer._complete_display_item(
            "The urgency of adopting robust benchmarking frameworks for"
        )
        == ""
    )
    assert (
        renderer._complete_display_item(
            "The proliferation of AI models across enterprise applications has outpaced the development of evaluation"
        )
        == ""
    )
    assert (
        renderer._complete_display_item(
            "Organizations deploying models for consequential decisions need benchmarks that reflect their actual use"
        )
        == ""
    )
    assert (
        renderer._complete_display_item(
            "Organizations deploy models for consequential decisions."
        )
        == "Organizations deploy models for consequential decisions."
    )


def test_authored_split_lead_uses_subject_not_modal_fragment() -> None:
    renderer = DeterministicPptxRenderer()

    assert renderer._split_lead(
        "Synthetic benchmarks can create circular validation loops without operational grounding."
    ) == (
        "Synthetic benchmarks",
        "Can create circular validation loops without operational grounding.",
    )
    assert renderer._split_lead(
        "Model contracts make inputs, outputs, success criteria, and evaluation rules explicit."
    ) == (
        "Model contracts",
        "Make inputs, outputs, success criteria, and evaluation rules explicit.",
    )
    assert renderer._split_lead(
        "Bootstrapping strategies: map proprietary data into reusable evidence."
    ) == (
        "Bootstrapping strategies",
        "Map proprietary data into reusable evidence.",
    )
    assert renderer._split_lead(
        "The recommended shift is from manual benchmark creation to governed evidence discovery."
    ) == (
        "Recommended shift",
        "Moves from manual benchmark creation to governed evidence discovery.",
    )
    assert renderer._split_lead(
        "Implicit ground truth already exists in operational data, approved documents, replicated experiments, and decisions."
    ) == (
        "Implicit ground truth",
        "Already exists in operational data, approved documents, replicated experiments, and decisions.",
    )
    assert renderer._split_lead(
        "Executives need evaluation systems that reflect real use cases rather than generic leaderboard tasks."
    ) == (
        "Executives",
        "Need evaluation systems that reflect real use cases rather than generic leaderboard tasks.",
    )
    assert renderer._split_lead(
        "Agents can discover benchmark cases by finding evidence that real processes have already validated."
    ) == (
        "Agents",
        "Can discover benchmark cases by finding evidence that real processes have already validated.",
    )
    assert renderer._split_lead(
        "A lifecycle for harness execution helps teams reproduce, update, and compare benchmark runs."
    ) == (
        "A lifecycle for harness execution",
        "Helps teams reproduce, update, and compare benchmark runs.",
    )


def test_authored_text_truncation_removes_dangling_endings() -> None:
    renderer = DeterministicPptxRenderer()

    assert renderer._truncate_at_word(
        "Executives need evaluation systems that reflect real use cases.",
        41,
    ) == "Executives need evaluation systems"
    assert renderer._truncate_at_word(
        "Confidence calibration matters because source evidence varies in certainty and review quality.",
        76,
    ) == "Confidence calibration matters because source evidence varies in certainty"
    assert renderer._truncate_at_word(
        "A lifecycle for harness execution helps teams reproduce, update, and compare benchmark runs.",
        70,
    ) == "A lifecycle for harness execution helps teams reproduce, update"


def test_authored_renderer_does_not_emit_generic_renderer_filler(tmp_path) -> None:
    outline = _authored_card_outline(2, layout="callouts")
    outline.content_json["action_title"] = (
        "Model contracts make evaluation expectations explicit"
    )
    outline.content_json["bullets"] = [
        "Model contracts make expectations explicit."
    ]
    outline.content_json["exhibit_spec"] = {
        "type": "callouts",
        "points": ["Model contracts make expectations explicit."],
    }
    pptx_path = tmp_path / "no-renderer-filler.pptx"

    AuthoredPptxRenderer().render([outline], BrandDNA(), pptx_path)
    payload, issues = RenderedSlideAudit().inspect(
        pptx_path,
        AuthoredPptxRenderer().author_outlines([outline]),
    )
    visible = " ".join(" ".join(slide["text"]) for slide in payload["slides"]).lower()

    assert "tie the claim" not in visible
    assert "connect the source evidence to the decision" not in visible
    assert "make the next move visible" not in visible
    assert "evidence tension" not in visible
    assert not any(issue.category == "renderer_filler_copy" for issue in issues)


def test_checklist_body_preserves_owner_timing_suffix() -> None:
    renderer = DeterministicPptxRenderer()
    body = renderer._checklist_body_text(
        "Orchestration Layer: Top-level agent that reasons about which models need evaluation, what data is needed, and which execution path should run.",
        "Data owner / Next",
    )

    assert body.endswith("(Data owner / Next)")
    assert "(Data )" not in body
    assert len(body) <= 121


def test_source_rich_fallback_does_not_force_fragile_code_or_matrix() -> None:
    outlines, _warnings = ContentPlanner().plan(
        _template("freeform"),
        _rich_bundle(),
        instructions="Create a consulting deck about moving beyond vibe coding.",
        generation_mode="freeform",
        quality_profile="showcase",
        length_strategy="auto",
    )

    archetypes = [outline.content_json["archetype"] for outline in outlines]

    assert "code_panel" not in archetypes
    assert "reference" not in archetypes
    assert "matrix_2x2" not in archetypes


def test_openai_compatible_client_extracts_json_from_fenced_response() -> None:
    response = """Here is the plan:
```json
{"deck_title":"Test","slides":[]}
```"""
    payload = OpenAICompatibleClient.extract_json(response)
    assert payload == {"deck_title": "Test", "slides": []}


def test_openai_compatible_client_extracts_nested_fenced_json() -> None:
    # The old non-greedy regex stopped at the first '}', breaking nested objects.
    response = '```json\n{"a":{"b":2},"c":3}\n```'
    assert OpenAICompatibleClient.extract_json(response) == {"a": {"b": 2}, "c": 3}


def test_openai_compatible_client_salvages_truncated_json() -> None:
    # A local model that hits its token budget mid-deck returns an unbalanced
    # object; salvage closes open structures so planning can still proceed.
    truncated = '{"deck_title":"D","slides":[{"n":1,"title":"Some incomplete tit'
    payload = OpenAICompatibleClient.extract_json(truncated)
    assert payload is not None
    assert payload["deck_title"] == "D"
    assert payload["slides"][0]["n"] == 1

    after_comma = '{"slides":[{"n":1},{"n":2},'
    assert OpenAICompatibleClient.extract_json(after_comma) == {"slides": [{"n": 1}, {"n": 2}]}

    dangling_colon = '{"a":1,"b":2,"c":'
    assert OpenAICompatibleClient.extract_json(dangling_colon) == {"a": 1, "b": 2}


def test_openai_compatible_client_extract_json_rejects_non_objects() -> None:
    assert OpenAICompatibleClient.extract_json("") is None
    assert OpenAICompatibleClient.extract_json("no json here") is None
    assert OpenAICompatibleClient.extract_json("[1, 2, 3]") is None


def test_planner_repairs_dangling_sentence_fragments() -> None:
    planner = ContentPlanner()

    cleaned = planner._phrase(
        "The following architecture is adapted from the Cline Memory Bank methodology, "
        "which has emerged as a",
        "",
    )

    assert cleaned == "The following architecture is adapted from the Cline Memory Bank methodology"
    assert not cleaned.endswith("as a")
    assert planner._truncate_title(
        "The Memory Bank architecture provides the AI with everything needed to work effectively without prior"
    ).endswith("without") is False
    assert planner._truncate_title(
        "The Memory Bank consists of six core files arranged in a dependency hierarchy for optimal"
    ).endswith("optimal") is False
    assert (
        planner._truncate_title(
            "Commit to the Agentic Coding framework to ensure reliable"
        )
        == "Commit to the Agentic Coding framework"
    )
    assert (
        planner._truncate_title(
            "Commit to Agentic Coding to ensure reliable, traceable"
        )
        == "Commit to Agentic Coding"
    )


def test_openai_compatible_client_sends_reasoning_effort(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "OK", "reasoning_content": ""}}]}

    class FakeHTTPClient:
        payload: dict | None = None

        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self) -> "FakeHTTPClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url: str, json: dict, headers: dict) -> FakeResponse:
            FakeHTTPClient.payload = json
            return FakeResponse()

    monkeypatch.setattr("app.clients.openai_compatible_client.httpx.Client", FakeHTTPClient)

    client = OpenAICompatibleClient(
        Settings(
            OPENAI_COMPATIBLE_BASE_URL="http://metis.local:1240/v1",
            OPENAI_COMPATIBLE_MODEL="qwen3.6-35b-a3b-mtp",
            OPENAI_COMPATIBLE_API_KEY="lm-studio",
            OPENAI_COMPATIBLE_REASONING_EFFORT="none",
            BEDROCK_VALIDATE=False,
        )
    )

    assert client.complete_text("", "Reply exactly with OK.", max_tokens=32, temperature=0) == "OK"
    assert FakeHTTPClient.payload is not None
    assert FakeHTTPClient.payload["reasoning_effort"] == "none"
    assert FakeHTTPClient.payload["messages"][0]["content"].endswith("/no_think")


def test_openai_compatible_client_retries_non_json_response(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, content: str) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": self.content}}]}

    class FakeHTTPClient:
        payloads: list[dict] = []

        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self) -> "FakeHTTPClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url: str, json: dict, headers: dict) -> FakeResponse:
            self.payloads.append(json)
            if len(self.payloads) == 1:
                return FakeResponse("I cannot comply with JSON.")
            return FakeResponse('{"deck_title":"Recovered","slides":[]}')

    monkeypatch.setattr("app.clients.openai_compatible_client.httpx.Client", FakeHTTPClient)

    client = OpenAICompatibleClient(
        Settings(
            OPENAI_COMPATIBLE_BASE_URL="http://metis.local:1240/v1",
            OPENAI_COMPATIBLE_MODEL="qwen3.6-35b-a3b-mtp",
            OPENAI_COMPATIBLE_API_KEY="lm-studio",
            OPENAI_COMPATIBLE_REASONING_EFFORT="none",
            BEDROCK_VALIDATE=False,
        )
    )

    payload = client.complete_json("Return JSON.", "Create a deck.", max_tokens=32)

    assert payload == {"deck_title": "Recovered", "slides": []}
    assert len(FakeHTTPClient.payloads) == 2
    assert "previous response was not parseable" in FakeHTTPClient.payloads[1]["messages"][1]["content"]


def test_openai_compatible_client_extracts_list_content_text() -> None:
    text = OpenAICompatibleClient._extract_message_text(
        {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": '{"deck_title":"A"'},
                            {"type": "text", "text": ',"slides":[]}'},
                        ]
                    }
                }
            ]
        }
    )

    assert text == '{"deck_title":"A"\n,"slides":[]}'


def test_openai_compatible_client_extracts_reasoning_content_when_content_empty() -> None:
    text = OpenAICompatibleClient._extract_message_text(
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": '{"deck_title":"A","slides":[]}',
                    }
                }
            ]
        }
    )

    assert text == '{"deck_title":"A","slides":[]}'


def test_freeform_planner_creates_consulting_slide_specs() -> None:
    planner = ContentPlanner()
    outlines, warnings = planner.plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert len(outlines) >= 4
    assert outlines[0].content_json["action_title"]
    assert outlines[0].content_json["sources"]
    assert all(outline.layout_json["generation_mode"] == "freeform" for outline in outlines)
    assert not any("generic topic label" in warning["message"].lower() for warning in warnings)


def test_source_rich_fallback_uses_adaptive_blueprint_and_archetypes() -> None:
    outlines, warnings = ContentPlanner().plan(
        _template("freeform"),
        _rich_bundle(),
        instructions="Create a consulting deck about moving beyond vibe coding.",
        generation_mode="freeform",
        quality_profile="showcase",
        length_strategy="auto",
    )

    archetypes = [outline.content_json["archetype"] for outline in outlines]
    titles = [outline.content_json["action_title"] for outline in outlines]

    assert 10 <= len(outlines) <= 14
    assert len(set(archetypes)) >= 7
    assert len(set(titles)) == len(titles)
    assert outlines[0].content_json["narrative_role"] == "cover"
    assert outlines[0].layout_json["layout"] == "cover"
    assert all(outline.content_json.get("exhibit_spec") for outline in outlines)
    assert any(archetype == "comparison_table" for archetype in archetypes)
    assert any(archetype == "callouts" for archetype in archetypes)
    assert any(archetype == "icon_rows" for archetype in archetypes)
    assert "code_panel" not in archetypes
    assert "matrix_2x2" not in archetypes
    assert sum(
        archetype in {"dependency_map", "framework_cycle", "code_panel", "table_reference"}
        for archetype in archetypes
    ) <= 5
    assert any(
        warning["field"] == "llm_planning"
        and "not configured" in warning["message"]
        for warning in warnings
    )


def _many_section_bundle(n: int = 24) -> DocumentBundle:
    return DocumentBundle(
        job_id="rich",
        sections=[
            DocumentSection(
                title=f"Topic {i + 1}",
                level=1,
                content="Detailed evidence and analysis for this topic. " * 18,
                source_doc_id="doc-1",
            )
            for i in range(n)
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Rich"),
        content_inventory=[],
    )


def test_source_rich_expanded_blueprint_extends_to_long_deck() -> None:
    planner = ContentPlanner()
    # A genuinely large source (24 sections) so Expanded reaches the ceiling
    # rather than being held back by the source-aware cap.
    blueprint = planner._build_blueprint(
        _many_section_bundle(24),
        "Create a consulting deck about many topics.",
        "freeform",
        quality_profile="fast",
        length_strategy="expanded",
    )

    assert blueprint.target_slide_count == 22
    assert len(blueprint.archetype_sequence) == 22
    assert len(set(blueprint.archetype_sequence)) >= 10
    assert not {
        "code_panel",
        "reference",
        "matrix_2x2",
        "dependency_map",
        "framework_cycle",
    }.intersection(blueprint.archetype_sequence)


def test_expanded_is_capped_by_thin_source_but_explicit_count_is_honored() -> None:
    planner = ContentPlanner()
    thin = _many_section_bundle(6)  # only ~6 topics of distinct material
    expanded = planner._build_blueprint(
        thin, "deck", "freeform", quality_profile="fast", length_strategy="expanded"
    ).target_slide_count
    assert expanded <= 10  # capped near what 6 sections support, not padded to 16/22
    # An explicit brief count is still honored literally despite the thin source.
    explicit = planner._build_blueprint(
        thin, "make an 18 slide deck", "freeform", quality_profile="fast", length_strategy="expanded"
    ).target_slide_count
    assert explicit == 18


def test_spec_gate_does_not_demote_source_rich_cover_to_content_layout() -> None:
    sections = [
        DocumentSection(
            title="Overview",
            level=1,
            content="Overview needs source-backed review before scaling.",
            source_doc_id="doc-1",
            source_id="doc-1:overview",
        ),
        DocumentSection(
            title="Executive Summary",
            level=1,
            content=(
                "Current benchmarking is constrained by saturation, high labeling cost, "
                "and weak fit to enterprise use cases."
            ),
            source_doc_id="doc-1",
            source_id="doc-1:summary",
        ),
        DocumentSection(
            title="The Harness-Centric View",
            level=1,
            content=(
                "The harness-centric view treats benchmark generation as a validity "
                "problem, not a data-generation task."
            ),
            source_doc_id="doc-1",
            source_id="doc-1:harness",
        ),
    ]
    bundle = DocumentBundle(
        job_id="cover-regression",
        sections=sections,
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Bootstrapping Benchmarks"),
        content_inventory=[],
        source_index={
            section.source_id: {"label": f"Bootstrapping Benchmarks > {section.title}"}
            for section in sections
            if section.source_id
        },
    )

    outlines, _warnings = ContentPlanner().plan(
        _template("freeform"),
        bundle,
        instructions="Create a consulting deck about bootstrapping benchmarks.",
        generation_mode="freeform",
        quality_profile="showcase",
        length_strategy="expanded",
    )

    assert outlines[0].layout_json["layout"] == "cover"
    assert outlines[0].layout_json["archetype"] == "cover"
    assert outlines[0].content_json["narrative_role"] == "cover"
    assert outlines[0].label == "Bootstrapping Benchmarks"


def test_fallback_executive_summary_includes_metric_proof_points() -> None:
    bundle = _bundle()
    bundle.metrics = [
        DocumentMetric(
            label="Developers regularly using AI tools",
            value=85,
            unit="%",
            source_doc_id="doc-1",
        ),
        DocumentMetric(
            label="AI-generated codebases",
            value=95,
            unit="%",
            source_doc_id="doc-1",
        ),
    ]
    bundle.sections[0].content += " Developers regularly using AI tools reached 85%."
    bundle.sections[0].content += " AI-generated codebases reached 95%."

    outlines, _warnings = ContentPlanner().plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
        quality_profile="showcase",
        length_strategy="expanded",
    )

    executive = next(
        outline
        for outline in outlines
        if outline.layout_json["layout"] == "executive_summary"
    )
    proof_points = executive.content_json["exhibit_spec"]["proof_points"]

    assert {point["label"] for point in proof_points} >= {
        "Developers regularly using AI tools",
        "AI-generated codebases",
    }


def test_planner_enriches_legacy_llm_specs_with_exhibit_metadata() -> None:
    class LegacySpecLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "checklist",
                        "action_title": "Adopt the transition through a short checklist",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Create memory files", "Define review gates", "Run pilot"],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=LegacySpecLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].content_json["archetype"] == "checklist"
    assert outlines[0].content_json["narrative_role"] == "implementation"
    assert outlines[0].content_json["exhibit_spec"]["type"] == "checklist"
    assert outlines[0].layout_json["archetype"] == "checklist"
    assert not warnings


def test_planner_upgrades_generic_memory_bank_reference_tables() -> None:
    class GenericReferenceLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": "Structure the Memory Bank with Core Files",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "table",
                                "body": [
                                    ["Item", "Implication"],
                                    ["Organize files", "Use a memory-bank directory."],
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the reference artifacts.",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "reference_table",
                            "columns": ["Item", "Implication"],
                            "rows": [["Organize files", "Use a memory-bank directory."]],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=GenericReferenceLLM()).plan(
        _template("freeform"),
        _rich_bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    exhibit = outlines[0].content_json["exhibit_spec"]

    assert warnings == []
    assert outlines[0].layout_json["layout"] == "table_reference"
    assert exhibit["columns"] == ["File", "Role", "Update trigger"]
    assert any(row[0] == "projectbrief.md" for row in exhibit["rows"])


def test_planner_ignores_table_width_metadata_for_numeric_grounding() -> None:
    class ColumnMetadataLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "comparison",
                        "action_title": "Contrast vibe coding with managed agentic engineering",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["The old model relies on memory; the new model uses structure."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the comparison.",
                        "archetype": "comparison_table",
                        "narrative_role": "evidence",
                        "exhibit_spec": {
                            "type": "comparison_table",
                            "columns": [
                                {"name": "Aspect", "width": "20%"},
                                {"name": "Vibe coding", "width": "40%"},
                                {"name": "Managed agentic work", "width": "40%"},
                            ],
                            "rows": [
                                {
                                    "label": "Context",
                                    "values": ["Chat history", "Persistent memory"],
                                }
                            ],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=ColumnMetadataLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    content = outlines[0].content_json

    assert not any(warning["field"] == "source_coverage" for warning in warnings)
    assert content["sources"] == ["Uploaded source"]
    assert "[source needed]" not in str(content["exhibit_spec"])


def test_planner_builds_contextual_code_panel_specs() -> None:
    section = DocumentSection(
        title="3.3 When and How to Update",
        level=2,
        content=(
            "Update memory after meaningful changes so context does not go stale "
            "during the workflow."
        ),
        source_doc_id="beyond-vibe",
    )

    exhibit = ContentPlanner()._exhibit_for_archetype(
        "code_panel",
        section,
        [section],
        [],
    )

    assert exhibit["title"] == "memory-bank/update-protocol.md"
    assert "activeContext.md" in exhibit["lines"][0]
    assert "progress.md" in " ".join(exhibit["lines"])

    reference_exhibit = ContentPlanner()._exhibit_for_archetype(
        "reference",
        DocumentSection(
            title="3. The Memory Bank",
            level=1,
            content="The memory bank acts as persistent context for future sessions.",
            source_doc_id="beyond-vibe",
        ),
        [section],
        [],
    )

    assert reference_exhibit["type"] == "code_panel"
    assert reference_exhibit["title"] == "memory-bank/README.md"

    cycle_exhibit = ContentPlanner()._exhibit_for_archetype(
        "reference",
        DocumentSection(
            title="4.1 The Six-Phase Loop",
            level=2,
            content="The agentic cycle uses phases to frame, prime, generate, review, and reset.",
            source_doc_id="beyond-vibe",
        ),
        [section],
        [],
    )

    assert cycle_exhibit["title"] == "agentic-cycle.md"
    assert "Prime the agent" in cycle_exhibit["lines"][1]

    manager_exhibit = ContentPlanner()._exhibit_for_archetype(
        "code_panel",
        DocumentSection(
            title="2.1 The Developer as Product Manager",
            level=2,
            content="The developer manages an AI employee by assigning scoped work.",
            source_doc_id="beyond-vibe",
        ),
        [section],
        [],
    )

    assert manager_exhibit["title"] == "agent-brief.md"
    assert "assigning work" in manager_exhibit["lines"][0]


def test_section_title_cleanup_removes_multi_level_numbers() -> None:
    planner = ContentPlanner()

    assert planner._clean_section_title("3.1 The Core Files") == "The Core Files"
    assert planner._clean_section_title("8.3 The Accept-All Reflex") == "The Accept-All Reflex"
    assert (
        planner._clean_section_title("4.1 The Agentic Cycle: A Workflow for Reliability")
        == "The Agentic Cycle"
    )


def test_update_section_title_rewrites_without_multiple_messages() -> None:
    title = ContentPlanner()._action_title(
        "3.3 When and How to Update",
        "Update memory after meaningful changes so context does not go stale.",
    )

    assert title == "Update memory after meaningful changes"
    assert " and " not in title.lower()


def test_themed_title_frames_prioritize_specific_cues_before_memory() -> None:
    planner = ContentPlanner()

    assert planner._themed_action_title(
        "context rot",
        "context rot occurs when finite windows erase project memory",
    ) == "Eliminate context rot before it undermines reliability"
    assert planner._themed_action_title(
        "the agentic cycle",
        "the workflow uses a repeatable cycle and reset phase",
    ) == "Run the agentic cycle as a repeatable operating loop"
    assert planner._themed_action_title(
        "markdown-driven development",
        "markdown rules preserve constraints as context changes",
    ) == "Codify markdown-driven development into rules the team can reuse"


def test_benchmark_section_titles_use_domain_specific_action_frames() -> None:
    planner = ContentPlanner()

    assert planner._action_title(
        "Why Not Simply Generate Synthetic Benchmarks?",
        "Static synthetic benchmarks fail to reflect validated operating evidence.",
    ) == "Synthetic benchmarks cannot substitute for validated operating evidence"
    assert planner._action_title(
        "The Model Contract",
        "The model contract specifies the expected behavior and success criteria.",
    ) == "Model contracts make evaluation expectations explicit"
    assert planner._action_title(
        "The Harness Interface",
        "The harness interface defines how evaluation happens in production.",
    ) == "Harness interfaces turn contracts into repeatable tests"
    assert planner._action_title(
        "Conclusion and Future Directions",
        "Agent-assisted benchmark discovery requires governed deployment.",
    ) == "Govern agent-assisted benchmark discovery before deployment"


def test_benchmark_title_repair_removes_qwen_fragment_frames() -> None:
    planner = ContentPlanner()
    slide = GeneratedSlideSpec(
        slide_number=1,
        slide_type="content",
        action_title=(
            "Prioritize leaders must shift mental models from manual labeling "
            "tasks to systematic discovery of implicit ground truth"
        ),
        subheading="Manual labeling should give way to systematic discovery.",
        content_blocks=[],
        sources=["Uploaded source"],
        archetype="quote_sidebar",
        narrative_role="decision",
    )

    assert (
        planner._repair_weak_action_title(slide, slide.action_title)
        == "Shift leaders from manual labeling to systematic discovery"
    )
    assert (
        planner._benchmark_title_repair("make the case for implicit ground truth discovery")
        == "Implicit ground truth discovery turns existing evidence into benchmarks"
    )
    assert (
        planner._benchmark_title_repair("the harness interface defines execution")
        == "Harness interfaces standardize benchmark execution across domains"
    )

    closing = GeneratedSlideSpec(
        slide_number=2,
        slide_type="closing",
        action_title="Commit to the recommendation with named ownership",
        subheading="Benchmark governance requires real operating evidence.",
        content_blocks=[],
        sources=["Uploaded source"],
        archetype="closing_recommendation",
        narrative_role="closing",
    )
    assert (
        planner._repair_weak_action_title(closing, closing.action_title)
        == "Build evaluation systems around real use cases"
    )


def test_fallback_section_selection_uses_blueprint_source_map() -> None:
    sections = [
        DocumentSection(title="Overview", level=1, content="Intro", source_doc_id="doc"),
        DocumentSection(
            title="3.3 When and How to Update",
            level=2,
            content="Update memory after meaningful changes.",
            source_doc_id="doc",
        ),
    ]
    blueprint = DeckBlueprint(
        deck_title="Beyond Vibe Coding",
        audience="Engineering leaders",
        core_thesis="Persistent context makes AI work reliable.",
        target_slide_count=2,
        story_beats=[{"label": "Open"}, {"label": "Reference"}],
        section_plan=[{"label": "Open"}, {"label": "Reference"}],
        archetype_sequence=["cover", "code_panel"],
        source_coverage_map={"2": ["doc:When and How to Update"]},
    )

    section = ContentPlanner()._section_for_blueprint_slot(1, sections, blueprint)

    assert section.title == "3.3 When and How to Update"


def test_blueprint_source_map_spans_long_documents() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="long-doc",
        sections=[
            DocumentSection(
                title=f"Chapter {index}",
                level=1,
                content=f"Evidence from chapter {index}.",
                source_doc_id="doc",
            )
            for index in range(1, 31)
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Long Document"),
        content_inventory=[],
    )

    source_map = planner._source_coverage_map(bundle, target_slide_count=5)

    assert "Chapter 1" in source_map["1"][0]
    assert "Chapter 30" in source_map["5"][0]
    assert len({refs[0] for refs in source_map.values()}) == 5


def test_blueprint_source_map_represents_multiple_documents() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="multi-doc",
        sections=[
            DocumentSection(
                title=f"Alpha {index}",
                level=1,
                content=f"Alpha document section {index}.",
                source_doc_id="alpha",
            )
            for index in range(1, 6)
        ]
        + [
            DocumentSection(
                title=f"Beta {index}",
                level=1,
                content=f"Beta document section {index}.",
                source_doc_id="beta",
            )
            for index in range(1, 6)
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Multi Document"),
        content_inventory=[],
    )

    source_map = planner._source_coverage_map(bundle, target_slide_count=4)
    refs = [refs[0] for refs in source_map.values()]

    assert any(ref.startswith("alpha:") for ref in refs)
    assert any(ref.startswith("beta:") for ref in refs)


def test_planner_source_packet_includes_whole_document_outline() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="long-doc",
        sections=[
            DocumentSection(
                title=f"Chapter {index}",
                level=1,
                content=(
                    f"Evidence from chapter {index}. "
                    f"Decision implication {index} should inform the story."
                ),
                source_doc_id="doc",
            )
            for index in range(1, 31)
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Long Document"),
        content_inventory=[],
    )
    blueprint = DeckBlueprint(
        deck_title="Long Document",
        audience="Engineering leaders",
        core_thesis="The whole document should inform the deck.",
        target_slide_count=5,
        story_beats=[],
        section_plan=[],
        archetype_sequence=[
            "cover",
            "executive_summary",
            "comparison_table",
            "checklist",
            "closing_recommendation",
        ],
        source_coverage_map=planner._source_coverage_map(bundle, target_slide_count=5),
    )

    packet = planner._planner_source_packet(bundle, blueprint, "balanced")

    outline_titles = [
        section["title"] for section in packet["document_outline"]["sections"]
    ]
    detailed_titles = [section["title"] for section in packet["sections"]]
    assert packet["document_outline"]["section_count"] == 30
    assert "Chapter 30" in outline_titles
    assert "Chapter 30" in detailed_titles


def test_planner_source_packet_caps_huge_document_outline() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="huge-doc",
        sections=[
            DocumentSection(
                title=f"Chapter {index}",
                level=1,
                content=(
                    f"Evidence from chapter {index}. "
                    f"Decision implication {index} should inform the story."
                ),
                source_doc_id="doc",
            )
            for index in range(1, 151)
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Huge Document"),
        content_inventory=[],
    )
    blueprint = DeckBlueprint(
        deck_title="Huge Document",
        audience="Engineering leaders",
        core_thesis="The full document should inform the deck.",
        target_slide_count=12,
        story_beats=[],
        section_plan=[],
        archetype_sequence=["cover"] * 12,
        source_coverage_map=planner._source_coverage_map(bundle, target_slide_count=12),
    )

    packet = planner._planner_source_packet(bundle, blueprint, "balanced")
    outline_titles = [
        section["title"] for section in packet["document_outline"]["sections"]
    ]

    assert packet["document_outline"]["section_count"] == 150
    assert packet["document_outline"]["included_section_count"] == 80
    assert packet["document_outline"]["omitted_section_count"] == 70
    assert packet["document_outline"]["coverage"] == "representative"
    assert "Chapter 150" in outline_titles


def test_source_compression_spans_long_documents_and_estimates_tokens() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="long-compression",
        sections=[
            DocumentSection(
                title=f"Chapter {index}",
                level=1,
                content=f"Evidence from chapter {index}. Risk and recommendation {index}.",
                source_doc_id="doc",
            )
            for index in range(1, 31)
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Long Compression"),
        content_inventory=[],
    )

    compression = planner._build_source_compression(bundle, "balanced")
    titles = [unit.title for unit in compression.evidence_units]

    assert compression.section_count == 30
    assert compression.coverage == "full"
    assert compression.estimated_tokens > 0
    assert "Chapter 1" in titles
    assert "Chapter 30" in titles
    assert compression.tensions


def test_source_compression_represents_multiple_documents() -> None:
    planner = ContentPlanner()
    bundle = DocumentBundle(
        job_id="multi-compression",
        sections=[
            DocumentSection(
                title="Alpha opening",
                level=1,
                content="Alpha evidence creates the initial problem.",
                source_doc_id="alpha",
            ),
            DocumentSection(
                title="Beta opening",
                level=1,
                content="Beta evidence defines the recommendation.",
                source_doc_id="beta",
            ),
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Multi Compression"),
        content_inventory=[],
    )

    compression = planner._build_source_compression(bundle, "fast")

    assert {entry["source_doc_id"] for entry in compression.document_manifest} == {
        "alpha",
        "beta",
    }
    assert {unit.source_doc_id for unit in compression.evidence_units} == {
        "alpha",
        "beta",
    }


def test_story_map_uses_llm_and_fails_when_deck_planning_fails() -> None:
    class StoryMapLLM:
        def __init__(self) -> None:
            self.prompts = []

        def complete_json(self, **kwargs):
            self.prompts.append(kwargs["user_prompt"])
            if "Create a consulting story map" in kwargs["user_prompt"]:
                return {
                    "thesis": "Persistent context improves delivery.",
                    "narrative_arc": "Situation -> Complication -> Resolution",
                    "recommendation": "Adopt source-backed review.",
                    "beats": [
                        {
                            "beat_number": 1,
                            "role": "cover",
                            "claim": "Translate persistent context into a delivery decision",
                            "source_refs": ["doc-1:Developer Productivity"],
                            "preferred_exhibit": "cover",
                            "rationale": "Set the thesis.",
                        },
                        {
                            "beat_number": 2,
                            "role": "evidence",
                            "claim": "Use source-backed review to reduce delivery risk",
                            "source_refs": ["doc-1:Quality Risk"],
                            "preferred_exhibit": "callouts",
                            "rationale": "Support the decision.",
                        },
                    ],
                }
            return None

    llm = StoryMapLLM()
    planner = ContentPlanner(llm_client=llm)
    with pytest.raises(PlanningFailedError, match="deterministic planning fallback is disabled"):
        planner.plan(
            _template("freeform"),
            _bundle(),
            instructions="Create a deck on moving beyond vibe coding.",
            generation_mode="freeform",
            quality_profile="fast",
        )

    assert planner.last_planning_artifacts["story-map"]["status"] == "llm"
    assert any("Story map:" in prompt for prompt in llm.prompts)


def test_story_map_marks_malformed_llm_response_unavailable() -> None:
    class MalformedStoryMapLLM:
        def complete_json(self, **kwargs):
            if "Create a consulting story map" in kwargs["user_prompt"]:
                return {"beats": []}
            return None

    planner = ContentPlanner(llm_client=MalformedStoryMapLLM())
    with pytest.raises(PlanningFailedError, match="deterministic planning fallback is disabled"):
        planner.plan(
            _template("freeform"),
            _bundle(),
            instructions="Create a deck on moving beyond vibe coding.",
            generation_mode="freeform",
            quality_profile="fast",
        )

    story_map = planner.last_planning_artifacts["story-map"]
    assert story_map["status"] == "unavailable"
    assert story_map["beats"] == []
    assert "contained no beats" in story_map["fallback_reason"]


def test_qwen_planner_uses_llm_story_map() -> None:
    class QwenDeckLLM:
        model = "qwen3.6-35b-a3b-mtp"

        def __init__(self) -> None:
            self.prompts = []

        def complete_json(self, **kwargs):
            self.prompts.append(kwargs["user_prompt"])
            if "Create a consulting story map" in kwargs["user_prompt"]:
                return {
                    "thesis": "Persistent context improves delivery.",
                    "narrative_arc": "Situation -> Complication -> Resolution",
                    "recommendation": "Adopt source-backed review.",
                    "beats": [
                        {
                            "beat_number": 1,
                            "role": "cover",
                            "claim": "Translate AI delivery into an executive operating decision",
                            "source_refs": ["doc-1:Developer Productivity"],
                            "preferred_exhibit": "cover",
                            "rationale": "Set the thesis.",
                        },
                        {
                            "beat_number": 2,
                            "role": "evidence",
                            "claim": "Use source-backed review to reduce quality risk",
                            "source_refs": ["doc-1:Quality Risk"],
                            "preferred_exhibit": "callouts",
                            "rationale": "Prove the operating need.",
                        },
                    ],
                }
            target = int(re.search(r"Create a (\d+)-slide", kwargs["user_prompt"]).group(1))
            slides = [
                {
                    "slide_number": 1,
                    "slide_type": "cover",
                    "action_title": "Translate AI delivery into an executive operating decision",
                    "subheading": "Persistent context improves delivery reliability.",
                    "content_blocks": [
                        {
                            "type": "bullets",
                            "body": ["Persistent context improves delivery reliability."],
                            "annotations": [],
                            "callouts": [],
                        }
                    ],
                    "chart_spec": None,
                    "sources": ["Uploaded source"],
                    "speaker_notes": "Set the thesis.",
                    "archetype": "cover",
                    "narrative_role": "cover",
                    "exhibit_spec": {"type": "cover"},
                    "source_refs": ["doc-1:Developer Productivity"],
                    "qa": {
                        "consulting_status": "pending",
                        "visual_status": "pending",
                        "issues": [],
                    },
                }
            ]
            workflow_names = [
                "priority intake",
                "architecture review",
                "acceptance testing",
                "release readiness",
                "handoff governance",
                "memory refresh",
                "quality review",
                "decision logging",
                "operating cadence",
                "risk triage",
            ]
            for number in range(2, target + 1):
                workflow = workflow_names[(number - 2) % len(workflow_names)]
                slides.append(
                    {
                        "slide_number": number,
                        "slide_type": "content",
                        "action_title": f"Use source-backed review to reduce {workflow} risk",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Testing and acceptance criteria reduce quality risk."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "archetype": "callouts",
                        "narrative_role": "evidence",
                        "exhibit_spec": {
                            "type": "callouts",
                            "points": ["Testing and acceptance criteria reduce quality risk."],
                        },
                        "source_refs": ["doc-1:Quality Risk"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                )
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": slides,
            }

    llm = QwenDeckLLM()
    # This test pins the monolithic single-call path it was written for; the
    # decomposed (batched/per-slide) path is covered by test_planning_decomposition.
    planner = ContentPlanner(llm_client=llm, decompose=False)
    outlines, warnings = planner.plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
        quality_profile="fast",
    )

    assert outlines
    assert any("Create a consulting story map" in prompt for prompt in llm.prompts)
    # Exactly one monolithic deck call (no schema-repair retry).
    assert len([p for p in llm.prompts if "consulting deck plan" in p]) == 1
    story_map = planner.last_planning_artifacts["story-map"]
    assert story_map["status"] == "llm"
    assert story_map["fallback_reason"] is None
    assert not any(warning["field"] == "llm_planning" for warning in warnings)


def test_qwen_partial_deck_is_completed_from_blueprint_without_schema_retry() -> None:
    class PartialQwenLLM:
        model = "qwen3.6-35b-a3b-mtp"

        def __init__(self) -> None:
            self.prompts = []

        def complete_json(self, **kwargs):
            self.prompts.append(kwargs["user_prompt"])
            if "Create a consulting story map" in kwargs["user_prompt"]:
                return {
                    "thesis": "Benchmark harnesses make model quality observable.",
                    "narrative_arc": "Situation -> Complication -> Resolution",
                    "recommendation": "Adopt contract-driven benchmark loops.",
                    "beats": [
                        {
                            "beat_number": 1,
                            "role": "cover",
                            "claim": "Make benchmark quality visible before scaling agents",
                            "source_refs": ["doc-1:Developer Productivity"],
                            "preferred_exhibit": "cover",
                            "rationale": "Set the decision.",
                        }
                    ],
                }
            if "Your previous response did not satisfy" in kwargs["user_prompt"]:
                raise AssertionError("Qwen harness should not run giant schema repair retry")
            return {
                "deck_title": "Bootstrapping Benchmarks",
                "audience": "AI product leaders",
                "goal": "Define the harness decision.",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "cover",
                        "action_title": "Make benchmark quality visible before scaling agents",
                        "subheading": "Harness design turns model behavior into operating evidence.",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Benchmark harnesses expose quality before rollout."],
                            }
                        ],
                        "sources": ["Uploaded source"],
                        "archetype": "cover",
                        "narrative_role": "cover",
                        "exhibit_spec": {"type": "cover"},
                        "source_refs": ["doc-1:Developer Productivity"],
                    },
                    {
                        "slide_number": 2,
                        "slide_type": "content",
                        "action_title": "Use model contracts to constrain benchmark interpretation",
                        "subheading": "Contracts separate expected behavior from anecdotal demos.",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Contracts define what the model must prove."],
                            }
                        ],
                        "sources": ["Uploaded source"],
                        "archetype": "callouts",
                        "narrative_role": "evidence",
                        "exhibit_spec": {"type": "callouts", "points": ["Contracts define proof."]},
                        "source_refs": ["doc-1:Quality Risk"],
                    },
                ],
            }

    llm = PartialQwenLLM()
    # Pins the monolithic single-call completion path this test validates.
    outlines, warnings = ContentPlanner(llm_client=llm, decompose=False).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a concise executive deck about bootstrapping benchmarks.",
        generation_mode="freeform",
        quality_profile="fast",
    )

    # The minimal 2-section fixture floors at 6 slides; the partial deck is
    # completed from the blueprint up to that target.
    assert len(outlines) == 6
    # Partial deck completed from the blueprint with no schema-repair retry:
    # exactly one monolithic deck-generation call.
    assert len([p for p in llm.prompts if "consulting deck plan" in p]) == 1
    assert outlines[1].content_json["action_title"].startswith("Use model contracts")
    assert outlines[2].content_json["action_title"]
    assert not any(warning["field"] == "llm_planning" for warning in warnings)


def test_llm_deck_payload_must_match_blueprint_slide_count() -> None:
    blueprint = DeckBlueprint(
        deck_title="Beyond Vibe Coding",
        audience="Engineering leaders",
        core_thesis="Persistent context improves delivery.",
        target_slide_count=4,
        archetype_sequence=["cover", "executive_summary", "comparison_table", "closing_recommendation"],
        source_coverage_map={},
    )
    payload = {
        "deck_title": "Beyond Vibe Coding",
        "audience": "Engineering leaders",
        "goal": "Improve AI-assisted delivery quality",
        "narrative_arc": "Situation -> Complication -> Resolution",
        "slides": [
            {
                "slide_number": 1,
                "slide_type": "cover",
                "action_title": "Translate AI delivery into an executive operating decision",
                "subheading": "Persistent context improves delivery reliability.",
                "content_blocks": [
                    {
                        "type": "bullets",
                        "body": ["Persistent context improves delivery reliability."],
                    }
                ],
                "sources": ["Uploaded source"],
                "archetype": "cover",
                "narrative_role": "cover",
            }
        ],
    }
    planner = ContentPlanner()

    deck = planner._validate_deck_payload(payload, blueprint)

    assert deck is None
    assert "exactly 4 slides" in (planner._last_planning_error or "")


def test_llm_payload_normalizes_structured_callouts_before_validation() -> None:
    planner = ContentPlanner()
    blueprint = DeckBlueprint(
        deck_title="Bootstrapping Benchmarks",
        audience="AI leaders",
        core_thesis="Harnesses make model quality observable.",
        target_slide_count=1,
        archetype_sequence=["callouts"],
    )
    deck = planner._validate_deck_payload(
        {
            "deck_title": "Bootstrapping Benchmarks",
            "audience": "AI leaders",
            "goal": "Improve benchmark quality.",
            "narrative_arc": "Situation -> Complication -> Resolution",
            "slides": [
                {
                    "slide_number": 1,
                    "slide_type": "content",
                    "action_title": "Use benchmark contracts to focus model evaluation",
                    "subheading": "Structured callouts should validate.",
                    "content_blocks": [
                        {
                            "type": "callout",
                            "body": ["Benchmark contracts reduce ambiguity."],
                            "callouts": [
                                {
                                    "title": "Benchmark saturation",
                                    "description": "Static suites hide real-world failures.",
                                }
                            ],
                        }
                    ],
                    "sources": ["Uploaded source"],
                    "archetype": "callouts",
                    "narrative_role": "evidence",
                    "exhibit_spec": {"type": "callouts"},
                    "source_refs": ["doc-1:Benchmarks"],
                }
            ],
        },
        blueprint,
    )

    assert deck is not None
    assert (
        deck.slides[0].content_blocks[0].callouts
        == ["Benchmark saturation: Static suites hide real-world failures."]
    )


def test_exhibit_selector_promotes_metric_claim_to_chart() -> None:
    planner = ContentPlanner()
    bundle = _bundle()
    bundle.metrics = [
        DocumentMetric(
            label="Developers using AI",
            value=85,
            unit="%",
            source_doc_id="doc-1",
        ),
        DocumentMetric(
            label="AI-generated code",
            value=95,
            unit="%",
            source_doc_id="doc-1",
        ),
        DocumentMetric(
            label="Context window",
            value=200000,
            unit="tokens",
            source_doc_id="doc-1",
        ),
    ]
    slide = GeneratedSlideSpec(
        slide_number=1,
        slide_type="content",
        action_title="Quantify AI adoption before scaling delivery",
        content_blocks=[ContentBlock(type="bullets", body=["AI adoption reached 85%."])],
        sources=["Uploaded source"],
        source_refs=["doc-1:Developer Productivity"],
        archetype="two_column",
        exhibit_spec={"type": "two_column", "points": ["AI adoption reached 85%."]},
    )
    deck = DeckSpec(deck_title="Selector", slides=[slide])

    planner._apply_exhibit_selection(deck, bundle)

    assert deck.slides[0].archetype == "metric_chart"
    assert deck.slides[0].chart_spec["type"] == "bar"


def test_spec_gate_repairs_duplicate_and_over_budget_slide_specs() -> None:
    planner = ContentPlanner()
    bundle = _bundle()
    blueprint = planner._build_blueprint(
        bundle,
        "Create a deck.",
        "freeform",
        quality_profile="balanced",
        length_strategy="auto",
    )
    compression = planner._build_source_compression(bundle, "balanced")
    story_map = StoryMap(
        status="fallback",
        thesis="Improve delivery quality.",
        recommendation="Adopt source-backed review.",
        beats=[],
    )
    duplicate_body = [" ".join(["Repeated evidence point"] * 20) for _ in range(8)]
    slides = [
        GeneratedSlideSpec(
            slide_number=1,
            slide_type="content",
            action_title="Overview",
            content_blocks=[ContentBlock(type="bullets", body=duplicate_body)],
            sources=["Uploaded source"],
            source_refs=["doc-1:Developer Productivity"],
            archetype="two_column",
            exhibit_spec={"type": "two_column", "points": duplicate_body},
        ),
        GeneratedSlideSpec(
            slide_number=2,
            slide_type="content",
            action_title="Overview",
            content_blocks=[ContentBlock(type="bullets", body=duplicate_body)],
            sources=["Uploaded source"],
            source_refs=["doc-1:Developer Productivity"],
            archetype="two_column",
            exhibit_spec={"type": "two_column", "points": duplicate_body},
        ),
    ]
    deck = DeckSpec(deck_title="Gate", slides=slides, blueprint=blueprint)

    report = planner._run_spec_gate(deck, bundle, compression, story_map)

    categories = {issue.category for issue in report.issues}
    assert "action_title" in categories
    assert "content_budget" in categories
    assert "duplicate_slide" in categories
    assert report.repaired_count >= 3
    assert deck.slides[1].source_refs != ["doc-1:Developer Productivity"]
    assert len(deck.slides[0].content_blocks[0].body) <= 5


def test_spec_gate_removes_supported_model_source_placeholder() -> None:
    planner = ContentPlanner()
    bundle = _bundle()
    bundle.sections[0].content += " Teams reported 42% fewer escaped defects."
    blueprint = planner._build_blueprint(
        bundle,
        "Create a deck.",
        "freeform",
        quality_profile="fast",
        length_strategy="concise",
    )
    compression = planner._build_source_compression(bundle, "fast")
    story_map = StoryMap(
        status="fallback",
        thesis="Improve delivery quality.",
        recommendation="Adopt source-backed review.",
        beats=[],
    )
    deck = DeckSpec(
        deck_title="Gate",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Reduce escaped defects by 42%",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Teams reported 42% fewer defects after adoption. [source needed]"],
                    )
                ],
                sources=["Uploaded source", "[source needed]"],
                source_refs=["doc-1:Developer Productivity", "[source needed]"],
                archetype="two_column",
                exhibit_spec={
                    "type": "two_column",
                    "points": ["Teams reported 42% fewer defects after adoption. [source needed]"],
                },
            )
        ],
        blueprint=blueprint,
    )

    report = planner._run_spec_gate(deck, bundle, compression, story_map)

    assert "[source needed]" not in deck.slides[0].content_blocks[0].body[0]
    assert "[source needed]" not in str(deck.slides[0].exhibit_spec)
    assert deck.slides[0].sources == ["Uploaded source"]
    assert deck.slides[0].source_refs == ["doc-1:Developer Productivity"]
    assert any(
        repair.action == "remove_supported_source_placeholder"
        for repair in report.repairs
    )
    assert report.unresolved_count == 0


def test_spec_gate_removes_nonnumeric_source_placeholder_when_slide_is_grounded() -> None:
    planner = ContentPlanner()
    bundle = _bundle()
    blueprint = planner._build_blueprint(
        bundle,
        "Create a deck.",
        "freeform",
        quality_profile="fast",
        length_strategy="concise",
    )
    compression = planner._build_source_compression(bundle, "fast")
    story_map = StoryMap(
        status="fallback",
        thesis="Improve delivery quality.",
        recommendation="Adopt source-backed review.",
        beats=[],
    )
    deck = DeckSpec(
        deck_title="Gate",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Persistent context reduces delivery ambiguity [source needed]",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Persistent context keeps review decisions traceable. [source needed]"],
                    )
                ],
                sources=["Uploaded source", "[source needed]"],
                source_refs=["doc-1:Developer Productivity", "[source needed]"],
                archetype="two_column",
                exhibit_spec={
                    "type": "two_column",
                    "points": [
                        "Persistent context keeps review decisions traceable. [source needed]"
                    ],
                },
            )
        ],
        blueprint=blueprint,
    )

    report = planner._run_spec_gate(deck, bundle, compression, story_map)

    assert "[source needed]" not in deck.slides[0].action_title
    assert "[source needed]" not in deck.slides[0].content_blocks[0].body[0]
    assert "[source needed]" not in str(deck.slides[0].exhibit_spec)
    assert deck.slides[0].source_refs == ["doc-1:Developer Productivity"]
    assert report.unresolved_count == 0


def test_spec_gate_rebuilds_malformed_llm_source_fragments() -> None:
    planner = ContentPlanner()
    bundle = _bundle()
    blueprint = planner._build_blueprint(
        bundle,
        "Create a deck.",
        "freeform",
        quality_profile="fast",
        length_strategy="concise",
    )
    compression = planner._build_source_compression(bundle, "fast")
    story_map = StoryMap(
        status="fallback",
        thesis="Improve delivery quality.",
        recommendation="Adopt source-backed review.",
        beats=[],
    )
    deck = DeckSpec(
        deck_title="Gate",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Rather than asking how do we",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=[
                            "Test generated work against harness-centric design turns existing.",
                            "Instead of looking at using models to create direct synthetic data.",
                        ],
                    )
                ],
                sources=["Uploaded source"],
                source_refs=["doc-1:Developer Productivity"],
                archetype="comparison_table",
                exhibit_spec={
                    "type": "comparison_table",
                    "columns": ["Signal", "Current readout", "Target move"],
                    "rows": [
                        [
                            "Current readout",
                            "Rather than asking how do we",
                            "Test generated work against harness-centric design turns existing.",
                        ]
                    ],
                },
            )
        ],
        blueprint=blueprint,
    )

    report = planner._run_spec_gate(deck, bundle, compression, story_map)
    rendered = json.dumps(deck.slides[0].model_dump()).lower()

    assert any(repair.action == "rebuild_bad_copy" for repair in report.repairs)
    assert "rather than asking how do we" not in rendered
    assert "turns existing" not in rendered
    assert "instead of looking at using models" not in rendered
    assert deck.slides[0].archetype in {"callouts", "icon_rows"}
    assert report.unresolved_count == 0


def test_planner_raises_when_configured_client_fails() -> None:
    class FailingLLM:
        def complete_json(self, **kwargs):
            raise TimeoutError("model timed out")

    planner = ContentPlanner(llm_client=FailingLLM())
    with pytest.raises(PlanningFailedError, match="TimeoutError: model timed out"):
        planner.plan(
            _template("freeform"),
            _bundle(),
            instructions="Create a deck on moving beyond vibe coding.",
            generation_mode="freeform",
        )


def test_planner_ignores_malformed_llm_blueprint_metadata() -> None:
    class MalformedBlueprintLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "blueprint": {
                    "deck_title": "Beyond Vibe Coding",
                    "audience": "Engineering leaders",
                    "core_thesis": "Persistent context improves reliability.",
                    "target_slide_count": 1,
                    "story_beats": ["A malformed but harmless beat"],
                    "section_plan": [],
                    "archetype_sequence": ["cover"],
                    "source_coverage_map": {},
                },
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "cover",
                        "action_title": "Adopt Agentic Coding to Manage AI Reliability",
                        "subheading": "A practical operating model",
                        "content_blocks": [
                            {
                                "type": "text",
                                "body": ["Persistent context makes AI work reliable."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Open the deck.",
                        "archetype": "cover",
                        "narrative_role": "cover",
                        "exhibit_spec": {"type": "cover"},
                        "design_intent": "dark editorial cover",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=MalformedBlueprintLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert len(outlines) == 1
    assert outlines[0].label == "Beyond Vibe Coding"
    assert outlines[0].content_json["deck_title"] == "Beyond Vibe Coding"
    assert not any(warning["field"] == "llm_planning" for warning in warnings)


def test_planner_repairs_compound_llm_action_titles() -> None:
    class CompoundTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": (
                            "Identify context rot and hallucination as structural barriers "
                            "to scalable AI development."
                        ),
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Context loss and hallucinations reduce reliability."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the risk.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    planner = ContentPlanner(llm_client=CompoundTitleLLM())
    outlines, warnings = planner.plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Identify structural barriers to scalable AI development"
    assert not warnings


def test_planner_repairs_qwen_cover_title_concatenation() -> None:
    planner = ContentPlanner()
    deck = DeckSpec(
        deck_title="Beyond Vibe Coding",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="cover",
                action_title=(
                    "Beyond Vibe Coding a Framework for Agentic Software "
                    "Development How to stop chatting with AI"
                ),
                archetype="cover",
                narrative_role="cover",
            )
        ],
    )

    planner._repair_model_titles(deck)

    assert deck.slides[0].action_title == "Beyond Vibe Coding"


def test_planner_repairs_reviewer_mode_title_artifact() -> None:
    planner = ContentPlanner()
    deck = DeckSpec(
        deck_title="Beyond Vibe Coding",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="quote",
                action_title=(
                    "Review reviewer mode the developers new core competency "
                    "before trusting the generated output"
                ),
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Reviewer mode requires checking outputs against the plan."],
                    )
                ],
                archetype="quote_sidebar",
                narrative_role="decision",
            )
        ],
    )

    planner._repair_model_titles(deck)

    assert deck.slides[0].action_title == "Use reviewer mode as the default quality gate"


def test_planner_repairs_generic_model_action_titles() -> None:
    class GenericTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Define Specifications",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": [
                                    "Acceptance criteria should constrain generation before agents build."
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the operating rule.",
                        "archetype": "checklist",
                        "narrative_role": "implementation",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=GenericTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Define acceptance criteria before execution begins"
    assert not warnings


def test_planner_repairs_repeated_action_titles_without_slide_suffix() -> None:
    class RepeatedTitleLLM:
        def complete_json(self, **kwargs):
            slides = []
            for idx, archetype in enumerate(["code_panel", "checklist"], start=1):
                slides.append(
                    {
                        "slide_number": idx,
                        "slide_type": "reference" if archetype == "code_panel" else "checklist",
                        "action_title": "Define acceptance criteria before execution begins",
                        "subheading": "Evidence from Quality Risk",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Acceptance criteria make generated work reviewable."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the operating discipline.",
                        "archetype": archetype,
                        "narrative_role": "implementation",
                        "exhibit_spec": {"type": archetype, "items": []},
                        "design_intent": "acceptance criteria operating rules",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                )
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": slides,
            }

    outlines, warnings = ContentPlanner(llm_client=RepeatedTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    titles = [outline.label for outline in outlines]
    assert len(titles) == len(set(titles))
    assert all("for slide" not in title.lower() for title in titles)
    assert titles[1] == "Use acceptance criteria as pre-execution review gates"
    assert not warnings


def test_planner_removes_ellipsis_from_repaired_action_titles() -> None:
    class EllipsisTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": "Standardize a structured set of markdown files... as a reusable reference",
                        "subheading": "Evidence from a structured set of markdown files that preserve context",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Memory files preserve decisions across sessions."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the reference.",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "exhibit_spec": {"type": "reference_table", "rows": []},
                        "design_intent": "compact reference table",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=EllipsisTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert "..." not in outlines[0].label
    assert "…" not in outlines[0].label
    assert not warnings


def test_planner_repairs_reference_to_titles_for_code_panels() -> None:
    class ReferenceTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": "Turn reference to the six-phase loop",
                        "subheading": "Evidence from agentic cycle",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["The cycle uses frame, prime, generate, review, and reset phases."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the cycle reference.",
                        "archetype": "code_panel",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "code_panel",
                            "lines": ["Frame the request", "Review the output"],
                        },
                        "design_intent": "reference the six-phase loop",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=ReferenceTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Codify the operating cycle as reusable rules"
    assert not warnings


def test_planner_repairs_detail_titles_for_code_panels() -> None:
    class DetailTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": (
                            "Detail the six-phase loop that guarantees reliable agentic software development"
                        ),
                        "subheading": "Evidence from agentic cycle",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["The six-phase loop structures reliable agentic work."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the cycle reference.",
                        "archetype": "code_panel",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "code_panel",
                            "lines": ["Frame the request", "Review the output"],
                        },
                        "design_intent": "reference the six-phase loop",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=DetailTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Codify the operating cycle as reusable rules"
    assert not warnings


def test_planner_repairs_embedded_source_clause_titles() -> None:
    class EmbeddedClauseTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "chart",
                        "action_title": (
                            "Turn context windows are finite even large into an explicit operating decision"
                        ),
                        "subheading": "Evidence from context windows",
                        "content_blocks": [
                            {
                                "type": "chart",
                                "body": [
                                    {"label": "Context window", "value": "1M", "unit": "tokens"}
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain why external memory is needed.",
                        "archetype": "metric_chart",
                        "narrative_role": "evidence",
                        "exhibit_spec": {
                            "type": "metric_chart",
                            "metrics": [
                                {"label": "Context window", "value": "1M", "unit": "tokens"}
                            ],
                        },
                        "design_intent": "metric chart about finite context windows",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=EmbeddedClauseTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Quantify context-window limits before relying on model memory"
    assert not warnings


def test_planner_repairs_embedded_source_clause_reference_titles() -> None:
    class EmbeddedReferenceClauseLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": (
                            "Standardize six core files arranged in a as a reusable reference"
                        ),
                        "subheading": "Evidence from Memory Bank structure",
                        "content_blocks": [
                            {
                                "type": "table",
                                "body": [
                                    ["File", "Role", "Update trigger"],
                                    ["projectbrief.md", "Foundation", "Scope changes"],
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the reference table.",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "reference_table",
                            "columns": ["File", "Role", "Update trigger"],
                            "rows": [["projectbrief.md", "Foundation", "Scope changes"]],
                        },
                        "design_intent": "compact memory bank reference table",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=EmbeddedReferenceClauseLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Standardize Memory Bank files as a reusable reference"
    assert not warnings


def test_planner_repairs_awry_memory_reference_titles() -> None:
    class AwryReferenceTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "reference",
                        "action_title": (
                            "Standardize the core files six-file hierarchy as a reusable reference"
                        ),
                        "subheading": "Evidence from Memory Bank structure",
                        "content_blocks": [
                            {
                                "type": "table",
                                "body": [
                                    ["File", "Role", "Update trigger"],
                                    ["projectbrief.md", "Foundation", "Scope changes"],
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the reference table.",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "reference_table",
                            "columns": ["File", "Role", "Update trigger"],
                            "rows": [["projectbrief.md", "Foundation", "Scope changes"]],
                        },
                        "design_intent": "compact memory bank reference table",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=AwryReferenceTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Standardize Memory Bank files as a reusable reference"
    assert not warnings


def test_planner_repairs_process_titles_on_closing_slides() -> None:
    class ProcessClosingTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "closing",
                        "action_title": "Run the operating cycle with explicit review gates",
                        "subheading": "Reset sessions after updating memory",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Adopt the cycle as the default operating cadence."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Close with the decision.",
                        "archetype": "closing_recommendation",
                        "narrative_role": "closing",
                        "exhibit_spec": {
                            "type": "recommendation",
                            "recommendation": "Adopt the operating cycle",
                            "next_steps": ["Name owner"],
                        },
                        "design_intent": "closing recommendation",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=ProcessClosingTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Commit to persistent context as the operating default"
    assert not warnings


def test_planner_repairs_wordy_section_divider_titles() -> None:
    class WordyDividerTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "section",
                        "action_title": (
                            "Translate why ephemeral conversations fail into an explicit operating decision"
                        ),
                        "subheading": "Why ephemeral conversations fail professional software development",
                        "content_blocks": [
                            {
                                "type": "text",
                                "body": ["Ephemeral prompting loses context between sessions."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Introduce the next section.",
                        "archetype": "section_divider",
                        "narrative_role": "evidence",
                        "exhibit_spec": {"type": "section_divider"},
                        "design_intent": "dark editorial divider",
                        "source_refs": ["Uploaded source"],
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=WordyDividerTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    # Headline casing lowercases the minor word "from" (AP style, matching the
    # reference deck's titles) while keeping the major words capitalized.
    assert outlines[0].label == "Shift from Ephemeral Chat to Persistent Context"
    assert not warnings


def test_planner_removes_meta_exhibit_language_from_action_titles() -> None:
    class MetaTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "checklist",
                        "action_title": "Use step-by-step guide to establishing memory bank as a distinct exhibit",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Create files", "Assign owners", "Refresh memory"],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the checklist.",
                        "archetype": "checklist",
                        "narrative_role": "implementation",
                        "exhibit_spec": {
                            "type": "checklist",
                            "items": [
                                {"action": "Create files", "owner": "Lead", "timing": "Initial"},
                                {"action": "Assign owners", "owner": "EM", "timing": "Initial"},
                                {"action": "Refresh memory", "owner": "Team", "timing": "Ongoing"},
                            ],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=MetaTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert "distinct exhibit" not in outlines[0].label.lower()
    assert outlines[0].label == "Implement the memory bank through a short operating checklist"
    assert not warnings


def test_planner_replaces_meta_storyline_action_titles() -> None:
    class MetaStorylineTitleLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "table_reference",
                        "action_title": "Advance the Storyline with Source-Grounded Evidence",
                        "subheading": "Six-phase operating loop",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": [
                                    "Plan work",
                                    "Generate code",
                                    "Review output",
                                    "Update memory",
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the reusable reference.",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "design_intent": "compact reference table for the six-phase operating loop",
                        "exhibit_spec": {
                            "type": "table_reference",
                            "columns": ["Phase", "Rule"],
                            "rows": [
                                ["Plan", "Set acceptance criteria"],
                                ["Generate", "Use current context"],
                                ["Review", "Check against source"],
                            ],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=MetaStorylineTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].label == "Standardize six-phase operating loop as a reusable reference"
    assert "source-grounded" not in outlines[0].label.lower()
    assert "storyline" not in outlines[0].label.lower()
    assert not warnings


def test_planner_rewrites_soft_beat_titles_before_consulting_qa() -> None:
    class SoftBeatTitleLLM:
        def complete_json(self, **kwargs):
            common = {
                "subheading": "Evidence from uploaded source",
                "content_blocks": [
                    {
                        "type": "bullets",
                        "body": [
                            "Teams need explicit context.",
                            "Review gates improve reliability.",
                            "Shared artifacts preserve decisions.",
                        ],
                        "annotations": [],
                        "callouts": [],
                    }
                ],
                "chart_spec": None,
                "sources": ["Uploaded source"],
                "speaker_notes": "Explain the exhibit.",
                "qa": {
                    "consulting_status": "pending",
                    "visual_status": "pending",
                    "issues": [],
                },
            }
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        **common,
                        "slide_number": 1,
                        "slide_type": "framework",
                        "action_title": "Provide an operating cycle leaders can manage for reliability",
                        "archetype": "framework_cycle",
                        "narrative_role": "framework",
                        "exhibit_spec": {"type": "cycle", "steps": [{"label": "Plan"}]},
                    },
                    {
                        **common,
                        "slide_number": 2,
                        "slide_type": "checklist",
                        "action_title": "Make the next steps executable for immediate adoption",
                        "archetype": "checklist",
                        "narrative_role": "implementation",
                        "exhibit_spec": {
                            "type": "checklist",
                            "items": [
                                {"action": "Create artifacts"},
                                {"action": "Assign owner"},
                                {"action": "Run review"},
                            ],
                        },
                    },
                    {
                        **common,
                        "slide_number": 3,
                        "slide_type": "reference",
                        "action_title": "Provide a compact reference leaders can reuse",
                        "subheading": "Core operating artifacts",
                        "archetype": "table_reference",
                        "narrative_role": "reference",
                        "exhibit_spec": {
                            "type": "reference_table",
                            "columns": ["Artifact", "Role"],
                            "rows": [["rules.md", "Constrains execution"]],
                        },
                    },
                    {
                        **common,
                        "slide_number": 4,
                        "slide_type": "closing",
                        "action_title": "End with a clear recommendation",
                        "archetype": "closing_recommendation",
                        "narrative_role": "closing",
                        "exhibit_spec": {
                            "type": "recommendation",
                            "recommendation": "Approve a governed pilot",
                            "next_steps": ["Name owner"],
                        },
                    },
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=SoftBeatTitleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    titles = [outline.label for outline in outlines]

    assert "Run the operating cycle with explicit review gates" in titles
    assert "Implement next steps through a short operating checklist" in titles
    assert "Standardize core operating artifacts as a reusable reference" in titles
    assert "Commit to the recommendation with named ownership" in titles
    assert outlines[0].content_json["diagram_spec"] is None
    assert not any(warning["field"] == "consulting_qa" for warning in warnings)


def test_planner_repairs_sparse_anti_pattern_exhibits() -> None:
    class SparseAntiPatternLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "anti_pattern",
                        "action_title": "Identify anti-patterns before AI work scales",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Context disappears between sessions."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the failure modes.",
                        "archetype": "anti_patterns",
                        "narrative_role": "problem",
                        "exhibit_spec": {
                            "type": "anti_patterns",
                            "patterns": [
                                {
                                    "name": "Context rot",
                                    "symptom": "Context disappears between sessions.",
                                    "better_behavior": "Persist context outside the chat.",
                                }
                            ],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=SparseAntiPatternLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    patterns = outlines[0].content_json["exhibit_spec"]["patterns"]

    assert len(patterns) >= 3
    assert all(pattern["name"] and pattern["symptom"] for pattern in patterns[:3])
    assert not warnings


def test_repeated_reference_titles_repair_to_code_panel_action() -> None:
    class DuplicateReferenceLLM:
        def complete_json(self, **kwargs):
            slide = {
                "slide_type": "reference",
                "action_title": "Reference the Six-Phase Loop for Continuous Improvement",
                "subheading": "Evidence from uploaded source",
                "content_blocks": [
                    {
                        "type": "bullets",
                        "body": [
                            "The six-phase loop provides a comprehensive framework.",
                            "Each phase feeds the next, creating a reliable delivery pattern.",
                        ],
                        "annotations": [],
                        "callouts": [],
                    }
                ],
                "chart_spec": None,
                "sources": ["Uploaded source"],
                "speaker_notes": "Explain the reusable loop.",
                "archetype": "reference",
                "narrative_role": "reference",
                "exhibit_spec": {
                    "type": "code_panel",
                    "title": "agentic-cycle.md",
                    "lines": [
                        "Frame the request with an explicit outcome.",
                        "Prime the agent with memory and constraints.",
                        "Review output before updating memory.",
                    ],
                },
                "qa": {
                    "consulting_status": "pending",
                    "visual_status": "pending",
                    "issues": [],
                },
            }
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {"slide_number": 1, **slide},
                    {"slide_number": 2, **slide},
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=DuplicateReferenceLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    titles = [outline.label for outline in outlines]

    assert "Codify the operating cycle as reusable rules" in titles
    assert not any("..." in title for title in titles)
    assert not any("focused recommendation" in title.lower() for title in titles)
    assert not any(warning["field"] == "consulting_qa" for warning in warnings)


def test_planner_varies_generic_llm_slide_layouts() -> None:
    class GenericSlidesLLM:
        def complete_json(self, **kwargs):
            target = int(re.search(r"Create a (\d+)-slide", kwargs["user_prompt"]).group(1))
            titles = [
                "Improve agentic delivery discipline across priority workflows",
                "Standardize context management across software delivery teams",
                "Reduce review gaps through explicit acceptance criteria",
                "Adopt persistent memory to improve agent reliability",
                "Secure production quality with structured oversight",
            ]
            while len(titles) < target:
                suffixes = [
                    "intake",
                    "review",
                    "handoff",
                    "release",
                    "memory",
                    "governance",
                    "cadence",
                ]
                titles.append(
                    "Improve delivery reliability through "
                    f"{suffixes[len(titles) % len(suffixes)]} standards"
                )
            slides = []
            for number, title in enumerate(titles[:target], start=1):
                slides.append(
                    {
                        "slide_number": number,
                        "slide_type": "content",
                        "action_title": title,
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams need structure, context, and review discipline."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                )
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": slides,
            }

    planner = ContentPlanner(llm_client=GenericSlidesLLM())
    outlines, warnings = planner.plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )
    layouts = [outline.layout_json["layout"] for outline in outlines]

    assert len(set(layouts)) >= 3
    assert not any(left == middle == right for left, middle, right in zip(layouts, layouts[1:], layouts[2:]))
    assert not warnings


def test_planner_routes_claude_style_archetypes_to_distinct_layouts() -> None:
    class ClaudeStyleLLM:
        def complete_json(self, **kwargs):
            titles = [
                ("anti_pattern", "Recognize three failure modes that break vibe coding"),
                ("framework", "Run the agentic cycle as a managed workflow"),
                ("content", "Implement the Memory Bank hierarchy for persistent context"),
                ("reference", "Codify rules files beside the codebase"),
                ("checklist", "Adopt the agentic workflow tomorrow"),
                ("quote", "Reframe the developer role from coder to AI manager"),
                ("executive_summary", "Define the Memory Bank architecture for immediate implementation"),
            ]
            slides = []
            for number, (slide_type, title) in enumerate(titles, start=1):
                slides.append(
                    {
                        "slide_number": number,
                        "slide_type": slide_type,
                        "action_title": title,
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": [
                                    "Persistent context changes the operating model.",
                                    "Structured review reduces fragile outputs.",
                                    "Managers need clear rules and memory.",
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                )
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": slides,
            }

    outlines, warnings = ContentPlanner(llm_client=ClaudeStyleLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    layouts = [outline.layout_json["layout"] for outline in outlines]

    assert layouts == [
        "anti_patterns",
        "callouts",
        "dependency_map",
        "comparison_table",
        "checklist",
        "quote_sidebar",
        "table_reference",
    ]
    assert not warnings


def test_planner_strips_diagram_description_placeholders_from_bullets() -> None:
    class DiagramDescriptionLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Map the External Brain architecture",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": [
                                    "[Diagram Description: Central Node with arrows] Project context persists.",
                                    "Rules files guide each AI session.",
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, _warnings = ContentPlanner(llm_client=DiagramDescriptionLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    bullets = outlines[0].content_json["bullets"]

    assert bullets[0] == "Project context persists."
    assert not any("Diagram Description" in bullet for bullet in bullets)


def test_planner_summary_truncates_at_word_boundary() -> None:
    summary = ContentPlanner()._summarize(" ".join(["agentic"] * 40))

    assert summary.endswith("...")
    assert len(summary) <= 160
    assert summary.removesuffix("...").split()[-1] == "agentic"


def test_planner_marks_unsupported_numeric_claims_source_needed() -> None:
    class UnsupportedMetricLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Reduce escaped defects by 42%",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams reported 42% fewer defects after adoption."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=UnsupportedMetricLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert "[source needed]" in outlines[0].content_json["sources"]
    assert outlines[0].content_json["content_blocks"][0]["body"][0].endswith(
        "[source needed]"
    )
    assert any(warning["field"] == "source_coverage" for warning in warnings)


def test_planner_ignores_bare_single_digit_ordinals_for_numeric_grounding() -> None:
    planner = ContentPlanner()

    tokens = planner._numeric_tokens(
        "Layer 2 connects to step 3 and stage 4, while the top 1% and 42% remain claims."
    )

    assert {"2", "3", "4"}.isdisjoint(tokens)
    assert {"1%", "42%"}.issubset(tokens)


def test_planner_allows_numeric_claims_present_in_source() -> None:
    class SupportedMetricLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Reduce escaped defects by 42%",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams reported 42% fewer defects after adoption."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    bundle = _bundle()
    bundle.sections[0].content += " Teams reported 42% fewer escaped defects."
    outlines, warnings = ContentPlanner(llm_client=SupportedMetricLLM()).plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert "[source needed]" not in outlines[0].content_json["sources"]
    assert "[source needed]" not in outlines[0].content_json["content_blocks"][0]["body"][0]
    assert not any(warning["field"] == "source_coverage" for warning in warnings)


def test_planner_normalizes_invented_source_labels() -> None:
    class InventedSourceLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Improve review discipline before scaling agents",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams need clearer review standards."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["McKinsey AI engineering survey 2026"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=InventedSourceLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].content_json["sources"] == ["[source needed]"]
    assert any(warning["field"] == "source_label" for warning in warnings)
    assert "McKinsey" in warnings[0]["message"]


def test_planner_adds_source_label_when_llm_omits_sources() -> None:
    class MissingSourceLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Improve review discipline before scaling agents",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams need clearer review standards."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=MissingSourceLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].content_json["sources"] == ["Uploaded source"]
    assert any(warning["field"] == "source_label" for warning in warnings)


def test_planner_rejects_uploaded_source_label_without_source_material() -> None:
    class UnsupportedSourceLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Prompt Only Deck",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "content",
                        "action_title": "Improve review discipline before scaling agents",
                        "subheading": "Prompt-only context",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Teams need clearer review standards."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    bundle = DocumentBundle(
        job_id="job-1",
        sections=[],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(),
        content_inventory=[],
    )
    outlines, warnings = ContentPlanner(llm_client=UnsupportedSourceLLM()).plan(
        _template("freeform"),
        bundle,
        instructions="Create a prompt-only deck.",
        generation_mode="freeform",
    )

    assert outlines[0].content_json["sources"] == ["[source needed]"]
    assert any(warning["field"] == "source_label" for warning in warnings)


def test_planner_prompt_includes_allowed_numeric_tokens() -> None:
    class CapturingLLM:
        prompt = ""

        def complete_json(self, **kwargs):
            self.prompt = kwargs["user_prompt"]
            return None

    bundle = _bundle()
    bundle.sections[0].content += " Teams reported 42% fewer escaped defects."
    llm = CapturingLLM()
    with pytest.raises(PlanningFailedError, match="deterministic planning fallback is disabled"):
        ContentPlanner(llm_client=llm).plan(
            _template("freeform"),
            bundle,
            instructions="Create a deck on moving beyond vibe coding.",
            generation_mode="freeform",
        )

    assert "Allowed numeric tokens" in llm.prompt
    assert "42%" in llm.prompt
    assert "Use source_refs for exact source packet ids" in llm.prompt
    assert "Do not invent document names" in llm.prompt


def test_showcase_planner_uses_richer_source_packet_and_output_budget() -> None:
    class CapturingLLM:
        kwargs = {}

        def complete_json(self, **kwargs):
            self.kwargs = kwargs
            return None

    sections = [
        DocumentSection(
            title=f"Section {idx}",
            level=1,
            content=(
                f"Section {idx} explains the operating model, evidence base, "
                "review gate, ownership model, and implementation implications. "
                "It includes enough detail to support a distinct authored slide."
            ),
            source_doc_id="doc-1",
        )
        for idx in range(1, 19)
    ]
    bundle = _bundle()
    bundle.sections = sections
    llm = CapturingLLM()

    with pytest.raises(PlanningFailedError, match="deterministic planning fallback is disabled"):
        ContentPlanner(llm_client=llm).plan(
            _template("freeform"),
            bundle,
            instructions="Create a deck on moving beyond vibe coding.",
            generation_mode="freeform",
            quality_profile="showcase",
            length_strategy="expanded",
        )

    assert llm.kwargs["max_tokens"] == 40000
    prompt = llm.kwargs["user_prompt"]
    packet = json.loads(prompt.split("Source packet: ", 1)[1].split("\nMetrics:", 1)[0])
    assert packet["section_count"] == 18
    assert packet["included_section_count"] == 18
    assert any(section["id"] == "doc-1:Section 18" for section in packet["sections"])
    assert packet["document_outline"]["section_count"] == 18
    assert "key_points" in packet["sections"][0]


def test_planner_extracts_chart_metrics_from_qwen_data_points() -> None:
    class ChartSpecLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "chart",
                        "action_title": "Quantify production readiness before scaling AI development",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Adoption is high enough to require operating discipline."],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": {
                            "type": "bar_chart",
                            "data_points": [
                                {"label": "Developers", "value": 85, "unit": "%"},
                                {"label": "AI-generated code", "value": 95, "unit": "%"},
                            ],
                        },
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    bundle = _bundle()
    bundle.sections[0].content += " Developers reached 85% adoption and 95% AI-generated code."
    outlines, warnings = ContentPlanner(llm_client=ChartSpecLLM()).plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].layout_json["layout"] == "chart"
    assert {
        (metric["label"], metric["value"], metric["unit"])
        for metric in outlines[0].content_json["metrics"]
    } == {
        ("Developers", 85, "%"),
        ("AI-generated code", 95, "%"),
    }
    assert not warnings


def test_planner_promotes_numeric_chart_slide_without_chart_spec() -> None:
    class NumericChartLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "chart",
                        "action_title": "Visualize AI adoption before scaling delivery",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": [
                                    "Developers using AI tools reached 85% by 2025.",
                                    "Minimum context tokens reached 32,000.",
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the implication.",
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    bundle = _bundle()
    bundle.sections[0].content += " Developers using AI tools reached 85% by 2025 with 32,000 context tokens."
    outlines, warnings = ContentPlanner(llm_client=NumericChartLLM()).plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    assert outlines[0].layout_json["layout"] == "chart"
    assert outlines[0].content_json["metrics"][:2] == [
        {"label": "Developers using AI tools reached", "value": 85, "unit": "%"},
        {"label": "Minimum context tokens reached", "value": 32000, "unit": None},
    ]
    assert not warnings


def test_document_ingester_extracts_metrics_without_dates() -> None:
    markdown = (
        "February 2026 update. On February 3, 2025, the market was still shifting. "
        "By the end of 2025, roughly 85% of developers were regularly using AI "
        "tools for coding. Y Combinator reported that a quarter of its Winter 2025 "
        "batch had codebases that were 95% AI-generated. The context window ranges "
        "from roughly 32,000 to 200,000 tokens, and some modern advancements have "
        "scaled this window to 1 million tokens."
    )

    metrics = DocumentIngester()._parse_metrics("doc-1", markdown)

    values = {(metric.value, metric.unit) for metric in metrics}
    labels = [metric.label for metric in metrics]
    assert (85, "%") in values
    assert (95, "%") in values
    assert (32_000, "tokens") in values
    assert (200_000, "tokens") in values
    assert (1_000_000, "tokens") in values
    assert not any(metric.unit is None and metric.value in {3, 2025, 2026} for metric in metrics)
    assert any("Developers" in label for label in labels)
    assert "AI-generated codebases" in labels


def test_planner_metric_selection_filters_date_like_values() -> None:
    metrics = [
        DocumentMetric(label="February", value=2026, unit=None, source_doc_id="doc-1"),
        DocumentMetric(label="on February", value=3, unit=None, source_doc_id="doc-1"),
        DocumentMetric(label="Developers using AI tools", value=85, unit="%", source_doc_id="doc-1"),
        DocumentMetric(label="AI-generated codebases", value=95, unit="%", source_doc_id="doc-1"),
        DocumentMetric(label="Context window maximum", value=200_000, unit="tokens", source_doc_id="doc-1"),
    ]

    selected = ContentPlanner()._pick_metrics(metrics, count=3)

    assert selected == [
        {"label": "AI-generated codebases", "value": 95, "unit": "%"},
        {"label": "Developers using AI tools", "value": 85, "unit": "%"},
        {"label": "Context window maximum", "value": 200_000, "unit": "tokens"},
    ]


def test_planner_chart_metric_extraction_skips_leading_years() -> None:
    slide = GeneratedSlideSpec(
        slide_number=1,
        slide_type="chart",
        action_title="Visualize adoption before scaling AI delivery",
        content_blocks=[
            ContentBlock(
                type="bullets",
                body=["By 2025, 85% of developers were regularly using AI tools."],
            )
        ],
    )

    metrics = ContentPlanner()._metrics_from_slide(slide)

    assert metrics == [
        {"label": "developers were regularly using AI tools", "value": 85, "unit": "%"}
    ]


def test_planner_repairs_sparse_comparison_exhibits_before_render() -> None:
    class SparseComparisonLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "comparison",
                        "action_title": "Contrast vibe coding with managed agentic engineering",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "table",
                                "body": [
                                    ["Aspect", "Vibe coding", "Agentic engineering"],
                                    ["Context", "", ""],
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": None,
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the comparison.",
                        "archetype": "comparison_table",
                        "narrative_role": "evidence",
                        "exhibit_spec": {
                            "type": "comparison_table",
                            "columns": ["Aspect", "Vibe coding", "Agentic engineering"],
                            "rows": [{"label": "Context", "values": ["", ""]}],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    outlines, warnings = ContentPlanner(llm_client=SparseComparisonLLM()).plan(
        _template("freeform"),
        _bundle(),
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    exhibit = outlines[0].content_json["exhibit_spec"]
    body = outlines[0].content_json["content_blocks"][0]["body"]

    assert warnings == []
    assert exhibit["columns"] == ["Dimension", "Current state", "Target state"]
    assert len(exhibit["rows"]) == 3
    assert all(row["values"][0] and row["values"][1] for row in exhibit["rows"])
    assert body[0] == ["Dimension", "Current state", "Target state"]
    assert len(body) == 4


def test_planner_enriches_single_metric_chart_from_source_metrics() -> None:
    class SparseMetricLLM:
        def complete_json(self, **kwargs):
            return {
                "deck_title": "Beyond Vibe Coding",
                "audience": "Engineering leaders",
                "goal": "Improve AI-assisted delivery quality",
                "narrative_arc": "Situation -> Complication -> Resolution",
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_type": "chart",
                        "action_title": "Quantify adoption pressure before redesigning delivery",
                        "subheading": "Evidence from uploaded source",
                        "content_blocks": [
                            {
                                "type": "chart",
                                "body": [
                                    {
                                        "label": "Developers using AI tools",
                                        "value": 85,
                                        "unit": "%",
                                    }
                                ],
                                "annotations": [],
                                "callouts": [],
                            }
                        ],
                        "chart_spec": {
                            "type": "bar_chart",
                            "data_points": [
                                {
                                    "label": "Developers using AI tools",
                                    "value": 85,
                                    "unit": "%",
                                }
                            ],
                        },
                        "sources": ["Uploaded source"],
                        "speaker_notes": "Explain the adoption pressure.",
                        "archetype": "metric_chart",
                        "narrative_role": "evidence",
                        "exhibit_spec": {
                            "type": "metric_chart",
                            "metrics": [
                                    {
                                        "label": "Developers using AI tools",
                                        "value": 85,
                                        "unit": "%",
                                    }
                            ],
                        },
                        "qa": {
                            "consulting_status": "pending",
                            "visual_status": "pending",
                            "issues": [],
                        },
                    }
                ],
            }

    bundle = _bundle()
    bundle.metrics = [
        DocumentMetric(
            label="Developers regularly using AI tools",
            value=85,
            unit="%",
            source_doc_id="doc-1",
        ),
        DocumentMetric(
            label="AI-generated codebases",
            value=95,
            unit="%",
            source_doc_id="doc-1",
        ),
        DocumentMetric(
            label="Context window",
            value=1_000_000,
            unit="tokens",
            source_doc_id="doc-1",
        ),
    ]
    bundle.sections[0].content += " Developers regularly using AI tools reached 85%."
    bundle.sections[0].content += " AI-generated codebases reached 95%."

    outlines, warnings = ContentPlanner(llm_client=SparseMetricLLM()).plan(
        _template("freeform"),
        bundle,
        instructions="Create a deck on moving beyond vibe coding.",
        generation_mode="freeform",
    )

    metrics = outlines[0].content_json["metrics"]
    exhibit_metrics = outlines[0].content_json["exhibit_spec"]["metrics"]

    assert warnings == []
    assert len(exhibit_metrics) == 3
    assert {metric["label"] for metric in exhibit_metrics} == {
        "Developers using AI tools",
        "AI-generated codebases",
        "Context window",
    }
    assert len({(metric["value"], metric["unit"]) for metric in exhibit_metrics}) == 3
    assert metrics == exhibit_metrics


def test_brand_builder_outputs_valid_pptx(tmp_path: Path) -> None:
    planner = ContentPlanner()
    outlines, _ = planner.plan(
        _template("brand"),
        _bundle(),
        instructions="Create a brand-aligned executive deck.",
        generation_mode="brand",
    )
    output_path = tmp_path / "brand-output.pptx"
    builder = PptxBuilder(node_runner=object())  # renderer path does not use Node

    warnings = builder.build_deck(_template("brand"), outlines, output_path, tmp_path)

    assert warnings == []
    assert output_path.exists()
    with zipfile.ZipFile(output_path, "r") as pptx_zip:
        assert pptx_zip.testzip() is None
        assert "[Content_Types].xml" in pptx_zip.namelist()
    rendered = Presentation(output_path.as_posix())
    assert len(rendered.slides) == len(outlines)


def test_strict_xml_injector_updates_text_without_python_pptx_write(tmp_path: Path) -> None:
    template_path, template, outline = _strict_fixture(tmp_path)
    output_path = tmp_path / "strict-output.pptx"

    warnings = StrictSlideInjector().inject(template_path, template, [outline], output_path)

    assert warnings == []
    rendered = Presentation(output_path.as_posix())
    texts = [shape.text for shape in rendered.slides[0].shapes if shape.has_text_frame]
    assert "Beyond Vibe Coding" in texts


def test_template_analyzer_extracts_strict_table_cell_fields(tmp_path: Path) -> None:
    template_path = tmp_path / "strict-table-template.pptx"
    _write_table_template(template_path)

    profile, _ = TemplateAnalyzer().analyze(
        template_path,
        template_name="Strict Table",
        template_type="strict",
        template_id="strict-table",
    )

    assert profile.slides[0].mode == "strict"
    assert profile.slides[0].slide_schema is not None
    locations = {field.location for field in profile.slides[0].slide_schema.fields}
    assert "table:DecisionTable:1:1" in locations


def test_strict_xml_injector_updates_table_cell_without_rebuilding_table(tmp_path: Path) -> None:
    template_path = tmp_path / "strict-table-template.pptx"
    _write_table_template(template_path)
    template = _template("strict", source_file=template_path.as_posix())
    template.slides = [
        SlideSpec(
            index=0,
            mode="strict",
            label="Decision Table",
            schema=SlideSchema(
                fields=[
                    SlideField(
                        id="decision_table_2_2",
                        type="text",
                        location="table:DecisionTable:1:1",
                        required=True,
                    )
                ]
            ),
        )
    ]
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="strict",
        label="Decision Table",
        content_json={"fields": {"decision_table_2_2": "Launch controlled pilot"}},
        layout_json={"layout": "strict", "visual_elements": []},
        created_at=_timestamp(),
    )
    output_path = tmp_path / "strict-table-output.pptx"

    warnings = StrictSlideInjector().inject(template_path, template, [outline], output_path)

    assert warnings == []
    rendered = Presentation(output_path.as_posix())
    table = next(shape.table for shape in rendered.slides[0].shapes if shape.has_table)
    assert table.cell(1, 1).text == "Launch controlled pilot"
    assert table.cell(0, 0).text == "Decision"
    assert table.cell(1, 0).text == "Recommendation"


def test_template_analyzer_extracts_strict_chart_fields(tmp_path: Path) -> None:
    template_path = tmp_path / "strict-chart-template.pptx"
    _write_chart_template(template_path)

    profile, _ = TemplateAnalyzer().analyze(
        template_path,
        template_name="Strict Chart",
        template_type="strict",
        template_id="strict-chart",
    )

    assert profile.slides[0].mode == "strict"
    assert profile.slides[0].slide_schema is not None
    locations = {field.location for field in profile.slides[0].slide_schema.fields}
    assert "chart:RevenueChart:series_name:0" in locations
    assert "chart:RevenueChart:category:1" in locations
    assert "chart:RevenueChart:value:0:1" in locations


def test_strict_xml_injector_updates_chart_cache_values(tmp_path: Path) -> None:
    template_path = tmp_path / "strict-chart-template.pptx"
    _write_chart_template(template_path)
    template = _template("strict", source_file=template_path.as_posix())
    template.slides = [
        SlideSpec(
            index=0,
            mode="strict",
            label="Revenue Chart",
            schema=SlideSchema(
                fields=[
                    SlideField(
                        id="revenue_chart_series_1_name",
                        type="text",
                        location="chart:RevenueChart:series_name:0",
                        required=True,
                    ),
                    SlideField(
                        id="revenue_chart_category_2",
                        type="text",
                        location="chart:RevenueChart:category:1",
                        required=True,
                    ),
                    SlideField(
                        id="revenue_chart_series_1_value_2",
                        type="number",
                        location="chart:RevenueChart:value:0:1",
                        required=True,
                    ),
                ]
            ),
        )
    ]
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="strict",
        label="Revenue Chart",
        content_json={
            "fields": {
                "revenue_chart_series_1_name": "Target",
                "revenue_chart_category_2": "Scaled pilots",
                "revenue_chart_series_1_value_2": 35,
            }
        },
        layout_json={"layout": "strict", "visual_elements": []},
        created_at=_timestamp(),
    )
    output_path = tmp_path / "strict-chart-output.pptx"

    warnings = StrictSlideInjector().inject(template_path, template, [outline], output_path)

    assert warnings == []
    chart_xml = _read_chart_xml(output_path)
    assert _chart_text(chart_xml, ".//c:ser/c:tx//c:v") == "Target"
    assert _chart_text(chart_xml, ".//c:ser/c:cat//c:pt[@idx='1']/c:v") == "Scaled pilots"
    assert _chart_text(chart_xml, ".//c:ser/c:val//c:pt[@idx='1']/c:v") == "35.0"
    workbook = _read_embedded_workbook(output_path)
    assert workbook["Sheet1"]["B1"].value == "Target"
    assert workbook["Sheet1"]["A3"].value == "Scaled pilots"
    assert workbook["Sheet1"]["B3"].value == 35


def test_strict_builder_outputs_valid_pptx(tmp_path: Path) -> None:
    template_path, template, outline = _strict_fixture(tmp_path)
    output_path = tmp_path / "strict-builder-output.pptx"
    builder = PptxBuilder(node_runner=object())

    warnings = builder.build_deck(template, [outline], output_path, tmp_path)

    assert warnings == []
    with zipfile.ZipFile(output_path, "r") as pptx_zip:
        assert pptx_zip.testzip() is None
    rendered = Presentation(output_path.as_posix())
    texts = [shape.text for shape in rendered.slides[0].shapes if shape.has_text_frame]
    assert "Beyond Vibe Coding" in texts


def test_strict_planner_semantically_maps_common_text_fields() -> None:
    template = _template("strict")
    template.slides = [
        SlideSpec(
            index=0,
            mode="strict",
            label="Strict Summary",
            schema=SlideSchema(
                fields=[
                    SlideField(
                        id="key_implication",
                        type="text",
                        location="shape:KeyImplication",
                        required=True,
                    )
                ]
            ),
        )
    ]

    outlines, warnings = ContentPlanner().plan(
        template,
        _bundle(),
        instructions="Populate strict fields.",
        generation_mode="strict",
    )

    assert warnings == []
    assert outlines[0].content_json["fields"]["key_implication"] != "[INSERT CONTENT HERE]"


def test_strict_planner_uses_insert_placeholder_for_unmapped_fields() -> None:
    template = _template("strict")
    template.slides = [
        SlideSpec(
            index=0,
            mode="strict",
            label="Strict Summary",
            schema=SlideSchema(
                fields=[
                    SlideField(
                        id="unmapped_required_field",
                        type="text",
                        location="shape:UnmappedField",
                        required=True,
                    )
                ]
            ),
        )
    ]

    outlines, warnings = ContentPlanner().plan(
        template,
        _bundle(),
        instructions="Populate strict fields.",
        generation_mode="strict",
    )

    assert outlines[0].content_json["fields"]["unmapped_required_field"] == "[INSERT CONTENT HERE]"
    assert warnings == [
        {
            "slide_index": 0,
            "field": "unmapped_required_field",
            "message": "Missing content for strict field.",
        }
    ]


def _strict_fixture(tmp_path: Path) -> tuple[Path, TemplateProfile, SlideOutline]:
    template_path = tmp_path / "strict-template.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    box.name = "ProjectTitle"
    box.text = "Old title"
    prs.save(template_path.as_posix())

    template = _template("strict", source_file=template_path.as_posix())
    template.slides = [
        SlideSpec(
            index=0,
            mode="strict",
            label="Title",
            schema=SlideSchema(
                fields=[
                    SlideField(
                        id="project_title",
                        type="text",
                        location="shape:ProjectTitle",
                        required=True,
                    )
                ]
            ),
        )
    ]
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="strict",
        label="Title",
        content_json={"fields": {"project_title": "Beyond Vibe Coding"}},
        layout_json={"layout": "strict", "visual_elements": []},
        created_at=_timestamp(),
    )
    return template_path, template, outline


def _write_table_template(path: Path) -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    table_shape = slide.shapes.add_table(
        2, 2, Inches(1), Inches(1), Inches(6), Inches(1.4)
    )
    table_shape.name = "DecisionTable"
    table = table_shape.table
    table.cell(0, 0).text = "Decision"
    table.cell(0, 1).text = "Owner"
    table.cell(1, 0).text = "Recommendation"
    table.cell(1, 1).text = "TBD"
    prs.save(path.as_posix())


def _write_chart_template(path: Path) -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    chart_data = CategoryChartData()
    chart_data.categories = ["Prototype", "Pilot"]
    chart_data.add_series("Current", [10, 20])
    chart_shape = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        Inches(1),
        Inches(1),
        Inches(6),
        Inches(4),
        chart_data,
    )
    chart_shape.name = "RevenueChart"
    prs.save(path.as_posix())


def _read_chart_xml(path: Path) -> etree._Element:
    with zipfile.ZipFile(path, "r") as pptx_zip:
        return etree.fromstring(pptx_zip.read("ppt/charts/chart1.xml"))


def _read_embedded_workbook(path: Path):
    with zipfile.ZipFile(path, "r") as pptx_zip:
        workbook_name = next(
            name for name in pptx_zip.namelist() if name.startswith("ppt/embeddings/")
        )
        return load_workbook(BytesIO(pptx_zip.read(workbook_name)))


def _chart_text(chart_xml: etree._Element, xpath: str) -> str:
    ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
    node = chart_xml.find(xpath, namespaces=ns)
    assert node is not None
    return node.text
