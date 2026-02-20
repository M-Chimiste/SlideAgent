from typing import Any, List, Optional

from pydantic import BaseModel


class JobRecord(BaseModel):
    id: str
    template_id: str
    instructions: Optional[str] = None
    config_json: Optional[dict[str, Any]] = None
    status: str
    progress: float
    qa_rounds: int
    warnings: List[dict[str, Any]]
    result_file: Optional[str] = None
    preview_dir: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
