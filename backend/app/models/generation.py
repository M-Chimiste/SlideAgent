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


class DeckBlueprint(BaseModel):
    deck_title: str
    audience: str = "Executive audience"
    core_thesis: str = "The deck should move leaders from context to decision."
    target_slide_count: int = 8
    story_beats: list[dict[str, Any]] = Field(default_factory=list)
    section_plan: list[dict[str, Any]] = Field(default_factory=list)
    archetype_sequence: list[str] = Field(default_factory=list)
    source_coverage_map: dict[str, list[str]] = Field(default_factory=dict)


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
    archetype: Optional[str] = None
    narrative_role: Optional[str] = None
    exhibit_spec: Optional[dict[str, Any]] = None
    diagram_spec: Optional[dict[str, Any]] = None
    design_intent: Optional[str] = None
    source_refs: List[str] = Field(default_factory=list)


class DeckSpec(BaseModel):
    deck_title: str
    audience: str = "Executive audience"
    goal: str = "Communicate a clear recommendation."
    narrative_arc: str = "Situation -> Complication -> Resolution"
    slides: List[GeneratedSlideSpec]
    blueprint: Optional[DeckBlueprint] = None
