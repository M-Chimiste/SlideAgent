"""Template routes: list, retrieve, upload, and manage templates."""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.dependencies import get_storage, get_template_registry
from app.services.template_registry import (
    TemplateRegistry,
    _parse_layouts_schema,
    _parse_slides_schema,
)
from app.services.template_validator import TemplateValidationError, validate_template
from app.models.templates import TemplateMode, TemplateRecord
from app.storage.local import LocalStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("")
async def list_templates(registry: TemplateRegistry = Depends(get_template_registry)):
    templates = registry.list_active_templates()
    return [
        {
            "template_id": t.template_id,
            "version": t.version,
            "display_name": t.display_name,
            "description": t.description,
            "mode": t.mode,
            "is_active": t.is_active,
        }
        for t in templates
    ]


@router.post("", status_code=201)
async def upload_template(
    pptx_file: UploadFile = File(..., description="The .pptx template file"),
    template_schema: str = Form(..., alias="schema", description="JSON schema for the template fields"),
    template_id: str = Form(..., description="Unique template identifier"),
    display_name: str = Form(..., description="Human-readable template name"),
    description: str = Form("", description="Template description"),
    mode: str = Form(..., description="Template mode: mode1, mode2, or both"),
    version: str = Form("1.0.0", description="Template version string"),
    storage: LocalStorage = Depends(get_storage),
    registry: TemplateRegistry = Depends(get_template_registry),
):
    """Upload a new template with PPTX file and schema."""
    # Validate mode
    try:
        template_mode = TemplateMode(mode)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid mode '{mode}'. Must be one of: mode1, mode2, both",
        )

    # Parse schema JSON
    try:
        schema = json.loads(template_schema)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"Invalid schema JSON: {e}")

    # Validate schema has the right top-level key
    if "slides" not in schema and "layouts" not in schema:
        raise HTTPException(
            status_code=422,
            detail="Schema must contain either 'slides' or 'layouts' key",
        )

    # Read PPTX bytes
    pptx_bytes = await pptx_file.read()
    if len(pptx_bytes) == 0:
        raise HTTPException(status_code=422, detail="PPTX file is empty")

    # Validate template PPTX against schema
    try:
        warnings = validate_template(pptx_bytes, schema)
    except TemplateValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={"message": "Template validation failed", "errors": e.errors},
        )

    # Store files: templates/{template_id}/{version}/
    base_key = f"templates/{template_id}/{version}"

    meta = {
        "template_id": template_id,
        "version": version,
        "display_name": display_name,
        "description": description,
        "mode": mode,
    }

    await storage.write_bytes(f"{base_key}/template.pptx", pptx_bytes)
    await storage.write_bytes(f"{base_key}/meta.json", json.dumps(meta, indent=2).encode())
    await storage.write_bytes(f"{base_key}/schema.json", json.dumps(schema, indent=2).encode())

    # Also write to the flat path for backward compatibility with load_all()
    flat_key = f"templates/{template_id}"
    await storage.write_bytes(f"{flat_key}/template.pptx", pptx_bytes)
    await storage.write_bytes(f"{flat_key}/meta.json", json.dumps(meta, indent=2).encode())
    await storage.write_bytes(f"{flat_key}/schema.json", json.dumps(schema, indent=2).encode())

    # Parse schema into models and register in-memory
    slides = _parse_slides_schema(schema) if "slides" in schema else None
    layouts = _parse_layouts_schema(schema) if "layouts" in schema else None

    # Resolve the pptx_path to the flat location (what load_all uses)
    pptx_path = str(storage._resolve(f"{flat_key}/template.pptx"))

    record = TemplateRecord(
        template_id=template_id,
        version=version,
        display_name=display_name,
        description=description or None,
        mode=template_mode,
        pptx_path=pptx_path,
        slides=slides,
        layouts=layouts,
        created_at=datetime.now(tz=timezone.utc),
    )
    registry.register_template(record)

    return {
        "template_id": template_id,
        "version": version,
        "display_name": display_name,
        "description": description,
        "mode": mode,
        "warnings": warnings,
    }


@router.patch("/{template_id}")
async def update_template_status(
    template_id: str,
    is_active: bool = Form(..., description="Whether the template should be active"),
    registry: TemplateRegistry = Depends(get_template_registry),
):
    """Activate or deactivate a template."""
    if is_active:
        success = registry.activate_template(template_id)
    else:
        success = registry.deactivate_template(template_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    template = registry.get_template(template_id)
    return {
        "template_id": template.template_id,
        "version": template.version,
        "is_active": template.is_active,
    }


@router.get("/{template_id}/versions")
async def list_template_versions(
    template_id: str,
    registry: TemplateRegistry = Depends(get_template_registry),
):
    """List all versions of a template."""
    versions = registry.list_versions(template_id)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    return [
        {
            "template_id": v.template_id,
            "version": v.version,
            "display_name": v.display_name,
            "mode": v.mode,
            "is_active": v.is_active,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]


@router.get("/{template_id}")
async def get_template(
    template_id: str,
    registry: TemplateRegistry = Depends(get_template_registry),
):
    template = registry.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    schema = registry.get_schema_for_template(template_id)
    schema_dict = None
    if schema is not None:
        schema_dict = {
            slide_key: {
                "slide_index": slide.slide_index,
                "description": slide.description,
                "fields": {
                    name: field.model_dump(exclude_none=True)
                    for name, field in slide.fields.items()
                },
            }
            for slide_key, slide in schema.items()
        }

    layouts = registry.get_layouts_for_template(template_id)
    layouts_dict = None
    if layouts is not None:
        layouts_dict = {
            key: layout.model_dump()
            for key, layout in layouts.items()
        }

    return {
        "template_id": template.template_id,
        "version": template.version,
        "display_name": template.display_name,
        "description": template.description,
        "mode": template.mode,
        "is_active": template.is_active,
        "schema": schema_dict,
        "layouts": layouts_dict,
    }
