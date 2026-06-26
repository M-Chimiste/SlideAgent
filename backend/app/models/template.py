from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

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
    model_config = ConfigDict(populate_by_name=True)

    index: int
    mode: str
    label: str
    layout_name: Optional[str] = None
    layout_index: Optional[int] = None
    slide_schema: Optional[SlideSchema] = Field(default=None, alias="schema")
    intent: Optional[str] = None
    content_category: Optional[str] = None
    visual_guidance: Optional[str] = None
    classification_reason: Optional[str] = None


class PlaceholderSpec(BaseModel):
    """A placeholder slot on a template slide layout."""

    idx: int
    ph_type: str
    name: str = ""
    bounds: Optional[dict[str, float]] = None


class LayoutSpec(BaseModel):
    """A reusable slide layout from the uploaded template's layout library."""

    index: int
    name: str
    role: str
    placeholders: List[PlaceholderSpec] = Field(default_factory=list)
    text_slot_count: int = 0
    media_slot_count: int = 0
    has_title: bool = False


class TemplateProfile(BaseModel):
    id: str
    name: str
    type: str
    brand: BrandDNA
    slides: List[SlideSpec]
    source_file: str
    created_at: str
    updated_at: str
    layout_library: List[LayoutSpec] = Field(default_factory=list)


class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    slides: Optional[List[SlideSpec]] = None
