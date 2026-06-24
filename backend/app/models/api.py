from typing import Any, List, Optional

from pydantic import BaseModel

from app.models.job import JobRecord
from app.models.qa import QAIssue
from app.models.template import TemplateProfile


class TemplateListResponse(BaseModel):
    templates: List[TemplateProfile]


class JobListResponse(BaseModel):
    jobs: List[JobRecord]


class JobStatusResponse(BaseModel):
    job: JobRecord
    warnings: List[dict[str, Any]]
    preview_images: Optional[List[str]] = None
    qa_summary: Optional[dict[str, Any]] = None
    qa_issues: Optional[List[QAIssue]] = None
    qa_history: Optional[List[dict[str, Any]]] = None
    planning_summary: Optional[dict[str, Any]] = None
