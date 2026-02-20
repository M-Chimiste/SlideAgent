from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.brand import BrandDNA


class SlideField(BaseModel):
    id: str
    type: str
    location: str
    required: bool = False
    max_chars: Optional[int] = None
    values: Optional[List[str]] = None
    format: Optional[str] = None
    render: Optional[str] = None
    color_map: Optional[dict[str, str]] = None
    max_items: Optional[int] = None
    max_chars_per_item: Optional[int] = None


class SlideSchema(BaseModel):
    fields: List[SlideField]


class SlideSpec(BaseModel):
    index: int
    mode: str
    label: str
    layout_name: Optional[str] = None
    schema: Optional[SlideSchema] = None
    intent: Optional[str] = None
    content_category: Optional[str] = None
    visual_guidance: Optional[str] = None
    classification_reason: Optional[str] = None


class TemplateProfile(BaseModel):
    id: str
    name: str
    type: str
    brand: BrandDNA
    slides: List[SlideSpec]
    source_file: str
    created_at: str
    updated_at: str


class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    slides: Optional[List[SlideSpec]] = None
