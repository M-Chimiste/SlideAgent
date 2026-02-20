from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor

from app.models.outline import SlideOutline
from app.models.template import SlideSpec, TemplateProfile
from app.services.strict_validator import StrictSchemaValidator


class StrictSlideInjector:
    def __init__(self) -> None:
        self.validator = StrictSchemaValidator()

    def inject(
        self,
        template_path: Path,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        output_path: Path,
    ) -> list[dict[str, str | int]]:
        presentation = Presentation(template_path.as_posix())
        outline_map = {outline.slide_index: outline for outline in outlines}
        warnings: list[dict[str, str | int]] = []
        for slide_spec in template.slides:
            if slide_spec.mode != "strict":
                continue
            outline = outline_map.get(slide_spec.index)
            if not outline:
                continue
            slide = presentation.slides[slide_spec.index]
            warnings.extend(self._apply_outline(slide, slide_spec, outline))
        presentation.save(output_path.as_posix())
        return warnings

    def _apply_outline(
        self, slide, slide_spec: SlideSpec, outline: SlideOutline
    ) -> list[dict[str, str | int]]:
        values = outline.content_json.get("fields", {})
        if not slide_spec.schema:
            return []
        warnings: list[dict[str, str | int]] = []
        for field in slide_spec.schema.fields:
            value = values.get(field.id)
            normalized_value, field_warnings = self.validator.validate_field_value(field, value)
            for warning in field_warnings:
                warnings.append(
                    {"slide_index": slide_spec.index, "field": field.id, "message": warning}
                )
            if value is None:
                continue
            shape = self._find_shape(slide, field.location)
            if not shape:
                warnings.append(
                    {
                        "slide_index": slide_spec.index,
                        "field": field.id,
                        "message": f"Shape not found for location {field.location}",
                    }
                )
                continue
            self._apply_value(shape, field, normalized_value)
        return warnings

    def _find_shape(self, slide, location: str):
        if location.startswith("shape:"):
            name = location.split(":", 1)[1]
            for shape in slide.shapes:
                if shape.name == name:
                    return shape
        return None

    def _apply_value(self, shape, field, value: Any) -> None:
        if field.type == "text_list" and isinstance(value, list):
            text_value = "\n".join(str(item) for item in value)
        else:
            text_value = str(value)

        if field.render == "fill_color" and field.color_map:
            color = field.color_map.get(str(value).lower())
            if color:
                shape.fill.solid()
                shape.fill.fore_color.rgb = RGBColor.from_string(color)

        if shape.has_text_frame:
            shape.text = text_value
