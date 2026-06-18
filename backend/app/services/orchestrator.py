from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from app.config import Settings
from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.infra.local_storage import LocalStorage
from app.infra.sqlite_store import SQLiteStore
from app.models.brand import BrandDNA
from app.models.job import JobRecord
from app.models.job import FREEFORM_TEMPLATE_ID
from app.models.outline import SlideOutline
from app.models.template import TemplateProfile
from app.services.content_planner import ContentPlanner
from app.services.design_agent import DesignAgent
from app.services.document_ingester import DocumentIngester
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

    async def run_job(self, job_id: str) -> None:
        job = await self.store.get_job(job_id)
        if not job:
            return
        template = (
            self._freeform_template()
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
        document_paths = self._load_document_paths(job_id)
        await self._run_job(job, template, document_paths)

    async def _run_job(
        self,
        job: JobRecord,
        template: TemplateProfile,
        document_paths: Iterable[Path],
    ) -> None:
        try:
            await self.store.update_job(job.id, status="analyzing", progress=0.1)
            records, bundle = self.ingester.ingest_documents(job.id, document_paths)
            for record in records:
                await self.store.add_job_document(record)
                if record.markdown_content:
                    self.storage.save_markdown(
                        job.id, record.id, record.markdown_content
                    )

            await self.store.update_job(job.id, status="planning", progress=0.3)
            generation_mode = self._generation_mode(job, template)
            planner = self._planner_for_job(job)
            outlines, warnings = planner.plan(
                template,
                bundle,
                instructions=job.instructions or "",
                generation_mode=generation_mode,
                quality_profile=self._quality_profile(job),
                length_strategy=self._length_strategy(job),
            )
            outlines = self.designer.apply_design(outlines)
            await self.store.add_slide_outlines(outlines)

            await self.store.update_job(
                job.id, status="generating", progress=0.55, warnings_json=warnings
            )
            working_dir = self.storage.job_dir(job.id)
            working_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.storage.output_pptx_path(job.id)
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
                self.storage.save_qa_log(job.id, qa_round, qa_result.model_dump_json())
                seen_actionable_signatures: set[tuple[tuple[int | None, str, str], ...]] = set()
                while qa_round < self.settings.qa_max_rounds:
                    actionable_signature = self._actionable_qa_signature(qa_result)
                    if (
                        not actionable_signature
                        or actionable_signature in seen_actionable_signatures
                    ):
                        break
                    seen_actionable_signatures.add(actionable_signature)
                    qa_round += 1
                    outlines = self._apply_qa_fixes(outlines, qa_result)
                    await self._persist_slide_outlines(outlines, qa_result)
                    strict_warnings = self.builder.build_deck(
                        template, outlines, output_path, working_dir
                    )
                    if strict_warnings:
                        warnings = self._merge_warnings(warnings, strict_warnings)
                        await self.store.update_job(job.id, warnings_json=warnings)
                    qa_result, images = self.qa_agent.inspect_deck(
                        output_path, working_dir / "preview", outlines
                    )
                    self.storage.save_qa_log(job.id, qa_round, qa_result.model_dump_json())
            else:
                qa_result, images = self.qa_agent.inspect_deck(
                    output_path,
                    working_dir / "preview",
                    outlines,
                )
                self.storage.save_qa_log(job.id, qa_round, qa_result.model_dump_json())
            self.storage.save_preview_images(job.id, images)
            pdf_path = self.qa_agent.export_pdf(output_path, working_dir)
            if pdf_path and pdf_path != output_path.with_suffix(".pdf"):
                output_path.with_suffix(".pdf").write_bytes(pdf_path.read_bytes())

            await self.store.update_job(
                job.id,
                status="done",
                progress=1.0,
                qa_rounds=qa_round,
                result_file=output_path.as_posix(),
                preview_dir=(working_dir / "preview").as_posix(),
                completed_at=self._timestamp(),
            )
        except Exception as exc:
            await self.store.update_job(
                job.id, status="error", error_message=str(exc), completed_at=self._timestamp()
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
        await self.store.update_job(
            job_id,
            status="done",
            progress=1.0,
            warnings_json=strict_warnings,
            result_file=output_path.as_posix(),
            preview_dir=(working_dir / "preview").as_posix(),
            completed_at=self._timestamp(),
        )

    def _apply_qa_fixes(self, outlines: list[SlideOutline], qa_result) -> list[SlideOutline]:
        return self.designer.revise_deck_for_qa(outlines, qa_result.issues)

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
        return ContentPlanner(llm_client=OpenAICompatibleClient(deep_settings))

    def _freeform_template(self) -> TemplateProfile:
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
