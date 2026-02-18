"""Job routes: create, status, list, approve."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.config import Settings
from app.dependencies import (
    get_constraint_validator,
    get_content_generator,
    get_deck_planner,
    get_input_parser,
    get_job_store,
    get_pipeline,
    get_settings,
    get_template_registry,
)
from app.models.jobs import (
    JobCreateRequest,
    JobCreateResponse,
    JobRecord,
    JobStatus,
    JobStatusResponse,
    OutlineApprovalRequest,
)
from app.models.schemas import DeckOutline
from app.services.constraint_validator import ConstraintValidator
from app.services.content_generator import ContentGenerator
from app.services.deck_planner import DeckPlanner
from app.services.input_parser import InputParser
from app.services.job_runner import JobRunner
from app.services.pptx_pipeline import PPTXPipeline
from app.services.template_registry import TemplateRegistry
from app.store.sqlite import SQLiteJobStore

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=202, response_model=JobCreateResponse)
async def create_job(
    request: JobCreateRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    job_store: SQLiteJobStore = Depends(get_job_store),
    registry: TemplateRegistry = Depends(get_template_registry),
    input_parser: InputParser = Depends(get_input_parser),
    validator: ConstraintValidator = Depends(get_constraint_validator),
    pipeline: PPTXPipeline = Depends(get_pipeline),
    deck_planner: Optional[DeckPlanner] = Depends(get_deck_planner),
    content_generator: Optional[ContentGenerator] = Depends(get_content_generator),
):
    # Validate template exists
    template = registry.get_template(request.template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template '{request.template_id}' not found")

    # Validate mode matches template
    if request.mode not in (template.mode, "both"):
        if template.mode != "both" and request.mode != template.mode:
            raise HTTPException(
                status_code=400,
                detail=f"Template '{request.template_id}' does not support mode '{request.mode}'"
            )

    # Mode 2 requires Bedrock
    if request.mode == "mode2" and deck_planner is None:
        raise HTTPException(
            status_code=503,
            detail="Mode 2 requires Bedrock (LLM service not configured)"
        )

    now = datetime.now(tz=timezone.utc)
    job_id = str(uuid.uuid4())

    job = JobRecord(
        job_id=job_id,
        template_id=request.template_id,
        template_version=template.version,
        mode=request.mode,
        status=JobStatus.queued,
        current_stage="queued",
        input_payload=request.input_data,
        created_at=now,
        updated_at=now,
        ttl_expires_at=now + timedelta(hours=settings.max_job_ttl_hours),
    )

    await job_store.create_job(job)

    # Build job runner
    runner = JobRunner(
        job_store=job_store,
        template_registry=registry,
        input_parser=input_parser,
        constraint_validator=validator,
        pipeline=pipeline,
        deck_planner=deck_planner,
        content_generator=content_generator,
    )

    # Dispatch based on mode
    if request.mode == "mode2":
        background_tasks.add_task(runner.run_mode2_planning, job_id)
    else:
        background_tasks.add_task(runner.run_mode1, job_id)

    return JobCreateResponse(job_id=job_id, status=JobStatus.queued)


@router.post("/{job_id}/approve", response_model=JobStatusResponse)
async def approve_outline(
    job_id: str,
    request: OutlineApprovalRequest,
    background_tasks: BackgroundTasks,
    job_store: SQLiteJobStore = Depends(get_job_store),
    registry: TemplateRegistry = Depends(get_template_registry),
    input_parser: InputParser = Depends(get_input_parser),
    validator: ConstraintValidator = Depends(get_constraint_validator),
    pipeline: PPTXPipeline = Depends(get_pipeline),
    deck_planner: Optional[DeckPlanner] = Depends(get_deck_planner),
    content_generator: Optional[ContentGenerator] = Depends(get_content_generator),
):
    """Approve or reject a Mode 2 deck outline."""
    job = await job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status != JobStatus.awaiting_approval:
        raise HTTPException(
            status_code=409,
            detail=f"Job is in '{job.status}' state, expected 'awaiting_approval'"
        )

    runner = JobRunner(
        job_store=job_store,
        template_registry=registry,
        input_parser=input_parser,
        constraint_validator=validator,
        pipeline=pipeline,
        deck_planner=deck_planner,
        content_generator=content_generator,
    )

    if request.approved:
        # If user provided a revised outline, update it
        if request.revised_outline is not None:
            await job_store.update_job(job_id, outline=request.revised_outline)

        # Transition to generating and spawn generation task
        await job_store.update_job(
            job_id,
            status=JobStatus.generating,
            current_stage="generating",
            progress=35,
        )
        background_tasks.add_task(runner.run_mode2_generation, job_id)

    else:
        # Rejection: re-plan with revision instructions
        if not request.revision_instructions:
            raise HTTPException(
                status_code=400,
                detail="revision_instructions required when rejecting outline"
            )

        previous_outline = DeckOutline.model_validate(job.outline)

        background_tasks.add_task(
            runner.run_mode2_replan,
            job_id,
            previous_outline,
            request.revision_instructions,
        )

    # Return updated job status
    updated_job = await job_store.get_job(job_id)
    return _job_to_response(updated_job)


@router.get("", response_model=list[JobStatusResponse])
async def list_jobs(
    limit: int = 50,
    job_store: SQLiteJobStore = Depends(get_job_store),
):
    jobs = await job_store.list_jobs(limit=limit)
    return [_job_to_response(j) for j in jobs]


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: str,
    job_store: SQLiteJobStore = Depends(get_job_store),
):
    job = await job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return _job_to_response(job)


def _job_to_response(job: JobRecord) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        current_stage=job.current_stage,
        outline=job.outline,
        warnings=job.warnings,
        error=job.error,
        output_url=job.output_url,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
