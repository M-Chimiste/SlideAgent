from typing import Optional

from pydantic import BaseModel, Field

from .templates import ContentType


# --- InputParser LLM I/O ---


class CoercionInput(BaseModel):
    raw_fields: dict[str, str]
    schema_fields: dict[str, dict]
    mismatched_pairs: list[tuple[str, str]]


class CoercedField(BaseModel):
    schema_field_name: str
    coerced_value: str
    confidence: float
    note: Optional[str] = None


class CoercionOutput(BaseModel):
    coerced_fields: list[CoercedField]
    unresolvable_fields: list[str]


# --- PPTX Pipeline ---


class InjectionTarget(BaseModel):
    slide_index: int
    shape_id: int
    field_name: str
    value: str
    was_truncated: bool = False
    original_value: Optional[str] = None


class PipelineResult(BaseModel):
    success: bool
    output_path: str
    injection_targets: list[InjectionTarget]
    warnings: list[str]
    error: Optional[str] = None
    staging_dir: Optional[str] = None


# --- Mode 2: DeckPlanner LLM I/O ---


class SlideOutlineEntry(BaseModel):
    slide_number: int
    layout_name: str
    title: str
    content_summary: str
    content_type: ContentType


class DeckOutline(BaseModel):
    deck_title: str
    audience: str
    narrative_arc: str
    slides: list[SlideOutlineEntry]
    total_slides: int


# --- Mode 2: ContentGenerator LLM I/O ---


class SlideFieldContent(BaseModel):
    field_name: str
    content: str


class SlideContent(BaseModel):
    slide_number: int
    layout_name: str
    fields: list[SlideFieldContent]


# --- Mode 2: CoherenceCheck LLM I/O ---


class CoherenceIssue(BaseModel):
    slide_number: int
    issue_type: str = Field(description="repetition | tonal_drift | inconsistency | other")
    description: str
    severity: str = Field(description="minor | major")
    suggested_fix: Optional[str] = None


class CoherenceCheckOutput(BaseModel):
    issues: list[CoherenceIssue]
    overall_coherence_score: float = Field(ge=0.0, le=1.0)
    summary: str
