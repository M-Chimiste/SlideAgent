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
from app.services.design_languages import VALID_LANGUAGES
from app.services.job_queue import JobQueue
from app.services.orchestrator import JobOrchestrator
from app.services.presentation_styles import VALID_STYLES

router = APIRouter()


class OutlineEdit(BaseModel):
    slide_index: int
    action_title: Optional[str] = None
    subheading: Optional[str] = None


class OutlinePatchRequest(BaseModel):
    slides: list[OutlineEdit]


class SlidePointEdit(BaseModel):
    title: str = ""
    body: str = ""
    icon: str = ""


class SlideEditRequest(BaseModel):
    action_title: Optional[str] = None
    subheading: Optional[str] = None
    points: Optional[list[SlidePointEdit]] = None
    layout: Optional[str] = None


class RegenerateSlideRequest(BaseModel):
    guidance: str = ""
    # Optional manual edits applied BEFORE the LLM regeneration, so the model
    # reworks the user's version of the slide in a single rebuild.
    edits: Optional[SlideEditRequest] = None


# Layouts a user may switch a slide to from the review cockpit (mirrors the
# planner's guided-regeneration whitelist).
EDITABLE_SLIDE_LAYOUTS = {
    "callouts", "icon_rows", "two_column", "checklist", "comparison_table",
    "quote_sidebar", "matrix_2x2", "framework_cycle", "dependency_map",
    "table_reference", "metric_chart", "anti_patterns", "executive_summary",
    "closing_recommendation",
}


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
    presentation_style: str = Form("auto"),
    design_language: str = Form("auto"),
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
    presentation_style = _form_value(presentation_style, "auto").strip().lower() or "auto"
    if presentation_style not in VALID_STYLES:
        raise HTTPException(status_code=422, detail="Invalid presentation style.")
    design_language = _form_value(design_language, "auto").strip().lower() or "auto"
    if design_language not in VALID_LANGUAGES:
        raise HTTPException(status_code=422, detail="Invalid design language.")
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
            "presentation_style": presentation_style,
            "design_language": design_language,
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
    qa_summary = _qa_summary(qa_payload)
    audit_summary = _rendered_slide_audit_summary(storage, job_id)
    planning_summary = _planning_summary(storage, job_id)
    final_qa_passed = _final_qa_passed(qa_payload)
    unresolved_editing_contract_count = _editing_contract_issue_count(planning_summary)
    return JobStatusResponse(
        job=job,
        warnings=job.warnings,
        preview_images=preview_images,
        qa_summary=qa_summary,
        qa_issues=_qa_issues(qa_payload),
        qa_history=_qa_history(storage, job_id),
        planning_summary=planning_summary,
        final_qa_passed=final_qa_passed,
        final_review_passed=_final_review_passed(
            job.status,
            final_qa_passed,
            unresolved_editing_contract_count,
        ),
        unresolved_critical_count=qa_summary["critical"],
        unresolved_actionable_issue_count=_payload_int(
            qa_payload, "actionable_issue_count"
        ),
        unresolved_editing_contract_count=unresolved_editing_contract_count,
        rendered_slide_audit=audit_summary,
        visual_review=_visual_review_summary(job, preview_images, audit_summary),
        template_clone_edit=_template_clone_edit_summary(storage, job_id),
        template_frame_map=_template_frame_map_summary(storage, job_id),
        template_deviation_log=_template_deviation_log_summary(storage, job_id),
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
    if artifact_name not in {
        "source-compression", "story-map", "spec-gate", "editing-contract",
        "narrative-pass", "refine-pass",
    }:
        raise HTTPException(status_code=404, detail="Planning artifact not found.")
    path = storage.planning_artifact_path(job_id, artifact_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Planning artifact not found.")
    try:
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        raise HTTPException(status_code=500, detail="Planning artifact could not be read.")


@router.get("/jobs/{job_id}/qa/rendered-slide-audit")
async def get_rendered_slide_audit(
    job_id: str,
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
) -> JSONResponse:
    job = await store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    path = _rendered_slide_audit_path(storage, job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Rendered slide audit not found.")
    try:
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        raise HTTPException(status_code=500, detail="Rendered slide audit could not be read.")


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
                "actionable_issue_count": _payload_int(
                    payload, "actionable_issue_count"
                ),
                "repair_applied": bool(payload.get("repair_applied"))
                if isinstance(payload, dict)
                else False,
                "stop_reason": payload.get("stop_reason")
                if isinstance(payload, dict)
                else None,
            }
        )
    return history


def _payload_int(payload: dict | None, key: str) -> int:
    if not isinstance(payload, dict):
        return 0
    try:
        return int(payload.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _payload_float(payload: dict | None, key: str) -> float:
    if not isinstance(payload, dict):
        return 0
    try:
        return round(float(payload.get(key, 0) or 0), 3)
    except (TypeError, ValueError):
        return 0


def _coerce_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _final_qa_passed(payload: dict | None) -> bool | None:
    if not isinstance(payload, dict):
        return None
    return bool(payload.get("passed")) and _payload_int(payload, "actionable_issue_count") == 0


def _final_review_passed(
    job_status: str,
    final_qa_passed: bool | None,
    editing_issue_count: int,
) -> bool | None:
    if job_status not in {"done", "review_failed"}:
        return None
    if final_qa_passed is None:
        return None
    return bool(final_qa_passed) and editing_issue_count == 0 and job_status == "done"


def _editing_contract_issue_count(planning_summary: dict | None) -> int:
    if not isinstance(planning_summary, dict):
        return 0
    editing = planning_summary.get("editing_contract")
    if not isinstance(editing, dict):
        return 0
    return _payload_int(editing, "warning_requirement_count") or _payload_int(
        editing,
        "issue_count",
    )


def _rendered_slide_audit_path(storage: LocalStorage, job_id: str) -> Path:
    return storage.job_dir(job_id) / "qa" / "rendered-slide-audit.json"


def _rendered_slide_audit_summary(storage: LocalStorage, job_id: str) -> dict:
    path = _rendered_slide_audit_path(storage, job_id)
    if not path.exists():
        return {"available": False, "artifact": "rendered-slide-audit"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "artifact": "rendered-slide-audit", "error": "unreadable"}
    visual_rhythm = payload.get("visual_rhythm") if isinstance(payload.get("visual_rhythm"), dict) else {}
    slides = payload.get("slides") if isinstance(payload.get("slides"), list) else []
    slide_count = len(slides) or _payload_int(visual_rhythm, "slide_count")
    family_counts = visual_rhythm.get("family_counts")
    most_repeated_family = None
    if isinstance(family_counts, dict) and family_counts:
        family, count = max(
            family_counts.items(),
            key=lambda item: _coerce_int(item[1]),
        )
        most_repeated_family = {
            "family": str(family),
            "count": _coerce_int(count),
        }
    return {
        "available": True,
        "artifact": "rendered-slide-audit",
        "path": "qa/rendered-slide-audit",
        "passed": bool(payload.get("passed")),
        "issue_count": _payload_int(payload, "issue_count"),
        "critical_count": _payload_int(payload, "critical_count"),
        "warning_count": _payload_int(payload, "warning_count"),
        "slide_count": slide_count,
        "rhythm_slide_count": _payload_int(visual_rhythm, "slide_count"),
        "unique_family_count": _payload_int(visual_rhythm, "unique_family_count"),
        "card_like_ratio": _payload_float(visual_rhythm, "card_like_ratio"),
        "most_repeated_family": most_repeated_family,
        "top_issues": _audit_issue_samples(payload),
    }


def _audit_issue_samples(payload: dict) -> list[dict]:
    issue_payloads = payload.get("issues")
    samples: list[dict] = []
    if isinstance(issue_payloads, list):
        samples.extend(_normalize_audit_issues(issue_payloads))
    if not samples:
        slides = payload.get("slides")
        if isinstance(slides, list):
            for slide in slides:
                if not isinstance(slide, dict):
                    continue
                slide_issues = slide.get("issues")
                if isinstance(slide_issues, list):
                    samples.extend(
                        _normalize_audit_issues(
                            slide_issues,
                            slide.get("slide_index"),
                        )
                    )
                if len(samples) >= 5:
                    break
    samples.sort(key=lambda item: 0 if item.get("severity") == "CRITICAL" else 1)
    return samples[:5]


def _normalize_audit_issues(
    issues: list[object],
    fallback_slide_index: object = None,
) -> list[dict]:
    normalized: list[dict] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        normalized.append(
            {
                "severity": str(issue.get("severity") or "WARNING"),
                "category": str(issue.get("category") or "rendered_slide_audit"),
                "message": str(issue.get("message") or "")[:280],
                "slide_index": issue.get("slide_index", fallback_slide_index),
            }
        )
    return normalized


def _template_clone_edit_summary(storage: LocalStorage, job_id: str) -> dict:
    path = storage.job_dir(job_id) / "template-clone-edit.json"
    if not path.exists():
        return {"available": False, "artifact": "template-clone-edit"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "artifact": "template-clone-edit", "error": "unreadable"}
    mappings = payload.get("mappings") if isinstance(payload.get("mappings"), list) else []
    cleanup = payload.get("package_cleanup") if isinstance(payload.get("package_cleanup"), dict) else {}
    edit_target_count = 0
    deleted_target_count = 0
    rewritten_target_count = 0
    rewritten_table_cell_count = 0
    rewritten_chart_count = 0
    rewritten_chart_point_count = 0
    bolded_text_run_count = 0
    deleted_table_row_count = 0
    deleted_media_placeholder_count = 0
    planned_excess_slot_count = 0
    actual_deleted_slot_count = 0
    unsatisfied_slot_cleanup_count = 0
    blocked_mapping_count = 0
    weak_mapping_count = 0
    unfilled_placeholder_count = 0
    closest_candidate_count = 0
    closest_candidate_samples: list[dict[str, object]] = []
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        if mapping.get("clone_edit_blocked"):
            blocked_mapping_count += 1
        method = str(mapping.get("method") or "").strip().lower()
        confidence = str(mapping.get("match_confidence") or "").strip().lower()
        if method in {"cyclic_fallback", "low_confidence_match"} or confidence in {"fallback", "low"}:
            weak_mapping_count += 1
        unfilled_placeholder_count += _payload_int(mapping, "unfilled_placeholder_count")
        closest_candidates = (
            mapping.get("closest_candidates")
            if isinstance(mapping.get("closest_candidates"), list)
            else []
        )
        closest_candidate_count += len(closest_candidates)
        if len(closest_candidate_samples) < 3:
            for candidate in closest_candidates:
                if not isinstance(candidate, dict):
                    continue
                closest_candidate_samples.append(
                    {
                        "output_slide": mapping.get("output_slide"),
                        "source_slide": candidate.get("source_slide"),
                        "label": candidate.get("label") or candidate.get("layout_name"),
                        "match_score": candidate.get("match_score"),
                        "match_reason": candidate.get("match_reason"),
                    }
                )
                if len(closest_candidate_samples) >= 3:
                    break
        rewritten_table_cell_count += _payload_int(mapping, "rewritten_table_cell_count")
        rewritten_chart_count += _payload_int(mapping, "rewritten_chart_count")
        rewritten_chart_point_count += _payload_int(mapping, "rewritten_chart_point_count")
        bolded_text_run_count += _payload_int(mapping, "bolded_text_run_count")
        deleted_table_row_count += _payload_int(mapping, "deleted_table_row_count")
        deleted_media_placeholder_count += _payload_int(mapping, "deleted_media_placeholder_count")
        slot_cleanup = mapping.get("slot_cleanup")
        if isinstance(slot_cleanup, dict):
            planned_excess_slot_count += _payload_int(slot_cleanup, "planned_excess_slot_count")
            actual_deleted_slot_count += _payload_int(slot_cleanup, "actual_deleted_slot_count")
            if slot_cleanup.get("cleanup_required") and not slot_cleanup.get("cleanup_satisfied"):
                unsatisfied_slot_cleanup_count += 1
        targets = mapping.get("editTargets") if isinstance(mapping.get("editTargets"), list) else []
        edit_target_count += len(targets)
        for target in targets:
            if not isinstance(target, dict):
                continue
            action = target.get("action")
            if action == "delete":
                deleted_target_count += 1
            if action == "rewrite":
                rewritten_target_count += 1
    return {
        "available": True,
        "artifact": "template-clone-edit",
        "status": payload.get("status"),
        "slide_count": _payload_int(payload, "slide_count"),
        "mapping_count": len(mappings),
        "blocked_mapping_count": blocked_mapping_count,
        "weak_mapping_count": weak_mapping_count,
        "unfilled_placeholder_count": unfilled_placeholder_count,
        "closest_candidate_count": closest_candidate_count,
        "closest_candidate_samples": closest_candidate_samples,
        "edit_target_count": edit_target_count,
        "rewritten_target_count": rewritten_target_count,
        "deleted_target_count": deleted_target_count,
        "rewritten_table_cell_count": rewritten_table_cell_count,
        "rewritten_chart_count": rewritten_chart_count,
        "rewritten_chart_point_count": rewritten_chart_point_count,
        "bolded_text_run_count": bolded_text_run_count,
        "deleted_table_row_count": deleted_table_row_count,
        "deleted_media_placeholder_count": deleted_media_placeholder_count,
        "planned_excess_slot_count": planned_excess_slot_count,
        "actual_deleted_slot_count": actual_deleted_slot_count,
        "unsatisfied_slot_cleanup_count": unsatisfied_slot_cleanup_count,
        "package_cleanup_deleted_part_count": _payload_int(cleanup, "deleted_part_count"),
        "package_cleanup_deleted_media_part_count": _payload_int(
            cleanup,
            "deleted_unreferenced_media_part_count",
        ),
        "package_cleanup_removed_override_count": _payload_int(
            cleanup,
            "removed_content_type_override_count",
        ),
        "warning_count": len(payload.get("warnings") or []),
    }


def _template_deviation_log_summary(storage: LocalStorage, job_id: str) -> dict:
    path = storage.job_dir(job_id) / "template-deviation-log.json"
    if not path.exists():
        return {"available": False, "artifact": "template-deviation-log"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "available": False,
            "artifact": "template-deviation-log",
            "error": "unreadable",
        }
    deviations = (
        payload.get("deviations")
        if isinstance(payload.get("deviations"), list)
        else []
    )
    samples: list[dict[str, object]] = []
    for deviation in deviations:
        if not isinstance(deviation, dict):
            continue
        samples.append(
            {
                "type": deviation.get("type"),
                "severity": deviation.get("severity"),
                "output_slide": deviation.get("output_slide"),
                "source_slide": deviation.get("source_slide"),
                "reason": str(deviation.get("reason") or "")[:240],
            }
        )
        if len(samples) >= 3:
            break
    return {
        "available": True,
        "artifact": "template-deviation-log",
        "status": payload.get("status"),
        "deviation_count": _payload_int(payload, "deviation_count"),
        "samples": samples,
    }


def _template_frame_map_summary(storage: LocalStorage, job_id: str) -> dict:
    path = storage.job_dir(job_id) / "template-frame-map.json"
    if not path.exists():
        return {"available": False, "artifact": "template-frame-map"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "available": False,
            "artifact": "template-frame-map",
            "error": "unreadable",
        }
    output_slides = (
        payload.get("outputSlides")
        if isinstance(payload.get("outputSlides"), list)
        else []
    )
    omitted = (
        payload.get("omittedSourceSlides")
        if isinstance(payload.get("omittedSourceSlides"), list)
        else []
    )
    blocked = [
        slide
        for slide in output_slides
        if isinstance(slide, dict) and slide.get("reuseMode") == "blocked"
    ]
    samples: list[dict[str, object]] = []
    for slide in output_slides[:3]:
        if not isinstance(slide, dict):
            continue
        samples.append(
            {
                "output_slide": slide.get("outputSlide"),
                "source_slide": slide.get("sourceSlide"),
                "reuse_mode": slide.get("reuseMode"),
                "match_confidence": slide.get("matchConfidence"),
                "match_score": slide.get("matchScore"),
            }
        )
    return {
        "available": True,
        "artifact": "template-frame-map",
        "status": payload.get("status"),
        "output_slide_count": len(output_slides),
        "source_slide_count": _payload_int(payload, "sourceSlideCount"),
        "omitted_source_slide_count": len(omitted),
        "blocked_output_slide_count": len(blocked),
        "samples": samples,
    }


def _visual_review_summary(
    job,
    preview_images: list[str],
    audit_summary: dict,
) -> dict:
    preview_count = len(preview_images)
    audit_available = bool(audit_summary.get("available"))
    audit_slide_count = int(audit_summary.get("slide_count") or 0)
    expected_slide_count = max(audit_slide_count, preview_count)
    preview_coverage = bool(
        expected_slide_count and preview_count == expected_slide_count
    )
    audit_preview_match = (
        not audit_available
        or audit_slide_count <= 0
        or audit_slide_count == preview_count
    )
    audit_passed = audit_summary.get("passed") if audit_available else None
    rendered_terminal = job.status in {"done", "review_failed"}
    if rendered_terminal:
        status = (
            "pass"
            if preview_coverage
            and audit_available
            and audit_passed is True
            and audit_preview_match
            else "warning"
        )
    else:
        status = "pending"
    if status == "pass":
        message = "Full-resolution previews and rendered-slide audit are complete."
    elif status == "warning":
        message = "Full-resolution preview coverage or rendered-slide audit needs review."
    else:
        message = "Full-resolution visual review runs after rendering."
    return {
        "status": status,
        "preview_count": preview_count,
        "expected_slide_count": expected_slide_count,
        "preview_coverage": preview_coverage,
        "audit_available": audit_available,
        "audit_slide_count": audit_slide_count,
        "audit_preview_match": audit_preview_match,
        "audit_passed": audit_passed,
        "audit_issue_count": int(audit_summary.get("issue_count") or 0),
        "audit_critical_count": int(audit_summary.get("critical_count") or 0),
        "message": message,
    }


def _planning_summary(storage: LocalStorage, job_id: str) -> dict:
    planning_dir = storage.job_dir(job_id) / "planning"
    artifact_names = ["source-compression", "story-map", "spec-gate", "editing-contract"]
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
    editing = _read_planning_artifact(storage, job_id, "editing-contract") or {}
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
        "editing_contract": {
            "standard": editing.get("standard"),
            "source": editing.get("source"),
            "status": editing.get("status"),
            "phase": editing.get("phase"),
            "issue_count": editing.get("issue_count", 0),
            "requirement_count": len(
                editing.get("requirements")
                if isinstance(editing.get("requirements"), list)
                else []
            ),
            "passed_requirement_count": _requirement_status_count(editing, "pass"),
            "warning_requirement_count": _requirement_status_count(editing, "warning"),
            "slide_count": editing.get("slide_count", 0),
            "unique_layout_count": editing.get("unique_layout_count", 0),
            "unique_composition_family_count": editing.get(
                "unique_composition_family_count",
                0,
            ),
            "bullet_card_ratio": editing.get("bullet_card_ratio", 0),
            "composition_card_ratio": editing.get("composition_card_ratio", 0),
            "diagram_count": editing.get("diagram_count", 0),
            "template_mapped_count": editing.get("template_mapped_count", 0),
            "slot_risk_count": editing.get("slot_risk_count", 0),
            "structural_operation_count": editing.get("structural_operation_count", 0),
            "structural_warning_count": editing.get("structural_warning_count", 0),
            "formatting_fix_count": editing.get("formatting_fix_count", 0),
            "formatting_warning_count": editing.get("formatting_warning_count", 0),
            "requirements": _editing_requirement_summary(editing),
            "warnings": _string_list(editing.get("warnings"), limit=6),
        },
    }


def _requirement_status_count(payload: dict, status: str) -> int:
    requirements = payload.get("requirements")
    if not isinstance(requirements, list):
        return 0
    return sum(
        1
        for item in requirements
        if isinstance(item, dict) and item.get("status") == status
    )


def _editing_requirement_summary(payload: dict) -> list[dict]:
    requirements = payload.get("requirements")
    if not isinstance(requirements, list):
        return []
    summary: list[dict] = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        summary.append(
            {
                "id": str(item.get("id") or ""),
                "label": str(item.get("label") or item.get("id") or "Requirement"),
                "status": str(item.get("status") or "unknown"),
                "message": str(item.get("message") or "")[:280],
            }
        )
    return summary


def _string_list(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            items.append(text[:240])
        if len(items) >= limit:
            break
    return items


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
    template_frame = _safe_template_frame(layout.get("template_frame") or content.get("template_frame"))
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
        "composition_family": layout.get("composition_family")
        or content.get("composition_family"),
        "composition_signature": layout.get("composition_signature")
        or content.get("composition_signature"),
        "template_frame": template_frame,
        "visual_intent": content.get("visual_intent") or {},
        "visual_degradation": content.get("visual_degradation") or {},
        "exhibit_type": exhibit.get("type") if isinstance(exhibit, dict) else None,
        "points": _outline_points(content),
        "sources": content.get("sources") or [],
        "source_refs": content.get("source_refs") or [],
        "speaker_notes": content.get("speaker_notes") or "",
        "qa_status": outline.qa_status,
        "qa_issues": issues,
    }


def _outline_points(content: dict) -> list[dict]:
    """Editable {title, body, icon} points for the review cockpit editor."""
    exhibit = content.get("exhibit_spec")
    raw = []
    if isinstance(exhibit, dict):
        for key in ("points", "items", "steps", "cards"):
            seq = exhibit.get(key)
            if isinstance(seq, list) and seq:
                raw = seq
                break
    if not raw:
        raw = content.get("bullets") or []
    points: list[dict] = []
    for entry in raw[:6]:
        if isinstance(entry, dict):
            points.append(
                {
                    "title": str(entry.get("title") or entry.get("label") or entry.get("name") or ""),
                    "body": str(
                        entry.get("body") or entry.get("text") or entry.get("description")
                        or entry.get("action") or ""
                    ),
                    "icon": str(entry.get("icon") or ""),
                }
            )
        elif isinstance(entry, str) and entry.strip():
            points.append({"title": "", "body": entry.strip(), "icon": ""})
    return points


def _safe_template_frame(frame) -> dict | None:
    if not isinstance(frame, dict):
        return None
    allowed = {
        "index",
        "source_slide",
        "label",
        "layout_name",
        "mode",
        "method",
        "match_score",
        "match_confidence",
        "match_reason",
        "intent",
        "content_category",
        "visual_guidance",
        "schema_field_count",
        "item_slot_count",
        "reuse_mode",
        "chrome_shape_count",
        "chrome_applied",
        "clone_edit_applied",
        "edit_target_count",
        "rewritten_text_shape_count",
        "rewritten_table_cell_count",
        "closest_candidates",
    }
    return {key: value for key, value in frame.items() if key in allowed}


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
    body: Optional[RegenerateSlideRequest] = None,
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
    guidance = (body.guidance if body else "").strip()
    edits = None
    if body and body.edits is not None:
        if body.edits.layout and body.edits.layout.strip().lower() not in EDITABLE_SLIDE_LAYOUTS:
            raise HTTPException(
                status_code=422,
                detail=f"layout must be one of {sorted(EDITABLE_SLIDE_LAYOUTS)}",
            )
        edits = {
            "action_title": body.edits.action_title,
            "subheading": body.edits.subheading,
            "points": [p.model_dump() for p in body.edits.points]
            if body.edits.points is not None
            else None,
            "layout": body.edits.layout,
        }
    await orchestrator.regenerate_slide(
        job_id, template, slide_index, guidance=guidance, edits=edits
    )
    return {"status": "regenerated"}


@router.patch("/jobs/{job_id}/slides/{slide_index}")
async def edit_slide(
    job_id: str,
    slide_index: int,
    body: SlideEditRequest,
    store: SQLiteStore = Depends(_get_store),
    orchestrator: JobOrchestrator = Depends(_get_orchestrator),
) -> dict[str, str]:
    """Direct user edits from the review cockpit: title, subheading, points,
    and/or layout. Terminal generated jobs rebuild the deck; planned jobs just
    persist (render happens later)."""
    job = await store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status not in {"done", "review_failed", "planned"}:
        raise HTTPException(
            status_code=409,
            detail="Slides can be edited only on completed or planned jobs.",
        )
    if body.layout and body.layout.strip().lower() not in EDITABLE_SLIDE_LAYOUTS:
        raise HTTPException(
            status_code=422,
            detail=f"layout must be one of {sorted(EDITABLE_SLIDE_LAYOUTS)}",
        )
    template = (
        orchestrator.freeform_template()
        if job.template_id == FREEFORM_TEMPLATE_ID
        else await store.get_template(job.template_id)
    )
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
    fields = {
        "action_title": body.action_title,
        "subheading": body.subheading,
        "points": [p.model_dump() for p in body.points] if body.points is not None else None,
        "layout": body.layout,
    }
    await orchestrator.edit_slide(
        job_id,
        template,
        slide_index,
        fields,
        rebuild=job.status in {"done", "review_failed"},
    )
    return {"status": "updated"}


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
