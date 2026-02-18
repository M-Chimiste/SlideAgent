from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class FieldType(str, Enum):
    text = "text"
    enum = "enum"
    date = "date"
    number = "number"


class TemplateFieldSchema(BaseModel):
    shape_id: int
    type: FieldType
    required: bool = True
    max_chars: Optional[int] = None
    allowed_values: Optional[list[str]] = None
    date_format: Optional[str] = None
    truncation_allowed: bool = True
    description: Optional[str] = None


class SlideSchema(BaseModel):
    slide_index: int
    description: Optional[str] = None
    fields: dict[str, TemplateFieldSchema]


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
    layout_name: str
    slide_layout_index: int
    suitable_for: list[ContentType]
    fields: dict[str, TemplateFieldSchema]
    notes: Optional[str] = None


class TemplateMode(str, Enum):
    mode1 = "mode1"
    mode2 = "mode2"
    both = "both"


class TemplateRecord(BaseModel):
    template_id: str
    version: str
    display_name: str
    description: Optional[str] = None
    mode: TemplateMode
    pptx_path: str
    slides: Optional[dict[str, SlideSchema]] = None
    layouts: Optional[dict[str, LayoutDefinition]] = None
    created_at: datetime
    is_active: bool = True
