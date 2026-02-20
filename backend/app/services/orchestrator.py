from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.config import Settings
from app.infra.local_storage import LocalStorage
from app.infra.sqlite_store import SQLiteStore
from app.models.job import JobRecord
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
        self.designer = designer
        self.builder = builder
        self.qa_agent = qa_agent

    async def run_job(self, job_id: str) -> None:
        job = await self.store.get_job(job_id)
        if not job:
            return
        template = await self.store.get_template(job.template_id)
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
            outlines, warnings = self.planner.plan(template, bundle)
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
            qa_result, images = self.qa_agent.inspect_deck(
                output_path, working_dir / "preview", outlines
            )
            while not qa_result.passed and qa_round < self.settings.qa_max_rounds:
                qa_round += 1
                outlines = self._apply_qa_fixes(outlines, qa_result)
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

    def _apply_qa_fixes(
        self, outlines: list[SlideOutline], qa_result
    ) -> list[SlideOutline]:
        issues_by_slide = {
            issue.slide_index
            for issue in qa_result.issues
            if issue.severity == "CRITICAL" and issue.slide_index is not None
        }
        updated = []
        for outline in outlines:
            if outline.slide_index in issues_by_slide:
                updated.append(self.designer.revise_for_qa(outline))
            else:
                updated.append(outline)
        return updated

    def _timestamp(self) -> str:
        return datetime.utcnow().isoformat() + "Z"

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
