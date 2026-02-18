import json
from pathlib import Path

import pytest


from app.models.templates import FieldType
from app.services.template_registry import TemplateRegistry


@pytest.fixture
def templates_dir(tmp_path):
    """Create a minimal template directory for testing."""
    tpl_dir = tmp_path / "test-template"
    tpl_dir.mkdir()

    (tpl_dir / "meta.json").write_text(json.dumps({
        "template_id": "test-template",
        "version": "1.0.0",
        "display_name": "Test Template",
        "description": "A test template",
        "mode": "mode1",
    }))

    (tpl_dir / "schema.json").write_text(json.dumps({
        "slides": {
            "1": {
                "description": "Title slide",
                "fields": {
                    "title": {"shape_id": 2, "type": "text", "max_chars": 60, "required": True},
                }
            },
            "2": {
                "description": "Content slide",
                "fields": {
                    "body": {"shape_id": 3, "type": "text", "max_chars": 300, "required": True},
                    "status": {
                        "shape_id": 4, "type": "enum",
                        "allowed_values": ["Green", "Red"], "required": True,
                    },
                }
            }
        }
    }))

    (tpl_dir / "template.pptx").write_bytes(b"fake pptx")
    return tmp_path


@pytest.mark.asyncio
async def test_load_and_list(templates_dir):
    registry = TemplateRegistry(str(templates_dir))
    await registry.load_all()
    templates = registry.list_templates()
    assert len(templates) == 1
    assert templates[0].template_id == "test-template"
    assert templates[0].display_name == "Test Template"


@pytest.mark.asyncio
async def test_get_template(templates_dir):
    registry = TemplateRegistry(str(templates_dir))
    await registry.load_all()
    tpl = registry.get_template("test-template")
    assert tpl is not None
    assert tpl.version == "1.0.0"


@pytest.mark.asyncio
async def test_get_template_missing(templates_dir):
    registry = TemplateRegistry(str(templates_dir))
    await registry.load_all()
    assert registry.get_template("nonexistent") is None


@pytest.mark.asyncio
async def test_get_schema(templates_dir):
    registry = TemplateRegistry(str(templates_dir))
    await registry.load_all()
    schema = registry.get_schema_for_template("test-template")
    assert schema is not None
    assert "1" in schema
    assert "2" in schema
    assert schema["1"].fields["title"].type == FieldType.text
    assert schema["1"].fields["title"].max_chars == 60
    assert schema["2"].fields["status"].allowed_values == ["Green", "Red"]


@pytest.mark.asyncio
async def test_get_template_path(templates_dir):
    registry = TemplateRegistry(str(templates_dir))
    await registry.load_all()
    path = registry.get_template_path("test-template")
    assert path is not None
    assert "template.pptx" in path


@pytest.mark.asyncio
async def test_load_real_template():
    """Test loading the actual sample template from the templates directory."""
    templates_path = Path(__file__).resolve().parent.parent.parent / "templates"
    registry = TemplateRegistry(str(templates_path))
    await registry.load_all()
    tpl = registry.get_template("novartis-status-weekly")
    if tpl is None:
        pytest.skip("Sample template not in expected location")
    assert tpl.display_name == "Weekly Status Deck"
    schema = registry.get_schema_for_template("novartis-status-weekly")
    assert schema is not None
    assert "1" in schema
    assert "2" in schema
    assert "deck_title" in schema["1"].fields
    assert "status" in schema["2"].fields


@pytest.mark.asyncio
async def test_empty_directory(tmp_path):
    registry = TemplateRegistry(str(tmp_path))
    await registry.load_all()
    assert registry.list_templates() == []


@pytest.mark.asyncio
async def test_nonexistent_directory(tmp_path):
    registry = TemplateRegistry(str(tmp_path / "nonexistent"))
    await registry.load_all()
    assert registry.list_templates() == []
