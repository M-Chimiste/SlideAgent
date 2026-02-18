"""Tests for Mode 2 API endpoints.

These tests mock the DeckPlanner and ContentGenerator since Bedrock isn't
available in test environments.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.models.schemas import (
    DeckOutline,
    SlideContent,
    SlideFieldContent,
    SlideOutlineEntry,
)
from app.models.templates import ContentType

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"

MOCK_OUTLINE = DeckOutline(
    deck_title="Test Strategy Deck",
    audience="Leadership team",
    narrative_arc="Context, analysis, recommendations",
    slides=[
        SlideOutlineEntry(
            slide_number=1,
            layout_name="title_slide",
            title="Q1 Strategy",
            content_summary="Opening title slide",
            content_type=ContentType.title,
        ),
        SlideOutlineEntry(
            slide_number=2,
            layout_name="content_bullets",
            title="Market Analysis",
            content_summary="Key market findings",
            content_type=ContentType.bullets,
        ),
        SlideOutlineEntry(
            slide_number=3,
            layout_name="closing",
            title="Next Steps",
            content_summary="Action items",
            content_type=ContentType.closing,
        ),
    ],
    total_slides=3,
)

MOCK_SLIDE_CONTENTS = [
    SlideContent(
        slide_number=1,
        layout_name="title_slide",
        fields=[
            SlideFieldContent(field_name="deck_title", content="Q1 Strategy"),
            SlideFieldContent(field_name="subtitle", content="Leadership Review"),
        ],
    ),
    SlideContent(
        slide_number=2,
        layout_name="content_bullets",
        fields=[
            SlideFieldContent(field_name="slide_title", content="Market Analysis"),
            SlideFieldContent(field_name="body", content="Revenue up 15%\nNew markets identified\nCompetitor analysis complete"),
        ],
    ),
    SlideContent(
        slide_number=3,
        layout_name="closing",
        fields=[
            SlideFieldContent(field_name="closing_title", content="Thank You"),
        ],
    ),
]


@pytest.fixture
def settings(tmp_path):
    return Settings(
        sqlite_path=str(tmp_path / "jobs.db"),
        templates_dir=str(TEMPLATES_DIR),
        staging_dir=str(tmp_path / "staging"),
        outputs_dir=str(tmp_path / "outputs"),
        bedrock_region="",  # Disable real Bedrock
    )


@pytest.fixture
async def client(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        # Inject mock Mode 2 services
        from app.services.deck_planner import DeckPlanner
        from app.services.content_generator import ContentGenerator

        mock_planner = AsyncMock(spec=DeckPlanner)
        mock_planner.plan_deck = AsyncMock(return_value=MOCK_OUTLINE)
        mock_planner.replan_deck = AsyncMock(return_value=MOCK_OUTLINE)
        app.state.deck_planner = mock_planner

        mock_generator = AsyncMock(spec=ContentGenerator)
        mock_generator.generate_all = AsyncMock(return_value=MOCK_SLIDE_CONTENTS)
        app.state.content_generator = mock_generator

        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_create_mode2_job(client):
    """Creating a Mode 2 job should return 202 and start planning."""
    resp = await client.post(
        "/jobs",
        json={
            "template_id": "corporate-deck",
            "mode": "mode2",
            "input_data": {
                "title": "Q1 Strategy Review",
                "audience": "Executive team",
                "key_messages": ["Revenue growth", "Market expansion"],
                "tone": "professional",
            },
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "queued"
    assert "job_id" in data


@pytest.mark.asyncio
async def test_mode2_planning_to_approval(client):
    """Mode 2 job should transition to awaiting_approval after planning."""
    resp = await client.post(
        "/jobs",
        json={
            "template_id": "corporate-deck",
            "mode": "mode2",
            "input_data": {
                "title": "Strategy Deck",
                "audience": "Leadership",
            },
        },
    )
    job_id = resp.json()["job_id"]

    # Poll until awaiting_approval
    for _ in range(30):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        status = status_resp.json()["status"]
        if status in ("awaiting_approval", "failed"):
            break

    final = (await client.get(f"/jobs/{job_id}")).json()
    assert final["status"] == "awaiting_approval", f"Expected awaiting_approval, got: {final}"
    assert final["outline"] is not None
    assert final["outline"]["deck_title"] == "Test Strategy Deck"
    assert len(final["outline"]["slides"]) == 3


@pytest.mark.asyncio
async def test_approve_outline(client):
    """Approving an outline should transition to generating and eventually complete."""
    # Create job and wait for approval
    resp = await client.post(
        "/jobs",
        json={
            "template_id": "corporate-deck",
            "mode": "mode2",
            "input_data": {"title": "Test", "audience": "Testers"},
        },
    )
    job_id = resp.json()["job_id"]

    for _ in range(30):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        if status_resp.json()["status"] == "awaiting_approval":
            break

    # Approve
    approve_resp = await client.post(
        f"/jobs/{job_id}/approve",
        json={"approved": True},
    )
    assert approve_resp.status_code == 200

    # Poll until complete
    for _ in range(30):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        status = status_resp.json()["status"]
        if status in ("complete", "failed"):
            break

    final = (await client.get(f"/jobs/{job_id}")).json()
    assert final["status"] == "complete", f"Job failed: {final.get('error')}"
    assert final["progress"] == 100


@pytest.mark.asyncio
async def test_approve_with_revised_outline(client):
    """Approving with a revised outline should update the stored outline."""
    resp = await client.post(
        "/jobs",
        json={
            "template_id": "corporate-deck",
            "mode": "mode2",
            "input_data": {"title": "Test", "audience": "Testers"},
        },
    )
    job_id = resp.json()["job_id"]

    for _ in range(30):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        if status_resp.json()["status"] == "awaiting_approval":
            break

    # Approve with revised outline
    revised = MOCK_OUTLINE.model_dump()
    revised["deck_title"] = "Revised Title"
    approve_resp = await client.post(
        f"/jobs/{job_id}/approve",
        json={"approved": True, "revised_outline": revised},
    )
    assert approve_resp.status_code == 200


@pytest.mark.asyncio
async def test_reject_outline_replans(client):
    """Rejecting an outline should re-run planning."""
    resp = await client.post(
        "/jobs",
        json={
            "template_id": "corporate-deck",
            "mode": "mode2",
            "input_data": {"title": "Test", "audience": "Testers"},
        },
    )
    job_id = resp.json()["job_id"]

    for _ in range(30):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        if status_resp.json()["status"] == "awaiting_approval":
            break

    # Reject with revision instructions
    reject_resp = await client.post(
        f"/jobs/{job_id}/approve",
        json={"approved": False, "revision_instructions": "Add more technical depth"},
    )
    assert reject_resp.status_code == 200

    # Should go back to planning and then awaiting_approval again
    for _ in range(30):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        status = status_resp.json()["status"]
        if status in ("awaiting_approval", "failed"):
            break

    final = (await client.get(f"/jobs/{job_id}")).json()
    assert final["status"] == "awaiting_approval"


@pytest.mark.asyncio
async def test_reject_without_instructions_fails(client):
    """Rejecting without revision_instructions should return 400."""
    resp = await client.post(
        "/jobs",
        json={
            "template_id": "corporate-deck",
            "mode": "mode2",
            "input_data": {"title": "Test", "audience": "Testers"},
        },
    )
    job_id = resp.json()["job_id"]

    for _ in range(30):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        if status_resp.json()["status"] == "awaiting_approval":
            break

    reject_resp = await client.post(
        f"/jobs/{job_id}/approve",
        json={"approved": False},
    )
    assert reject_resp.status_code == 400


@pytest.mark.asyncio
async def test_approve_wrong_state_fails(client):
    """Approving a job not in awaiting_approval state should return 409."""
    # Create a Mode 1 job (will be in queued/complete state)
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
                "status": "Green",
                "owner": "Tester",
            },
        },
    )
    job_id = resp.json()["job_id"]

    # Wait for it to finish
    for _ in range(20):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        if status_resp.json()["status"] in ("complete", "failed"):
            break

    # Try to approve
    approve_resp = await client.post(
        f"/jobs/{job_id}/approve",
        json={"approved": True},
    )
    assert approve_resp.status_code == 409


@pytest.mark.asyncio
async def test_approve_nonexistent_job(client):
    """Approving a nonexistent job should return 404."""
    resp = await client.post(
        "/jobs/nonexistent/approve",
        json={"approved": True},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mode2_full_e2e_with_download(client):
    """Full E2E: create → plan → approve → generate → download PPTX."""
    import io
    from pptx import Presentation

    # Create Mode 2 job
    resp = await client.post(
        "/jobs",
        json={
            "template_id": "corporate-deck",
            "mode": "mode2",
            "input_data": {
                "title": "Full E2E Test",
                "audience": "QA Team",
                "key_messages": ["Feature A", "Feature B"],
                "tone": "professional",
            },
        },
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # Wait for planning
    for _ in range(30):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        if status_resp.json()["status"] == "awaiting_approval":
            break

    assert (await client.get(f"/jobs/{job_id}")).json()["status"] == "awaiting_approval"

    # Approve
    await client.post(f"/jobs/{job_id}/approve", json={"approved": True})

    # Wait for completion
    for _ in range(30):
        await asyncio.sleep(0.1)
        status_resp = await client.get(f"/jobs/{job_id}")
        status = status_resp.json()["status"]
        if status in ("complete", "failed"):
            break

    final = (await client.get(f"/jobs/{job_id}")).json()
    assert final["status"] == "complete", f"Job failed: {final.get('error')}"

    # Download
    dl_resp = await client.get(f"/jobs/{job_id}/download")
    assert dl_resp.status_code == 200
    assert len(dl_resp.content) > 0

    # Verify PPTX
    prs = Presentation(io.BytesIO(dl_resp.content))
    assert len(prs.slides) == 3  # 3 slides from mock outline
