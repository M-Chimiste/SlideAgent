"""Tests for Mode 2 template registry and layout library."""

from pathlib import Path

import pytest

from app.models.templates import ContentType, LayoutDefinition
from app.services.template_registry import TemplateRegistry

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


@pytest.fixture
async def registry():
    reg = TemplateRegistry(templates_dir=str(TEMPLATES_DIR))
    await reg.load_all()
    return reg


@pytest.mark.asyncio
async def test_mode2_template_loaded(registry):
    """The corporate-deck Mode 2 template should be loaded."""
    template = registry.get_template("corporate-deck")
    assert template is not None
    assert template.mode == "mode2"
    assert template.display_name == "Corporate Deck"


@pytest.mark.asyncio
async def test_mode2_template_has_layouts(registry):
    """Mode 2 template should have layouts, not slides."""
    template = registry.get_template("corporate-deck")
    assert template.layouts is not None
    assert template.slides is None
    assert len(template.layouts) >= 4


@pytest.mark.asyncio
async def test_get_layouts_for_template(registry):
    """get_layouts_for_template should return layout definitions."""
    layouts = registry.get_layouts_for_template("corporate-deck")
    assert layouts is not None
    assert "title_slide" in layouts
    assert "content_bullets" in layouts
    assert "section_divider" in layouts
    assert "two_column" in layouts
    assert "closing" in layouts


@pytest.mark.asyncio
async def test_layout_definition_structure(registry):
    """Each layout should have proper fields and content type mapping."""
    layouts = registry.get_layouts_for_template("corporate-deck")

    title = layouts["title_slide"]
    assert isinstance(title, LayoutDefinition)
    assert title.layout_name == "Title Slide"
    assert title.slide_layout_index == 0
    assert ContentType.title in title.suitable_for
    assert "deck_title" in title.fields
    assert title.fields["deck_title"].shape_id == 2

    bullets = layouts["content_bullets"]
    assert ContentType.bullets in bullets.suitable_for
    assert "slide_title" in bullets.fields
    assert "body" in bullets.fields

    two_col = layouts["two_column"]
    assert "left_content" in two_col.fields
    assert "right_content" in two_col.fields


@pytest.mark.asyncio
async def test_get_layouts_for_mode1_template(registry):
    """get_layouts_for_template should return None for Mode 1 templates."""
    layouts = registry.get_layouts_for_template("novartis-status-weekly")
    assert layouts is None


@pytest.mark.asyncio
async def test_mode1_still_works(registry):
    """Mode 1 template should still work as before."""
    schema = registry.get_schema_for_template("novartis-status-weekly")
    assert schema is not None
    assert "1" in schema
    assert "deck_title" in schema["1"].fields
