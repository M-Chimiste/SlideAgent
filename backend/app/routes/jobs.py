import uuid
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.infra.local_storage import LocalStorage
from app.infra.sqlite_store import SQLiteStore
from app.models.api import JobListResponse, JobStatusResponse
from app.models.job import FREEFORM_TEMPLATE_ID, JobRecord
from app.models.qa import QAIssue
from app.services.job_queue import JobQueue
from app.services.orchestrator import JobOrchestrator

router = APIRouter()


class OutlineEdit(BaseModel):
    slide_index: int
    action_title: Optional[str] = None
    subheading: Optional[str] = None


class OutlinePatchRequest(BaseModel):
    slides: list[OutlineEdit]


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
    plan_only: bool = Form(False),
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
    plan_only_value = _form_bool(plan_only, False)

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
    if plan_only_value and generation_mode == "strict":
        raise HTTPException(status_code=422, detail="Plan preview is only supported for generated modes.")

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
            "plan_only": plan_only_value,
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
    qa_payload = _latest_qa_payload(storage, job_id)
    return JobStatusResponse(
        job=job,
        warnings=job.warnings,
        preview_images=preview_images,
        qa_summary=_qa_summary(qa_payload),
        qa_issues=_qa_issues(qa_payload),
        qa_history=_qa_history(storage, job_id),
        planning_summary=_planning_summary(storage, job_id),
    )


@router.post("/jobs/{job_id}/render", response_model=JobRecord)
async def render_planned_job(
    job_id: str,
    store: SQLiteStore = Depends(_get_store),
    job_queue: JobQueue = Depends(_get_job_queue),
) -> JobRecord:
    job = await store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "planned":
        raise HTTPException(status_code=409, detail="Only planned jobs can be rendered.")
    config = dict(job.config_json or {})
    config["plan_only"] = False
    config["render_from_plan"] = True
    await store.update_job(
        job_id,
        status="queued",
        progress=0.5,
        config_json=config,
        result_file=None,
        preview_dir=None,
        error_message=None,
        completed_at=None,
    )
    await job_queue.enqueue(job_id)
    updated = await store.get_job(job_id)
    return updated or job


@router.get("/jobs/{job_id}/outline")
async def get_job_outline(
    job_id: str,
    store: SQLiteStore = Depends(_get_store),
) -> dict[str, list[dict]]:
    job = await store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    outlines = await store.list_slide_outlines(job_id)
    return {"slides": [_outline_payload(outline) for outline in outlines]}


@router.patch("/jobs/{job_id}/outline")
async def update_job_outline(
    job_id: str,
    patch: OutlinePatchRequest,
    store: SQLiteStore = Depends(_get_store),
) -> dict[str, list[dict]]:
    job = await store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "planned":
        raise HTTPException(status_code=409, detail="Only planned job outlines can be edited.")
    outlines = await store.list_slide_outlines(job_id)
    by_index = {outline.slide_index: outline for outline in outlines}
    for edit in patch.slides:
        outline = by_index.get(edit.slide_index)
        if outline is None:
            continue
        content = dict(outline.content_json)
        label = outline.label
        if edit.action_title is not None:
            title = edit.action_title.strip()
            if title:
                label = title
                content["action_title"] = title
                content["title"] = title
        if edit.subheading is not None:
            content["subheading"] = edit.subheading.strip()
        await store.update_slide_outline(
            outline.id,
            label=label,
            content_json=content,
        )
    outlines = await store.list_slide_outlines(job_id)
    return {"slides": [_outline_payload(outline) for outline in outlines]}


@router.get("/jobs/{job_id}/planning/{artifact_name}")
async def get_planning_artifact(
    job_id: str,
    artifact_name: str,
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
) -> JSONResponse:
    job = await store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if artifact_name not in {"source-compression", "story-map", "spec-gate"}:
        raise HTTPException(status_code=404, detail="Planning artifact not found.")
    path = storage.planning_artifact_path(job_id, artifact_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Planning artifact not found.")
    try:
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        raise HTTPException(status_code=500, detail="Planning artifact could not be read.")


def _latest_qa_payload(storage: LocalStorage, job_id: str) -> dict | None:
    qa_dir = storage.job_dir(job_id) / "qa"
    if not qa_dir.exists():
        return None
    logs = sorted(qa_dir.glob("round-*.json"))
    if not logs:
        return None
    try:
        return json.loads(logs[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def _qa_history(storage: LocalStorage, job_id: str) -> list[dict]:
    qa_dir = storage.job_dir(job_id) / "qa"
    if not qa_dir.exists():
        return []
    history = []
    for log_path in sorted(qa_dir.glob("round-*.json")):
        try:
            payload = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            payload = None
        round_label = log_path.stem.removeprefix("round-")
        try:
            round_number = int(round_label)
        except ValueError:
            round_number = len(history)
        history.append(
            {
                "round": round_number,
                "passed": bool(payload.get("passed")) if isinstance(payload, dict) else False,
                "summary": _qa_summary(payload if isinstance(payload, dict) else None),
            }
        )
    return history


def _planning_summary(storage: LocalStorage, job_id: str) -> dict:
    planning_dir = storage.job_dir(job_id) / "planning"
    artifact_names = ["source-compression", "story-map", "spec-gate"]
    artifacts = [
        name
        for name in artifact_names
        if (planning_dir / f"{name}.json").exists()
    ]
    if not artifacts:
        return {
            "artifacts": [],
            "available": False,
        }
    source = _read_planning_artifact(storage, job_id, "source-compression") or {}
    story = _read_planning_artifact(storage, job_id, "story-map") or {}
    gate = _read_planning_artifact(storage, job_id, "spec-gate") or {}
    return {
        "available": True,
        "artifacts": artifacts,
        "story_map_status": story.get("status"),
        "story_map_fallback_reason": story.get("fallback_reason"),
        "source_coverage": {
            "section_count": source.get("section_count", 0),
            "included_section_count": source.get("included_section_count", 0),
            "omitted_section_count": source.get("omitted_section_count", 0),
            "estimated_tokens": source.get("estimated_tokens", 0),
        },
        "spec_gate": {
            "status": gate.get("status"),
            "issue_count": gate.get("issue_count", 0),
            "repaired_count": gate.get("repaired_count", 0),
            "unresolved_count": gate.get("unresolved_count", 0),
        },
    }


def _read_planning_artifact(
    storage: LocalStorage,
    job_id: str,
    artifact_name: str,
) -> dict | None:
    path = storage.planning_artifact_path(job_id, artifact_name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _qa_issues(payload: dict | None) -> list[QAIssue]:
    if not payload:
        return []
    issues = []
    for issue in payload.get("issues", []):
        try:
            issues.append(QAIssue.model_validate(issue))
        except Exception:
            continue
    return issues


def _qa_summary(payload: dict | None) -> dict:
    issues = _qa_issues(payload)
    return {
        "critical": sum(1 for issue in issues if issue.severity == "CRITICAL"),
        "warning": sum(1 for issue in issues if issue.severity == "WARNING"),
        "info": sum(1 for issue in issues if issue.severity == "INFO"),
        "count": len(issues),
    }


def _outline_payload(outline) -> dict:
    content = outline.content_json or {}
    layout = outline.layout_json or {}
    exhibit = content.get("exhibit_spec")
    issues = []
    if isinstance(outline.qa_issues_json, dict):
        raw_issues = outline.qa_issues_json.get("issues", [])
        if isinstance(raw_issues, list):
            issues = raw_issues
    return {
        "slide_index": outline.slide_index,
        "mode": outline.mode,
        "label": outline.label,
        "action_title": content.get("action_title") or content.get("title") or outline.label,
        "subheading": content.get("subheading") or "",
        "narrative_role": content.get("narrative_role") or layout.get("narrative_role"),
        "layout": layout.get("layout"),
        "archetype": content.get("archetype") or layout.get("archetype"),
        "exhibit_type": exhibit.get("type") if isinstance(exhibit, dict) else None,
        "sources": content.get("sources") or [],
        "source_refs": content.get("source_refs") or [],
        "speaker_notes": content.get("speaker_notes") or "",
        "qa_status": outline.qa_status,
        "qa_issues": issues,
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
    template = (
        orchestrator.freeform_template()
        if job.template_id == FREEFORM_TEMPLATE_ID
        else await store.get_template(job.template_id)
    )
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
    await orchestrator.regenerate_slide(job_id, template, slide_index)
    return {"status": "regenerated"}


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
