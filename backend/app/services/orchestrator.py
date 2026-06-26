import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from app.config import Settings
from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.infra.local_storage import LocalStorage
from app.infra.sqlite_store import SQLiteStore
from app.models.brand import BrandDNA
from app.models.document import DocumentBundle
from app.models.job import JobRecord
from app.models.job import FREEFORM_TEMPLATE_ID
from app.models.outline import SlideOutline
from app.models.template import TemplateProfile
from app.services.content_planner import ContentPlanner
from app.services.design_agent import DesignAgent
from app.services.document_ingester import DocumentIngester
from app.services.design_languages import VALID_LANGUAGES, resolve_design_language
from app.services.freeform_theme import derive_freeform_brand
from app.services.presentation_styles import VALID_STYLES, get_style, infer_style
from app.services.generation_editing_contract import GenerationEditingContract
from app.services.pptx_builder import PptxBuilder
from app.services.visual_qa_agent import VisualQAAgent


class JobOrchestrator:
    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore,
        storage: LocalStorage,
        ingester: DocumentIngester,
        planner: ContentPlanner,
        designer: DesignAgent,
        builder: PptxBuilder,
        qa_agent: VisualQAAgent,
    ) -> None:
        self.settings = settings
        self.store = store
        self.storage = storage
        self.ingester = ingester
        self.planner = planner
        self.deep_planner = self._build_deep_planner()
        self.designer = designer
        self.builder = builder
        self.qa_agent = qa_agent
        self.editing_contract = GenerationEditingContract()

    async def run_job(self, job_id: str) -> None:
        job = await self.store.get_job(job_id)
        if not job:
            return
        template = (
            self.freeform_template()
            if job.template_id == FREEFORM_TEMPLATE_ID
            else await self.store.get_template(job.template_id)
        )
        if not template:
            await self.store.update_job(
                job_id,
                status="error",
                error_message="Template not found for job.",
                completed_at=self._timestamp(),
            )
            return
        if self._render_from_plan(job):
            await self._render_planned_job(job, template)
            return
        document_paths = self._load_document_paths(job_id)
        await self._run_job(job, template, document_paths)

    async def _run_job(
        self,
        job: JobRecord,
        template: TemplateProfile,
        document_paths: Iterable[Path],
    ) -> None:
        planner: ContentPlanner | None = None
        try:
            await self.store.update_job(job.id, status="analyzing", progress=0.1)
            records, bundle = self.ingester.ingest_documents(job.id, document_paths)
            self.storage.save_document_bundle(job.id, bundle)
            for record in records:
                await self.store.add_job_document(record)
                if record.markdown_content:
                    self.storage.save_markdown(
                        job.id, record.id, record.markdown_content
                    )

            await self.store.update_job(job.id, status="planning", progress=0.3)
            presentation_style, design_language = self._resolve_style_design(job, bundle)
            await self._persist_style_design(job, presentation_style, design_language)
            generation_mode = self._generation_mode(job, template)
            template = self._template_for_generation(
                template, generation_mode, bundle, job, design_language, presentation_style
            )
            planner = self._planner_for_job(job)
            outlines, warnings = planner.plan(
                template,
                bundle,
                instructions=job.instructions or "",
                generation_mode=generation_mode,
                quality_profile=self._quality_profile(job),
                length_strategy=self._length_strategy(job),
                presentation_style=presentation_style,
            )
            if planner.last_planning_artifacts:
                self.storage.save_planning_artifacts(
                    job.id,
                    planner.last_planning_artifacts,
                )
            outlines = planner.repair_weak_outline_claims(outlines, bundle)
            outlines = self.designer.apply_design(outlines)
            outlines, consulting_warnings = self._run_consulting_qa_repairs(
                outlines, bundle
            )
            outlines = self.designer.apply_editing_contract(outlines)
            outlines = self.builder.prepare_outlines(template, outlines)
            if consulting_warnings:
                warnings = self._merge_warnings(warnings, consulting_warnings)
            contract = self._save_editing_contract(job.id, template, outlines, "planned")
            warnings = self._merge_warnings(
                warnings,
                self._editing_contract_warnings(contract),
            )
            await self.store.add_slide_outlines(outlines)

            if self._plan_only(job):
                await self.store.update_job(
                    job.id,
                    status="planned",
                    progress=0.5,
                    qa_rounds=0,
                    warnings_json=warnings,
                    result_file=None,
                    preview_dir=None,
                    error_message=None,
                    completed_at=self._timestamp(),
                )
                return

            await self._render_outlines(job, template, outlines, bundle, warnings)
        except Exception as exc:
            if planner is not None and planner.last_planning_artifacts:
                self.storage.save_planning_artifacts(
                    job.id,
                    planner.last_planning_artifacts,
                )
            await self.store.update_job(
                job.id, status="error", error_message=str(exc), completed_at=self._timestamp()
            )

    async def _render_planned_job(
        self,
        job: JobRecord,
        template: TemplateProfile,
    ) -> None:
        try:
            bundle = self.storage.load_document_bundle(job.id)
            if bundle is None:
                raise RuntimeError("Planned job is missing its persisted source bundle.")
            generation_mode = self._generation_mode(job, template)
            presentation_style, design_language = self._resolve_style_design(job, bundle)
            template = self._template_for_generation(
                template, generation_mode, bundle, job, design_language, presentation_style
            )
            outlines = await self.store.list_slide_outlines(job.id)
            if not outlines:
                raise RuntimeError("Planned job is missing slide outlines.")
            outlines = self.planner.repair_weak_outline_claims(outlines, bundle)
            outlines = self.designer.apply_editing_contract(outlines)
            outlines = self.builder.prepare_outlines(template, outlines)
            await self._render_outlines(
                job,
                template,
                outlines,
                bundle,
                job.warnings or [],
            )
        except Exception as exc:
            await self.store.update_job(
                job.id,
                status="error",
                error_message=str(exc),
                completed_at=self._timestamp(),
            )

    async def _render_outlines(
        self,
        job: JobRecord,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        bundle: DocumentBundle,
        warnings: list[dict],
    ) -> None:
        working_dir = self.storage.job_dir(job.id)
        working_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.storage.output_pptx_path(job.id)
        outlines = self.planner.repair_weak_outline_claims(outlines, bundle)
        outlines = self.builder.prepare_outlines(template, outlines)
        self.storage.save_outline_snapshot(job.id, "render-input", outlines)
        contract = self._save_editing_contract(job.id, template, outlines, "render-input")
        warnings = self._merge_warnings(
            warnings,
            self._editing_contract_warnings(contract),
        )
        await self.store.update_job(
            job.id, status="generating", progress=0.55, warnings_json=warnings
        )
        strict_warnings = self.builder.build_deck(template, outlines, output_path, working_dir)
        if strict_warnings:
            warnings = self._merge_warnings(warnings, strict_warnings)
            await self.store.update_job(job.id, warnings_json=warnings)

        await self.store.update_job(job.id, status="qa", progress=0.75)
        qa_round = 0
        if self._run_visual_qa(job):
            qa_result, images = self.qa_agent.inspect_deck(
                output_path, working_dir / "preview", outlines
            )
            seen_actionable_signatures: set[tuple[tuple[int, str, str], ...]] = set()
            while True:
                actionable_signature = self._actionable_qa_signature(qa_result)
                if qa_round >= self.settings.qa_max_rounds:
                    self._save_qa_round_log(
                        job.id,
                        qa_round,
                        qa_result,
                        actionable_signature,
                        repair_applied=False,
                        stop_reason="max_rounds",
                    )
                    break
                if not actionable_signature:
                    self._save_qa_round_log(
                        job.id,
                        qa_round,
                        qa_result,
                        actionable_signature,
                        repair_applied=False,
                        stop_reason="no_actionable_issues",
                    )
                    break
                if actionable_signature in seen_actionable_signatures:
                    self._save_qa_round_log(
                        job.id,
                        qa_round,
                        qa_result,
                        actionable_signature,
                        repair_applied=False,
                        stop_reason="repeated_actionable_signature",
                    )
                    break
                seen_actionable_signatures.add(actionable_signature)
                self._save_qa_round_log(
                    job.id,
                    qa_round,
                    qa_result,
                    actionable_signature,
                    repair_applied=True,
                    stop_reason="repair_applied",
                )
                qa_round += 1
                await self.store.update_job(
                    job.id,
                    status="repairing",
                    progress=min(0.9, 0.75 + (qa_round * 0.08)),
                )
                outlines = self._apply_qa_fixes(outlines, qa_result, bundle)
                outlines, consulting_warnings = self._run_consulting_qa_repairs(
                    outlines, bundle
                )
                outlines = self.designer.apply_editing_contract(outlines)
                outlines = self.builder.prepare_outlines(template, outlines)
                self.storage.save_outline_snapshot(
                    job.id,
                    f"repair-round-{qa_round}",
                    outlines,
                )
                if consulting_warnings:
                    warnings = self._merge_warnings(warnings, consulting_warnings)
                    await self.store.update_job(job.id, warnings_json=warnings)
                await self._persist_slide_outlines(outlines, qa_result)
                contract = self._save_editing_contract(
                    job.id,
                    template,
                    outlines,
                    f"repair-round-{qa_round}",
                )
                contract_warnings = self._editing_contract_warnings(contract)
                if contract_warnings:
                    warnings = self._merge_warnings(warnings, contract_warnings)
                    await self.store.update_job(job.id, warnings_json=warnings)
                strict_warnings = self.builder.build_deck(
                    template, outlines, output_path, working_dir
                )
                if strict_warnings:
                    warnings = self._merge_warnings(warnings, strict_warnings)
                    await self.store.update_job(job.id, warnings_json=warnings)
                await self.store.update_job(
                    job.id,
                    status="qa",
                    progress=min(0.95, 0.8 + (qa_round * 0.08)),
                )
                qa_result, images = self.qa_agent.inspect_deck(
                    output_path, working_dir / "preview", outlines
                )
        else:
            qa_result, images = self.qa_agent.inspect_deck(
                output_path,
                working_dir / "preview",
                outlines,
            )
            self._save_qa_round_log(
                job.id,
                qa_round,
                qa_result,
                self._actionable_qa_signature(qa_result),
                repair_applied=False,
                stop_reason="repair_loop_disabled",
            )
        await self._persist_slide_outlines(outlines, qa_result)
        contract = self._save_editing_contract(job.id, template, outlines, "final")
        contract_warnings = self._editing_contract_warnings(contract)
        if contract_warnings:
            warnings = self._merge_warnings(warnings, contract_warnings)
            await self.store.update_job(job.id, warnings_json=warnings)
        self.storage.save_preview_images(job.id, images)
        pdf_path = self.qa_agent.export_pdf(output_path, working_dir)
        if pdf_path and pdf_path != output_path.with_suffix(".pdf"):
            output_path.with_suffix(".pdf").write_bytes(pdf_path.read_bytes())

        final_status, final_error = self._final_status_for_review(
            qa_result,
            contract_warnings,
        )
        await self.store.update_job(
            job.id,
            status=final_status,
            progress=1.0,
            qa_rounds=qa_round,
            result_file=output_path.as_posix(),
            preview_dir=(working_dir / "preview").as_posix(),
            error_message=final_error,
            completed_at=self._timestamp(),
        )

    async def regenerate_slide(
        self,
        job_id: str,
        template: TemplateProfile,
        slide_index: int,
    ) -> None:
        outlines = await self.store.list_slide_outlines(job_id)
        updated = []
        for outline in outlines:
            if outline.slide_index == slide_index and outline.mode == "flexible":
                updated.append(self.designer.revise_for_qa(outline))
            else:
                updated.append(outline)
        working_dir = self.storage.job_dir(job_id)
        output_path = self.storage.output_pptx_path(job_id)
        strict_warnings = self.builder.build_deck(template, updated, output_path, working_dir)
        qa_result, images = self.qa_agent.inspect_deck(
            output_path, working_dir / "preview", updated
        )
        self.storage.save_preview_images(job_id, images)
        pdf_path = self.qa_agent.export_pdf(output_path, working_dir)
        if pdf_path and pdf_path != output_path.with_suffix(".pdf"):
            output_path.with_suffix(".pdf").write_bytes(pdf_path.read_bytes())
        contract = self._save_editing_contract(job_id, template, updated, "regen-final")
        contract_warnings = self._editing_contract_warnings(contract)
        warnings = self._merge_warnings(strict_warnings, contract_warnings)
        final_status, final_error = self._final_status_for_review(
            qa_result,
            contract_warnings,
        )
        await self.store.update_job(
            job_id,
            status=final_status,
            progress=1.0,
            warnings_json=warnings,
            result_file=output_path.as_posix(),
            preview_dir=(working_dir / "preview").as_posix(),
            error_message=final_error,
            completed_at=self._timestamp(),
        )

    def _apply_qa_fixes(
        self,
        outlines: list[SlideOutline],
        qa_result,
        bundle: DocumentBundle,
    ) -> list[SlideOutline]:
        revised = self.designer.revise_deck_for_qa(outlines, qa_result.issues)
        return self.planner.repair_outlines_for_visual_qa(
            revised,
            qa_result.issues,
            bundle,
        )

    def _save_editing_contract(
        self,
        job_id: str,
        template: TemplateProfile,
        outlines: list[SlideOutline],
        phase: str,
    ) -> dict:
        contract = self.editing_contract.build(
            template,
            outlines,
            phase=phase,
        )
        self.storage.save_planning_artifacts(
            job_id,
            {"editing-contract": contract},
        )
        return contract

    def _editing_contract_warnings(self, contract: dict) -> list[dict]:
        warnings = []
        for requirement in contract.get("requirements", []):
            if not isinstance(requirement, dict):
                continue
            if requirement.get("status") != "warning":
                continue
            warnings.append(
                {
                    "slide_index": None,
                    "field": "editing_contract",
                    "severity": "WARNING",
                    "message": requirement.get("message")
                    or requirement.get("label")
                    or "Claude-style editing contract warning.",
                }
            )
        return warnings

    def _final_status_for_review(
        self,
        qa_result,
        editing_contract_warnings: list[dict] | None = None,
    ) -> tuple[str, str | None]:
        actionable = self._actionable_qa_signature(qa_result)
        contract_issue_count = len(editing_contract_warnings or [])
        if qa_result.passed and not actionable and contract_issue_count == 0:
            return "done", None
        issue_count = len(actionable) or sum(
            1 for issue in qa_result.issues if issue.severity == "CRITICAL"
        )
        issue_count += contract_issue_count
        if contract_issue_count and qa_result.passed and not actionable:
            return (
                "review_failed",
                (
                    "Deck generated but failed final review with "
                    f"{contract_issue_count} unresolved editing contract issue(s)."
                ),
            )
        return (
            "review_failed",
            f"Deck generated but failed final review with {issue_count} unresolved issue(s).",
        )

    def _save_qa_round_log(
        self,
        job_id: str,
        round_number: int,
        qa_result,
        actionable_signature: tuple[tuple[int, str, str], ...],
        repair_applied: bool,
        stop_reason: str,
    ) -> None:
        payload = qa_result.model_dump()
        payload["actionable_issue_count"] = len(actionable_signature)
        payload["repair_applied"] = repair_applied
        payload["stop_reason"] = stop_reason
        self.storage.save_qa_log(
            job_id,
            round_number,
            json.dumps(payload, ensure_ascii=True),
        )

    def _run_consulting_qa_repairs(
        self,
        outlines: list[SlideOutline],
        bundle,
    ) -> tuple[list[SlideOutline], list[dict]]:
        warnings: list[dict] = []
        seen_signatures: set[tuple[tuple[int, str, str], ...]] = set()
        repaired = outlines
        for round_index in range(max(1, self.settings.qa_max_rounds)):
            issues = self.planner.consulting_issues_for_outlines(repaired, bundle)
            signature = self._consulting_issue_signature(issues)
            if not signature:
                break
            warnings.extend(self._consulting_warnings(issues, round_index))
            if signature in seen_signatures:
                break
            seen_signatures.add(signature)
            repaired = self.planner.repair_outlines_for_consulting(
                repaired,
                issues,
                bundle,
            )
            repaired = self.designer.apply_design(repaired)
        return repaired, warnings

    def _has_actionable_qa_issues(self, qa_result) -> bool:
        return bool(self._actionable_qa_signature(qa_result))

    def _actionable_qa_signature(
        self, qa_result
    ) -> tuple[tuple[int, str, str], ...]:
        return tuple(
            sorted(
                (
                    -1 if issue.slide_index is None else issue.slide_index,
                    issue.category or "",
                    " ".join(issue.message.lower().split())[:160],
                )
                for issue in qa_result.issues
                if issue.severity == "CRITICAL"
                or self.designer.is_actionable_qa_issue(issue)
            )
        )

    def _consulting_issue_signature(
        self, issues
    ) -> tuple[tuple[int, str, str], ...]:
        return tuple(
            sorted(
                (
                    -1 if issue.slide_index is None else issue.slide_index,
                    issue.category or "",
                    " ".join(issue.message.lower().split())[:160],
                )
                for issue in issues
                if issue.severity in {"CRITICAL", "WARNING"}
            )
        )

    def _consulting_warnings(self, issues, round_index: int) -> list[dict]:
        return [
            {
                "slide_index": issue.slide_index,
                "field": "consulting_qa",
                "message": f"Round {round_index}: {issue.message}",
            }
            for issue in issues
            if issue.severity in {"CRITICAL", "WARNING"}
        ]

    async def _persist_slide_outlines(
        self, outlines: list[SlideOutline], qa_result
    ) -> None:
        issues_by_slide: dict[int, list[dict]] = {}
        for issue in qa_result.issues:
            if issue.slide_index is None:
                continue
            issues_by_slide.setdefault(issue.slide_index, []).append(issue.model_dump())
        for outline in outlines:
            await self.store.update_slide_outline(
                outline.id,
                content_json=outline.content_json,
                layout_json=outline.layout_json,
                qa_status="warning" if issues_by_slide.get(outline.slide_index) else "pass",
                qa_issues_json={"issues": issues_by_slide.get(outline.slide_index, [])},
            )

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _load_document_paths(self, job_id: str) -> list[Path]:
        doc_dir = self.storage.job_dir(job_id) / "documents"
        if not doc_dir.exists():
            return []
        return sorted([path for path in doc_dir.iterdir() if path.is_file()])

    def _merge_warnings(
        self, existing: list[dict], incoming: list[dict]
    ) -> list[dict]:
        merged = list(existing)
        seen = {str(item) for item in merged}
        for warning in incoming:
            key = str(warning)
            if key in seen:
                continue
            seen.add(key)
            merged.append(warning)
        return merged

    def _generation_mode(self, job: JobRecord, template: TemplateProfile) -> str:
        if job.config_json and job.config_json.get("generation_mode"):
            return str(job.config_json["generation_mode"])
        return template.type

    def _template_for_generation(
        self,
        template: TemplateProfile,
        generation_mode: str,
        bundle: DocumentBundle,
        job: JobRecord,
        design_language: str = "auto",
        presentation_style: str = "consulting",
    ) -> TemplateProfile:
        if generation_mode != "freeform":
            return template
        return template.model_copy(
            update={
                "brand": derive_freeform_brand(
                    bundle,
                    job.instructions or "",
                    design_language=design_language,
                    presentation_style=presentation_style,
                ),
            }
        )

    def _planner_for_job(self, job: JobRecord) -> ContentPlanner:
        if self._planner_profile(job) == "deep" and self.deep_planner is not None:
            return self.deep_planner
        return self.planner

    def _planner_profile(self, job: JobRecord) -> str:
        if job.config_json and job.config_json.get("planner_profile"):
            profile = str(job.config_json["planner_profile"]).strip().lower()
            if profile in {"fast", "deep"}:
                return profile
        return "fast"

    def _quality_profile(self, job: JobRecord) -> str:
        if job.config_json and job.config_json.get("quality_profile"):
            profile = str(job.config_json["quality_profile"]).strip().lower()
            if profile in {"fast", "balanced", "showcase"}:
                return profile
        return "balanced"

    def _length_strategy(self, job: JobRecord) -> str:
        if job.config_json and job.config_json.get("length_strategy"):
            strategy = str(job.config_json["length_strategy"]).strip().lower()
            if strategy in {"auto", "concise", "expanded"}:
                return strategy
        return "auto"

    def _run_visual_qa(self, job: JobRecord) -> bool:
        if job.config_json and "run_visual_qa" in job.config_json:
            return bool(job.config_json["run_visual_qa"])
        return True

    def _plan_only(self, job: JobRecord) -> bool:
        return bool(job.config_json and job.config_json.get("plan_only"))

    def _render_from_plan(self, job: JobRecord) -> bool:
        return bool(job.config_json and job.config_json.get("render_from_plan"))

    def _presentation_style(self, job: JobRecord) -> str:
        if job.config_json and job.config_json.get("presentation_style"):
            value = str(job.config_json["presentation_style"]).strip().lower()
            if value in VALID_STYLES:
                return value
        return "auto"

    def _design_language(self, job: JobRecord) -> str:
        if job.config_json and job.config_json.get("design_language"):
            value = str(job.config_json["design_language"]).strip().lower()
            if value in VALID_LANGUAGES:
                return value
        return "auto"

    def _style_topic_text(self, bundle: DocumentBundle, instructions: str) -> str:
        parts = [instructions, bundle.metadata.title or ""]
        parts.extend(section.title for section in bundle.sections[:20])
        return " ".join(parts)

    def _resolve_style_design(self, job: JobRecord, bundle: DocumentBundle) -> tuple[str, str]:
        """Resolve "auto" style/design to concrete values from the brief + topic."""
        topic_text = self._style_topic_text(bundle, job.instructions or "")
        raw_style = self._presentation_style(job)
        style = infer_style(topic_text) if raw_style == "auto" else raw_style
        raw_language = self._design_language(job)
        style_default = get_style(style).default_design_language
        language = resolve_design_language(raw_language, style_default, topic_text)
        return style, language

    async def _persist_style_design(self, job: JobRecord, style: str, language: str) -> None:
        config = dict(job.config_json or {})
        if config.get("presentation_style") == style and config.get("design_language") == language:
            return
        config["presentation_style"] = style
        config["design_language"] = language
        await self.store.update_job(job.id, config_json=config)
        job.config_json = config

    def _build_deep_planner(self) -> ContentPlanner | None:
        if self.settings.llm_provider != "openai_compatible":
            return None
        deep_settings = self.settings.model_copy(
            update={
                "openai_compatible_base_url": self.settings.deep_planner_base_url,
                "openai_compatible_model": self.settings.deep_planner_model,
                "openai_compatible_timeout_seconds": self.settings.deep_planner_timeout_seconds,
                "openai_compatible_reasoning_effort": self.settings.deep_planner_reasoning_effort,
            }
        )
        return ContentPlanner(
            llm_client=OpenAICompatibleClient(deep_settings),
            slide_generation_strategy="per_slide",
            decompose=self.settings.planner_decompose,
        )

    def freeform_template(self) -> TemplateProfile:
        timestamp = self._timestamp()
        return TemplateProfile(
            id=FREEFORM_TEMPLATE_ID,
            name="Freeform",
            type="freeform",
            brand=BrandDNA(),
            slides=[],
            source_file="",
            created_at=timestamp,
            updated_at=timestamp,
        )
