"""Shared test fixtures."""

from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
SAMPLE_TEMPLATE = TEMPLATES_DIR / "novartis-status-weekly" / "template.pptx"


@pytest.fixture
def templates_dir():
    return TEMPLATES_DIR


@pytest.fixture
def sample_template_path():
    return SAMPLE_TEMPLATE
