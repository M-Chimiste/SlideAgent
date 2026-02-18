"""ContentGenerator: Generates slide content from an approved outline using LLM.

Uses Bedrock Sonnet to generate full field content for each slide concurrently
via asyncio.gather with a semaphore for concurrency control.
"""

import asyncio
import logging

from app.models.schemas import DeckOutline, SlideContent, SlideOutlineEntry
from app.models.templates import LayoutDefinition
from app.services.bedrock import BedrockClient

logger = logging.getLogger(__name__)

MAX_CONCURRENT_LLM_CALLS = 5

SYSTEM_PROMPT = """\
You are a presentation content writer. Given a slide outline and layout \
definition, generate the full text content for each field in the slide.

Rules:
1. Write content appropriate for the specified audience and tone.
2. Respect max_chars limits for each field — stay well under the limit.
3. For bullet points, use newline-separated items (no bullet characters).
4. Keep content concise and impactful for a presentation format.
5. Ensure the content matches the slide's title and content_summary from the outline.
6. Return field_name values that exactly match the layout's field names.
"""


def _build_slide_prompt(
    slide_entry: SlideOutlineEntry,
    layout: LayoutDefinition,
    outline: DeckOutline,
    input_data: dict,
) -> str:
    """Build the user prompt for generating a single slide's content."""
    parts = []

    parts.append("## Deck Context")
    parts.append(f"Title: {outline.deck_title}")
    parts.append(f"Audience: {outline.audience}")
    parts.append(f"Narrative arc: {outline.narrative_arc}")

    if "tone" in input_data:
        parts.append(f"Tone: {input_data['tone']}")

    if "brief" in input_data:
        parts.append(f"\nOriginal brief:\n{input_data['brief']}")

    if "key_messages" in input_data:
        msgs = input_data["key_messages"]
        if isinstance(msgs, list):
            parts.append("\nKey messages:")
            for m in msgs:
                parts.append(f"  - {m}")

    parts.append(f"\n## This Slide (#{slide_entry.slide_number} of {outline.total_slides})")
    parts.append(f"Title: {slide_entry.title}")
    parts.append(f"Content summary: {slide_entry.content_summary}")
    parts.append(f"Content type: {slide_entry.content_type}")
    parts.append(f"Layout: {slide_entry.layout_name}")

    parts.append("\n## Fields to Generate")
    for field_name, field_def in layout.fields.items():
        constraint = f"max {field_def.max_chars} chars" if field_def.max_chars else "no limit"
        required = "required" if field_def.required else "optional"
        desc = field_def.description or ""
        parts.append(f"- **{field_name}** ({field_def.type}, {required}, {constraint}): {desc}")

    # Full outline for context
    parts.append("\n## Full Deck Outline")
    for s in outline.slides:
        marker = " ← THIS SLIDE" if s.slide_number == slide_entry.slide_number else ""
        parts.append(f"  {s.slide_number}. [{s.layout_name}] {s.title}{marker}")

    return "\n".join(parts)


class ContentGenerator:
    def __init__(self, bedrock_client: BedrockClient, model_id: str):
        self._bedrock = bedrock_client
        self._model_id = model_id
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

    async def generate_slide(
        self,
        slide_entry: SlideOutlineEntry,
        layout: LayoutDefinition,
        outline: DeckOutline,
        input_data: dict,
    ) -> SlideContent:
        """Generate content for a single slide."""
        async with self._semaphore:
            user_prompt = _build_slide_prompt(slide_entry, layout, outline, input_data)

            logger.info(
                "Generating content for slide %d: %s",
                slide_entry.slide_number, slide_entry.title,
            )

            return await self._bedrock.converse_structured(
                model_id=self._model_id,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                output_schema=SlideContent,
                max_tokens=2048,
                temperature=0.3,
            )

    async def generate_all(
        self,
        outline: DeckOutline,
        layouts: dict[str, LayoutDefinition],
        input_data: dict,
    ) -> list[SlideContent]:
        """Generate content for all slides concurrently."""
        tasks = []
        for slide_entry in outline.slides:
            layout = layouts.get(slide_entry.layout_name)
            if layout is None:
                logger.warning(
                    "No layout '%s' for slide %d, skipping",
                    slide_entry.layout_name, slide_entry.slide_number,
                )
                continue

            tasks.append(
                self.generate_slide(slide_entry, layout, outline, input_data)
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        slide_contents: list[SlideContent] = []
        for r in results:
            if isinstance(r, Exception):
                logger.error("Slide generation failed: %s", r)
                raise r
            slide_contents.append(r)

        return slide_contents
