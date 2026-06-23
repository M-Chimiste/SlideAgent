from app.services.visual_qa_agent import VisualQAAgent
from app.models.outline import SlideOutline
from app.services.rendering import RenderingError

import zipfile
from io import BytesIO

from PIL import Image
from pptx import Presentation
from pptx.util import Inches


def test_extract_json_from_fenced_block() -> None:
    agent = VisualQAAgent()
    report = """Some explanation
```json
{"issues":[{"severity":"CRITICAL","message":"Overlap"}]}
```
"""
    payload = agent._extract_json(report)
    assert payload is not None
    assert payload["issues"][0]["message"] == "Overlap"


def test_parse_report_schema_fallback_warning() -> None:
    agent = VisualQAAgent()
    issues = agent._parse_report("not-json", 2)
    assert len(issues) == 1
    assert issues[0].severity == "WARNING"
    assert issues[0].slide_index == 2


def test_parse_report_uses_actual_image_index_for_single_slide_inspection() -> None:
    agent = VisualQAAgent()
    report = (
        '{"issues":[{"severity":"CRITICAL","message":"Overlap",'
        '"category":"overlap","slide_index":0}]}'
    )

    issues = agent._parse_report(report, 4)

    assert len(issues) == 1
    assert issues[0].slide_index == 4


def test_rule_checks_ignore_stale_source_placeholder_when_refs_are_valid() -> None:
    outline = SlideOutline(
        id="outline-source-stale",
        job_id="job-source",
        slide_index=0,
        mode="flexible",
        label="Context rot makes long-running work unreliable",
        content_json={
            "sources": ["[source needed]", "Beyond Vibe Coding > Context Rot"],
            "source_refs": ["doc-1:section:context-rot"],
        },
        layout_json={"layout": "chart", "visual_elements": ["charts"]},
        created_at="2026-01-01T00:00:00Z",
    )

    issues = VisualQAAgent()._rule_based_checks([outline])

    assert "source_placeholder" not in {issue.category for issue in issues}


class DummyVisionClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete_vision(self, **kwargs) -> str:
        self.calls += 1
        return '{"issues":[{"severity":"INFO","message":"Looks clean","category":"visual","slide_index":0}]}'


def test_openai_vision_client_is_used_for_image_inspection(tmp_path) -> None:
    image_path = tmp_path / "slide-1.jpg"
    image_path.write_bytes(b"fake-image")
    client = DummyVisionClient()
    agent = VisualQAAgent(openai_client=client)

    report = agent._inspect_image(image_path)

    assert client.calls == 1
    assert "Looks clean" in report


class CapturingVisionClient:
    def __init__(self) -> None:
        self.image_bytes = b""

    def complete_vision(self, **kwargs) -> str:
        self.image_bytes = kwargs["image_bytes"]
        return '{"issues":[]}'


def test_openai_vision_client_receives_downscaled_slide_image(tmp_path) -> None:
    image_path = tmp_path / "large-slide.jpg"
    Image.new("RGB", (2400, 1350), "#ffffff").save(image_path)
    client = CapturingVisionClient()

    VisualQAAgent(openai_client=client)._inspect_image(image_path)

    with Image.open(BytesIO(client.image_bytes)) as inspected:
        assert max(inspected.size) <= 1280


class CriticalVisionClient:
    def complete_vision(self, **kwargs) -> str:
        return '{"issues":[{"severity":"CRITICAL","message":"Possible cutoff","category":"cut-off-text","slide_index":0}]}'


class FailingVisionClient:
    def complete_vision(self, **kwargs) -> str:
        raise TimeoutError("vision timed out")


def test_vision_failure_warns_without_crashing(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "slide-1.jpg"
    image_path.write_bytes(b"fake-image")
    pptx_path = tmp_path / "deck.pptx"
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    prs.save(pptx_path.as_posix())
    monkeypatch.setattr(
        "app.services.visual_qa_agent.render_pptx_to_images",
        lambda *args, **kwargs: [image_path],
    )

    result, images = VisualQAAgent(openai_client=FailingVisionClient()).inspect_deck(
        pptx_path, tmp_path / "preview", []
    )

    assert images == [image_path]
    assert result.passed is True
    assert any(issue.category == "vision_unavailable" for issue in result.issues)


def test_render_unavailable_warns_without_blocking(tmp_path) -> None:
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Slide",
        content_json={"title": "Action title"},
        layout_json={"layout": "two_column", "visual_elements": ["structured_text"]},
        created_at="2026-01-01T00:00:00Z",
    )
    agent = VisualQAAgent()

    result, images = agent.inspect_deck(
        tmp_path / "missing.pptx", tmp_path / "preview", [outline]
    )

    assert images == []
    assert result.passed is False
    assert result.issues[0].category == "render_unavailable"
    assert any(issue.category == "office_compatibility" for issue in result.issues)


def test_render_unavailable_uses_pptx_preview_fallback(tmp_path, monkeypatch) -> None:
    def fail_render(*args, **kwargs):
        raise RenderingError("LibreOffice is unavailable")

    pptx_path = tmp_path / "deck.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    box.text = "A clear action title"
    prs.save(pptx_path.as_posix())
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Slide",
        content_json={"title": "Action title", "sources": ["Uploaded source"]},
        layout_json={"layout": "two_column", "visual_elements": ["structured_text"]},
        created_at="2026-01-01T00:00:00Z",
    )
    monkeypatch.setattr("app.services.visual_qa_agent.render_pptx_to_images", fail_render)

    result, images = VisualQAAgent().inspect_deck(
        pptx_path, tmp_path / "preview", [outline]
    )

    assert images
    assert images[0].exists()
    assert result.passed is True
    assert {issue.category for issue in result.issues} >= {
        "render_unavailable",
        "render_fallback",
    }


def test_fallback_preview_vision_criticals_are_non_blocking(tmp_path, monkeypatch) -> None:
    def fail_render(*args, **kwargs):
        raise RenderingError("LibreOffice is unavailable")

    pptx_path = tmp_path / "deck.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    box.text = "A clear action title"
    prs.save(pptx_path.as_posix())
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Slide",
        content_json={"title": "Action title", "sources": ["Uploaded source"]},
        layout_json={"layout": "two_column", "visual_elements": ["structured_text"]},
        created_at="2026-01-01T00:00:00Z",
    )
    monkeypatch.setattr("app.services.visual_qa_agent.render_pptx_to_images", fail_render)

    result, images = VisualQAAgent(openai_client=CriticalVisionClient()).inspect_deck(
        pptx_path, tmp_path / "preview", [outline]
    )

    assert images
    assert result.passed is True
    assert not any(issue.severity == "CRITICAL" for issue in result.issues)
    assert any(issue.category == "cut-off-text" for issue in result.issues)
    assert any(
        issue.message.startswith("Approximate preview finding:")
        for issue in result.issues
        if issue.category == "cut-off-text"
    )


def test_rule_based_checks_detect_source_and_layout_risks() -> None:
    outlines = [
        SlideOutline(
            id=f"outline-{idx}",
            job_id="job-1",
            slide_index=idx,
            mode="flexible",
            label=f"Slide {idx}",
            content_json={"title": f"Slide {idx}", "sources": []},
            layout_json={"layout": "two_column", "visual_elements": ["structured_text"]},
            created_at="2026-01-01T00:00:00Z",
        )
        for idx in range(4)
    ]

    issues = VisualQAAgent()._rule_based_checks(outlines)
    categories = {issue.category for issue in issues}

    assert "source_coverage" in categories
    assert "layout_variety" in categories
    assert "layout_repetition" in categories


def test_rule_based_checks_detect_repeated_heavy_comparison_treatment() -> None:
    outlines = []
    for idx, layout in enumerate(
        ["comparison_table", "callouts", "comparison_table", "icon_rows"]
    ):
        outlines.append(
            SlideOutline(
                id=f"outline-heavy-repeat-{idx}",
                job_id="job-heavy-repeat",
                slide_index=idx,
                mode="flexible",
                label=f"Slide {idx}",
                content_json={
                    "title": f"Slide {idx}",
                    "sources": ["Uploaded source"],
                    "exhibit_spec": {
                        "type": layout if layout != "icon_rows" else "callouts",
                        "columns": ["Dimension", "Current state", "Target state"],
                        "rows": [{"label": "Process", "values": ["Ad hoc", "Managed"]}],
                    },
                },
                layout_json={"layout": layout, "visual_elements": ["structured_text"]},
                created_at="2026-01-01T00:00:00Z",
            )
        )

    issues = VisualQAAgent()._rule_based_checks(outlines)

    assert "visual_repetition" in {issue.category for issue in issues}


def test_pptx_structure_checks_detect_text_density(tmp_path) -> None:
    pptx_path = tmp_path / "dense.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(1), Inches(0.4))
    box.text = " ".join(["dense"] * 120)
    prs.save(pptx_path.as_posix())

    issues = VisualQAAgent()._pptx_structure_checks(pptx_path, [])

    assert any(issue.category == "overflow_risk" for issue in issues)


def test_pptx_structure_checks_allow_short_structured_exhibit_labels(tmp_path) -> None:
    pptx_path = tmp_path / "structured-labels.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    labels = [
        "FILE",
        "ROLE",
        "UPDATE TRIGGER",
        "projectbrief.md",
        "Purpose and scope",
        "Scope changes",
        "productContext.md",
        "User goals",
        "Insight changes",
        "systemPatterns.md",
        "Architecture rules",
        "Design changes",
        "activeContext.md",
        "Current focus",
        "Each session",
    ]
    for idx, label in enumerate(labels):
        row = idx // 3
        col = idx % 3
        box = slide.shapes.add_textbox(
            Inches(1 + col * 3.2),
            Inches(1.2 + row * 0.52),
            Inches(2.6),
            Inches(0.3),
        )
        box.text = label
    prs.save(pptx_path.as_posix())
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Reference map",
        content_json={"archetype": "table_reference", "sources": ["Uploaded source"]},
        layout_json={"layout": "table_reference"},
        created_at="2026-01-01T00:00:00Z",
    )

    issues = VisualQAAgent()._pptx_structure_checks(pptx_path, [outline])

    assert not any(issue.category == "scanability" for issue in issues)


def test_pptx_structure_checks_still_flags_many_paragraph_objects(tmp_path) -> None:
    pptx_path = tmp_path / "many-paragraphs.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    paragraph = "This paragraph-style evidence box forces the reader to parse another sentence."
    for idx in range(12):
        row = idx // 3
        col = idx % 3
        box = slide.shapes.add_textbox(
            Inches(0.7 + col * 4.0),
            Inches(1.1 + row * 0.76),
            Inches(3.2),
            Inches(0.42),
        )
        box.text = paragraph
    prs.save(pptx_path.as_posix())
    outline = SlideOutline(
        id="outline-1",
        job_id="job-1",
        slide_index=0,
        mode="flexible",
        label="Dense slide",
        content_json={"archetype": "two_column", "sources": ["Uploaded source"]},
        layout_json={"layout": "two_column"},
        created_at="2026-01-01T00:00:00Z",
    )

    issues = VisualQAAgent()._pptx_structure_checks(pptx_path, [outline])

    assert any(issue.category == "scanability" for issue in issues)


def test_pptx_structure_checks_allow_valid_package(tmp_path) -> None:
    pptx_path = tmp_path / "valid.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    box.text = "A clear action title"
    prs.save(pptx_path.as_posix())

    issues = VisualQAAgent()._pptx_structure_checks(pptx_path, [])

    assert not any(issue.category == "office_compatibility" for issue in issues)


def test_pptx_structure_checks_detect_missing_relationship_target(tmp_path) -> None:
    pptx_path = tmp_path / "broken-rel.pptx"
    _write_basic_pptx(pptx_path)
    rel_name = "ppt/slides/_rels/slide1.xml.rels"
    with zipfile.ZipFile(pptx_path, "r") as source_zip:
        entries = {name: source_zip.read(name) for name in source_zip.namelist()}
    rel_xml = entries[rel_name].replace(b"../slideLayouts/slideLayout7.xml", b"../slideLayouts/missing.xml")
    entries[rel_name] = rel_xml
    _write_zip_entries(pptx_path, entries)

    issues = VisualQAAgent()._pptx_structure_checks(pptx_path, [])

    assert any(
        issue.category == "office_compatibility"
        and "Relationship target is missing" in issue.message
        for issue in issues
    )


def test_pptx_structure_checks_detect_missing_content_type(tmp_path) -> None:
    pptx_path = tmp_path / "missing-content-type.pptx"
    _write_basic_pptx(pptx_path)
    with zipfile.ZipFile(pptx_path, "r") as source_zip:
        entries = {name: source_zip.read(name) for name in source_zip.namelist()}
    entries["ppt/customData/custom.dat"] = b"custom"
    _write_zip_entries(pptx_path, entries)

    issues = VisualQAAgent()._pptx_structure_checks(pptx_path, [])

    assert any(
        issue.category == "office_compatibility"
        and "no content type declaration" in issue.message
        for issue in issues
    )


def _write_basic_pptx(path) -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    box.text = "A clear action title"
    prs.save(path.as_posix())


def _write_zip_entries(path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as output_zip:
        for name, data in entries.items():
            output_zip.writestr(name, data)
