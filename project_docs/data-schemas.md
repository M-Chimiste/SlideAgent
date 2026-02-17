# SlideAgent — Data Schemas

## Overview
All schemas are defined in Pydantic v2. LLM output schemas are enforced via Bedrock tool use (the LLM is required to call a single tool whose input matches the desired schema). API request/response schemas are used by FastAPI for validation and OpenAPI generation.

---

## Template Registry Schemas

### TemplateFieldSchema
Defines a single injectable field within a Mode 1 template.

```python
from pydantic import BaseModel
from enum import Enum
from typing import Optional

class FieldType(str, Enum):
    text = "text"
    enum = "enum"
    date = "date"
    number = "number"

class TemplateFieldSchema(BaseModel):
    shape_id: int                        # Stable shape ID from PPTX XML
    type: FieldType
    required: bool = True
    max_chars: Optional[int] = None      # Text/enum: max character length
    allowed_values: Optional[list[str]] = None  # enum type only
    date_format: Optional[str] = None    # date type: strftime format string
    truncation_allowed: bool = True      # If False, overflow is a hard error
    description: Optional[str] = None   # Human-readable hint for LLM coercion
```

### SlideSchema
Defines all injectable fields for a single slide.

```python
class SlideSchema(BaseModel):
    slide_index: int                     # 1-based slide number
    description: Optional[str] = None   # What this slide is for
    fields: dict[str, TemplateFieldSchema]  # field_name → field definition
```

### LayoutDefinition
Defines an available slide layout for Mode 2 templates.

```python
class ContentType(str, Enum):
    title = "title"
    section_divider = "section_divider"
    bullets = "bullets"
    two_column = "two_column"
    stat_callout = "stat_callout"
    quote = "quote"
    image_text = "image_text"
    table = "table"
    timeline = "timeline"
    closing = "closing"

class LayoutDefinition(BaseModel):
    layout_name: str                     # Matches slide layout name in PPTX
    slide_layout_index: int              # Index in pptx slideLayouts
    suitable_for: list[ContentType]
    fields: dict[str, TemplateFieldSchema]
    notes: Optional[str] = None         # Guidance for the DeckPlanner
```

### TemplateRecord
Top-level template registry entry.

```python
class TemplateMode(str, Enum):
    mode1 = "mode1"
    mode2 = "mode2"
    both = "both"

class TemplateRecord(BaseModel):
    template_id: str                     # Slug, e.g. "novartis-status-weekly"
    version: str                         # Semver, e.g. "1.2.0"
    display_name: str
    description: Optional[str] = None
    mode: TemplateMode
    pptx_path: str                       # S3 key or local path
    slides: Optional[dict[str, SlideSchema]] = None      # Mode 1
    layouts: Optional[dict[str, LayoutDefinition]] = None # Mode 2
    created_at: datetime
    is_active: bool = True
```

---

## Job Schemas

### JobStatus Enum
```python
class JobStatus(str, Enum):
    queued = "queued"
    parsing = "parsing"
    planning = "planning"                # Mode 2 only
    awaiting_approval = "awaiting_approval"  # Mode 2 only
    generating = "generating"
    packaging = "packaging"
    complete = "complete"
    failed = "failed"
```

### JobRecord
```python
class JobRecord(BaseModel):
    job_id: str                          # UUID4
    template_id: str
    template_version: str
    mode: TemplateMode
    status: JobStatus
    progress: int = 0                    # 0-100
    current_stage: Optional[str] = None
    input_payload: dict                  # Raw input, stored for debugging
    outline: Optional["DeckOutline"] = None  # Mode 2: set after planning
    warnings: list[str] = []
    error: Optional["JobError"] = None
    output_url: Optional[str] = None    # Presigned S3 URL when complete
    created_at: datetime
    updated_at: datetime
    ttl_expires_at: datetime

class JobError(BaseModel):
    stage: str
    message: str
    detail: Optional[str] = None
    retryable: bool
```

### JobCreateRequest (API)
```python
class JobCreateRequest(BaseModel):
    template_id: str
    mode: TemplateMode
    input_data: dict                     # Mode 1: field map. Mode 2: brief fields.
    options: Optional["JobOptions"] = None

class JobOptions(BaseModel):
    layout_preference: Optional[str] = None  # "auto" | "content-heavy" | "visual-heavy"
    slide_count_min: Optional[int] = None
    slide_count_max: Optional[int] = None
```

### JobStatusResponse (API)
```python
class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: int
    current_stage: Optional[str]
    outline: Optional["DeckOutline"]     # Populated in awaiting_approval
    warnings: list[str]
    error: Optional[JobError]
    output_url: Optional[str]
    created_at: datetime
    updated_at: datetime
```

### OutlineApprovalRequest (API, Mode 2 only)
```python
class OutlineApprovalRequest(BaseModel):
    job_id: str
    approved: bool
    revised_outline: Optional["DeckOutline"] = None  # If approved with edits
    revision_instructions: Optional[str] = None      # If not approved: re-plan with these
```

---

## Agent I/O Schemas (LLM Tool Use)

### InputCoercionInput / Output (LLM call in InputParser)
```python
class CoercionInput(BaseModel):
    raw_fields: dict[str, str]           # Field name → raw value from user input
    schema_fields: dict[str, dict]       # Schema definition for each field
    mismatched_pairs: list[tuple[str, str]]  # (raw_name, schema_name) pairs to resolve

class CoercedField(BaseModel):
    schema_field_name: str
    coerced_value: str
    confidence: float                    # 0-1
    note: Optional[str] = None

class CoercionOutput(BaseModel):
    coerced_fields: list[CoercedField]
    unresolvable_fields: list[str]       # Raw field names the LLM couldn't map
```

### DeckOutline (LLM output from DeckPlanner, also used in approval)
```python
class SlideOutlineEntry(BaseModel):
    slide_number: int
    layout_name: str                     # Must match a layout in the template's layout library
    title: str
    content_summary: str                 # 1-2 sentences describing slide content
    content_type: ContentType

class DeckOutline(BaseModel):
    deck_title: str
    audience: str
    narrative_arc: str                   # 2-3 sentence description of the overall story
    slides: list[SlideOutlineEntry]
    total_slides: int
```

### SlideContent (LLM output from ContentGenerator, per slide)
```python
class SlideFieldContent(BaseModel):
    field_name: str
    content: str                         # Final text to inject

class SlideContent(BaseModel):
    slide_number: int
    layout_name: str
    fields: list[SlideFieldContent]
```

### CoherenceCheckOutput (LLM output from CoherenceCheck)
```python
class CoherenceIssue(BaseModel):
    slide_number: int
    issue_type: str                      # "repetition" | "tonal_drift" | "inconsistency" | "other"
    description: str
    severity: str                        # "minor" | "major"
    suggested_fix: Optional[str] = None

class CoherenceCheckOutput(BaseModel):
    issues: list[CoherenceIssue]
    overall_coherence_score: float       # 0-1, for logging
    summary: str
```

---

## PPTX Pipeline Internal Schemas

### InjectionTarget
Maps a resolved field value to its XML location.

```python
class InjectionTarget(BaseModel):
    slide_index: int                     # 1-based
    shape_id: int
    field_name: str
    value: str                           # Final validated value
    was_truncated: bool = False
    original_value: Optional[str] = None  # If truncated, the original
```

### PipelineResult
Returned by the full PPTX pipeline on completion.

```python
class PipelineResult(BaseModel):
    success: bool
    output_path: str
    injection_targets: list[InjectionTarget]
    warnings: list[str]
    error: Optional[str] = None
    staging_dir: Optional[str] = None   # Preserved on failure for debugging
```

---

## Template Analysis (Dev Tool Output)

### ShapeMap
Output of `scripts/analyze_template.py` — used to author template schemas.

```python
class ShapeInfo(BaseModel):
    shape_id: int
    shape_name: str
    slide_index: int
    shape_type: str
    has_text: bool
    current_text: Optional[str] = None  # First 100 chars of current content
    position: dict                       # {"x": float, "y": float, "w": float, "h": float} in inches
    placeholder_type: Optional[str] = None

class ShapeMap(BaseModel):
    template_path: str
    slide_count: int
    shapes: list[ShapeInfo]
```
