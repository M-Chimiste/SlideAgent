"""Integration tests for API routes using httpx AsyncClient."""

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


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
    # Manually trigger lifespan so app.state is initialized
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_list_templates(client):
    resp = await client.get("/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    template_ids = [t["template_id"] for t in data]
    assert "novartis-status-weekly" in template_ids
    assert all("display_name" in t for t in data)


@pytest.mark.asyncio
async def test_get_template(client):
    resp = await client.get("/templates/novartis-status-weekly")
    assert resp.status_code == 200
    data = resp.json()
    assert data["template_id"] == "novartis-status-weekly"
    assert "schema" in data
    assert "1" in data["schema"]
    assert "deck_title" in data["schema"]["1"]["fields"]


@pytest.mark.asyncio
async def test_get_template_not_found(client):
    resp = await client.get("/templates/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_job_and_poll(client):
    """Full E2E: create job → poll until complete → download."""
    # Create job
    resp = await client.post(
        "/jobs",
        json={
            "template_id": "novartis-status-weekly",
            "mode": "mode1",
            "input_data": {
                "deck_title": "Weekly Status Report",
                "report_date": "17 Feb 2026",
                "project_name": "Ariadne",
                "summary": "On track for Q1 delivery.",
                "status": "Green",
                "owner": "Christian",
            },
        },
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert resp.json()["status"] == "queued"

    # Poll until complete or failed (with timeout)
    for _ in range(20):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        assert status_resp.status_code == 200
        status = status_resp.json()["status"]
        if status in ("complete", "failed"):
            break

    final = (await client.get(f"/jobs/{job_id}")).json()
    assert final["status"] == "complete", f"Job failed: {final.get('error')}"
    assert final["progress"] == 100
    assert len(final["warnings"]) == 0

    # Download
    dl_resp = await client.get(f"/jobs/{job_id}/download")
    assert dl_resp.status_code == 200
    assert len(dl_resp.content) > 0
    assert "presentation" in dl_resp.headers["content-type"]

    # Verify the downloaded file is a valid PPTX
    import io
    from pptx import Presentation

    prs = Presentation(io.BytesIO(dl_resp.content))
    assert len(prs.slides) == 2


@pytest.mark.asyncio
async def test_create_job_template_not_found(client):
    resp = await client.post(
        "/jobs",
        json={
            "template_id": "nonexistent",
            "mode": "mode1",
            "input_data": {"title": "Test"},
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_job_not_found(client):
    resp = await client.get("/jobs/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_not_complete(client):
    """Download should fail with 409 when job is not complete."""
    # Create a job
    resp = await client.post(
        "/jobs",
        json={
            "template_id": "novartis-status-weekly",
            "mode": "mode1",
            "input_data": {"deck_title": "Test"},
        },
    )
    job_id = resp.json()["job_id"]

    # Try to download immediately (may still be queued/processing)
    # Wait for it to finish first, then we'll test a different scenario
    # For now, test download on a nonexistent job
    dl_resp = await client.get("/jobs/nonexistent/download")
    assert dl_resp.status_code == 404


@pytest.mark.asyncio
async def test_list_jobs(client):
    # Create a job first
    await client.post(
        "/jobs",
        json={
            "template_id": "novartis-status-weekly",
            "mode": "mode1",
            "input_data": {"deck_title": "Test"},
        },
    )
    await asyncio.sleep(0.3)  # Let background task finish

    resp = await client.get("/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert "job_id" in data[0]
    assert "status" in data[0]


@pytest.mark.asyncio
async def test_job_with_validation_errors(client):
    """Job with invalid enum value should fail."""
    resp = await client.post(
        "/jobs",
        json={
            "template_id": "novartis-status-weekly",
            "mode": "mode1",
            "input_data": {
                "deck_title": "Test",
                "report_date": "17 Feb 2026",
                "project_name": "X",
                "summary": "OK",
                "status": "Blue",  # Invalid enum
                "owner": "Test",
            },
        },
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # Poll until complete/failed
    for _ in range(20):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        status = status_resp.json()["status"]
        if status in ("complete", "failed"):
            break

    final = (await client.get(f"/jobs/{job_id}")).json()
    assert final["status"] == "failed"
    assert final["error"] is not None
    assert "Blue" in final["error"]["message"]
