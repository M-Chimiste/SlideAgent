from typing import Any, Optional

from pydantic import BaseModel


class SlideOutline(BaseModel):
    id: str
    job_id: str
    slide_index: int
    mode: str
    label: str
    content_json: dict[str, Any]
    layout_json: dict[str, Any]
    pptxgenjs_code: Optional[str] = None
    qa_status: Optional[str] = None
    qa_issues_json: Optional[dict[str, Any]] = None
    created_at: str
