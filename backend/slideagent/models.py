"""Public API models for the SlideAgent programmatic interface."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class DeckMode(str, Enum):
    mode1 = "mode1"
    mode2 = "mode2"


class GenerateResult(BaseModel):
    """Result of a deck generation operation."""

    success: bool
    output_path: str = ""
    warnings: list[str] = []
    error: Optional[str] = None

    # Mode 2 only: the outline that was generated/approved
    outline: Optional[dict] = None
