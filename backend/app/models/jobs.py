from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class JobStatus(str, Enum):
    queued = "queued"
    parsing = "parsing"
    planning = "planning"
    awaiting_approval = "awaiting_approval"
    generating = "generating"
    packaging = "packaging"
    complete = "complete"
    failed = "failed"


class JobError(BaseModel):
    stage: str
    message: str
    detail: Optional[str] = None
    retryable: bool


class JobOptions(BaseModel):
    layout_preference: Optional[str] = None
    slide_count_min: Optional[int] = None
    slide_count_max: Optional[int] = None


class JobRecord(BaseModel):
    job_id: str
    template_id: str
    template_version: str
    mode: str
    status: JobStatus
    progress: int = 0
    current_stage: Optional[str] = None
    input_payload: dict
    outline: Optional[dict] = None
    warnings: list[str] = []
    error: Optional[JobError] = None
    output_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    ttl_expires_at: datetime


class JobCreateRequest(BaseModel):
    template_id: str
    mode: str
    input_data: dict
    options: Optional[JobOptions] = None


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: int
    current_stage: Optional[str]
    outline: Optional[dict]
    warnings: list[str]
    error: Optional[JobError]
    output_url: Optional[str]
    created_at: datetime
    updated_at: datetime


class OutlineApprovalRequest(BaseModel):
    approved: bool
    revised_outline: Optional[dict] = None
    revision_instructions: Optional[str] = None
