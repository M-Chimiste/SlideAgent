"""JobRunner: Orchestrates Mode 1 and Mode 2 pipelines as background tasks.

Mode 1: InputParser → ConstraintValidator → build InjectionTargets → PPTXPipeline.
Mode 2 Planning: DeckPlanner → store outline → awaiting_approval (then exit).
Mode 2 Generation: ContentGenerator → CoherenceCheck → ConstraintValidator → PPTXPipeline.
"""

import logging
from typing import TYPE_CHECKING

from app.models.jobs import JobError, JobStatus
from app.models.schemas import DeckOutline, InjectionTarget
from app.models.templates import SlideSchema
from app.services.constraint_validator import ConstraintValidator
from app.services.input_parser import InputParser
from app.services.pptx_pipeline import PPTXPipeline
from app.services.template_registry import TemplateRegistry
from app.store.sqlite import SQLiteJobStore

if TYPE_CHECKING:
    from app.services.content_generator import ContentGenerator
    from app.services.deck_planner import DeckPlanner

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(
        self,
        job_store: SQLiteJobStore,
        template_registry: TemplateRegistry,
        input_parser: InputParser,
        constraint_validator: ConstraintValidator,
        pipeline: PPTXPipeline,
        deck_planner: "DeckPlanner | None" = None,
        content_generator: "ContentGenerator | None" = None,
    ):
        self._job_store = job_store
        self._registry = template_registry
        self._parser = input_parser
        self._validator = constraint_validator
        self._pipeline = pipeline
        self._deck_planner = deck_planner
        self._content_generator = content_generator

    async def run_mode1(self, job_id: str) -> None:
        """Execute Mode 1 pipeline for a job. Called as a background task."""
        try:
            job = await self._job_store.get_job(job_id)
            if job is None:
                logger.error("Job %s not found", job_id)
                return

            template_id = job.template_id

            # --- Stage: parsing ---
            await self._job_store.update_job(
                job_id, status=JobStatus.parsing, current_stage="parsing", progress=10,
            )

            schema = self._registry.get_schema_for_template(template_id)
            if schema is None:
                await self._fail(job_id, "parsing", f"No schema found for template '{template_id}'")
                return

            template_path = self._registry.get_template_path(template_id)
            if template_path is None:
                await self._fail(job_id, "parsing", f"Template file not found for '{template_id}'")
                return

            # Parse input fields against schema
            parsed_fields = await self._parser.parse(job.input_payload, schema)

            await self._job_store.update_job(job_id, progress=30)

            # --- Stage: generating (validation + target building) ---
            await self._job_store.update_job(
                job_id, status=JobStatus.generating, current_stage="validating", progress=40,
            )

            validated_fields, warnings, errors = self._validator.validate(parsed_fields, schema)

            if errors:
                await self._fail(job_id, "validating", "; ".join(errors))
                return

            # Build injection targets from validated fields
            targets = self._build_targets(validated_fields, schema)

            await self._job_store.update_job(job_id, progress=50, warnings=warnings)

            # --- Stage: packaging ---
            await self._job_store.update_job(
                job_id, status=JobStatus.packaging, current_stage="packaging", progress=60,
            )

            # Convert absolute template path to storage-relative path
            storage_path = self._registry_path_to_storage_path(template_path)

            result = await self._pipeline.execute(
                template_path=storage_path,
                targets=targets,
                job_id=job_id,
            )

            if not result.success:
                await self._fail(job_id, "packaging", result.error or "Pipeline failed")
                return

            # Merge pipeline warnings with validation warnings
            all_warnings = warnings + result.warnings

            # --- Stage: complete ---
            await self._job_store.update_job(
                job_id,
                status=JobStatus.complete,
                current_stage="complete",
                progress=100,
                output_url=result.output_path,
                warnings=all_warnings,
            )
            logger.info("Job %s completed successfully", job_id)

        except Exception as e:
            logger.exception("Unhandled error in job %s", job_id)
            await self._fail(job_id, "unknown", str(e))

    async def run_mode2_planning(self, job_id: str) -> None:
        """Execute Mode 2 planning phase. Generates outline, then exits.

        The background task ends at awaiting_approval. A separate call to
        run_mode2_generation() is spawned after the user approves the outline.
        """
        try:
            if self._deck_planner is None:
                await self._fail(job_id, "planning", "DeckPlanner not configured (Bedrock unavailable)")
                return

            job = await self._job_store.get_job(job_id)
            if job is None:
                logger.error("Job %s not found", job_id)
                return

            # --- Stage: planning ---
            await self._job_store.update_job(
                job_id, status=JobStatus.planning, current_stage="planning", progress=10,
            )

            layouts = self._registry.get_layouts_for_template(job.template_id)
            if layouts is None:
                await self._fail(
                    job_id, "planning",
                    f"No layouts found for template '{job.template_id}'",
                )
                return

            outline = await self._deck_planner.plan_deck(job.input_payload, layouts)

            # Store outline and transition to awaiting_approval
            await self._job_store.update_job(
                job_id,
                status=JobStatus.awaiting_approval,
                current_stage="awaiting_approval",
                progress=30,
                outline=outline.model_dump(),
            )
            logger.info("Job %s outline ready, awaiting approval", job_id)

        except Exception as e:
            logger.exception("Unhandled error in Mode 2 planning for job %s", job_id)
            await self._fail(job_id, "planning", str(e))

    async def run_mode2_replan(
        self, job_id: str, previous_outline: DeckOutline, revision_instructions: str,
    ) -> None:
        """Re-plan Mode 2 outline based on user revision instructions."""
        try:
            if self._deck_planner is None:
                await self._fail(job_id, "planning", "DeckPlanner not configured")
                return

            job = await self._job_store.get_job(job_id)
            if job is None:
                logger.error("Job %s not found", job_id)
                return

            await self._job_store.update_job(
                job_id, status=JobStatus.planning, current_stage="planning", progress=10,
            )

            layouts = self._registry.get_layouts_for_template(job.template_id)
            if layouts is None:
                await self._fail(job_id, "planning", f"No layouts for template '{job.template_id}'")
                return

            outline = await self._deck_planner.replan_deck(
                job.input_payload, layouts, previous_outline, revision_instructions,
            )

            await self._job_store.update_job(
                job_id,
                status=JobStatus.awaiting_approval,
                current_stage="awaiting_approval",
                progress=30,
                outline=outline.model_dump(),
            )
            logger.info("Job %s re-planned outline ready, awaiting approval", job_id)

        except Exception as e:
            logger.exception("Unhandled error in Mode 2 re-plan for job %s", job_id)
            await self._fail(job_id, "planning", str(e))

    async def run_mode2_generation(self, job_id: str) -> None:
        """Execute Mode 2 generation phase after outline approval.

        ContentGenerator → CoherenceCheck → ConstraintValidator → PPTXPipeline.
        """
        try:
            if self._content_generator is None:
                await self._fail(job_id, "generating", "ContentGenerator not configured")
                return

            job = await self._job_store.get_job(job_id)
            if job is None:
                logger.error("Job %s not found", job_id)
                return

            if job.outline is None:
                await self._fail(job_id, "generating", "No approved outline found")
                return

            outline = DeckOutline.model_validate(job.outline)
            template_id = job.template_id

            layouts = self._registry.get_layouts_for_template(template_id)
            if layouts is None:
                await self._fail(job_id, "generating", f"No layouts for template '{template_id}'")
                return

            template_path = self._registry.get_template_path(template_id)
            if template_path is None:
                await self._fail(job_id, "generating", f"Template not found: '{template_id}'")
                return

            # --- Stage: generating ---
            await self._job_store.update_job(
                job_id, status=JobStatus.generating, current_stage="generating", progress=40,
            )

            # Generate content for all slides
            slide_contents = await self._content_generator.generate_all(
                outline=outline,
                layouts=layouts,
                input_data=job.input_payload,
            )

            await self._job_store.update_job(job_id, progress=60)

            # --- Validate + build injection targets ---
            warnings: list[str] = []
            targets: list[InjectionTarget] = []

            for sc in slide_contents:
                layout_key = sc.layout_name
                layout = layouts.get(layout_key)
                if layout is None:
                    warnings.append(f"Slide {sc.slide_number}: unknown layout '{layout_key}'")
                    continue

                # Build a flat field dict for this slide's content
                field_values = {f.field_name: f.content for f in sc.fields}

                # Validate against layout field constraints
                validated, val_warnings, val_errors = self._validator.validate_flat(
                    field_values, layout.fields,
                )
                warnings.extend(val_warnings)
                if val_errors:
                    warnings.extend(
                        f"Slide {sc.slide_number}: {e}" for e in val_errors
                    )

                # Build injection targets (slide_index is 1-based from slide_number)
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

            await self._job_store.update_job(job_id, progress=70, warnings=warnings)

            # --- Stage: packaging ---
            await self._job_store.update_job(
                job_id, status=JobStatus.packaging, current_stage="packaging", progress=75,
            )

            storage_path = self._registry_path_to_storage_path(template_path)

            result = await self._pipeline.execute_mode2(
                template_path=storage_path,
                outline=outline,
                layouts=layouts,
                targets=targets,
                job_id=job_id,
            )

            if not result.success:
                await self._fail(job_id, "packaging", result.error or "Pipeline failed")
                return

            all_warnings = warnings + result.warnings

            # --- Stage: complete ---
            await self._job_store.update_job(
                job_id,
                status=JobStatus.complete,
                current_stage="complete",
                progress=100,
                output_url=result.output_path,
                warnings=all_warnings,
            )
            logger.info("Job %s Mode 2 completed successfully", job_id)

        except Exception as e:
            logger.exception("Unhandled error in Mode 2 generation for job %s", job_id)
            await self._fail(job_id, "generating", str(e))

    def _build_targets(
        self, fields: dict[str, str], schema: dict[str, SlideSchema]
    ) -> list[InjectionTarget]:
        """Convert validated field dict to InjectionTarget list using schema shape IDs."""
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
        """Convert an absolute template path to a storage-relative path.

        The template registry stores absolute paths, but storage uses relative keys
        like 'templates/novartis-status-weekly/template.pptx'.
        """
        # Find "templates/" in the path and return from there
        idx = absolute_path.find("templates/")
        if idx >= 0:
            return absolute_path[idx:]
        return absolute_path

    async def _fail(self, job_id: str, stage: str, message: str) -> None:
        """Mark job as failed with error details."""
        logger.error("Job %s failed at %s: %s", job_id, stage, message)
        await self._job_store.update_job(
            job_id,
            status=JobStatus.failed,
            current_stage=stage,
            error=JobError(stage=stage, message=message, retryable=False),
        )
