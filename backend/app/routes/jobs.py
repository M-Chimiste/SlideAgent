import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.infra.local_storage import LocalStorage
from app.infra.sqlite_store import SQLiteStore
from app.models.api import JobListResponse, JobStatusResponse
from app.models.job import FREEFORM_TEMPLATE_ID, JobRecord
from app.services.job_queue import JobQueue
from app.services.orchestrator import JobOrchestrator

router = APIRouter()


def _get_store(request: Request) -> SQLiteStore:
    return request.app.state.store


def _get_storage(request: Request) -> LocalStorage:
    return request.app.state.storage


def _get_orchestrator(request: Request) -> JobOrchestrator:
    return request.app.state.orchestrator


def _get_job_queue(request: Request) -> JobQueue:
    return request.app.state.job_queue


@router.post("/jobs", response_model=JobRecord)
async def create_job(
    template_id: str = Form(""),
    generation_mode: str = Form(""),
    planner_profile: str = Form("fast"),
    instructions: str = Form(""),
    documents: Optional[list[UploadFile]] = File(None),
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
    job_queue: JobQueue = Depends(_get_job_queue),
) -> JobRecord:
    generation_mode = generation_mode.strip().lower()
    if not generation_mode:
        generation_mode = "freeform" if not template_id else ""
    if generation_mode not in {"", "freeform", "brand", "strict"}:
        raise HTTPException(status_code=422, detail="Invalid generation mode.")
    planner_profile = planner_profile.strip().lower() or "fast"
    if planner_profile not in {"fast", "deep"}:
        raise HTTPException(status_code=422, detail="Invalid planner profile.")

    template = None
    if generation_mode == "freeform":
        template_id = FREEFORM_TEMPLATE_ID
    else:
        if not template_id:
            raise HTTPException(status_code=422, detail="Template is required for this mode.")
        template = await store.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found.")
        generation_mode = generation_mode or template.type

    job_id = str(uuid.uuid4())
    job = JobRecord(
        id=job_id,
        template_id=template_id,
        instructions=instructions,
        config_json={
            "generation_mode": generation_mode,
            "planner_profile": planner_profile,
        },
        status="queued",
        progress=0.0,
        qa_rounds=0,
        warnings=[],
        result_file=None,
        preview_dir=None,
        error_message=None,
        created_at=_timestamp(),
        completed_at=None,
    )
    await store.create_job(job)

    for doc in documents or []:
        content = await doc.read()
        storage.save_job_document(job_id, doc.filename, content)

    await job_queue.enqueue(job.id)
    return job


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(store: SQLiteStore = Depends(_get_store)) -> JobListResponse:
    jobs = await store.list_jobs()
    return JobListResponse(jobs=jobs)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
) -> JobStatusResponse:
    job = await store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    preview_images = []
    preview_dir = storage.preview_dir(job_id)
    if preview_dir.exists():
        preview_images = sorted(
            [image.name for image in preview_dir.glob("slide-*.jpg")]
        )
    return JobStatusResponse(job=job, warnings=job.warnings, preview_images=preview_images)


@router.get("/jobs/{job_id}/preview")
async def get_job_preview(
    job_id: str, storage: LocalStorage = Depends(_get_storage)
) -> dict[str, list[str]]:
    preview_dir = storage.preview_dir(job_id)
    if not preview_dir.exists():
        raise HTTPException(status_code=404, detail="Preview not found.")
    images = sorted([image.name for image in preview_dir.glob("slide-*.jpg")])
    return {"images": images}


@router.get("/jobs/{job_id}/preview/{image_name}")
async def get_preview_image(
    job_id: str,
    image_name: str,
    storage: LocalStorage = Depends(_get_storage),
) -> FileResponse:
    preview_dir = storage.preview_dir(job_id)
    image_path = preview_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Preview image not found.")
    return FileResponse(image_path.as_posix(), filename=image_path.name)


@router.get("/jobs/{job_id}/download")
async def download_job(
    job_id: str,
    format: str = "pptx",
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
) -> FileResponse:
    job = await store.get_job(job_id)
    if not job or not job.result_file:
        raise HTTPException(status_code=404, detail="Result not available.")
    file_path = Path(job.result_file)
    if format == "pdf":
        pdf_path = file_path.with_suffix(".pdf")
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF export not found.")
        return FileResponse(pdf_path.as_posix(), filename=pdf_path.name)
    return FileResponse(file_path.as_posix(), filename=file_path.name)


@router.post("/jobs/{job_id}/regen/{slide_index}")
async def regenerate_slide(
    job_id: str,
    slide_index: int,
    store: SQLiteStore = Depends(_get_store),
    orchestrator: JobOrchestrator = Depends(_get_orchestrator),
) -> dict[str, str]:
    job = await store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    template = await store.get_template(job.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
    await orchestrator.regenerate_slide(job_id, template, slide_index)
    return {"status": "regenerated"}


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
