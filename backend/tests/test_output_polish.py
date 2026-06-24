import json
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.util import Inches

from app.models.brand import BrandDNA
from app.models.document import (
    DocumentBundle,
    DocumentMetadata,
    DocumentMetric,
    DocumentSection,
    DocumentTable,
)
from app.models.generation import ContentBlock, DeckSpec, GeneratedSlideSpec
from app.models.outline import SlideOutline
from app.models.qa import QAIssue
from app.models.template import TemplateProfile
from app.services.consulting_qa import ConsultingQA
from app.services.content_planner import ContentPlanner
from app.services.document_ingester import DocumentIngester
from app.services.planning.exhibits import ExhibitCompiler
from app.services.pptx_renderer import DeterministicPptxRenderer
from app.services.template_analyzer import TemplateAnalyzer
from app.services.visual_qa_agent import VisualQAAgent


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _template() -> TemplateProfile:
    return TemplateProfile(
        id="freeform-template",
        name="Freeform Template",
        type="freeform",
        brand=BrandDNA(),
        slides=[],
        source_file="",
        created_at=_timestamp(),
        updated_at=_timestamp(),
    )


def _source_bundle() -> DocumentBundle:
    section = DocumentSection(
        title="External Brain",
        level=1,
        content=(
            "Persistent context improves handoffs. Explicit review gates reduce "
            "missed requirements before production work scales."
        ),
        source_doc_id="source-doc",
        source_id="source-doc:section:1:external-brain",
    )
    return DocumentBundle(
        job_id="job-polish",
        sections=[section],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[],
        source_index={
            section.source_id: {
                "kind": "section",
                "source_doc_id": "source-doc",
                "filename": "Beyond Vibe Coding.docx",
                "title": "External Brain",
                "label": "Beyond Vibe Coding > External Brain",
            }
        },
    )


def _outline(
    index: int,
    title: str,
    bullets: list[str],
    source_refs: list[str] | None = None,
    exhibit_spec: dict | None = None,
) -> SlideOutline:
    content = {
        "action_title": title,
        "title": title,
        "narrative_role": "evidence",
        "archetype": "comparison_table",
        "bullets": bullets,
        "content_blocks": [{"type": "bullets", "body": bullets}],
        "sources": ["Uploaded source"],
    }
    if source_refs is not None:
        content["source_refs"] = source_refs
    if exhibit_spec is not None:
        content["exhibit_spec"] = exhibit_spec
    return SlideOutline(
        id=f"outline-{index}",
        job_id="job-polish",
        slide_index=index,
        mode="flexible",
        label=title,
        content_json=content,
        layout_json={"layout": "comparison_table", "archetype": "comparison_table"},
        created_at="2026-01-01T00:00:00Z",
    )


def test_ingester_assigns_source_ids_and_source_index(tmp_path: Path) -> None:
    source_path = tmp_path / "Source Notes.md"
    source_path.write_text(
        "# External Brain\n"
        "Teams reported 42% faster handoffs after documenting decisions.\n",
        encoding="utf-8",
    )

    records, bundle = DocumentIngester().ingest_documents("job-provenance", [source_path])
    record_id = records[0].id

    assert bundle.sections[0].source_id.startswith(
        f"{record_id}:section:1:external-brain"
    )
    assert bundle.metrics[0].source_id.startswith(f"{record_id}:metric:1:")
    assert bundle.source_index[bundle.sections[0].source_id]["label"] == (
        "Source Notes > External Brain"
    )

    ingester = DocumentIngester()
    tables = ingester._parse_tables(
        record_id,
        "| Stage | Owner |\n|---|---|\n| Plan | Lead |\n",
    )
    source_index: dict[str, dict[str, str]] = {}
    ingester._assign_table_source_ids(tables, records[0], source_index)

    assert tables[0].source_id.startswith(f"{record_id}:table:1:")
    assert source_index[tables[0].source_id]["kind"] == "table"


def test_ingester_native_fallbacks_work_without_markitdown(tmp_path: Path) -> None:
    from docx import Document
    from openpyxl import Workbook

    ingester = DocumentIngester()
    ingester.markitdown = None

    docx_path = tmp_path / "notes.docx"
    document = Document()
    document.add_heading("Executive Context", level=1)
    document.add_paragraph("Structured source review improves deck quality.")
    document.save(docx_path.as_posix())

    pptx_path = tmp_path / "source-deck.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(0.8), Inches(0.7), Inches(8), Inches(1)).text = (
        "Review checkpoints build user trust."
    )
    presentation.save(pptx_path.as_posix())

    xlsx_path = tmp_path / "metrics.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Metrics"
    sheet.append(["Metric", "Value"])
    sheet.append(["Trust lift", "42%"])
    workbook.save(xlsx_path.as_posix())

    assert "# Executive Context" in ingester._convert_to_markdown(docx_path)
    assert "Review checkpoints build user trust." in ingester._convert_to_markdown(pptx_path)
    assert "| Metric | Value |" in ingester._convert_to_markdown(xlsx_path)


def test_grounding_resolves_source_refs_to_section_labels() -> None:
    bundle = _source_bundle()
    deck = DeckSpec(
        deck_title="Polish",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Use persistent context to improve handoffs",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Persistent context improves handoffs."],
                    )
                ],
                sources=["Uploaded source"],
                source_refs=[bundle.sections[0].source_id],
            )
        ],
    )

    warnings = ContentPlanner()._normalize_source_labels(deck, bundle)

    assert warnings == []
    assert deck.slides[0].sources == ["Beyond Vibe Coding > External Brain"]


def test_grounding_accepts_source_ids_in_human_source_labels() -> None:
    bundle = _source_bundle()
    deck = DeckSpec(
        deck_title="Polish",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Use persistent context to improve handoffs",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Persistent context improves handoffs."],
                    )
                ],
                sources=[bundle.sections[0].source_id],
                source_refs=[bundle.sections[0].source_id],
            )
        ],
    )

    warnings = ContentPlanner()._normalize_source_labels(deck, bundle)

    assert warnings == []
    assert deck.slides[0].sources == ["Beyond Vibe Coding > External Brain"]


def test_grounding_rejects_invented_source_labels() -> None:
    bundle = _source_bundle()
    deck = DeckSpec(
        deck_title="Polish",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Use persistent context to improve handoffs",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Persistent context improves handoffs."],
                    )
                ],
                sources=["Invented AI Operations Survey 2026"],
            )
        ],
    )

    warnings = ContentPlanner()._normalize_source_labels(deck, bundle)

    assert deck.slides[0].sources == ["[source needed]"]
    assert deck.slides[0].source_refs == ["[source needed]"]
    assert warnings[0]["field"] == "source_label"


def test_numeric_grounding_ignores_source_metadata_ids() -> None:
    bundle = _source_bundle()
    deck = DeckSpec(
        deck_title="Polish",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Use persistent context to improve handoffs",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Persistent context improves handoffs."],
                    )
                ],
                sources=["Uploaded source"],
                source_refs=[bundle.sections[0].source_id],
                exhibit_spec={
                    "type": "callouts",
                    "source_id": "doc:section:1:06845393",
                    "source_refs": ["doc:section:2:4206"],
                    "points": ["Persistent context improves handoffs."],
                },
            )
        ],
    )

    warnings = ContentPlanner()._ground_numeric_claims(deck, bundle)

    assert warnings == []
    assert "[source needed]" not in str(deck.slides[0].exhibit_spec)


def test_consulting_qa_flags_outline_polish_issues() -> None:
    duplicate = "Overview"
    outlines = [
        _outline(0, duplicate, ["Preserve context before work begins"]),
        _outline(1, duplicate, ["Preserve context before work begins"]),
    ]

    issues = ConsultingQA().inspect_outlines(outlines, has_source_material=True)
    categories = {issue.category for issue in issues}

    assert {
        "action_title",
        "horizontal_flow",
        "generic_filler",
        "repeated_bullet",
        "source_refs",
        "missing_exhibit",
    } <= categories


def test_consulting_qa_ignores_repeated_table_headers_as_evidence() -> None:
    outlines = [
        _outline(
            0,
            "Use persistent context to improve handoffs",
            [],
            source_refs=["source-doc:section:1:external-brain"],
            exhibit_spec={"type": "reference_table"},
        ),
        _outline(
            1,
            "Codify rules before assigning agent work",
            [],
            source_refs=["source-doc:section:2:rules"],
            exhibit_spec={"type": "reference_table"},
        ),
    ]
    for idx, outline in enumerate(outlines):
        outline.content_json["content_blocks"] = [
            {
                "type": "table",
                "body": [
                    ["Item", "Implication", "Update trigger"],
                    [
                        "Context" if idx == 0 else "Rules",
                        "Persistent memory reduces handoff loss."
                        if idx == 0
                        else "Explicit rules make review gates inspectable.",
                        "When conditions change",
                    ],
                ],
            }
        ]

    issues = ConsultingQA().inspect_outlines(outlines, has_source_material=True)

    assert "repeated_bullet" not in {issue.category for issue in issues}


def test_consulting_qa_uses_real_verbs_not_gerund_noise_for_titles() -> None:
    issues = ConsultingQA().inspect_outlines(
        [
            _outline(
                0,
                "Specify the six-phase loop before delegating it to the agent",
                ["Finite context windows make prior decisions disappear."],
                source_refs=["source-doc:section:1:external-brain"],
                exhibit_spec={"type": "callouts"},
            ),
            _outline(
                1,
                "Vibe coding operating patterns",
                ["Unstructured prompting makes work harder to reproduce."],
                source_refs=["source-doc:section:1:external-brain"],
                exhibit_spec={"type": "callouts"},
            ),
        ],
        has_source_material=True,
    )

    action_title_issues = {
        issue.slide_index
        for issue in issues
        if issue.category == "action_title"
        and "verb" in issue.message.lower()
    }

    assert 0 not in action_title_issues
    assert 1 in action_title_issues


def test_consulting_qa_flags_repeated_action_title_frames() -> None:
    issues = ConsultingQA().inspect_outlines(
        [
            _outline(
                0,
                "Persist core files so context survives every reset",
                ["Core files make context survive resets."],
                source_refs=["source-doc:section:1:external-brain"],
                exhibit_spec={"type": "callouts"},
            ),
            _outline(
                1,
                "Persist six-phase loop so context survives every reset",
                ["The six-phase loop preserves context between sessions."],
                source_refs=["source-doc:section:1:external-brain"],
                exhibit_spec={"type": "callouts"},
            ),
        ],
        has_source_material=True,
    )

    frame_issues = [
        issue
        for issue in issues
        if issue.category == "horizontal_flow"
        and "sentence frame" in issue.message.lower()
    ]

    assert [issue.slide_index for issue in frame_issues] == [1]


def test_consulting_repair_avoids_repeated_action_title_frames() -> None:
    sections = [
        DocumentSection(
            title="Core Files",
            level=1,
            content="Core files preserve decisions for future sessions.",
            source_doc_id="source-doc",
            source_id="source-doc:section:1:core-files",
        ),
        DocumentSection(
            title="Six-Phase Loop",
            level=1,
            content="The operating loop reviews output before context is reset.",
            source_doc_id="source-doc",
            source_id="source-doc:section:2:six-phase-loop",
        ),
    ]
    bundle = DocumentBundle(
        job_id="job-polish",
        sections=sections,
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[],
    )
    outlines = [
        _outline(
            0,
            "Persist core files so context survives every reset",
            ["Core files make context survive resets."],
            source_refs=[sections[0].source_id],
            exhibit_spec={"type": "callouts"},
        ),
        _outline(
            1,
            "Persist six-phase loop so context survives every reset",
            ["The six-phase loop preserves context between sessions."],
            source_refs=[sections[1].source_id],
            exhibit_spec={"type": "callouts"},
        ),
    ]
    planner = ContentPlanner()
    issues = ConsultingQA().inspect_outlines(outlines, has_source_material=True)

    repaired = planner.repair_outlines_for_consulting(outlines, issues, bundle)
    frame_keys = [
        planner._title_frame_key(outline.label)
        for outline in repaired
        if planner._title_frame_key(outline.label)
    ]

    assert len(frame_keys) == len(set(frame_keys))
    assert repaired[1].label != outlines[1].label


def test_consulting_qa_flags_exhibit_type_mismatches() -> None:
    outline = _outline(
        0,
        "The Memory Bank files form a directed dependency graph",
        ["The files feed one another in sequence."],
        source_refs=["source-doc:section:1:external-brain"],
        exhibit_spec={"type": "callouts", "points": ["The files feed one another."]},
    )

    issues = ConsultingQA().inspect_outlines([outline], has_source_material=True)

    assert any(issue.category == "exhibit_structure" for issue in issues)


def test_consulting_qa_exhibit_mismatch_uses_title_not_supporting_body() -> None:
    outline = _outline(
        0,
        "Adopt Markdown-Driven Development to communicate intent through files",
        [
            "Specification files and rules files preserve intent for later sessions.",
            "The workflow can reference those files before execution.",
        ],
        source_refs=["source-doc:section:1:external-brain"],
        exhibit_spec={"type": "checklist", "items": [{"action": "Write the file"}]},
    )

    issues = ConsultingQA().inspect_outlines([outline], has_source_material=True)

    assert not any(issue.category == "exhibit_structure" for issue in issues)


def test_consulting_qa_allows_checklist_for_phase_loop_titles() -> None:
    outline = _outline(
        0,
        "Specify the six-phase loop before delegating it to the agent",
        ["Every development session follows five ordered phases."],
        source_refs=["source-doc:section:1:external-brain"],
        exhibit_spec={
            "type": "checklist",
            "items": [
                {"action": "Load context"},
                {"action": "Plan"},
                {"action": "Review"},
            ],
        },
    )

    issues = ConsultingQA().inspect_outlines([outline], has_source_material=True)

    assert not any(issue.category == "exhibit_structure" for issue in issues)


def test_consulting_repair_rebuilds_mismatched_dependency_exhibit() -> None:
    section = DocumentSection(
        title="3.2 The File Hierarchy",
        level=2,
        content=(
            "The Memory Bank files form a directed dependency graph. "
            "project_brief.md feeds product_context.md, system_patterns.md, and progress.md."
        ),
        source_doc_id="source-doc",
        source_id="source-doc:section:1:file-hierarchy",
    )
    bundle = DocumentBundle(
        job_id="job-polish",
        sections=[section],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[],
    )
    outline = _outline(
        0,
        "The Memory Bank files form a directed dependency graph",
        ["The files feed one another in sequence."],
        source_refs=[section.source_id],
        exhibit_spec={"type": "callouts", "points": ["The files feed one another."]},
    )
    issues = ConsultingQA().inspect_outlines([outline], has_source_material=True)

    repaired = ContentPlanner().repair_outlines_for_consulting([outline], issues, bundle)

    assert repaired[0].content_json["archetype"] == "dependency_map"
    assert repaired[0].content_json["exhibit_spec"]["type"] == "dependency_map"
    assert repaired[0].layout_json["layout"] == "dependency_map"


def test_consulting_title_repair_uses_grammatical_question_heading_frames() -> None:
    planner = ContentPlanner()

    why_titles = planner._question_subject_titles("why the reset matters")
    how_titles = planner._question_subject_titles("how to review AI plans")

    assert why_titles == ["Clarify why the reset matters before teams act"]
    assert how_titles == ["Define how to review AI plans before execution begins"]
    assert not any(title.lower().startswith("make why") for title in why_titles)


def test_consulting_qa_does_not_force_cover_into_action_title_shape() -> None:
    cover = _outline(
        0,
        "Beyond Vibe Coding",
        ["How to stop chatting with AI and start managing it."],
        source_refs=["source-doc:section:1:external-brain"],
        exhibit_spec={"type": "cover"},
    )
    cover.content_json["narrative_role"] = "cover"
    cover.content_json["archetype"] = "cover"
    cover.layout_json["layout"] = "cover"

    issues = ConsultingQA().inspect_outlines([cover], has_source_material=True)

    assert not any(issue.category == "action_title" for issue in issues)
    assert not any(issue.category == "title_body_support" for issue in issues)


def test_consulting_qa_recognizes_semantic_body_support() -> None:
    outlines = [
        _outline(
            0,
            "Unverified claims create quality risk before evidence is checked",
            [
                "Hallucinations in AI-generated code are correlated with ambiguity.",
                "Vague prompts make fabricated solutions harder to catch.",
            ],
            source_refs=["source-doc:section:1:external-brain"],
            exhibit_spec={
                "type": "checklist",
                "items": [
                    {"action": "Verify claims against source evidence before review."}
                ],
            },
        ),
        _outline(
            1,
            "Make the six-phase loop an explicit operating decision",
            [
                "Every development session follows six phases.",
                "The workflow resets context after review.",
            ],
            source_refs=["source-doc:section:1:external-brain"],
            exhibit_spec={"type": "cycle", "steps": [{"label": "Review"}]},
        ),
    ]

    issues = ConsultingQA().inspect_outlines(outlines, has_source_material=True)

    unsupported = (
        issue.slide_index
        for issue in issues
        if issue.category == "title_body_support"
    )

    assert set(unsupported).isdisjoint({0, 1})


def test_consulting_qa_flags_near_duplicate_slides() -> None:
    exhibit = {
        "type": "comparison_table",
        "rows": [{"label": "Context", "values": ["Fragmented", "Persistent"]}],
    }
    outlines = [
        _outline(
            0,
            "Use persistent context to improve AI handoffs",
            [
                "Persistent context improves handoffs.",
                "Review gates reduce missed requirements.",
            ],
            source_refs=["source-doc:section:1:external-brain"],
            exhibit_spec=exhibit,
        ),
        _outline(
            1,
            "Use persistent context to improve team handoffs",
            [
                "Persistent context improves handoffs.",
                "Review gates reduce missed requirements.",
            ],
            source_refs=["source-doc:section:1:external-brain"],
            exhibit_spec=exhibit,
        ),
    ]

    issues = ConsultingQA().inspect_outlines(outlines, has_source_material=True)

    assert "duplicate_slide" in {issue.category for issue in issues}


def test_consulting_repair_rewrites_titles_sources_and_exhibits() -> None:
    bundle = _source_bundle()
    outlines = [
        _outline(0, "Overview", ["Preserve context before work begins"]),
        _outline(1, "Overview", ["Preserve context before work begins"]),
    ]
    planner = ContentPlanner()
    issues = planner.consulting_issues_for_outlines(outlines, bundle)

    repaired = planner.repair_outlines_for_consulting(outlines, issues, bundle)

    assert repaired[0].label != "Overview"
    assert repaired[0].label != repaired[1].label
    assert repaired[0].content_json["source_refs"] == [bundle.sections[0].source_id]
    assert repaired[0].content_json["sources"] == [
        "Beyond Vibe Coding > External Brain"
    ]
    assert repaired[0].content_json["exhibit_spec"]["type"] == "comparison_table"
    assert "Preserve context before work begins" not in str(
        repaired[0].content_json["exhibit_spec"]
    )
    assert "external brain" in str(repaired[0].content_json["exhibit_spec"]).lower()


def test_consulting_repair_moves_duplicate_slide_to_unused_source() -> None:
    first = DocumentSection(
        title="External Brain",
        level=1,
        content="Persistent context improves handoffs before work scales.",
        source_doc_id="source-doc",
        source_id="source-doc:section:1:external-brain",
    )
    second = DocumentSection(
        title="Reviewer Mode",
        level=1,
        content="Reviewer mode catches defects before generated code ships.",
        source_doc_id="source-doc",
        source_id="source-doc:section:2:reviewer-mode",
    )
    bundle = DocumentBundle(
        job_id="job-polish",
        sections=[first, second],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[],
        source_index={
            first.source_id: {
                "kind": "section",
                "source_doc_id": "source-doc",
                "filename": "Beyond Vibe Coding.docx",
                "title": "External Brain",
                "label": "Beyond Vibe Coding > External Brain",
            },
            second.source_id: {
                "kind": "section",
                "source_doc_id": "source-doc",
                "filename": "Beyond Vibe Coding.docx",
                "title": "Reviewer Mode",
                "label": "Beyond Vibe Coding > Reviewer Mode",
            },
        },
    )
    exhibit = {
        "type": "comparison_table",
        "rows": [{"label": "Context", "values": ["Fragmented", "Persistent"]}],
    }
    outlines = [
        _outline(
            0,
            "Use persistent context to improve AI handoffs",
            ["Persistent context improves handoffs before work scales."],
            source_refs=[first.source_id],
            exhibit_spec=exhibit,
        ),
        _outline(
            1,
            "Use persistent context to improve team handoffs",
            ["Persistent context improves handoffs before work scales."],
            source_refs=[first.source_id],
            exhibit_spec=exhibit,
        ),
    ]
    planner = ContentPlanner()
    issues = planner.consulting_issues_for_outlines(outlines, bundle)

    repaired = planner.repair_outlines_for_consulting(outlines, issues, bundle)

    assert any(issue.category == "duplicate_slide" for issue in issues)
    assert repaired[1].content_json["source_refs"] == [second.source_id]
    assert repaired[1].label != repaired[0].label
    assert "Reviewer Mode" in repaired[1].content_json["sources"][0]


def test_consulting_repair_dedupes_rebuilt_closing_recommendation_steps() -> None:
    repeated = "The Memory Bank consists of six core files arranged in a dependency hierarchy."
    closing_section = DocumentSection(
        title="File Hierarchy",
        level=2,
        content=(
            f"{repeated} "
            "Tools will change and models will improve, but disciplined workflows endure. "
            "The developer who thrives writes specifications and reviews logic."
        ),
        source_doc_id="source-doc",
        source_id="source-doc:section:2:file-hierarchy",
    )
    bundle = DocumentBundle(
        job_id="job-polish",
        sections=[closing_section],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[],
    )
    prior = _outline(
        0,
        "Use a memory bank to turn ad hoc work into persistent context",
        [repeated],
        source_refs=[closing_section.source_id],
        exhibit_spec={"type": "code_panel", "lines": [repeated]},
    )
    closing = _outline(
        1,
        "Commit to the Memory Bank framework for reliable AI-assisted development",
        [repeated],
        source_refs=[closing_section.source_id],
        exhibit_spec={
            "type": "recommendation",
            "recommendation": "Keep persistent context current through named ownership.",
            "next_steps": [repeated],
        },
    )
    closing.content_json["archetype"] = "closing_recommendation"
    closing.content_json["narrative_role"] = "closing"
    closing.layout_json["layout"] = "closing_recommendation"
    closing.layout_json["archetype"] = "closing_recommendation"

    repaired = ContentPlanner().repair_outlines_for_consulting(
        [prior, closing],
        [
            QAIssue(
                severity="WARNING",
                category="repeated_bullet",
                message="Repeated evidence bullet appears on multiple slides.",
                slide_index=1,
            )
        ],
        bundle,
    )

    closing_exhibit = repaired[1].content_json["exhibit_spec"]
    assert repeated not in closing_exhibit["next_steps"]


def test_exhibit_selection_diversifies_repeated_visual_motifs() -> None:
    bundle = _source_bundle()
    repeated_exhibit = {
        "type": "dependency_map",
        "left_node": "Source evidence",
        "middle_nodes": ["Context rot", "Hallucination amplification", "Reproducibility gap"],
        "right_outcome": "Confident decision",
        "connector_labels": ["feeds", "constrains", "verifies"],
    }
    deck = DeckSpec(
        deck_title="Polish",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Map source dependencies before teams make the decision",
                subheading="Dependency map from the source",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Source context feeds the decision model."],
                    )
                ],
                sources=["Uploaded source"],
                source_refs=[bundle.sections[0].source_id],
                archetype="dependency_map",
                narrative_role="evidence",
                exhibit_spec=repeated_exhibit,
            ),
            GeneratedSlideSpec(
                slide_number=2,
                slide_type="content",
                action_title="Map source dependencies before teams scale the workflow",
                subheading="Dependency map from the source",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["Source context feeds the decision model."],
                    )
                ],
                sources=["Uploaded source"],
                source_refs=[bundle.sections[0].source_id],
                archetype="dependency_map",
                narrative_role="evidence",
                exhibit_spec=dict(repeated_exhibit),
            ),
        ],
    )

    ContentPlanner()._apply_exhibit_selection(deck, bundle)

    assert deck.slides[0].archetype == "dependency_map"
    assert deck.slides[1].archetype != "dependency_map"
    assert deck.slides[1].exhibit_spec["type"] != "dependency_map"


def test_exhibit_selection_keeps_strong_dependency_cues_out_of_metric_cards() -> None:
    sections = [
        DocumentSection(
            title="External Brain",
            level=1,
            content="Source context feeds the decision model.",
            source_doc_id="source-doc",
            source_id="source-doc:section:1:external-brain",
        ),
        DocumentSection(
            title="3.2 The File Hierarchy",
            level=2,
            content=(
                "These files are not independent; they form a directed dependency graph. "
                "project_brief.md feeds product_context.md, system_patterns.md, and progress.md."
            ),
            source_doc_id="source-doc",
            source_id="source-doc:section:2:file-hierarchy",
        ),
    ]
    bundle = DocumentBundle(
        job_id="job-polish",
        sections=sections,
        tables=[],
        metrics=[
            DocumentMetric(label="Developers using AI tools", value=85, unit="%", source_doc_id="source-doc"),
            DocumentMetric(label="AI-generated codebases", value=95, unit="%", source_doc_id="source-doc"),
            DocumentMetric(label="Context window minimum", value=32000, unit="tokens", source_doc_id="source-doc"),
        ],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[],
    )
    deck = DeckSpec(
        deck_title="Polish",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Map source dependencies before teams make the decision",
                content_blocks=[ContentBlock(type="bullets", body=["Source context feeds decisions."])],
                sources=["Uploaded source"],
                source_refs=[sections[0].source_id],
                archetype="dependency_map",
                exhibit_spec={
                    "type": "dependency_map",
                    "left_node": "Source evidence",
                    "middle_nodes": ["Context", "Rules", "Review"],
                    "right_outcome": "Confident decision",
                },
            ),
            GeneratedSlideSpec(
                slide_number=2,
                slide_type="content",
                action_title="These files are not independent; they form a directed dependency graph",
                content_blocks=[
                    ContentBlock(
                        type="bullets",
                        body=["85% adoption should not replace the actual file hierarchy."],
                    )
                ],
                sources=["Uploaded source"],
                source_refs=[sections[1].source_id],
                archetype="callouts",
                exhibit_spec={
                    "type": "callouts",
                    "metrics": [
                        {"label": "Developers using AI tools", "value": 85, "unit": "%"},
                    ],
                },
            ),
        ],
    )

    ContentPlanner()._apply_exhibit_selection(deck, bundle)

    assert deck.slides[1].archetype == "dependency_map"
    assert deck.slides[1].exhibit_spec["type"] == "dependency_map"
    assert "metrics" not in deck.slides[1].exhibit_spec


def test_exhibit_selection_promotes_core_files_to_reference_table() -> None:
    section = DocumentSection(
        title="3.1 The Core Files",
        level=2,
        content=(
            "The Memory Bank consists of six core files arranged in a dependency hierarchy. "
            "project_brief.md is the foundation and active_context.md tracks current work."
        ),
        source_doc_id="source-doc",
        source_id="source-doc:section:1:core-files",
    )
    bundle = DocumentBundle(
        job_id="job-polish",
        sections=[section],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[],
    )
    slide = GeneratedSlideSpec(
        slide_number=1,
        slide_type="comparison",
        action_title="Structure the Memory Bank with six core files in a dependency hierarchy",
        content_blocks=[ContentBlock(type="bullets", body=["Six core files define the Memory Bank."])],
        sources=["Uploaded source"],
        source_refs=[section.source_id],
        archetype="comparison_table",
        exhibit_spec={
            "type": "comparison_table",
            "columns": ["Current", "Target"],
            "rows": [{"label": "Context", "values": ["Fragmented", "Persistent"]}],
        },
    )
    deck = DeckSpec(deck_title="Polish", slides=[slide])

    ContentPlanner()._apply_exhibit_selection(deck, bundle)

    assert deck.slides[0].archetype == "table_reference"
    assert deck.slides[0].exhibit_spec["type"] == "reference_table"


def test_exhibit_selection_prioritizes_dependency_graph_over_file_reference() -> None:
    sections = [
        DocumentSection(
            title="External Brain",
            level=1,
            content="Source context feeds the decision model.",
            source_doc_id="source-doc",
            source_id="source-doc:section:1:external-brain",
        ),
        DocumentSection(
            title="3.1 The Core Files",
            level=2,
            content="The Memory Bank consists of six core files.",
            source_doc_id="source-doc",
            source_id="source-doc:section:2:core-files",
        ),
        DocumentSection(
            title="3.2 The File Hierarchy",
            level=2,
            content=(
                "The Memory Bank files form a directed dependency graph. "
                "project_brief.md feeds product_context.md, system_patterns.md, and progress.md."
            ),
            source_doc_id="source-doc",
            source_id="source-doc:section:3:file-hierarchy",
        ),
    ]
    bundle = DocumentBundle(
        job_id="job-polish",
        sections=sections,
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[],
    )
    deck = DeckSpec(
        deck_title="Polish",
        slides=[
            GeneratedSlideSpec(
                slide_number=1,
                slide_type="content",
                action_title="Map source dependencies before teams make the decision",
                content_blocks=[ContentBlock(type="bullets", body=["Source context feeds decisions."])],
                sources=["Uploaded source"],
                source_refs=[sections[0].source_id],
                archetype="dependency_map",
                exhibit_spec={
                    "type": "dependency_map",
                    "left_node": "Source evidence",
                    "middle_nodes": ["Context", "Rules", "Review"],
                    "right_outcome": "Decision",
                },
            ),
            GeneratedSlideSpec(
                slide_number=2,
                slide_type="reference",
                action_title="Standardize Memory Bank files as a reusable reference",
                content_blocks=[ContentBlock(type="bullets", body=["Six core files define the system."])],
                sources=["Uploaded source"],
                source_refs=[sections[1].source_id],
                archetype="table_reference",
                exhibit_spec={
                    "type": "reference_table",
                    "columns": ["File", "Role"],
                    "rows": [["project_brief.md", "Foundation"]],
                },
            ),
            GeneratedSlideSpec(
                slide_number=3,
                slide_type="content",
                action_title="The Memory Bank files form a directed dependency graph",
                content_blocks=[ContentBlock(type="bullets", body=["The files feed one another."])],
                sources=["Uploaded source"],
                source_refs=[sections[2].source_id],
                archetype="callouts",
                exhibit_spec={"type": "callouts", "points": ["The files feed one another."]},
            ),
        ],
    )

    ContentPlanner()._apply_exhibit_selection(deck, bundle)

    assert deck.slides[2].archetype == "dependency_map"
    assert deck.slides[2].exhibit_spec["type"] == "dependency_map"


def test_unrelated_source_fallback_does_not_leak_demo_language() -> None:
    bundle = DocumentBundle(
        job_id="job-field-service",
        sections=[
            DocumentSection(
                title="Field Maintenance Dispatch",
                level=1,
                content=(
                    "Dispatch coordinators need route visibility, inventory checks, "
                    "and service-window escalation rules before crews leave the depot."
                ),
                source_doc_id="field-doc",
            )
        ],
        tables=[],
        metrics=[],
        metadata=DocumentMetadata(title="Field Maintenance Dispatch"),
    )

    outlines, _warnings = ContentPlanner().plan(
        _template(),
        bundle,
        instructions="Create a dispatch operations improvement deck.",
        generation_mode="freeform",
    )
    output_text = json.dumps([outline.content_json for outline in outlines]).lower()

    assert "vibe coding" not in output_text
    assert "memory bank" not in output_text
    assert "agentic" not in output_text


def test_exhibit_compiler_routes_source_shapes_to_exhibits() -> None:
    compiler = ExhibitCompiler()
    section = DocumentSection(
        title="Operating Model",
        level=1,
        content=(
            "First assign an owner. Then set the review gate. Next track the "
            "handoff. Finally confirm the decision."
        ),
        source_doc_id="doc",
    )
    metrics = [
        DocumentMetric(label="Quality 2024", value=70, unit="%", source_doc_id="doc"),
        DocumentMetric(label="Quality 2025", value=82, unit="%", source_doc_id="doc"),
        DocumentMetric(label="Quality 2026", value=91, unit="%", source_doc_id="doc"),
    ]
    table = DocumentTable(
        title="Adoption trend",
        headers=["Year", "Adoption"],
        rows=[["2024", "40%"], ["2025", "60%"], ["2026", "75%"]],
        source_doc_id="doc",
    )

    metric_exhibit = compiler.compile("metric_chart", "evidence", section, [], metrics)
    line_exhibit = compiler.compile("table_reference", "evidence", section, [table], [])
    matrix_exhibit = compiler.compile("matrix_2x2", "evidence", section, [], [])

    assert metric_exhibit["type"] == "metric_chart"
    assert line_exhibit["type"] == "line_chart"
    assert matrix_exhibit["type"] == "matrix_2x2"
    assert len(matrix_exhibit["quadrants"]) == 4


def test_template_analyzer_extracts_layout_profile(tmp_path: Path) -> None:
    logo_path = tmp_path / "logo.png"
    Image.new("RGB", (120, 40), "#111827").save(logo_path)
    template_path = tmp_path / "profile-template.pptx"

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    background = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(0),
        Inches(0),
        Inches(13.333),
        Inches(7.5),
    )
    background.fill.solid()
    background.fill.fore_color.rgb = RGBColor(244, 247, 251)
    background.line.fill.background()
    title = slide.shapes.add_textbox(Inches(1.1), Inches(0.45), Inches(7.0), Inches(0.55))
    title.text = "Profile title"
    body = slide.shapes.add_textbox(Inches(1.2), Inches(1.55), Inches(8.0), Inches(3.2))
    body.text = "Body region"
    footer = slide.shapes.add_textbox(Inches(1.1), Inches(6.8), Inches(3.2), Inches(0.25))
    footer.text = "Source: Example"
    slide.shapes.add_picture(
        logo_path.as_posix(),
        Inches(11.4),
        Inches(0.35),
        Inches(0.85),
        Inches(0.3),
    )
    presentation.save(template_path.as_posix())

    profile, _thumbnails = TemplateAnalyzer().analyze(
        template_path,
        template_name="Profile Template",
        template_type="brand",
    )

    layout_profile = profile.brand.layout_profile

    assert abs(layout_profile["title_box"]["x"] - 1.1) < 0.05
    assert abs(layout_profile["footer_box"]["y"] - 6.8) < 0.05
    assert abs(layout_profile["logo_box"]["x"] - 11.4) < 0.05
    assert layout_profile["dominant_fill"] == "F4F7FB"


def test_renderer_applies_brand_layout_profile_positions(tmp_path: Path) -> None:
    logo_path = tmp_path / "logo.png"
    Image.new("RGB", (120, 40), "#111827").save(logo_path)
    brand = BrandDNA(
        logo={"path": logo_path.as_posix(), "w": 0.8, "h": 0.28},
        layout_profile={
            "title_box": {"x": 1.35, "y": 0.55, "w": 7.0, "h": 0.6},
            "footer_box": {"x": 1.25, "y": 6.85, "w": 3.5, "h": 0.25},
            "logo_box": {"x": 11.2, "y": 0.42, "w": 0.8, "h": 0.28},
        },
    )
    outline = SlideOutline(
        id="outline-brand-profile",
        job_id="job-brand",
        slide_index=0,
        mode="flexible",
        label="Prioritize route visibility before crews leave the depot",
        content_json={
            "action_title": "Prioritize route visibility before crews leave the depot",
            "bullets": ["Dispatchers need live route visibility."],
            "sources": ["Dispatch Notes > Route Visibility"],
        },
        layout_json={"layout": "two_column", "visual_elements": ["structured_text"]},
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "brand-profile-rendered.pptx"

    DeterministicPptxRenderer().render([outline], brand, output_path)

    rendered = Presentation(output_path.as_posix())
    slide = rendered.slides[0]
    title_shape = next(
        shape for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
        and shape.text.startswith("Prioritize route visibility")
    )
    footer_shape = next(
        shape for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
        and shape.text.startswith("Source:")
    )
    logo_shape = next(
        shape for shape in slide.shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
    )

    assert abs(title_shape.left / 914400 - 1.35) < 0.05
    assert abs(footer_shape.left / 914400 - 1.25) < 0.05
    assert abs(logo_shape.left / 914400 - 11.2) < 0.05


def test_vision_qa_downgrades_positive_critical_findings() -> None:
    report = json.dumps(
        {
            "issues": [
                {
                    "severity": "CRITICAL",
                    "category": "overlap",
                    "message": "No overlapping elements detected; layout is clean.",
                    "slide_index": 0,
                }
            ]
        }
    )

    issues = VisualQAAgent()._parse_report(report, slide_index=0)

    assert issues[0].severity == "INFO"


def test_vision_qa_downgrades_footer_readability_risk() -> None:
    report = json.dumps(
        {
            "issues": [
                {
                    "severity": "CRITICAL",
                    "category": "cut-off-text",
                    "message": "Cut-off text risk: Footer source line is very small and may be unreadable.",
                    "slide_index": 0,
                }
            ]
        }
    )

    issues = VisualQAAgent()._parse_report(report, slide_index=0)

    assert issues[0].severity == "WARNING"


def test_quote_sidebar_does_not_render_meta_instruction_text(tmp_path: Path) -> None:
    outline = SlideOutline(
        id="outline-quote",
        job_id="job-quote",
        slide_index=0,
        mode="flexible",
        label="Reframe the operating model before scaling delivery",
        content_json={
            "action_title": "Reframe the operating model before scaling delivery",
            "subheading": "Quote sidebar highlighting the mental model shift",
            "summary": "Quote sidebar highlighting the mental model shift",
            "bullets": [
                "Treat the model as a managed teammate.",
                "Set review gates before production use.",
                "Keep source context persistent across sessions.",
            ],
            "sources": ["Uploaded source"],
            "exhibit_spec": {
                "type": "quote_sidebar",
                "key_idea": "Quote sidebar highlighting the mental model shift",
                "supporting_points": [
                    "Treat the model as a managed teammate.",
                    "Set review gates before production use.",
                    "Keep source context persistent across sessions.",
                ],
            },
        },
        layout_json={"layout": "quote_sidebar", "visual_elements": ["quote"]},
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "quote-sidebar.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text = "\n".join(
        shape.text
        for shape in rendered.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )

    assert "Quote sidebar highlighting" not in text
    assert "Treat the model as a managed teammate" in text


def test_cover_stack_handles_null_model_signals() -> None:
    outline = SlideOutline(
        id="outline-cover-null-signals",
        job_id="job-cover",
        slide_index=0,
        mode="flexible",
        label="Beyond Vibe Coding",
        content_json={
            "action_title": "Beyond Vibe Coding",
            "bullets": ["Persistent context improves handoffs."],
        },
        layout_json={"layout": "cover"},
        created_at="2026-01-01T00:00:00Z",
    )

    items = DeterministicPptxRenderer()._cover_stack_items(
        {"type": "cover", "signals": None},
        outline,
    )

    assert len(items) == 3
    assert items[0][1] == "Persistent context improves"


def _all_slide_text(slide) -> str:
    parts = [
        shape.text
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    ]
    parts.extend(
        cell.text
        for shape in slide.shapes
        if getattr(shape, "has_table", False)
        for row in shape.table.rows
        for cell in row.cells
    )
    return "\n".join(parts)


def test_phase_a_rendering_correctness(tmp_path: Path) -> None:
    """Regression: metric dicts, unformatted numbers, and empty comparison columns
    must never reach the rendered surface (Phase A correctness fixes)."""

    def _outline(idx: int, label: str, archetype: str, content: dict) -> SlideOutline:
        return SlideOutline(
            id=f"pa-{idx}",
            job_id="job-pa",
            slide_index=idx,
            mode="flexible",
            label=label,
            content_json={
                "action_title": label,
                "subheading": "",
                "bullets": [],
                "sources": ["Uploaded source"],
                "archetype": archetype,
                **content,
            },
            layout_json={"layout": archetype, "icons": ["FaDatabase", "FaShieldAlt", "FaBolt"]},
            created_at="2026-01-01T00:00:00Z",
        )

    outlines = [
        # A1: metric dicts in bullets must not stringify as raw dicts.
        _outline(
            0,
            "Adoption is high enough to make discipline the constraint",
            "icon_rows",
            {
                "bullets": [
                    {"label": "AI-generated", "value": 95, "unit": "%"},
                    {"label": "Context window", "value": 200000, "unit": "tokens"},
                ]
            },
        ),
        # A2: callouts must humanize large numbers ("200k", never "200000tokens").
        _outline(
            1,
            "Capacity is high but discipline is the constraint",
            "callouts",
            {
                "metrics": [
                    {"label": "Adoption", "value": 85, "unit": "%"},
                    {"label": "Context window maximum", "value": 200000, "unit": "tokens"},
                ]
            },
        ),
        # A3: a comparison with no target-state column must not render empty cards.
        _outline(
            2,
            "Four steps immediately improve AI coding outcomes",
            "comparison_table",
            {
                "exhibit_spec": {
                    "type": "comparison_table",
                    "columns": ["Dimension", "Current state", "Target state"],
                    "rows": [
                        {"label": "Step 1", "values": ["Create a memory bank"]},
                        {"label": "Step 2", "values": ["Write specs before features"]},
                    ],
                }
            },
        ),
    ]
    output_path = tmp_path / "phase-a.pptx"
    DeterministicPptxRenderer().render(outlines, BrandDNA(), output_path)
    rendered = Presentation(output_path.as_posix())
    full = "\n".join(_all_slide_text(slide) for slide in rendered.slides)

    # A1: no raw dict reprs leaked into a text frame.
    for marker in ("{'label'", "{'value'", "{'unit'", '{"label"'):
        assert marker not in full
    assert "AI-generated: 95%" in full
    # A2: large number humanized, not raw-concatenated.
    assert "200k" in full
    assert "200000tokens" not in full
    # A3: empty-target comparison fell back instead of drawing blank target cards.
    assert "COMPARISON LENS" not in _all_slide_text(rendered.slides[2])


def test_metrics_do_not_repeat_across_slides() -> None:
    """Phase B: the same KPI must not appear on more than one slide's exhibit."""
    metrics = [
        DocumentMetric(label=f"Signal {i}", value=value, unit="%", source_doc_id="source-doc")
        for i, value in enumerate([95, 85, 72, 64, 58, 41, 33, 27], start=1)
    ]
    section = DocumentSection(
        title="Adoption signals",
        level=1,
        content="Adoption and capacity metrics across the program.",
        source_doc_id="source-doc",
        source_id="source-doc:section:1:adoption",
    )
    bundle = DocumentBundle(
        job_id="job-metric",
        sections=[section],
        tables=[],
        metrics=metrics,
        metadata=DocumentMetadata(title="Beyond Vibe Coding"),
        content_inventory=[],
        source_index={
            section.source_id: {
                "kind": "section",
                "source_doc_id": "source-doc",
                "title": "Adoption signals",
                "label": "Beyond Vibe Coding > Adoption signals",
            }
        },
    )
    deck = DeckSpec(
        deck_title="Adoption",
        slides=[
            GeneratedSlideSpec(
                slide_number=i,
                slide_type="chart",
                action_title=f"Adoption percentage rises across program area {i}",
                archetype="metric_chart",
                exhibit_spec=None,
                source_refs=[section.source_id],
            )
            for i in range(1, 4)
        ],
    )
    planner = ContentPlanner()
    planner._apply_exhibit_selection(deck, bundle)

    per_slide_keys = []
    for slide in deck.slides:
        exhibit = slide.exhibit_spec or {}
        per_slide_keys.append(
            {
                planner._metric_key(m.get("label"), m.get("value"), m.get("unit"))
                for m in exhibit.get("metrics", [])
                if isinstance(m, dict)
            }
        )

    seen: set[str] = set()
    for keys in per_slide_keys:
        assert not (keys & seen), f"metric reused across slides: {keys & seen}"
        seen |= keys
    # de-duplication still distributed real metrics to more than one slide
    assert sum(1 for keys in per_slide_keys if keys) >= 2


def test_section_numbers_are_sequential_and_cover_uses_deck_title() -> None:
    """Phase C: kickers read 01..0N monotonically; the cover shows the deck title."""
    roles = ["problem", "evidence", "evidence", "framework", "decision", "closing"]
    slides = [
        GeneratedSlideSpec(
            slide_number=1,
            slide_type="cover",
            action_title="Prioritize overview to strengthen the recommendation",
            archetype="cover",
            narrative_role="cover",
        )
    ]
    for i, role in enumerate(roles, start=2):
        slides.append(
            GeneratedSlideSpec(
                slide_number=i,
                slide_type="content",
                action_title=f"Claim number {i} states the operating point",
                archetype="two_column",
                narrative_role=role,
            )
        )
    deck = DeckSpec(deck_title="Beyond Vibe Coding", slides=slides)
    outlines = ContentPlanner()._deck_to_outlines(deck, "job-c", "freeform")

    # C2: the cover carries the real deck title, not the meta action title.
    assert outlines[0].content_json.get("deck_title") == "Beyond Vibe Coding"
    assert outlines[0].content_json.get("action_title") == "Beyond Vibe Coding"
    assert outlines[0].label == "Beyond Vibe Coding"
    assert outlines[0].layout_json.get("section_number") == ""

    # C1: section numbers are monotonic; contiguous same-label slides share one.
    numbers = [int(o.layout_json["section_number"]) for o in outlines[1:]]
    assert numbers == sorted(numbers)
    assert numbers == [1, 2, 2, 3, 4, 5]
