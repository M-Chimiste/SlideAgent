import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.infra.local_storage import LocalStorage
from app.infra.sqlite_store import SQLiteStore
from app.models.api import TemplateListResponse
from app.models.template import TemplateProfile, TemplateUpdateRequest
from app.services.template_analyzer import TemplateAnalyzer

router = APIRouter()


def _get_store() -> SQLiteStore:
    from fastapi import Request

    def dependency(request: Request) -> SQLiteStore:
        return request.app.state.store

    return dependency


def _get_storage() -> LocalStorage:
    from fastapi import Request

    def dependency(request: Request) -> LocalStorage:
        return request.app.state.storage

    return dependency


def _get_analyzer() -> TemplateAnalyzer:
    from fastapi import Request

    def dependency(request: Request) -> TemplateAnalyzer:
        return request.app.state.template_analyzer

    return dependency


@router.post("/templates/analyze", response_model=TemplateProfile)
async def analyze_template(
    file: UploadFile = File(...),
    name: str = Form(...),
    template_type: str = Form("brand"),
    store: SQLiteStore = _get_store(),
    storage: LocalStorage = _get_storage(),
    analyzer: TemplateAnalyzer = _get_analyzer(),
) -> TemplateProfile:
    content = await file.read()
    template_id = str(uuid.uuid4())
    source_path = storage.save_template_source(template_id, file.filename, content)
    profile, _ = analyzer.analyze(
        source_path, template_name=name, template_type=template_type, template_id=template_id
    )
    profile.source_file = source_path.as_posix()
    await store.create_template(profile)
    storage.save_template_profile(template_id, profile.model_dump_json())
    return profile


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(store: SQLiteStore = _get_store()) -> TemplateListResponse:
    templates = await store.list_templates()
    return TemplateListResponse(templates=templates)


@router.get("/templates/{template_id}", response_model=TemplateProfile)
async def get_template(
    template_id: str, store: SQLiteStore = _get_store()
) -> TemplateProfile:
    template = await store.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
    return template


@router.patch("/templates/{template_id}", response_model=TemplateProfile)
async def update_template(
    template_id: str,
    update: TemplateUpdateRequest,
    store: SQLiteStore = _get_store(),
    storage: LocalStorage = _get_storage(),
) -> TemplateProfile:
    updated = await store.update_template(template_id, update)
    if not updated:
        raise HTTPException(status_code=404, detail="Template not found.")
    storage.save_template_profile(template_id, updated.model_dump_json())
    return updated


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str, store: SQLiteStore = _get_store()
) -> dict[str, str]:
    await store.delete_template(template_id)
    return {"status": "deleted"}


@router.post("/templates/{template_id}/duplicate", response_model=TemplateProfile)
async def duplicate_template(
    template_id: str,
    store: SQLiteStore = _get_store(),
    storage: LocalStorage = _get_storage(),
) -> TemplateProfile:
    template = await store.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
    new_id = str(uuid.uuid4())
    duplicate = template.model_copy(
        update={"id": new_id, "name": f"{template.name} Copy"}
    )
    await store.create_template(duplicate)
    storage.save_template_profile(new_id, duplicate.model_dump_json())
    return duplicate
