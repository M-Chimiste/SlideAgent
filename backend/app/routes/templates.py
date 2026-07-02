import uuid
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.infra.local_storage import LocalStorage
from app.infra.sqlite_store import SQLiteStore
from app.models.api import TemplateListResponse
from pydantic import BaseModel

from app.models.brand import BrandLogo
from app.models.template import TemplateProfile, TemplateUpdateRequest
from app.services.template_analyzer import TemplateAnalyzer

router = APIRouter()


def _get_store(request: Request) -> SQLiteStore:
    return request.app.state.store


def _get_storage(request: Request) -> LocalStorage:
    return request.app.state.storage


def _get_analyzer(request: Request) -> TemplateAnalyzer:
    return request.app.state.template_analyzer


@router.post("/templates/analyze", response_model=TemplateProfile)
async def analyze_template(
    file: UploadFile = File(...),
    name: str = Form(...),
    template_type: str = Form("brand"),
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
    analyzer: TemplateAnalyzer = Depends(_get_analyzer),
) -> TemplateProfile:
    content = await file.read()
    template_id = str(uuid.uuid4())
    source_path = storage.save_template_source(template_id, file.filename, content)
    profile, _ = analyzer.analyze(
        source_path, template_name=name, template_type=template_type, template_id=template_id
    )
    profile.source_file = source_path.as_posix()
    try:
        analyzer.extract_image_assets(source_path)
    except Exception:
        pass  # discovered-image assets are best-effort
    await store.create_template(profile)
    storage.save_template_profile(template_id, profile.model_dump_json())
    return profile


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(store: SQLiteStore = Depends(_get_store)) -> TemplateListResponse:
    templates = await store.list_templates()
    return TemplateListResponse(templates=templates)


@router.get("/templates/{template_id}", response_model=TemplateProfile)
async def get_template(
    template_id: str, store: SQLiteStore = Depends(_get_store)
) -> TemplateProfile:
    template = await store.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
    return template


@router.get("/templates/{template_id}/assets")
async def get_template_assets(
    template_id: str,
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
) -> dict[str, object]:
    template = await store.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
    thumbnail_dir = storage.template_dir(template_id) / "thumbnails"
    thumbnails = []
    if thumbnail_dir.exists():
        thumbnails = sorted(
            [
                path.name
                for path in thumbnail_dir.iterdir()
                if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
            ]
        )
    logo_path = Path(template.brand.logo.path) if template.brand.logo else None
    images_dir = storage.template_dir(template_id) / "images"
    images = []
    if images_dir.exists():
        images = sorted(
            path.name
            for path in images_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        )
    frame_map = _template_frame_map_summary(storage, template_id)
    return {
        "template_id": template_id,
        "thumbnails": thumbnails,
        "logo_available": bool(logo_path and logo_path.exists()),
        "images": images,
        "frame_map": frame_map,
    }


def _template_frame_map_summary(
    storage: LocalStorage,
    template_id: str,
) -> dict[str, object] | None:
    path = storage.template_dir(template_id) / "frame-map.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "error": "unreadable"}
    slides = payload.get("slides") if isinstance(payload, dict) else []
    if not isinstance(slides, list):
        slides = []
    return {
        "available": True,
        "artifact": payload.get("artifact", "template-frame-map")
        if isinstance(payload, dict)
        else "template-frame-map",
        "standard": payload.get("standard") if isinstance(payload, dict) else None,
        "slide_count": int(payload.get("slide_count") or len(slides))
        if isinstance(payload, dict)
        else len(slides),
        "schema_bearing_slide_count": int(
            payload.get("schema_bearing_slide_count") or 0
        )
        if isinstance(payload, dict)
        else 0,
        "slot_count": int(payload.get("slot_count") or 0)
        if isinstance(payload, dict)
        else 0,
        "slides": [
            {
                "slide_index": slide.get("slide_index"),
                "label": slide.get("label"),
                "layout_name": slide.get("layout_name"),
                "mode": slide.get("mode"),
                "content_category": slide.get("content_category"),
                "visual_guidance": slide.get("visual_guidance"),
                "slot_count": slide.get("slot_count", 0),
                "text_slot_count": slide.get("text_slot_count", 0),
                "media_slot_count": slide.get("media_slot_count", 0),
                "schema_field_count": slide.get("schema_field_count", 0),
                "text_inventory": slide.get("text_inventory", ""),
            }
            for slide in slides[:12]
            if isinstance(slide, dict)
        ],
    }


@router.get("/templates/{template_id}/thumbnail/{image_name}")
async def get_template_thumbnail(
    template_id: str,
    image_name: str,
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
) -> FileResponse:
    template = await store.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
    if Path(image_name).name != image_name:
        raise HTTPException(status_code=404, detail="Thumbnail not found.")
    image_path = storage.template_dir(template_id) / "thumbnails" / image_name
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not found.")
    return FileResponse(image_path.as_posix(), filename=image_path.name)


@router.get("/templates/{template_id}/logo")
async def get_template_logo(
    template_id: str,
    store: SQLiteStore = Depends(_get_store),
) -> FileResponse:
    template = await store.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
    if not template.brand.logo:
        raise HTTPException(status_code=404, detail="Logo not found.")
    logo_path = Path(template.brand.logo.path)
    if not logo_path.exists() or not logo_path.is_file():
        raise HTTPException(status_code=404, detail="Logo not found.")
    return FileResponse(logo_path.as_posix(), filename=logo_path.name)


@router.get("/templates/{template_id}/image/{image_name}")
async def get_template_image(
    template_id: str,
    image_name: str,
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
) -> FileResponse:
    template = await store.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
    if Path(image_name).name != image_name:
        raise HTTPException(status_code=404, detail="Image not found.")
    image_path = storage.template_dir(template_id) / "images" / image_name
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found.")
    return FileResponse(image_path.as_posix(), filename=image_path.name)


class LogoUpdateRequest(BaseModel):
    # null/empty -> remove the logo; otherwise a file name from the template's
    # discovered images (GET /templates/{id}/assets -> images).
    image: str | None = None


@router.patch("/templates/{template_id}/logo", response_model=TemplateProfile)
async def update_template_logo(
    template_id: str,
    body: LogoUpdateRequest,
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
) -> TemplateProfile:
    template = await store.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")
    image = (body.image or "").strip()
    brand = template.brand.model_copy(deep=True)
    if not image:
        brand.logo = None
    else:
        if Path(image).name != image:
            raise HTTPException(status_code=404, detail="Image not found.")
        image_path = storage.template_dir(template_id) / "images" / image
        if not image_path.exists() or not image_path.is_file():
            raise HTTPException(status_code=404, detail="Image not found.")
        width_in, height_in = 1.2, 0.5
        try:
            from PIL import Image

            with Image.open(image_path) as img:
                w, h = img.size
            height_in = 0.5
            width_in = max(0.3, min(2.2, height_in * (w / max(1, h))))
        except Exception:
            pass
        brand.logo = BrandLogo(path=image_path.as_posix(), w=width_in, h=height_in)
    updated = await store.update_template(template_id, TemplateUpdateRequest(brand=brand))
    if not updated:
        raise HTTPException(status_code=404, detail="Template not found.")
    storage.save_template_profile(template_id, updated.model_dump_json())
    return updated


@router.patch("/templates/{template_id}", response_model=TemplateProfile)
async def update_template(
    template_id: str,
    update: TemplateUpdateRequest,
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
) -> TemplateProfile:
    updated = await store.update_template(template_id, update)
    if not updated:
        raise HTTPException(status_code=404, detail="Template not found.")
    storage.save_template_profile(template_id, updated.model_dump_json())
    return updated


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str, store: SQLiteStore = Depends(_get_store)
) -> dict[str, str]:
    await store.delete_template(template_id)
    return {"status": "deleted"}


@router.post("/templates/{template_id}/duplicate", response_model=TemplateProfile)
async def duplicate_template(
    template_id: str,
    store: SQLiteStore = Depends(_get_store),
    storage: LocalStorage = Depends(_get_storage),
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
