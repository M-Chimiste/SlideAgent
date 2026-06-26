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
    final_qa_passed: Optional[bool] = None
    final_review_passed: Optional[bool] = None
    unresolved_critical_count: int = 0
    unresolved_actionable_issue_count: int = 0
    unresolved_editing_contract_count: int = 0
    rendered_slide_audit: Optional[dict[str, Any]] = None
    visual_review: Optional[dict[str, Any]] = None
    template_clone_edit: Optional[dict[str, Any]] = None
    template_frame_map: Optional[dict[str, Any]] = None
    template_deviation_log: Optional[dict[str, Any]] = None
