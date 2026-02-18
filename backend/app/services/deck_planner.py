"""DeckPlanner: Generates a deck outline from a topic brief using LLM.

Uses Bedrock Sonnet to create a DeckOutline with slide structure and layout
assignments based on available template layouts.
"""

import logging

from app.models.schemas import DeckOutline, SlideOutlineEntry
from app.models.templates import LayoutDefinition
from app.services.bedrock import BedrockClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a presentation architect. Given a topic brief and a set of available \
slide layouts, create a coherent deck outline.

Rules:
1. Create a narrative arc: opening → context → body → conclusion.
2. Only use layout_name values from the provided layout library.
3. Match content_type to a layout whose suitable_for includes that type.
4. Each slide must have a clear, concise title and a 1-2 sentence content_summary.
5. Respect slide count constraints if provided.
6. The total_slides field must equal the length of the slides list.
7. Assign slide_number sequentially starting from 1.
"""

REPLAN_ADDENDUM = """

The user has reviewed your previous outline and requested changes. \
Their revision instructions are below. Produce a revised outline that \
addresses their feedback while maintaining a coherent narrative.

Previous outline:
{previous_outline}

User's revision instructions:
{revision_instructions}
"""


def _build_user_prompt(
    input_data: dict,
    layouts: dict[str, LayoutDefinition],
) -> str:
    """Build the user prompt from brief data and available layouts."""
    parts = []

    # Topic brief
    parts.append("## Topic Brief\n")
    if "title" in input_data:
        parts.append(f"Title: {input_data['title']}")
    if "audience" in input_data:
        parts.append(f"Audience: {input_data['audience']}")
    if "key_messages" in input_data:
        msgs = input_data["key_messages"]
        if isinstance(msgs, list):
            parts.append("Key Messages:")
            for m in msgs:
                parts.append(f"  - {m}")
        else:
            parts.append(f"Key Messages: {msgs}")
    if "tone" in input_data:
        parts.append(f"Tone: {input_data['tone']}")

    # Freeform brief
    if "brief" in input_data:
        parts.append(f"\nBrief:\n{input_data['brief']}")

    # Slide count constraints
    slide_min = input_data.get("slide_count_min")
    slide_max = input_data.get("slide_count_max")
    if slide_min or slide_max:
        parts.append(f"\nSlide count: {slide_min or '?'} to {slide_max or '?'} slides")

    # Available layouts
    parts.append("\n## Available Layouts\n")
    for key, layout in layouts.items():
        suitable = ", ".join(layout.suitable_for)
        field_names = ", ".join(layout.fields.keys())
        parts.append(f"- **{key}** (suitable_for: [{suitable}])")
        parts.append(f"  Fields: {field_names}")
        if layout.notes:
            parts.append(f"  Notes: {layout.notes}")

    return "\n".join(parts)


class DeckPlanner:
    def __init__(self, bedrock_client: BedrockClient, model_id: str):
        self._bedrock = bedrock_client
        self._model_id = model_id

    async def plan_deck(
        self,
        input_data: dict,
        layouts: dict[str, LayoutDefinition],
    ) -> DeckOutline:
        """Generate a deck outline from the topic brief and available layouts."""
        user_prompt = _build_user_prompt(input_data, layouts)

        logger.info("Planning deck outline for brief: %s", input_data.get("title", "untitled"))

        outline = await self._bedrock.converse_structured(
            model_id=self._model_id,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            output_schema=DeckOutline,
            max_tokens=4096,
            temperature=0.4,
        )

        # Validate layout_name references
        valid_layout_keys = set(layouts.keys())
        for slide in outline.slides:
            if slide.layout_name not in valid_layout_keys:
                logger.warning(
                    "DeckPlanner returned unknown layout '%s' for slide %d, "
                    "falling back to first suitable layout",
                    slide.layout_name, slide.slide_number,
                )
                # Find a suitable layout for this content type
                for key, layout in layouts.items():
                    if slide.content_type in layout.suitable_for:
                        slide.layout_name = key
                        break

        # Fix total_slides if needed
        outline.total_slides = len(outline.slides)

        return outline

    async def replan_deck(
        self,
        input_data: dict,
        layouts: dict[str, LayoutDefinition],
        previous_outline: DeckOutline,
        revision_instructions: str,
    ) -> DeckOutline:
        """Re-plan deck outline based on user revision instructions."""
        user_prompt = _build_user_prompt(input_data, layouts)

        system = SYSTEM_PROMPT + REPLAN_ADDENDUM.format(
            previous_outline=previous_outline.model_dump_json(indent=2),
            revision_instructions=revision_instructions,
        )

        logger.info("Re-planning deck outline with revision instructions")

        outline = await self._bedrock.converse_structured(
            model_id=self._model_id,
            system_prompt=system,
            user_prompt=user_prompt,
            output_schema=DeckOutline,
            max_tokens=4096,
            temperature=0.4,
        )

        outline.total_slides = len(outline.slides)
        return outline
