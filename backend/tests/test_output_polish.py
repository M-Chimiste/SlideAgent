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
