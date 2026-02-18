"""InputParser: Maps user input fields to template schema fields.

Exact matches pass through. Near-matches trigger LLM coercion via Bedrock Haiku.
Falls back to strict mode (exact matches only) when Bedrock is unavailable.
"""

import logging

from app.models.schemas import CoercionOutput
from app.models.templates import SlideSchema
from app.services.bedrock import BedrockClient

logger = logging.getLogger(__name__)

COERCION_SYSTEM_PROMPT = """\
You are a field mapping assistant. Given raw input field names and a template schema, \
map each raw field to the correct schema field and coerce its value to match the \
expected type and constraints.

Rules:
- Match fields by semantic similarity (e.g., "proj_name" matches "project_name")
- Coerce values to match the expected type (e.g., reformat dates)
- Set confidence to 1.0 for exact matches, lower for fuzzy matches
- If a raw field cannot be mapped, add it to unresolvable_fields
"""


class InputParser:
    def __init__(self, bedrock: BedrockClient | None = None, model_id: str = ""):
        self._bedrock = bedrock
        self._model_id = model_id

    async def parse(
        self,
        input_data: dict,
        schema: dict[str, SlideSchema],
    ) -> dict[str, str]:
        """Map input fields to schema fields. Returns flat dict of field_name -> value."""
        # Build flat lookup of all schema field names
        schema_fields: set[str] = set()
        for slide_schema in schema.values():
            schema_fields.update(slide_schema.fields.keys())

        matched: dict[str, str] = {}
        unmatched_raw: dict[str, str] = {}

        for raw_name, raw_value in input_data.items():
            value_str = str(raw_value)
            if raw_name in schema_fields:
                matched[raw_name] = value_str
            else:
                unmatched_raw[raw_name] = value_str

        if not unmatched_raw:
            return matched

        # Try LLM coercion for unmatched fields
        if self._bedrock is not None:
            try:
                coerced = await self._coerce_fields(unmatched_raw, schema)
                for field in coerced.coerced_fields:
                    if field.confidence >= 0.5:
                        matched[field.schema_field_name] = field.coerced_value
                        logger.info(
                            "Coerced %s -> %s (confidence: %.2f)",
                            field.schema_field_name,
                            field.coerced_value[:50],
                            field.confidence,
                        )
                if coerced.unresolvable_fields:
                    logger.warning("Unresolvable fields: %s", coerced.unresolvable_fields)
            except Exception:
                logger.exception("LLM coercion failed, falling back to strict mode")
        else:
            logger.warning(
                "No Bedrock client configured. Unmatched fields ignored: %s",
                list(unmatched_raw.keys()),
            )

        return matched

    async def _coerce_fields(
        self,
        unmatched: dict[str, str],
        schema: dict[str, SlideSchema],
    ) -> CoercionOutput:
        """Use LLM to coerce unmatched fields to schema fields."""
        assert self._bedrock is not None

        # Build schema description for the prompt
        schema_desc = {}
        for slide_key, slide_schema in schema.items():
            for field_name, field_def in slide_schema.fields.items():
                schema_desc[field_name] = {
                    "type": field_def.type.value,
                    "description": field_def.description or "",
                    "max_chars": field_def.max_chars,
                }

        user_prompt = (
            f"Raw input fields:\n{unmatched}\n\n"
            f"Schema fields:\n{schema_desc}\n\n"
            "Map each raw field to the best matching schema field and coerce its value."
        )

        return await self._bedrock.converse_structured(
            model_id=self._model_id,
            system_prompt=COERCION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            output_schema=CoercionOutput,
            max_tokens=1024,
            temperature=0.1,
        )
