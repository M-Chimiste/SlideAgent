"""Tests for Mode 2 data models."""

import pytest
from pydantic import ValidationError

from app.models.jobs import OutlineApprovalRequest
from app.models.schemas import (
    CoherenceCheckOutput,
    CoherenceIssue,
    DeckOutline,
    SlideContent,
    SlideFieldContent,
    SlideOutlineEntry,
)
from app.models.templates import ContentType


def test_slide_outline_entry():
    entry = SlideOutlineEntry(
        slide_number=1,
        layout_name="title_slide",
        title="Welcome",
        content_summary="Opening slide with deck title",
        content_type=ContentType.title,
    )
    assert entry.slide_number == 1
    assert entry.content_type == ContentType.title


def test_deck_outline():
    outline = DeckOutline(
        deck_title="Q1 Strategy",
        audience="Executive team",
        narrative_arc="Context, analysis, recommendations",
        slides=[
            SlideOutlineEntry(
                slide_number=1,
                layout_name="title_slide",
                title="Q1 Strategy",
                content_summary="Title slide",
                content_type=ContentType.title,
            ),
            SlideOutlineEntry(
                slide_number=2,
                layout_name="content_bullets",
                title="Key Findings",
                content_summary="Summary of market analysis",
                content_type=ContentType.bullets,
            ),
        ],
        total_slides=2,
    )
    assert outline.total_slides == 2
    assert len(outline.slides) == 2
    assert outline.slides[0].layout_name == "title_slide"


def test_deck_outline_serialization():
    outline = DeckOutline(
        deck_title="Test",
        audience="Developers",
        narrative_arc="Brief arc",
        slides=[
            SlideOutlineEntry(
                slide_number=1,
                layout_name="title_slide",
                title="Title",
                content_summary="Opening",
                content_type=ContentType.title,
            ),
        ],
        total_slides=1,
    )
    data = outline.model_dump()
    restored = DeckOutline.model_validate(data)
    assert restored.deck_title == "Test"
    assert restored.slides[0].title == "Title"


def test_slide_field_content():
    fc = SlideFieldContent(field_name="slide_title", content="Market Overview")
    assert fc.field_name == "slide_title"


def test_slide_content():
    sc = SlideContent(
        slide_number=2,
        layout_name="content_bullets",
        fields=[
            SlideFieldContent(field_name="slide_title", content="Key Points"),
            SlideFieldContent(field_name="body", content="Point 1\nPoint 2\nPoint 3"),
        ],
    )
    assert sc.slide_number == 2
    assert len(sc.fields) == 2


def test_coherence_issue():
    issue = CoherenceIssue(
        slide_number=3,
        issue_type="repetition",
        description="Same point repeated from slide 2",
        severity="minor",
        suggested_fix="Consolidate into slide 2",
    )
    assert issue.severity == "minor"
    assert issue.suggested_fix is not None


def test_coherence_check_output():
    output = CoherenceCheckOutput(
        issues=[
            CoherenceIssue(
                slide_number=3,
                issue_type="tonal_drift",
                description="Tone shifts to informal",
                severity="major",
            ),
        ],
        overall_coherence_score=0.85,
        summary="Generally coherent with one tonal issue",
    )
    assert output.overall_coherence_score == 0.85
    assert len(output.issues) == 1


def test_coherence_score_bounds():
    with pytest.raises(ValidationError):
        CoherenceCheckOutput(
            issues=[], overall_coherence_score=1.5, summary="Invalid"
        )

    with pytest.raises(ValidationError):
        CoherenceCheckOutput(
            issues=[], overall_coherence_score=-0.1, summary="Invalid"
        )


def test_outline_approval_approve():
    req = OutlineApprovalRequest(approved=True)
    assert req.approved
    assert req.revised_outline is None
    assert req.revision_instructions is None


def test_outline_approval_approve_with_edits():
    req = OutlineApprovalRequest(
        approved=True,
        revised_outline={
            "deck_title": "Updated Title",
            "audience": "Team",
            "narrative_arc": "Updated arc",
            "slides": [],
            "total_slides": 0,
        },
    )
    assert req.approved
    assert req.revised_outline is not None


def test_outline_approval_reject():
    req = OutlineApprovalRequest(
        approved=False,
        revision_instructions="Add more technical depth",
    )
    assert not req.approved
    assert req.revision_instructions == "Add more technical depth"
