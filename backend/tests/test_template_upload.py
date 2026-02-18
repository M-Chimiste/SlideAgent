"""Tests for template upload API (WI-3.1) and template management (WI-3.2)."""

import io
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pptx import Presentation

from app.config import Settings
from app.main import create_app
from app.services.template_validator import TemplateValidationError, validate_template

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
SAMPLE_PPTX = TEMPLATES_DIR / "novartis-status-weekly" / "template.pptx"
SAMPLE_SCHEMA = TEMPLATES_DIR / "novartis-status-weekly" / "schema.json"
MODE2_PPTX = TEMPLATES_DIR / "corporate-deck" / "template.pptx"
MODE2_SCHEMA = TEMPLATES_DIR / "corporate-deck" / "schema.json"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        sqlite_path=str(tmp_path / "jobs.db"),
        templates_dir=str(TEMPLATES_DIR),
        staging_dir=str(tmp_path / "staging"),
        outputs_dir=str(tmp_path / "outputs"),
    )


@pytest.fixture
async def client(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


# --- Template Validator Unit Tests ---


def test_validate_mode1_template_valid():
    """Valid Mode 1 template+schema should produce no errors."""
    pptx_bytes = SAMPLE_PPTX.read_bytes()
    schema = json.loads(SAMPLE_SCHEMA.read_text())
    warnings = validate_template(pptx_bytes, schema)
    assert isinstance(warnings, list)


def test_validate_mode2_template_valid():
    """Valid Mode 2 template+schema should produce no errors."""
    pptx_bytes = MODE2_PPTX.read_bytes()
    schema = json.loads(MODE2_SCHEMA.read_text())
    warnings = validate_template(pptx_bytes, schema)
    assert isinstance(warnings, list)


def test_validate_invalid_shape_id():
    """Schema referencing nonexistent shape ID should raise error."""
    pptx_bytes = SAMPLE_PPTX.read_bytes()
    schema = {
        "slides": {
            "1": {
                "fields": {
                    "bad_field": {"shape_id": 9999, "type": "text"}
                }
            }
        }
    }
    with pytest.raises(TemplateValidationError) as exc_info:
        validate_template(pptx_bytes, schema)
    assert any("9999" in e for e in exc_info.value.errors)


def test_validate_invalid_slide_index():
    """Schema referencing out-of-range slide index should raise error."""
    pptx_bytes = SAMPLE_PPTX.read_bytes()
    schema = {
        "slides": {
            "99": {
                "fields": {
                    "field1": {"shape_id": 2, "type": "text"}
                }
            }
        }
    }
    with pytest.raises(TemplateValidationError) as exc_info:
        validate_template(pptx_bytes, schema)
    assert any("out of range" in e for e in exc_info.value.errors)


def test_validate_invalid_layout_index():
    """Schema referencing out-of-range layout index should raise error."""
    pptx_bytes = MODE2_PPTX.read_bytes()
    schema = {
        "layouts": {
            "bad_layout": {
                "layout_name": "Bad",
                "slide_layout_index": 999,
                "fields": {},
            }
        }
    }
    with pytest.raises(TemplateValidationError) as exc_info:
        validate_template(pptx_bytes, schema)
    assert any("out of range" in e for e in exc_info.value.errors)


def test_validate_missing_schema_keys():
    """Schema without slides or layouts should raise error."""
    pptx_bytes = SAMPLE_PPTX.read_bytes()
    with pytest.raises(TemplateValidationError) as exc_info:
        validate_template(pptx_bytes, {"other": {}})
    assert any("slides" in e and "layouts" in e for e in exc_info.value.errors)


def test_validate_corrupt_pptx():
    """Non-PPTX bytes should raise validation error."""
    with pytest.raises(TemplateValidationError) as exc_info:
        validate_template(b"not a pptx", {"slides": {}})
    assert any("Failed to parse" in e for e in exc_info.value.errors)


# --- Template Upload API Tests ---


@pytest.mark.asyncio
async def test_upload_template(client):
    """Upload a valid Mode 1 template via API."""
    pptx_bytes = SAMPLE_PPTX.read_bytes()
    schema = SAMPLE_SCHEMA.read_text()

    resp = await client.post(
        "/templates",
        data={
            "schema": schema,
            "template_id": "test-upload",
            "display_name": "Test Upload Template",
            "description": "Uploaded via test",
            "mode": "mode1",
            "version": "1.0.0",
        },
        files={"pptx_file": ("template.pptx", pptx_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["template_id"] == "test-upload"
    assert data["version"] == "1.0.0"

    # Template should now be listed
    list_resp = await client.get("/templates")
    template_ids = [t["template_id"] for t in list_resp.json()]
    assert "test-upload" in template_ids

    # Template should be retrievable
    detail_resp = await client.get("/templates/test-upload")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["template_id"] == "test-upload"
    assert "schema" in detail_resp.json()


@pytest.mark.asyncio
async def test_upload_template_invalid_mode(client):
    """Upload with invalid mode should fail."""
    pptx_bytes = SAMPLE_PPTX.read_bytes()
    schema = SAMPLE_SCHEMA.read_text()

    resp = await client.post(
        "/templates",
        data={
            "schema": schema,
            "template_id": "test-bad-mode",
            "display_name": "Bad Mode",
            "mode": "mode3",
            "version": "1.0.0",
        },
        files={"pptx_file": ("template.pptx", pptx_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_template_invalid_schema(client):
    """Upload with malformed JSON schema should fail."""
    pptx_bytes = SAMPLE_PPTX.read_bytes()

    resp = await client.post(
        "/templates",
        data={
            "schema": "not valid json {{{",
            "template_id": "test-bad-schema",
            "display_name": "Bad Schema",
            "mode": "mode1",
            "version": "1.0.0",
        },
        files={"pptx_file": ("template.pptx", pptx_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_template_bad_shape_id(client):
    """Upload with schema referencing nonexistent shape should fail."""
    pptx_bytes = SAMPLE_PPTX.read_bytes()
    bad_schema = json.dumps({
        "slides": {
            "1": {
                "fields": {
                    "bad_field": {"shape_id": 9999, "type": "text"}
                }
            }
        }
    })

    resp = await client.post(
        "/templates",
        data={
            "schema": bad_schema,
            "template_id": "test-bad-shapes",
            "display_name": "Bad Shapes",
            "mode": "mode1",
            "version": "1.0.0",
        },
        files={"pptx_file": ("template.pptx", pptx_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 422
    assert "errors" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_template_empty_pptx(client):
    """Upload with empty PPTX should fail."""
    resp = await client.post(
        "/templates",
        data={
            "schema": json.dumps({"slides": {}}),
            "template_id": "test-empty",
            "display_name": "Empty",
            "mode": "mode1",
            "version": "1.0.0",
        },
        files={"pptx_file": ("template.pptx", b"", "application/octet-stream")},
    )
    assert resp.status_code == 422


# --- Template Activate/Deactivate Tests ---


@pytest.mark.asyncio
async def test_deactivate_template(client):
    """Deactivating a template should hide it from listings."""
    # Verify template is listed
    list_resp = await client.get("/templates")
    ids = [t["template_id"] for t in list_resp.json()]
    assert "novartis-status-weekly" in ids

    # Deactivate
    resp = await client.patch(
        "/templates/novartis-status-weekly",
        data={"is_active": "false"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    # Should not appear in list anymore
    list_resp = await client.get("/templates")
    ids = [t["template_id"] for t in list_resp.json()]
    assert "novartis-status-weekly" not in ids

    # But should still be retrievable by ID (for existing jobs)
    detail_resp = await client.get("/templates/novartis-status-weekly")
    assert detail_resp.status_code == 200

    # Re-activate
    resp = await client.patch(
        "/templates/novartis-status-weekly",
        data={"is_active": "true"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


@pytest.mark.asyncio
async def test_deactivate_nonexistent(client):
    """Deactivating nonexistent template should 404."""
    resp = await client.patch(
        "/templates/nonexistent",
        data={"is_active": "false"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_and_use_template(client):
    """Upload a template and use it to create a job."""
    pptx_bytes = SAMPLE_PPTX.read_bytes()
    schema = SAMPLE_SCHEMA.read_text()

    # Upload
    resp = await client.post(
        "/templates",
        data={
            "schema": schema,
            "template_id": "test-usable",
            "display_name": "Usable Template",
            "mode": "mode1",
            "version": "2.0.0",
        },
        files={"pptx_file": ("template.pptx", pptx_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 201

    # Create a job using the uploaded template
    import asyncio

    job_resp = await client.post(
        "/jobs",
        json={
            "template_id": "test-usable",
            "mode": "mode1",
            "input_data": {
                "deck_title": "Test Upload Use",
                "report_date": "17 Feb 2026",
                "project_name": "Upload Test",
                "summary": "Testing uploaded templates.",
                "status": "Green",
                "owner": "Test",
            },
        },
    )
    assert job_resp.status_code == 202
    job_id = job_resp.json()["job_id"]

    # Poll until done
    for _ in range(20):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        if status_resp.json()["status"] in ("complete", "failed"):
            break

    final = (await client.get(f"/jobs/{job_id}")).json()
    assert final["status"] == "complete", f"Job failed: {final.get('error')}"


# --- Template Versioning Tests ---


@pytest.mark.asyncio
async def test_upload_multiple_versions(client):
    """Upload two versions of the same template_id."""
    pptx_bytes = SAMPLE_PPTX.read_bytes()
    schema = SAMPLE_SCHEMA.read_text()

    # Upload v1
    resp = await client.post(
        "/templates",
        data={
            "schema": schema,
            "template_id": "test-versioned",
            "display_name": "Versioned Template",
            "mode": "mode1",
            "version": "1.0.0",
        },
        files={"pptx_file": ("template.pptx", pptx_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 201

    # Upload v2
    resp = await client.post(
        "/templates",
        data={
            "schema": schema,
            "template_id": "test-versioned",
            "display_name": "Versioned Template v2",
            "mode": "mode1",
            "version": "2.0.0",
        },
        files={"pptx_file": ("template.pptx", pptx_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 201

    # GET /templates should return latest version
    detail_resp = await client.get("/templates/test-versioned")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["version"] == "2.0.0"
    assert detail_resp.json()["display_name"] == "Versioned Template v2"


@pytest.mark.asyncio
async def test_list_template_versions(client):
    """List all versions of a template."""
    pptx_bytes = SAMPLE_PPTX.read_bytes()
    schema = SAMPLE_SCHEMA.read_text()

    # Upload two versions
    for ver in ["1.0.0", "1.1.0"]:
        await client.post(
            "/templates",
            data={
                "schema": schema,
                "template_id": "test-versions-list",
                "display_name": f"VList v{ver}",
                "mode": "mode1",
                "version": ver,
            },
            files={"pptx_file": ("template.pptx", pptx_bytes, "application/octet-stream")},
        )

    resp = await client.get("/templates/test-versions-list/versions")
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 2
    version_strings = [v["version"] for v in versions]
    assert "1.0.0" in version_strings
    assert "1.1.0" in version_strings


@pytest.mark.asyncio
async def test_list_versions_not_found(client):
    """Listing versions for nonexistent template should 404."""
    resp = await client.get("/templates/nonexistent/versions")
    assert resp.status_code == 404
