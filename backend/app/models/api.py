from typing import Any, List, Optional

from pydantic import BaseModel

from app.models.job import JobRecord
from app.models.template import TemplateProfile


class TemplateListResponse(BaseModel):
    templates: List[TemplateProfile]


class JobListResponse(BaseModel):
    jobs: List[JobRecord]


class JobStatusResponse(BaseModel):
    job: JobRecord
    warnings: List[dict[str, Any]]
    preview_images: Optional[List[str]] = None
