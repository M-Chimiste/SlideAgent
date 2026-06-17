from app.services.visual_qa_agent import VisualQAAgent
from app.models.outline import SlideOutline
from app.services.rendering import RenderingError

import zipfile

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


def test_pptx_structure_checks_detect_text_density(tmp_path) -> None:
    pptx_path = tmp_path / "dense.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(1), Inches(0.4))
    box.text = " ".join(["dense"] * 120)
    prs.save(pptx_path.as_posix())

    issues = VisualQAAgent()._pptx_structure_checks(pptx_path, [])

    assert any(issue.category == "overflow_risk" for issue in issues)


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
