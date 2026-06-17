from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class GenerationMode(str, Enum):
    freeform = "freeform"
    brand = "brand"
    strict = "strict"


class QAStatus(str, Enum):
    pending = "pending"
    pass_ = "pass"
    warning = "warning"
    fail = "fail"


class ContentBlock(BaseModel):
    type: str
    body: list[Any] = Field(default_factory=list)
    annotations: list[str] = Field(default_factory=list)
    callouts: list[str] = Field(default_factory=list)


class SlideQAState(BaseModel):
    consulting_status: str = QAStatus.pending
    visual_status: str = QAStatus.pending
    issues: list[dict[str, Any]] = Field(default_factory=list)


class GeneratedSlideSpec(BaseModel):
    slide_number: int
    slide_type: str
    action_title: str
    subheading: str = ""
    content_blocks: List[ContentBlock] = Field(default_factory=list)
    chart_spec: Optional[dict[str, Any]] = None
    sources: List[str] = Field(default_factory=list)
    speaker_notes: str = ""
    qa: SlideQAState = Field(default_factory=SlideQAState)


class DeckSpec(BaseModel):
    deck_title: str
    audience: str = "Executive audience"
    goal: str = "Communicate a clear recommendation."
    narrative_arc: str = "Situation -> Complication -> Resolution"
    slides: List[GeneratedSlideSpec]
