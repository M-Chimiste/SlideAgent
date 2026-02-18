"""Tests for the slideagent programmatic API (WI-3.5)."""

from pathlib import Path

import pytest

from slideagent import SlideAgentClient, GenerateResult, DeckMode

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
STORAGE_BASE = str(TEMPLATES_DIR.parent)


@pytest.fixture
async def client(tmp_path):
    c = SlideAgentClient(
        templates_dir=str(TEMPLATES_DIR),
        storage_base=STORAGE_BASE,
        staging_dir=str(tmp_path / "staging"),
    )
    await c.initialize()
    return c


@pytest.mark.asyncio
async def test_client_initializes(client):
    """Client should load templates on initialize."""
    templates = client.templates.list_templates()
    assert len(templates) >= 2
    ids = [t.template_id for t in templates]
    assert "novartis-status-weekly" in ids
    assert "corporate-deck" in ids


@pytest.mark.asyncio
async def test_generate_mode1(client, tmp_path):
    """Mode 1: generate deck from structured data."""
    result = await client.generate_deck(
        template_id="novartis-status-weekly",
        mode="mode1",
        input_data={
            "deck_title": "API Test Report",
            "report_date": "17 Feb 2026",
            "project_name": "Ariadne",
            "summary": "On track.",
            "status": "Green",
            "owner": "Test",
        },
    )

    assert result.success, f"Generation failed: {result.error}"
    assert result.output_path
    assert len(result.warnings) == 0

    # Verify the output file exists and is a valid PPTX
    import io
    from pptx import Presentation
    from app.storage.local import LocalStorage

    storage = LocalStorage(base_path=STORAGE_BASE)
    pptx_bytes = await storage.read_bytes(result.output_path)
    prs = Presentation(io.BytesIO(pptx_bytes))
    assert len(prs.slides) == 2


@pytest.mark.asyncio
async def test_generate_mode1_missing_template(client):
    """Mode 1 with nonexistent template should return error."""
    result = await client.generate_deck(
        template_id="nonexistent",
        mode="mode1",
        input_data={"title": "Test"},
    )
    assert not result.success
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_generate_mode1_validation_error(client):
    """Mode 1 with invalid enum should fail."""
    result = await client.generate_deck(
        template_id="novartis-status-weekly",
        mode="mode1",
        input_data={
            "deck_title": "Test",
            "report_date": "17 Feb 2026",
            "project_name": "X",
            "summary": "OK",
            "status": "Blue",  # Invalid enum
            "owner": "Test",
        },
    )
    assert not result.success
    assert "Blue" in result.error


@pytest.mark.asyncio
async def test_generate_mode2_without_bedrock(client):
    """Mode 2 without Bedrock should return error."""
    result = await client.generate_deck(
        template_id="corporate-deck",
        mode="mode2",
        input_data={"title": "Test"},
    )
    assert not result.success
    assert "Bedrock" in result.error


@pytest.mark.asyncio
async def test_deck_mode_enum():
    """DeckMode enum values."""
    assert DeckMode.mode1 == "mode1"
    assert DeckMode.mode2 == "mode2"


@pytest.mark.asyncio
async def test_generate_result_model():
    """GenerateResult model construction."""
    r = GenerateResult(success=True, output_path="test.pptx")
    assert r.success
    assert r.warnings == []
    assert r.error is None

    r2 = GenerateResult(success=False, error="Something went wrong")
    assert not r2.success
    assert r2.error == "Something went wrong"
