"""Tests for XMLInjector service."""
from pathlib import Path

import pytest
from lxml import etree

from app.models.schemas import InjectionTarget
from app.services.xml_injector import NSMAP, XMLInjector

# Minimal slide XML with known shape IDs
SAMPLE_SLIDE_XML = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Title 1"/>
          <p:cNvSpPr/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr/>
        <p:txBody>
          <a:bodyPr/>
          <a:p>
            <a:r>
              <a:rPr lang="en-US" sz="2400" b="1" dirty="0"/>
              <a:t>[TITLE]</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="3" name="Content 2"/>
          <p:cNvSpPr/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr/>
        <p:txBody>
          <a:bodyPr/>
          <a:p>
            <a:r>
              <a:rPr lang="en-US" sz="1800" dirty="0"/>
              <a:t>First part </a:t>
            </a:r>
            <a:r>
              <a:rPr lang="en-US" sz="1800" b="1" dirty="0"/>
              <a:t>bold part</a:t>
            </a:r>
          </a:p>
          <a:p>
            <a:r>
              <a:rPr lang="en-US" sz="1800" dirty="0"/>
              <a:t>Second paragraph</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>
"""


@pytest.fixture
def staging_dir(tmp_path):
    slides_dir = tmp_path / "ppt" / "slides"
    slides_dir.mkdir(parents=True)
    (slides_dir / "slide1.xml").write_text(SAMPLE_SLIDE_XML)
    return tmp_path


@pytest.fixture
def injector():
    return XMLInjector()


def _read_slide_xml(staging_dir: Path, slide_num: int = 1) -> etree._Element:
    path = staging_dir / "ppt" / "slides" / f"slide{slide_num}.xml"
    return etree.fromstring(path.read_bytes())


def _get_shape_text(root: etree._Element, shape_id: int) -> str:
    xpath = f".//p:sp[p:nvSpPr/p:cNvPr[@id='{shape_id}']]//a:t"
    texts = root.xpath(xpath, namespaces=NSMAP)
    return "".join(t.text or "" for t in texts)


def _get_first_run_props(root: etree._Element, shape_id: int) -> etree._Element | None:
    xpath = f".//p:sp[p:nvSpPr/p:cNvPr[@id='{shape_id}']]//a:r/a:rPr"
    results = root.xpath(xpath, namespaces=NSMAP)
    return results[0] if results else None


def test_simple_text_replacement(staging_dir, injector):
    targets = [
        InjectionTarget(slide_index=1, shape_id=2, field_name="title", value="New Title"),
    ]
    warnings = injector.inject(staging_dir, targets)
    assert warnings == []

    root = _read_slide_xml(staging_dir)
    assert _get_shape_text(root, 2) == "New Title"


def test_formatting_preserved(staging_dir, injector):
    targets = [
        InjectionTarget(slide_index=1, shape_id=2, field_name="title", value="Replaced"),
    ]
    injector.inject(staging_dir, targets)

    root = _read_slide_xml(staging_dir)
    rpr = _get_first_run_props(root, 2)
    assert rpr is not None
    assert rpr.get("sz") == "2400"
    assert rpr.get("b") == "1"
    assert rpr.get("lang") == "en-US"


def test_multi_run_consolidation(staging_dir, injector):
    """Multi-run text (shape 3) should be replaced with single text, keeping first run's format."""
    targets = [
        InjectionTarget(slide_index=1, shape_id=3, field_name="content", value="Single text now"),
    ]
    injector.inject(staging_dir, targets)

    root = _read_slide_xml(staging_dir)
    assert _get_shape_text(root, 3) == "Single text now"

    # Should only have one run now
    runs = root.xpath(
        ".//p:sp[p:nvSpPr/p:cNvPr[@id='3']]//a:r", namespaces=NSMAP
    )
    assert len(runs) == 1

    # First run's formatting preserved (not bold)
    rpr = _get_first_run_props(root, 3)
    assert rpr is not None
    assert rpr.get("sz") == "1800"
    assert rpr.get("b") is None  # First run was not bold


def test_shape_not_found_warning(staging_dir, injector):
    targets = [
        InjectionTarget(slide_index=1, shape_id=999, field_name="missing", value="val"),
    ]
    warnings = injector.inject(staging_dir, targets)
    assert len(warnings) == 1
    assert "999" in warnings[0]
    assert "missing" in warnings[0]


def test_slide_not_found_warning(staging_dir, injector):
    targets = [
        InjectionTarget(slide_index=99, shape_id=2, field_name="field", value="val"),
    ]
    warnings = injector.inject(staging_dir, targets)
    assert len(warnings) == 1
    assert "slide99" in warnings[0]


def test_multiple_shapes_same_slide(staging_dir, injector):
    targets = [
        InjectionTarget(slide_index=1, shape_id=2, field_name="title", value="Title Text"),
        InjectionTarget(slide_index=1, shape_id=3, field_name="content", value="Content Text"),
    ]
    warnings = injector.inject(staging_dir, targets)
    assert warnings == []

    root = _read_slide_xml(staging_dir)
    assert _get_shape_text(root, 2) == "Title Text"
    assert _get_shape_text(root, 3) == "Content Text"


def test_xml_remains_wellformed(staging_dir, injector):
    targets = [
        InjectionTarget(
            slide_index=1, shape_id=2, field_name="title",
            value="Text with <special> & \"chars\"",
        ),
    ]
    injector.inject(staging_dir, targets)

    # Read and parse — should not raise
    root = _read_slide_xml(staging_dir)
    assert _get_shape_text(root, 2) == 'Text with <special> & "chars"'
