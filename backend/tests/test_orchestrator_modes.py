from datetime import UTC, datetime
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Inches

from app.config import Settings
from app.infra.local_storage import LocalStorage
from app.infra.sqlite_store import SQLiteStore
from app.models.brand import BrandDNA
from app.models.document import DocumentBundle, DocumentMetadata, DocumentSection
from app.models.job import FREEFORM_TEMPLATE_ID, JobRecord
from app.models.outline import SlideOutline
from app.models.qa import QAIssue, QAResult
from app.models.template import SlideField, SlideSchema, SlideSpec, TemplateProfile
from app.services.content_planner import ContentPlanner
from app.services.design_agent import DesignAgent
from app.services.orchestrator import JobOrchestrator
from app.services.pptx_builder import PptxBuilder
from app.services.visual_qa_agent import VisualQAAgent


class StaticIngester:
    def ingest_documents(self, job_id: str, file_paths: list[Path]) -> tuple[list, DocumentBundle]:
        return [], DocumentBundle(
            job_id=job_id,
            sections=[
                DocumentSection(
                    title="Vibe Coding Risk",
                    level=1,
                    content=(
                        "Vibe coding accelerates prototypes but fails in production "
                        "when teams lose context, skip review, and cannot reproduce AI decisions."
                    ),
                    source_doc_id="doc-1",
                ),
                DocumentSection(
                    title="External Brain",
                    level=1,
                    content=(
                        "A memory bank and structured specification workflow preserve "
                        "context so AI agents can deliver reliable software across sessions."
                    ),
                    source_doc_id="doc-1",
                ),
            ],
            tables=[],
            metrics=[],
            metadata=DocumentMetadata(title="Beyond Vibe Coding"),
            content_inventory=[],
        )


class WarningThenCleanQAAgent:
    def __init__(self) -> None:
        self.calls = 0

    def inspect_deck(self, output_path, output_dir, outlines):
        self.calls += 1
        if self.calls == 1:
            return (
                QAResult(
                    passed=True,
                    issues=[
                        QAIssue(
                            severity="WARNING",
                            category="text_wall",
                            message="Slide reads as a text wall.",
                            slide_index=0,
                        )
                    ],
                ),
                [],
            )
        return QAResult(passed=True, issues=[]), []

    def export_pdf(self, output_path, working_dir):
        return None


class CleanQAAgent:
    def inspect_deck(self, output_path, output_dir, outlines):
        return QAResult(passed=True, issues=[]), []

    def export_pdf(self, output_path, working_dir):
        return None


class DuplicateOutlinePlanner(ContentPlanner):
    def plan(
        self,
        template: TemplateProfile,
        bundle: DocumentBundle,
        instructions: str = "",
        generation_mode: str | None = None,
        quality_profile: str = "balanced",
        length_strategy: str = "auto",
    ):
        created_at = "2026-01-01T00:00:00Z"
        outlines = []
        for index in range(2):
            outlines.append(
                SlideOutline(
                    id=f"weak-outline-{index}",
                    job_id=bundle.job_id,
                    slide_index=index,
                    mode="flexible",
                    label="Overview",
                    content_json={
                        "action_title": "Overview",
                        "title": "Overview",
                        "narrative_role": "evidence",
                        "archetype": "comparison_table",
                        "bullets": ["Preserve context before work begins"],
                        "content_blocks": [
                            {
                                "type": "bullets",
                                "body": ["Preserve context before work begins"],
                            }
                        ],
                        "sources": ["Uploaded source"],
                    },
                    layout_json={
                        "layout": "comparison_table",
                        "archetype": "comparison_table",
                    },
                    created_at=created_at,
                )
            )
        return outlines, []


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        sqlite_path=tmp_path / "data" / "jobs.sqlite",
        templates_dir=tmp_path / "data" / "templates",
        jobs_dir=tmp_path / "data" / "jobs",
        LLM_PROVIDER="none",
        BEDROCK_VALIDATE=False,
    )


def test_orchestrator_selects_deep_planner_profile(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        sqlite_path=tmp_path / "data" / "jobs.sqlite",
        templates_dir=tmp_path / "data" / "templates",
        jobs_dir=tmp_path / "data" / "jobs",
        LLM_PROVIDER="openai_compatible",
        DEEP_PLANNER_BASE_URL="http://athena.local:1240/v1",
        DEEP_PLANNER_MODEL="minimax-m2.7",
        BEDROCK_VALIDATE=False,
    )
    store = SQLiteStore(settings)
    storage = LocalStorage(settings)
    orchestrator = _orchestrator(settings, store, storage)
    job = _job("deep-job", FREEFORM_TEMPLATE_ID, "freeform")
    job.config_json = {"generation_mode": "freeform", "planner_profile": "deep"}

    planner = orchestrator._planner_for_job(job)

    assert planner is orchestrator.deep_planner
    assert planner.llm_client is not None
    assert planner.llm_client.base_url == "http://athena.local:1240/v1"
    assert planner.llm_client.model == "minimax-m2.7"


def _job(job_id: str, template_id: str, mode: str) -> JobRecord:
    return JobRecord(
        id=job_id,
        template_id=template_id,
        instructions="Create an executive deck about moving beyond vibe coding.",
        config_json={"generation_mode": mode},
        status="queued",
        progress=0,
        qa_rounds=0,
        warnings=[],
        created_at=_timestamp(),
    )


def _orchestrator(settings: Settings, store: SQLiteStore, storage: LocalStorage) -> JobOrchestrator:
    return JobOrchestrator(
        settings=settings,
        store=store,
        storage=storage,
        ingester=StaticIngester(),
        planner=ContentPlanner(),
        designer=DesignAgent(),
        builder=PptxBuilder(node_runner=object()),
        qa_agent=VisualQAAgent(),
    )


def _orchestrator_with_qa(
    settings: Settings,
    store: SQLiteStore,
    storage: LocalStorage,
    qa_agent,
) -> JobOrchestrator:
    return JobOrchestrator(
        settings=settings,
        store=store,
        storage=storage,
        ingester=StaticIngester(),
        planner=ContentPlanner(),
        designer=DesignAgent(),
        builder=PptxBuilder(node_runner=object()),
        qa_agent=qa_agent,
    )


@pytest.mark.asyncio
async def test_orchestrator_runs_freeform_job_without_template(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = SQLiteStore(settings)
    storage = LocalStorage(settings)
    await store.init()
    await store.create_job(_job("freeform-job", FREEFORM_TEMPLATE_ID, "freeform"))

    await _orchestrator(settings, store, storage).run_job("freeform-job")

    job = await store.get_job("freeform-job")
    outlines = await store.list_slide_outlines("freeform-job")

    assert job is not None
    assert job.status == "done"
    assert job.result_file
    assert Path(job.result_file).exists()
    assert outlines
    assert {outline.layout_json["generation_mode"] for outline in outlines} == {"freeform"}
    assert len(Presentation(job.result_file).slides) == len(outlines)
    assert list((storage.job_dir("freeform-job") / "preview").glob("slide-*.png"))


@pytest.mark.asyncio
async def test_orchestrator_repairs_actionable_warning_and_persists_outline(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    store = SQLiteStore(settings)
    storage = LocalStorage(settings)
    qa_agent = WarningThenCleanQAAgent()
    await store.init()
    await store.create_job(_job("repair-job", FREEFORM_TEMPLATE_ID, "freeform"))

    await _orchestrator_with_qa(settings, store, storage, qa_agent).run_job("repair-job")

    job = await store.get_job("repair-job")
    outlines = await store.list_slide_outlines("repair-job")

    assert job is not None
    assert job.status == "done"
    assert job.qa_rounds == 1
    assert qa_agent.calls == 2
    assert outlines[0].layout_json["qa_repair"]["applied"] is True
    assert (storage.job_dir("repair-job") / "qa" / "round-0.json").exists()
    assert (storage.job_dir("repair-job") / "qa" / "round-1.json").exists()


@pytest.mark.asyncio
async def test_orchestrator_repairs_consulting_issues_before_build(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    store = SQLiteStore(settings)
    storage = LocalStorage(settings)
    await store.init()
    await store.create_job(_job("consulting-repair-job", FREEFORM_TEMPLATE_ID, "freeform"))
    orchestrator = JobOrchestrator(
        settings=settings,
        store=store,
        storage=storage,
        ingester=StaticIngester(),
        planner=DuplicateOutlinePlanner(),
        designer=DesignAgent(),
        builder=PptxBuilder(node_runner=object()),
        qa_agent=CleanQAAgent(),
    )

    await orchestrator.run_job("consulting-repair-job")

    job = await store.get_job("consulting-repair-job")
    outlines = await store.list_slide_outlines("consulting-repair-job")

    assert job is not None
    assert job.status == "done"
    assert job.result_file
    assert Path(job.result_file).exists()
    assert len({outline.label for outline in outlines}) == len(outlines)
    assert all(outline.label != "Overview" for outline in outlines)
    assert all(outline.content_json.get("source_refs") for outline in outlines)
    assert all(outline.content_json.get("exhibit_spec") for outline in outlines)
    assert any(warning["field"] == "consulting_qa" for warning in job.warnings)


@pytest.mark.asyncio
async def test_orchestrator_runs_brand_job_from_template_profile(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = SQLiteStore(settings)
    storage = LocalStorage(settings)
    await store.init()
    template = TemplateProfile(
        id="brand-template",
        name="Brand Template",
        type="brand",
        brand=BrandDNA(primary_color="#111827", secondary_color="#2563eb"),
        slides=[],
        source_file="",
        created_at=_timestamp(),
        updated_at=_timestamp(),
    )
    await store.create_template(template)
    await store.create_job(_job("brand-job", "brand-template", "brand"))

    await _orchestrator(settings, store, storage).run_job("brand-job")

    job = await store.get_job("brand-job")
    outlines = await store.list_slide_outlines("brand-job")

    assert job is not None
    assert job.status == "done"
    assert job.result_file
    assert Path(job.result_file).exists()
    assert outlines
    assert {outline.layout_json["generation_mode"] for outline in outlines} == {"brand"}
    assert len(Presentation(job.result_file).slides) == len(outlines)


@pytest.mark.asyncio
async def test_orchestrator_runs_strict_job_with_xml_injection(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = SQLiteStore(settings)
    storage = LocalStorage(settings)
    await store.init()
    template_path = tmp_path / "strict-template.pptx"
    _write_strict_template(template_path)
    template = TemplateProfile(
        id="strict-template",
        name="Strict Template",
        type="strict",
        brand=BrandDNA(),
        source_file=template_path.as_posix(),
        slides=[
            SlideSpec(
                index=0,
                mode="strict",
                label="Executive Summary",
                schema=SlideSchema(
                    fields=[
                        SlideField(
                            id="project_title",
                            type="text",
                            location="shape:ProjectTitle",
                            required=True,
                            max_chars=90,
                        ),
                        SlideField(
                            id="executive_summary",
                            type="text",
                            location="shape:ExecutiveSummary",
                            required=True,
                            max_chars=260,
                        ),
                        SlideField(
                            id="key_implication",
                            type="text",
                            location="shape:KeyImplication",
                            required=True,
                            max_chars=260,
                        ),
                    ]
                ),
            )
        ],
        created_at=_timestamp(),
        updated_at=_timestamp(),
    )
    await store.create_template(template)
    await store.create_job(_job("strict-job", "strict-template", "strict"))

    await _orchestrator(settings, store, storage).run_job("strict-job")

    job = await store.get_job("strict-job")
    outlines = await store.list_slide_outlines("strict-job")

    assert job is not None
    assert job.status == "done"
    assert job.result_file
    rendered = Presentation(job.result_file)
    texts = [shape.text for shape in rendered.slides[0].shapes if shape.has_text_frame]
    assert outlines[0].mode == "strict"
    assert "Beyond Vibe Coding" in texts
    assert any("Vibe coding" in text for text in texts)


def _write_strict_template(path: Path) -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    for name, text, top in [
        ("ProjectTitle", "Old project title", 0.7),
        ("ExecutiveSummary", "Old summary", 1.6),
        ("KeyImplication", "Old implication", 4.2),
    ]:
        box = slide.shapes.add_textbox(Inches(0.8), Inches(top), Inches(11.5), Inches(0.8))
        box.name = name
        box.text = text
    prs.save(path.as_posix())
