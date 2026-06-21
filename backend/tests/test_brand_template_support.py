from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Inches

from app.models.brand import BrandDNA
from app.models.outline import SlideOutline
from app.services.pptx_renderer import DeterministicPptxRenderer
from app.services.template_analyzer import TemplateAnalyzer


def test_brand_dna_accepts_flat_brand_aliases() -> None:
    brand = BrandDNA(
        primary_color="#111827",
        secondary_color="#2563eb",
        accent_color="#16a34a",
        font_headings="Aptos Display",
        font_body="Aptos",
    )

    assert brand.colors.primary == "#111827"
    assert brand.colors.secondary == "#2563eb"
    assert brand.colors.accent == "#16a34a"
    assert brand.fonts.heading == "Aptos Display"
    assert brand.fonts.body == "Aptos"


def test_template_analyzer_extracts_logo_and_layout_notes(tmp_path: Path) -> None:
    template_path = tmp_path / "brand-template.pptx"
    logo_path = tmp_path / "logo.png"
    Image.new("RGB", (180, 60), "#111827").save(logo_path)
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_picture(logo_path.as_posix(), Inches(11.0), Inches(0.4), Inches(1.4), Inches(0.45))
    title = slide.shapes.add_textbox(Inches(0.8), Inches(1.2), Inches(6), Inches(0.5))
    title.text = "Brand example"
    presentation.save(template_path.as_posix())

    profile, thumbnails = TemplateAnalyzer().analyze(
        template_path,
        template_name="Brand Template",
        template_type="brand",
        template_id="template-1",
    )

    # thumbnails are produced only when render tools (soffice/pdftoppm) are present;
    # the analyzer falls back to [] otherwise, so don't couple this test to the env.
    assert isinstance(thumbnails, list)
    assert profile.brand.logo is not None
    assert Path(profile.brand.logo.path).exists()
    assert "Reusable layout examples" in (profile.brand.design_notes or "")
    assert profile.slides[0].layout_name


def test_renderer_places_extracted_brand_logo(tmp_path: Path) -> None:
    logo_path = tmp_path / "logo.png"
    Image.new("RGB", (180, 60), "#111827").save(logo_path)
    brand = BrandDNA(logo={"path": logo_path.as_posix(), "w": 1.2, "h": 0.4})
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Adopt agentic coding to improve production reliability",
        content_json={
            "title": "Adopt agentic coding to improve production reliability",
            "summary": "External memory and specifications improve delivery quality.",
            "bullets": ["Persistent context reduces rework.", "Structured specs improve review."],
            "sources": ["Uploaded source"],
        },
        layout_json={"layout": "two_column", "visual_elements": ["structured_text"]},
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "logo-rendered.pptx"

    DeterministicPptxRenderer().render([outline], brand, output_path)

    rendered = Presentation(output_path.as_posix())
    assert any(
        shape.shape_type == MSO_SHAPE_TYPE.PICTURE
        for shape in rendered.slides[0].shapes
    )


def test_renderer_omits_subheading_for_wrapped_long_title(tmp_path: Path) -> None:
    long_title = (
        "Replace ephemeral vibe coding with persistent agentic workflows for "
        "scalable software delivery"
    )
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label=long_title,
        content_json={
            "action_title": long_title,
            "subheading": "Executive Summary: The Shift from Chatting to Managing AI",
            "bullets": ["Persistent context reduces rework."],
            "sources": ["Uploaded source"],
        },
        layout_json={"layout": "two_column", "visual_elements": ["structured_text"]},
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "long-title-rendered.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text_shapes = [
        shape
        for shape in rendered.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and shape.text
    ]
    title_shape = next(shape for shape in text_shapes if shape.text.startswith("Replace"))

    assert title_shape.text.endswith("delivery")
    assert not any(shape.text.startswith("Executive Summary") for shape in text_shapes)


def test_renderer_adds_editorial_section_chrome(tmp_path: Path) -> None:
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Prevent context rot before AI work scales",
        content_json={
            "action_title": "Prevent context rot before AI work scales",
            "subheading": "Evidence from uploaded source",
            "bullets": ["Persistent memory keeps work reproducible."],
            "sources": ["Uploaded source"],
            "archetype": "anti_patterns",
            "narrative_role": "problem",
        },
        layout_json={
            "layout": "two_column",
            "visual_elements": ["structured_text"],
            "narrative_role": "problem",
            "archetype": "anti_patterns",
        },
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "editorial-chrome.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text = "\n".join(
        shape.text
        for shape in rendered.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and shape.text
    )

    assert "SECTION 02 - DIAGNOSIS" in text
    assert "Prevent context rot before AI work scales" in text


def test_renderer_adds_executive_summary_proof_rail(tmp_path: Path) -> None:
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=1,
        mode="flexible",
        label="Manage AI coding as an operating system, not a prompt habit",
        content_json={
            "action_title": "Manage AI coding as an operating system, not a prompt habit",
            "subheading": "Situation, complication, resolution",
            "bullets": [
                "AI coding works for fast starts.",
                "Production work needs repeatable context and review.",
                "Managed agentic engineering supplies the operating model.",
            ],
            "sources": ["Uploaded source"],
            "archetype": "executive_summary",
            "narrative_role": "executive_summary",
            "exhibit_spec": {
                "type": "executive_summary",
                "messages": [
                    {"label": "Situation", "text": "AI coding works for fast starts."},
                    {
                        "label": "Complication",
                        "text": "Production work needs repeatable context and review.",
                    },
                    {
                        "label": "Resolution",
                        "text": "Managed agentic engineering supplies the operating model.",
                    },
                ],
                "proof_points": [
                    {
                        "label": "AI-generated codebases",
                        "value": 95,
                        "unit": "%",
                        "detail": "Adoption pressure is already visible.",
                    },
                    {
                        "label": "Developers using AI tools",
                        "value": 85,
                        "unit": "%",
                        "detail": "Usage is mainstream enough to manage.",
                    },
                ],
            },
        },
        layout_json={
            "layout": "executive_summary",
            "visual_elements": ["summary"],
            "narrative_role": "executive_summary",
            "archetype": "executive_summary",
        },
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "executive-summary-proof-rail.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text = "\n".join(
        shape.text
        for shape in rendered.slides[0].shapes
        if getattr(shape, "has_text_frame", False) and shape.text
    )

    assert "PROOF POINTS" in text
    assert "95%" in text
    assert "Decision ask" in text


def test_renderer_does_not_pad_grid_with_generic_filler(tmp_path: Path) -> None:
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Adopt persistent context management",
        content_json={
            "action_title": "Adopt persistent context management",
            "subheading": "Three evidence-backed points",
            "bullets": [
                "Context files reduce repeated explanations.",
                "Specifications improve review quality.",
                "Decision trails support maintainability.",
            ],
            "sources": ["Uploaded source"],
        },
        layout_json={"layout": "icon_grid", "visual_elements": ["icons", "shapes"]},
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "grid-rendered.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text = "\n".join(
        shape.text
        for shape in rendered.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )

    assert "Clarify the implication" not in text
    assert "Decision trails support maintainability." in text


def test_renderer_draws_semantic_icons_as_embedded_artwork(tmp_path: Path) -> None:
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Quantify production readiness before scaling AI development",
        content_json={
            "action_title": "Quantify production readiness before scaling AI development",
            "subheading": "Three evidence-backed points",
            "bullets": [
                "Adoption is high enough to require operating discipline.",
                "Persistent memory reduces repeated context setup.",
                "Review standards protect production reliability.",
            ],
            "sources": ["Uploaded source"],
        },
        layout_json={
            "layout": "icon_grid",
            "visual_elements": ["icons", "shapes"],
            "icons": ["FaChartLine", "FaDatabase", "FaShieldAlt"],
        },
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "icons-rendered.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    pictures = [
        shape
        for shape in rendered.slides[0].shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
    ]
    icon_cache = output_path.parent / f"{output_path.stem}-icons"

    assert len(pictures) >= 3
    cached_icons = {path.name for path in icon_cache.glob("*.png")}
    assert any(name.startswith("fachartline-") for name in cached_icons)
    assert any(name.startswith("fadatabase-") for name in cached_icons)
    assert any(name.startswith("fashieldalt-") for name in cached_icons)


def test_renderer_does_not_show_diagram_description_placeholders(tmp_path: Path) -> None:
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Map the External Brain architecture",
        content_json={
            "action_title": "Map the External Brain architecture",
            "subheading": "Evidence from uploaded source",
            "bullets": [
                "[Diagram Description: Central Node with arrows] Project context persists.",
                "Rules files guide each AI session.",
                "Memory bank updates after every meaningful change.",
            ],
            "sources": ["Uploaded source"],
        },
        layout_json={"layout": "dependency_map", "visual_elements": ["diagram"]},
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "cleaned-rendered.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text = "\n".join(
        shape.text
        for shape in rendered.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )
    diagram_svgs = list((tmp_path / "cleaned-rendered-diagrams").glob("*.svg"))
    artifact_text = "\n".join(path.read_text(encoding="utf-8") for path in diagram_svgs)

    assert "Diagram Description" not in f"{text}\n{artifact_text}"
    assert "Project context" in f"{text}\n{artifact_text}"
    assert "persists." in f"{text}\n{artifact_text}"


def test_renderer_uses_structured_exhibit_specs_for_authored_archetypes(tmp_path: Path) -> None:
    archetypes = [
        (
            "comparison_table",
            {
                "type": "comparison_table",
                "columns": [
                    {"name": "Dimension", "width": "20%"},
                    {"name": "Before", "width": "40%"},
                    {"name": "After", "width": "40%"},
                ],
                "rows": [{"label": "Context", "values": ["Chat", "Memory bank"]}],
            },
        ),
        (
            "anti_patterns",
            {
                "type": "anti_patterns",
                "patterns": [
                    {
                        "name": "Context rot",
                        "symptom": "Memory disappears",
                        "better_behavior": "Persist context",
                    }
                ],
            },
        ),
        (
            "dependency_map",
            {
                "type": "dependency_map",
                "left_node": "Source packet",
                "middle_nodes": ["Rules", "Architecture", "Decision log"],
                "right_outcome": "Reliable output",
            },
        ),
        (
            "framework_cycle",
            {
                "type": "cycle",
                "center_label": "Agent loop",
                "steps": [
                    {"label": "Frame", "description": "Define the ask"},
                    {"label": "Prime", "description": "Load context"},
                    {"label": "Review", "description": "Check output"},
                ],
            },
        ),
        (
            "code_panel",
            {
                "type": "code_panel",
                "title": "AGENTS.md",
                "lines": ["Require evidence before merge"],
            },
        ),
        (
            "table_reference",
            {
                "type": "reference_table",
                "columns": ["Artifact", "Purpose", "Update trigger"],
                "rows": [
                    [
                        "decision-log.md",
                        "Keeps approvals and assumptions traceable",
                        "Decision changes",
                    ],
                    [
                        "review-gate.md",
                        "Defines the evidence check before rollout",
                        "Pilot milestone",
                    ],
                ],
            },
        ),
        (
            "checklist",
            {
                "type": "checklist",
                "items": [
                    {"action": "Create memory files", "owner": "Lead", "timing": "Week 1"},
                    {"action": "Define review gates", "owner": "Manager", "timing": "Week 1"},
                    {"action": "Run pilot", "owner": "Team", "timing": "Week 2"},
                ],
            },
        ),
    ]
    outlines = [
        SlideOutline(
            id=f"outline-{idx}",
            job_id="job-1",
            slide_index=idx,
            mode="flexible",
            label="Improve AI delivery discipline",
            content_json={
                "action_title": "Improve AI delivery discipline",
                "subheading": "Evidence from uploaded source",
                "bullets": [],
                "sources": ["Uploaded source"],
                "archetype": layout,
                "exhibit_spec": exhibit,
            },
            layout_json={
                "layout": layout,
                "visual_elements": ["structured_exhibit"],
                "icons": ["FaDatabase", "FaShieldAlt", "FaClipboardCheck"],
            },
            created_at="2026-01-01T00:00:00Z",
        )
        for idx, (layout, exhibit) in enumerate(archetypes)
    ]
    output_path = tmp_path / "structured-exhibits.pptx"

    DeterministicPptxRenderer().render(outlines, BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text_parts = [
        shape.text
        for slide in rendered.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    ]
    text_parts.extend(
        cell.text
        for slide in rendered.slides
        for shape in slide.shapes
        if getattr(shape, "has_table", False)
        for row in shape.table.rows
        for cell in row.cells
    )
    text = "\n".join(text_parts)
    diagram_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "structured-exhibits-diagrams").glob("*.svg")
    )
    rendered_surface = f"{text}\n{diagram_text}"

    assert "Memory bank" in text
    assert "COMPARISON LENS" in text
    assert "TARGET TEST" in text
    assert "{'name'" not in text
    assert "Context rot" in text
    assert "Symptom:" in text
    assert "Better move:" in text
    assert "Pattern 1" not in text
    assert "Source packet" in rendered_surface
    assert "project_brief.md" not in text
    assert "Agent loop" in rendered_surface
    assert "AGENTS.md" in text
    assert "OPERATING RULES" in text
    assert "REFERENCE ARTIFACT" in text
    assert "REFERENCE MAP" in text
    assert "UPDATE CADENCE" in text
    assert "decision-log.md" in text
    assert "REVIEW GATE" in text
    assert "UPDATE TRIGGER" in text
    assert "Create memory files (Lead / Week 1)" in text


def test_renderer_uses_dark_cadence_for_narrative_beats(tmp_path: Path) -> None:
    outlines = [
        SlideOutline(
            id="cycle-outline",
            job_id="job-1",
            slide_index=0,
            mode="flexible",
            label="Run the operating cycle with explicit review gates",
            content_json={
                "action_title": "Run the operating cycle with explicit review gates",
                "subheading": "A repeatable loop for source-grounded work",
                "bullets": [],
                "sources": ["Uploaded source"],
                "archetype": "framework_cycle",
                "narrative_role": "framework",
                "exhibit_spec": {
                    "type": "cycle",
                    "center_label": "Agent loop",
                    "steps": [
                        {"label": "Load"},
                        {"label": "Plan"},
                        {"label": "Execute"},
                        {"label": "Verify"},
                        {"label": "Update"},
                        {"label": "Reset"},
                    ],
                },
            },
            layout_json={"layout": "framework_cycle", "visual_elements": ["cycle"]},
            created_at="2026-01-01T00:00:00Z",
        ),
        SlideOutline(
            id="quote-outline",
            job_id="job-1",
            slide_index=1,
            mode="flexible",
            label="Adopt the external brain mental model",
            content_json={
                "action_title": "Adopt the external brain mental model",
                "subheading": "Persistent context changes the management problem",
                "bullets": [
                    "Context must survive the chat window.",
                    "Rules must constrain the next run.",
                ],
                "sources": ["Uploaded source"],
                "archetype": "quote_sidebar",
                "narrative_role": "decision",
                "exhibit_spec": {
                    "type": "quote_sidebar",
                    "key_idea": "Treat the agent as capable but memoryless unless context is explicit.",
                    "supporting_points": [
                        "Context must survive the chat window.",
                        "Rules must constrain the next run.",
                    ],
                },
            },
            layout_json={"layout": "quote_sidebar", "visual_elements": ["quote"]},
            created_at="2026-01-01T00:00:00Z",
        ),
        SlideOutline(
            id="closing-outline",
            job_id="job-1",
            slide_index=2,
            mode="flexible",
            label="Commit to governed agentic delivery",
            content_json={
                "action_title": "Commit to governed agentic delivery",
                "subheading": "Recommendation and next steps",
                "bullets": ["Name the owner.", "Pilot the loop.", "Refresh memory."],
                "sources": ["Uploaded source"],
                "archetype": "closing_recommendation",
                "narrative_role": "closing",
                "exhibit_spec": {
                    "type": "recommendation",
                    "recommendation": "Commit to governed agentic delivery",
                    "decision_ask": "Approve the pilot workflow.",
                    "next_steps": ["Name the owner.", "Pilot the loop.", "Refresh memory."],
                },
            },
            layout_json={"layout": "closing_recommendation", "visual_elements": ["decision"]},
            created_at="2026-01-01T00:00:00Z",
        ),
    ]
    output_path = tmp_path / "dark-cadence.pptx"

    DeterministicPptxRenderer().render(outlines, BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text = "\n".join(
        shape.text
        for slide in rendered.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    )

    assert "/ OPERATING MODEL" in text
    assert "/ DECISION LENS" in text
    assert "/ FINAL DECISION" in text
    assert "SECTION 04 - OPERATING MODEL" not in text
    assert "SECTION 07 - DECISION" not in text


def test_renderer_text_cleanup_avoids_dangling_truncation() -> None:
    renderer = DeterministicPptxRenderer()

    cleaned = renderer._clean_display_text("Windows range from 32000.0tokens to 1M tokens")
    truncated = renderer._truncate_phrase(
        "A moderately complex project spans dozens of files and services",
        48,
    )

    assert "32000 tokens" in cleaned
    assert not truncated.lower().endswith((" and", " of", " to", " with"))


def test_renderer_avoids_duplicate_closing_recommendation(tmp_path: Path) -> None:
    title = "Commit to the reset habit as the single highest-leverage practice"
    outline = SlideOutline(
        id="closing-outline",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label=title,
        content_json={
            "action_title": title,
            "subheading": "Recommendation and decision ask",
            "bullets": ["Name an owner.", "Run the pilot.", "Update memory."],
            "sources": ["Uploaded source"],
            "archetype": "closing_recommendation",
            "narrative_role": "closing",
            "exhibit_spec": {
                "type": "recommendation",
                "recommendation": title,
                "decision_ask": "Approve a governed pilot.",
                "next_steps": ["Name an owner.", "Run the pilot.", "Update memory."],
            },
        },
        layout_json={"layout": "closing_recommendation", "visual_elements": ["decision"]},
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "closing-deduped.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text = "\n".join(
        shape.text
        for shape in rendered.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )

    assert "Make the reset habit the default operating rule before scaling." in text


def test_renderer_completes_sparse_code_panel_rules(tmp_path: Path) -> None:
    outline = SlideOutline(
        id="code-outline",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Codify memory updates before context goes stale",
        content_json={
            "action_title": "Codify memory updates before context goes stale",
            "subheading": "Memory maintenance rules",
            "bullets": [],
            "sources": ["Uploaded source"],
            "archetype": "code_panel",
            "exhibit_spec": {
                "type": "code_panel",
                "title": "activeContext.md",
                "lines": ["Update active context after material changes."],
            },
        },
        layout_json={"layout": "code_panel", "visual_elements": ["reference_panel"]},
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "sparse-code-panel.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text = "\n".join(
        shape.text
        for shape in rendered.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )

    assert "Update active context after material changes." in text
    assert "Record decisions before starting the next session." in text
    assert "Keep progress notes synchronized with implementation status." in text


def test_renderer_completes_sparse_checklist_items(tmp_path: Path) -> None:
    outline = SlideOutline(
        id="checklist-outline",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Define acceptance criteria before execution begins",
        content_json={
            "action_title": "Define acceptance criteria before execution begins",
            "subheading": "Specification discipline",
            "bullets": [],
            "sources": ["Uploaded source"],
            "archetype": "checklist",
            "exhibit_spec": {
                "type": "checklist",
                "items": [{"action": "Write acceptance criteria before generation begins"}],
            },
        },
        layout_json={"layout": "checklist", "visual_elements": ["checklist"]},
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "sparse-checklist.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text = "\n".join(
        shape.text
        for shape in rendered.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )

    assert "Write acceptance criteria before generation begins." in text
    assert "Attach source evidence to each material claim." in text
    assert "Review output against the defined test before approval." in text


def test_renderer_splits_metric_units_to_avoid_card_label_overlap(tmp_path: Path) -> None:
    outline = SlideOutline(
        id="metric-outline",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Quantify capacity before scaling",
        content_json={
            "action_title": "Quantify capacity before scaling",
            "subheading": "Evidence from uploaded source",
            "bullets": [],
            "metrics": [
                {"label": "Context window maximum", "value": 1_000_000, "unit": "tokens"},
                {"label": "Adoption", "value": 95, "unit": "%"},
            ],
            "sources": ["Uploaded source"],
            "archetype": "metric_chart",
            "exhibit_spec": {
                "type": "metric_chart",
                "metrics": [
                    {"label": "Context window maximum", "value": 1_000_000, "unit": "tokens"},
                    {"label": "Adoption", "value": 95, "unit": "%"},
                ],
            },
        },
        layout_json={"layout": "chart", "visual_elements": ["metrics"]},
        created_at="2026-01-01T00:00:00Z",
    )
    output_path = tmp_path / "metric-units.pptx"

    DeterministicPptxRenderer().render([outline], BrandDNA(), output_path)

    rendered = Presentation(output_path.as_posix())
    text = "\n".join(
        shape.text
        for shape in rendered.slides[0].shapes
        if getattr(shape, "has_text_frame", False)
    )

    assert "1M" in text
    assert "tokens" in text
    assert "1M tokens" not in text
