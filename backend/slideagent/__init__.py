"""SlideAgent — Programmatic API for AI-powered PowerPoint generation.

This package provides a Python-first interface to SlideAgent's core services.
Use it to generate decks without going through the HTTP layer.

Quick start:

    from slideagent import SlideAgentClient

    client = SlideAgentClient(
        templates_dir="templates",
        storage_base=".",
        staging_dir=".data/staging",
    )
    await client.initialize()

    # Mode 1: Fill a template with structured data
    result = await client.generate_deck(
        template_id="novartis-status-weekly",
        mode="mode1",
        input_data={
            "deck_title": "Weekly Status Report",
            "report_date": "17 Feb 2026",
            "project_name": "Ariadne",
            "summary": "On track.",
            "status": "Green",
            "owner": "Christian",
        },
    )
    print(result.output_path)  # Path to generated PPTX

    # Mode 2: Generate from a brief
    result = await client.generate_deck(
        template_id="corporate-deck",
        mode="mode2",
        input_data={
            "title": "Q1 Strategy Review",
            "audience": "Leadership team",
            "brief": "Cover quarterly results and next steps.",
        },
    )
"""

from slideagent.client import SlideAgentClient
from slideagent.models import GenerateResult, DeckMode

__all__ = ["SlideAgentClient", "GenerateResult", "DeckMode"]
__version__ = "0.1.0"
