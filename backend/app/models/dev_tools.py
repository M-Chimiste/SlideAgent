from typing import Optional

from pydantic import BaseModel


class ShapeInfo(BaseModel):
    shape_id: int
    shape_name: str
    slide_index: int
    shape_type: str
    has_text: bool
    current_text: Optional[str] = None
    position: dict
    placeholder_type: Optional[str] = None


class ShapeMap(BaseModel):
    template_path: str
    slide_count: int
    shapes: list[ShapeInfo]
