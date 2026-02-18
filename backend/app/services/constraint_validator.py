"""ConstraintValidator: Pure Python validation of field values against template schema.

Enforces required fields, enum membership, max_chars, date format, number type.
Returns (validated_fields, warnings, errors).
"""

import logging
from datetime import datetime

from app.models.templates import FieldType, SlideSchema, TemplateFieldSchema

logger = logging.getLogger(__name__)


class ConstraintValidator:
    def validate(
        self,
        fields: dict[str, str],
        schema: dict[str, SlideSchema],
    ) -> tuple[dict[str, str], list[str], list[str]]:
        """Validate field values against the template schema.

        Args:
            fields: flat dict of field_name -> value
            schema: slide_key -> SlideSchema

        Returns:
            (validated_fields, warnings, errors)
        """
        validated: dict[str, str] = {}
        warnings: list[str] = []
        errors: list[str] = []

        # Build flat field definition lookup
        field_defs: dict[str, tuple[str, object]] = {}  # field_name -> (slide_key, TemplateFieldSchema)
        for slide_key, slide_schema in schema.items():
            for field_name, field_def in slide_schema.fields.items():
                field_defs[field_name] = (slide_key, field_def)

        # Check required fields
        for field_name, (slide_key, field_def) in field_defs.items():
            if field_def.required and field_name not in fields:
                errors.append(f"Required field missing: {field_name} (slide {slide_key})")

        # Validate each provided field
        for field_name, value in fields.items():
            if field_name not in field_defs:
                warnings.append(f"Unknown field ignored: {field_name}")
                continue

            _slide_key, field_def = field_defs[field_name]

            if field_def.type == FieldType.enum:
                if field_def.allowed_values and value not in field_def.allowed_values:
                    errors.append(
                        f"Invalid enum value for {field_name}: '{value}' "
                        f"(allowed: {field_def.allowed_values})"
                    )
                    continue
                validated[field_name] = value

            elif field_def.type == FieldType.date:
                validated_date = self._validate_date(field_name, value, field_def.date_format)
                if validated_date is None:
                    errors.append(
                        f"Invalid date for {field_name}: '{value}' "
                        f"(expected format: {field_def.date_format or 'auto'})"
                    )
                    continue
                validated[field_name] = validated_date

            elif field_def.type == FieldType.number:
                try:
                    float(value)
                    validated[field_name] = value
                except (ValueError, TypeError):
                    errors.append(f"Invalid number for {field_name}: '{value}'")
                    continue

            elif field_def.type == FieldType.text:
                validated[field_name] = value

            else:
                validated[field_name] = value

            # Check max_chars for validated fields
            if field_name in validated and field_def.max_chars is not None:
                if len(validated[field_name]) > field_def.max_chars:
                    if field_def.truncation_allowed:
                        original = validated[field_name]
                        validated[field_name] = self._truncate(original, field_def.max_chars)
                        warnings.append(
                            f"Truncated {field_name} from {len(original)} to "
                            f"{field_def.max_chars} chars"
                        )
                    else:
                        errors.append(
                            f"Field {field_name} exceeds max_chars ({len(validated[field_name])} > "
                            f"{field_def.max_chars}) and truncation is not allowed"
                        )
                        del validated[field_name]

        return validated, warnings, errors

    def validate_flat(
        self,
        fields: dict[str, str],
        field_defs: dict[str, TemplateFieldSchema],
    ) -> tuple[dict[str, str], list[str], list[str]]:
        """Validate a flat dict of field values against field definitions.

        Same logic as validate() but takes a flat field_name -> TemplateFieldSchema
        dict instead of the nested SlideSchema structure. Used by Mode 2 for
        per-slide validation against layout fields.
        """
        # Wrap in a single-slide schema to reuse validate()
        schema = {
            "1": SlideSchema(slide_index=1, fields=field_defs),
        }
        return self.validate(fields, schema)

    def _validate_date(
        self, field_name: str, value: str, date_format: str | None
    ) -> str | None:
        """Validate and reformat a date string. Returns formatted date or None."""
        if date_format:
            try:
                dt = datetime.strptime(value, date_format)
                return dt.strftime(date_format)
            except ValueError:
                pass

        # Try common formats as fallback
        common_formats = [
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%d %b %Y",
            "%d %B %Y",
            "%B %d, %Y",
            "%b %d, %Y",
        ]
        for fmt in common_formats:
            try:
                dt = datetime.strptime(value, fmt)
                if date_format:
                    return dt.strftime(date_format)
                return value
            except ValueError:
                continue

        return None

    def _truncate(self, text: str, max_chars: int) -> str:
        """Truncate text at word boundary, preferring complete sentences."""
        if len(text) <= max_chars:
            return text

        truncated = text[:max_chars]

        # Try to break at the last sentence boundary
        for sep in [". ", "! ", "? "]:
            last_sep = truncated.rfind(sep)
            if last_sep > max_chars // 2:
                return truncated[: last_sep + 1]

        # Fall back to word boundary
        last_space = truncated.rfind(" ")
        if last_space > max_chars // 2:
            return truncated[:last_space]

        return truncated
