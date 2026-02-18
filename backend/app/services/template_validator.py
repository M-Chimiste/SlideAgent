"""Validates uploaded template PPTX + schema pairs.

Ensures shape IDs referenced in the schema actually exist in the PPTX,
and that layout indices are valid for Mode 2 templates.
"""

import json
import logging
import tempfile
from pathlib import Path

from pptx import Presentation

logger = logging.getLogger(__name__)


class TemplateValidationError(Exception):
    """Raised when template validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Template validation failed: {'; '.join(errors)}")


def validate_template(pptx_bytes: bytes, schema: dict) -> list[str]:
    """Validate that a PPTX file matches its schema.

    Returns a list of warnings (empty = success).
    Raises TemplateValidationError if there are blocking errors.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Write PPTX to temp file for python-pptx
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        tmp.write(pptx_bytes)
        tmp_path = tmp.name

    try:
        prs = Presentation(tmp_path)

        if "slides" in schema:
            _validate_slides_schema(prs, schema, errors, warnings)
        elif "layouts" in schema:
            _validate_layouts_schema(prs, schema, errors, warnings)
        else:
            errors.append("Schema must contain either 'slides' or 'layouts' key")

    except Exception as e:
        errors.append(f"Failed to parse PPTX: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if errors:
        raise TemplateValidationError(errors)

    return warnings


def _validate_slides_schema(
    prs: Presentation, schema: dict, errors: list[str], warnings: list[str]
) -> None:
    """Validate Mode 1 schema: shape IDs must exist on the correct slides."""
    slides_data = schema.get("slides", {})
    slide_count = len(prs.slides)

    for slide_key, slide_def in slides_data.items():
        slide_idx = int(slide_key)
        if slide_idx < 1 or slide_idx > slide_count:
            errors.append(
                f"Slide {slide_key}: index {slide_idx} out of range "
                f"(template has {slide_count} slides)"
            )
            continue

        slide = prs.slides[slide_idx - 1]
        slide_shape_ids = {shape.shape_id for shape in slide.shapes}

        for field_name, field_def in slide_def.get("fields", {}).items():
            shape_id = field_def.get("shape_id")
            if shape_id is not None and shape_id not in slide_shape_ids:
                errors.append(
                    f"Slide {slide_key}, field '{field_name}': "
                    f"shape_id {shape_id} not found on slide "
                    f"(available: {sorted(slide_shape_ids)})"
                )


def _validate_layouts_schema(
    prs: Presentation, schema: dict, errors: list[str], warnings: list[str]
) -> None:
    """Validate Mode 2 schema: layout indices and shape IDs must exist."""
    layouts_data = schema.get("layouts", {})
    layout_count = len(prs.slide_layouts)

    for layout_key, layout_def in layouts_data.items():
        layout_idx = layout_def.get("slide_layout_index")
        if layout_idx is None:
            errors.append(f"Layout '{layout_key}': missing slide_layout_index")
            continue

        if layout_idx < 0 or layout_idx >= layout_count:
            errors.append(
                f"Layout '{layout_key}': slide_layout_index {layout_idx} out of range "
                f"(template has {layout_count} layouts, indices 0-{layout_count - 1})"
            )
            continue

        # Validate shape IDs against placeholder shapes in the layout
        layout = prs.slide_layouts[layout_idx]
        layout_shape_ids = {shape.shape_id for shape in layout.placeholders}

        for field_name, field_def in layout_def.get("fields", {}).items():
            shape_id = field_def.get("shape_id")
            if shape_id is not None and shape_id not in layout_shape_ids:
                # Also check non-placeholder shapes
                all_shape_ids = {shape.shape_id for shape in layout.shapes}
                if shape_id not in all_shape_ids:
                    warnings.append(
                        f"Layout '{layout_key}', field '{field_name}': "
                        f"shape_id {shape_id} not found in layout "
                        f"(available: {sorted(all_shape_ids)})"
                    )
