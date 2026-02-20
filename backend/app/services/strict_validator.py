import re
from typing import Any

from app.models.template import SlideField


class StrictSchemaValidator:
    def normalize_enum_value(self, value: Any, allowed: list[str]) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        allowed_map = {item.lower(): item for item in allowed}
        if normalized in allowed_map:
            return allowed_map[normalized]
        compact = re.sub(r"[^a-z0-9]", "", normalized)
        for candidate, raw in allowed_map.items():
            if compact == re.sub(r"[^a-z0-9]", "", candidate):
                return raw
        return None

    def validate_field_value(self, field: SlideField, value: Any) -> tuple[Any, list[str]]:
        warnings: list[str] = []
        if value is None:
            if field.required:
                warnings.append(f"Missing required field: {field.id}")
            return value, warnings

        if field.type == "enum" and field.values:
            mapped = self.normalize_enum_value(value, field.values)
            if mapped is None:
                warnings.append(f"Invalid enum value for {field.id}: {value}")
                return "[INSERT CONTENT HERE]", warnings
            return mapped, warnings

        if field.type in {"text", "date"}:
            text_value = str(value)
            if field.max_chars and len(text_value) > field.max_chars:
                warnings.append(
                    f"Value truncated for {field.id} to {field.max_chars} characters."
                )
                text_value = text_value[: field.max_chars]
            return text_value, warnings

        if field.type == "text_list":
            if not isinstance(value, list):
                value = [str(value)]
            normalized_items = [str(item).strip() for item in value if str(item).strip()]
            if field.max_items and len(normalized_items) > field.max_items:
                warnings.append(f"List truncated for {field.id} to {field.max_items} items.")
                normalized_items = normalized_items[: field.max_items]
            if field.max_chars_per_item:
                bounded = []
                for item in normalized_items:
                    if len(item) > field.max_chars_per_item:
                        warnings.append(
                            f"Item truncated for {field.id} to {field.max_chars_per_item} characters."
                        )
                        bounded.append(item[: field.max_chars_per_item])
                    else:
                        bounded.append(item)
                normalized_items = bounded
            return normalized_items, warnings

        if field.type == "number":
            try:
                return float(value), warnings
            except (TypeError, ValueError):
                warnings.append(f"Invalid numeric value for {field.id}: {value}")
                return "[INSERT CONTENT HERE]", warnings

        return value, warnings
