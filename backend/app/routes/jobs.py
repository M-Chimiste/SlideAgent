import uuid
import json
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
    quality_profile: str = Form("balanced"),
    length_strategy: str = Form("auto"),
    run_visual_qa: bool = Form(True),
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
    quality_profile = _form_value(quality_profile, "balanced").strip().lower() or "balanced"
    if quality_profile not in {"fast", "balanced", "showcase"}:
        raise HTTPException(status_code=422, detail="Invalid quality profile.")
    length_strategy = _form_value(length_strategy, "auto").strip().lower() or "auto"
    if length_strategy not in {"auto", "concise", "expanded"}:
        raise HTTPException(status_code=422, detail="Invalid length strategy.")

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
            "quality_profile": quality_profile,
            "length_strategy": length_strategy,
            "run_visual_qa": _form_bool(run_visual_qa, True),
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


def _form_value(value, default: str) -> str:
    if hasattr(value, "default"):
        value = value.default
    return str(value if value is not None else default)


def _form_bool(value, default: bool) -> bool:
    if hasattr(value, "default"):
        value = value.default
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
    return JobStatusResponse(
        job=job,
        warnings=job.warnings,
        preview_images=preview_images,
        qa_summary=_qa_summary(storage, job_id),
    )


def _qa_summary(storage: LocalStorage, job_id: str) -> dict:
    qa_dir = storage.job_dir(job_id) / "qa"
    if not qa_dir.exists():
        return {"critical": 0, "warning": 0, "info": 0, "count": 0}
    logs = sorted(qa_dir.glob("round-*.json"))
    if not logs:
        return {"critical": 0, "warning": 0, "info": 0, "count": 0}
    try:
        payload = json.loads(logs[-1].read_text(encoding="utf-8"))
    except Exception:
        return {"critical": 0, "warning": 0, "info": 0, "count": 0}
    issues = payload.get("issues", [])
    return {
        "critical": sum(1 for issue in issues if issue.get("severity") == "CRITICAL"),
        "warning": sum(1 for issue in issues if issue.get("severity") == "WARNING"),
        "info": sum(1 for issue in issues if issue.get("severity") == "INFO"),
        "count": len(issues),
    }


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
