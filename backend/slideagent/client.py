"""SlideAgentClient — Programmatic API for generating PowerPoint decks.

Wraps all core services behind a single async client. No FastAPI required.
"""

import logging
from typing import Optional

from app.models.schemas import DeckOutline, InjectionTarget
from app.models.templates import SlideSchema
from app.services.bedrock import BedrockClient
from app.services.coherence_check import CoherenceCheck
from app.services.constraint_validator import ConstraintValidator
from app.services.content_generator import ContentGenerator
from app.services.deck_planner import DeckPlanner
from app.services.input_parser import InputParser
from app.services.pptx_pipeline import PPTXPipeline
from app.services.template_registry import TemplateRegistry
from app.services.xml_injector import XMLInjector
from app.storage.local import LocalStorage

from slideagent.models import DeckMode, GenerateResult

logger = logging.getLogger(__name__)


class SlideAgentClient:
    """High-level programmatic API for generating PowerPoint decks.

    Args:
        templates_dir: Path to the templates directory.
        storage_base: Base path for storage (parent of templates_dir for local).
        staging_dir: Path for temporary pipeline staging files.
        bedrock_region: AWS region for Bedrock. Empty string disables LLM features.
        aws_profile: AWS CLI profile name. Empty string uses default credentials.
        sonnet_model_id: Bedrock model ID for planning/content generation.
        haiku_model_id: Bedrock model ID for coercion/coherence checks.
    """

    def __init__(
        self,
        templates_dir: str,
        storage_base: str,
        staging_dir: str = ".data/staging",
        bedrock_region: Optional[str] = None,
        aws_profile: str = "",
        sonnet_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        haiku_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    ):
        self._templates_dir = templates_dir
        self._storage = LocalStorage(base_path=storage_base)
        self._staging_dir = staging_dir
        self._registry = TemplateRegistry(templates_dir=templates_dir)

        # LLM services (initialized lazily if bedrock_region is provided)
        self._bedrock: Optional[BedrockClient] = None
        self._deck_planner: Optional[DeckPlanner] = None
        self._content_generator: Optional[ContentGenerator] = None
        self._coherence_check: Optional[CoherenceCheck] = None

        if bedrock_region:
            try:
                import boto3

                session_kwargs: dict = {"region_name": bedrock_region}
                if aws_profile:
                    session_kwargs["profile_name"] = aws_profile
                session = boto3.Session(**session_kwargs)
                session.client("sts").get_caller_identity()
                self._bedrock = BedrockClient(
                    region=bedrock_region, profile_name=aws_profile,
                )
                self._deck_planner = DeckPlanner(
                    bedrock_client=self._bedrock, model_id=sonnet_model_id,
                )
                self._content_generator = ContentGenerator(
                    bedrock_client=self._bedrock, model_id=sonnet_model_id,
                )
                self._coherence_check = CoherenceCheck(
                    bedrock_client=self._bedrock, model_id=haiku_model_id,
                )
                logger.info("Bedrock initialized (region=%s, profile=%s)",
                            bedrock_region, aws_profile or "default")
            except Exception:
                logger.info("Bedrock unavailable, Mode 2 disabled")

        self._input_parser = InputParser(
            bedrock=self._bedrock, model_id=haiku_model_id,
        )
        self._validator = ConstraintValidator()
        self._injector = XMLInjector()
        self._pipeline = PPTXPipeline(
            storage=self._storage,
            injector=self._injector,
            staging_base=staging_dir,
        )

    async def initialize(self) -> None:
        """Load templates. Must be called before generate_deck()."""
        await self._registry.load_all()
        logger.info(
            "SlideAgentClient initialized (%d templates)",
            len(self._registry.list_templates()),
        )

    @property
    def templates(self) -> TemplateRegistry:
        """Access the template registry for listing/querying templates."""
        return self._registry

    async def generate_deck(
        self,
        template_id: str,
        mode: str,
        input_data: dict,
        outline: Optional[DeckOutline] = None,
    ) -> GenerateResult:
        """Generate a PowerPoint deck.

        For Mode 1: input_data should contain field name → value mappings
        matching the template schema.

        For Mode 2: input_data should contain brief fields (title, audience,
        key_messages, tone, brief). If `outline` is provided, it is used
        directly (skipping planning). Otherwise, an outline is generated
        automatically and approved without user review.

        Args:
            template_id: ID of the template to use.
            mode: "mode1" or "mode2".
            input_data: Input fields or brief data.
            outline: Pre-approved outline (Mode 2 only, optional).

        Returns:
            GenerateResult with output_path, warnings, and success status.
        """
        deck_mode = DeckMode(mode)

        template = self._registry.get_template(template_id)
        if template is None:
            return GenerateResult(
                success=False,
                error=f"Template '{template_id}' not found",
            )

        if deck_mode == DeckMode.mode1:
            return await self._run_mode1(template_id, input_data)
        else:
            return await self._run_mode2(template_id, input_data, outline)

    async def _run_mode1(
        self, template_id: str, input_data: dict
    ) -> GenerateResult:
        """Execute Mode 1 pipeline synchronously."""
        schema = self._registry.get_schema_for_template(template_id)
        if schema is None:
            return GenerateResult(
                success=False, error=f"No schema for template '{template_id}'"
            )

        template_path = self._registry.get_template_path(template_id)
        if template_path is None:
            return GenerateResult(
                success=False, error=f"Template file not found for '{template_id}'"
            )

        # Parse input fields
        parsed_fields = await self._input_parser.parse(input_data, schema)

        # Validate
        validated_fields, warnings, errors = self._validator.validate(
            parsed_fields, schema
        )
        if errors:
            return GenerateResult(
                success=False, error="; ".join(errors), warnings=warnings
            )

        # Build injection targets
        targets = self._build_targets(validated_fields, schema)

        # Convert path
        storage_path = self._registry_path_to_storage_path(template_path)

        # Generate a unique job_id for staging
        import uuid

        job_id = str(uuid.uuid4())

        result = await self._pipeline.execute(
            template_path=storage_path,
            targets=targets,
            job_id=job_id,
        )

        return GenerateResult(
            success=result.success,
            output_path=result.output_path,
            warnings=warnings + result.warnings,
            error=result.error,
        )

    async def _run_mode2(
        self,
        template_id: str,
        input_data: dict,
        outline: Optional[DeckOutline] = None,
    ) -> GenerateResult:
        """Execute Mode 2 pipeline synchronously."""
        if self._deck_planner is None or self._content_generator is None:
            return GenerateResult(
                success=False,
                error="Mode 2 requires Bedrock (LLM service not configured)",
            )

        layouts = self._registry.get_layouts_for_template(template_id)
        if layouts is None:
            return GenerateResult(
                success=False, error=f"No layouts for template '{template_id}'"
            )

        template_path = self._registry.get_template_path(template_id)
        if template_path is None:
            return GenerateResult(
                success=False, error=f"Template file not found for '{template_id}'"
            )

        # Plan (or use provided outline)
        if outline is None:
            outline = await self._deck_planner.plan_deck(input_data, layouts)

        # Generate content
        slide_contents = await self._content_generator.generate_all(
            outline=outline,
            layouts=layouts,
            input_data=input_data,
        )

        # Validate + build targets
        warnings: list[str] = []
        targets: list[InjectionTarget] = []

        for sc in slide_contents:
            layout = layouts.get(sc.layout_name)
            if layout is None:
                warnings.append(
                    f"Slide {sc.slide_number}: unknown layout '{sc.layout_name}'"
                )
                continue

            field_values = {f.field_name: f.content for f in sc.fields}
            validated, val_warnings, val_errors = self._validator.validate_flat(
                field_values, layout.fields
            )
            warnings.extend(val_warnings)
            if val_errors:
                warnings.extend(f"Slide {sc.slide_number}: {e}" for e in val_errors)

            for field_name, value in validated.items():
                field_def = layout.fields.get(field_name)
                if field_def:
                    targets.append(
                        InjectionTarget(
                            slide_index=sc.slide_number,
                            shape_id=field_def.shape_id,
                            field_name=field_name,
                            value=value,
                        )
                    )

        # Execute pipeline
        storage_path = self._registry_path_to_storage_path(template_path)

        import uuid

        job_id = str(uuid.uuid4())

        result = await self._pipeline.execute_mode2(
            template_path=storage_path,
            outline=outline,
            layouts=layouts,
            targets=targets,
            job_id=job_id,
        )

        return GenerateResult(
            success=result.success,
            output_path=result.output_path,
            warnings=warnings + result.warnings,
            error=result.error,
            outline=outline.model_dump(),
        )

    def _build_targets(
        self, fields: dict[str, str], schema: dict[str, SlideSchema]
    ) -> list[InjectionTarget]:
        """Convert validated field dict to InjectionTarget list."""
        targets = []
        for slide_key, slide_schema in schema.items():
            for field_name, field_def in slide_schema.fields.items():
                if field_name in fields:
                    targets.append(
                        InjectionTarget(
                            slide_index=slide_schema.slide_index,
                            shape_id=field_def.shape_id,
                            field_name=field_name,
                            value=fields[field_name],
                        )
                    )
        return targets

    def _registry_path_to_storage_path(self, absolute_path: str) -> str:
        """Convert absolute template path to storage-relative path."""
        idx = absolute_path.find("templates/")
        if idx >= 0:
            return absolute_path[idx:]
        return absolute_path
