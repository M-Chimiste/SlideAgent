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

    assert thumbnails == []
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

    assert "Diagram Description" not in text
    assert "Project context persists." in text
