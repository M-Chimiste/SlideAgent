import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.models.templates import (
    LayoutDefinition,
    SlideSchema,
    TemplateFieldSchema,
    TemplateRecord,
)

logger = logging.getLogger(__name__)


class TemplateRegistry:
    def __init__(self, templates_dir: str):
        self._templates_dir = Path(templates_dir)
        # Current (latest) version per template_id
        self._templates: dict[str, TemplateRecord] = {}
        # All versions: template_id -> {version: TemplateRecord}
        self._versions: dict[str, dict[str, TemplateRecord]] = {}

    async def load_all(self) -> None:
        self._templates.clear()
        self._versions.clear()
        if not self._templates_dir.exists():
            logger.warning("Templates directory does not exist: %s", self._templates_dir)
            return

        for template_dir in sorted(self._templates_dir.iterdir()):
            if not template_dir.is_dir():
                continue

            meta_path = template_dir / "meta.json"
            schema_path = template_dir / "schema.json"
            pptx_path = template_dir / "template.pptx"

            if not meta_path.exists():
                logger.warning("Skipping %s: no meta.json", template_dir.name)
                continue

            try:
                meta = json.loads(meta_path.read_text())
                slides = None
                layouts = None
                if schema_path.exists():
                    schema_data = json.loads(schema_path.read_text())
                    if "slides" in schema_data:
                        slides = _parse_slides_schema(schema_data)
                    if "layouts" in schema_data:
                        layouts = _parse_layouts_schema(schema_data)

                record = TemplateRecord(
                    template_id=meta["template_id"],
                    version=meta.get("version", "1.0.0"),
                    display_name=meta["display_name"],
                    description=meta.get("description"),
                    mode=meta["mode"],
                    pptx_path=str(pptx_path),
                    slides=slides,
                    layouts=layouts,
                    created_at=datetime.now(tz=timezone.utc),
                )
                self._templates[record.template_id] = record
                # Also track in version history
                if record.template_id not in self._versions:
                    self._versions[record.template_id] = {}
                self._versions[record.template_id][record.version] = record
                logger.info("Loaded template: %s (v%s)", record.template_id, record.version)
            except Exception:
                logger.exception("Failed to load template from %s", template_dir.name)

    def get_template(self, template_id: str) -> TemplateRecord | None:
        return self._templates.get(template_id)

    def get_template_version(
        self, template_id: str, version: str
    ) -> TemplateRecord | None:
        """Get a specific version of a template."""
        versions = self._versions.get(template_id, {})
        return versions.get(version)

    def list_versions(self, template_id: str) -> list[TemplateRecord]:
        """List all versions of a template, newest first."""
        versions = self._versions.get(template_id, {})
        return sorted(versions.values(), key=lambda r: r.created_at, reverse=True)

    def list_templates(self) -> list[TemplateRecord]:
        return list(self._templates.values())

    def get_schema_for_template(self, template_id: str) -> dict[str, SlideSchema] | None:
        record = self._templates.get(template_id)
        if record is None or record.slides is None:
            return None
        return record.slides

    def get_layouts_for_template(
        self, template_id: str
    ) -> dict[str, LayoutDefinition] | None:
        record = self._templates.get(template_id)
        if record is None or record.layouts is None:
            return None
        return record.layouts

    def get_template_path(self, template_id: str) -> str | None:
        record = self._templates.get(template_id)
        if record is None:
            return None
        return record.pptx_path

    def register_template(self, record: TemplateRecord) -> None:
        """Add or replace a template in the in-memory registry.

        Always updates the current (latest) entry. Also adds to version history.
        """
        self._templates[record.template_id] = record
        if record.template_id not in self._versions:
            self._versions[record.template_id] = {}
        self._versions[record.template_id][record.version] = record
        logger.info("Registered template: %s (v%s)", record.template_id, record.version)

    def deactivate_template(self, template_id: str) -> bool:
        """Mark a template as inactive. Returns False if not found."""
        record = self._templates.get(template_id)
        if record is None:
            return False
        updated = record.model_copy(update={"is_active": False})
        self._templates[template_id] = updated
        # Also update in version history
        if template_id in self._versions and record.version in self._versions[template_id]:
            self._versions[template_id][record.version] = updated
        return True

    def activate_template(self, template_id: str) -> bool:
        """Mark a template as active. Returns False if not found."""
        record = self._templates.get(template_id)
        if record is None:
            return False
        updated = record.model_copy(update={"is_active": True})
        self._templates[template_id] = updated
        if template_id in self._versions and record.version in self._versions[template_id]:
            self._versions[template_id][record.version] = updated
        return True

    def list_active_templates(self) -> list[TemplateRecord]:
        """List only active templates."""
        return [t for t in self._templates.values() if t.is_active]


def _parse_slides_schema(data: dict) -> dict[str, SlideSchema]:
    slides = {}
    for slide_key, slide_data in data.get("slides", {}).items():
        fields = {}
        for field_name, field_data in slide_data.get("fields", {}).items():
            fields[field_name] = TemplateFieldSchema(**field_data)
        slides[slide_key] = SlideSchema(
            slide_index=int(slide_key),
            description=slide_data.get("description"),
            fields=fields,
        )
    return slides


def _parse_layouts_schema(data: dict) -> dict[str, LayoutDefinition]:
    layouts = {}
    for layout_key, layout_data in data.get("layouts", {}).items():
        fields = {}
        for field_name, field_data in layout_data.get("fields", {}).items():
            fields[field_name] = TemplateFieldSchema(**field_data)
        layouts[layout_key] = LayoutDefinition(
            layout_name=layout_data["layout_name"],
            slide_layout_index=layout_data["slide_layout_index"],
            suitable_for=layout_data.get("suitable_for", []),
            fields=fields,
            notes=layout_data.get("notes"),
        )
    return layouts
