import json

import pytest
from fastapi import HTTPException

from app.models.brand import BrandDNA
from app.models.job import FREEFORM_TEMPLATE_ID, JobRecord
from app.models.outline import SlideOutline
from app.models.template import TemplateProfile
from app.routes.jobs import (
    OutlineEdit,
    OutlinePatchRequest,
    create_job,
    get_job_outline,
    get_job_status,
    get_planning_artifact,
    render_planned_job,
    update_job_outline,
)
from app.routes.templates import (
    get_template_assets,
    get_template_logo,
    get_template_thumbnail,
)


class DummyStore:
    def __init__(self) -> None:
        self.created: list[JobRecord] = []
        self.templates = {
            "brand-template": TemplateProfile(
                id="brand-template",
                name="Brand",
                type="brand",
                brand=BrandDNA(),
                slides=[],
                source_file="",
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            ),
            "strict-template": TemplateProfile(
                id="strict-template",
                name="Strict",
                type="strict",
                brand=BrandDNA(),
                slides=[],
                source_file="",
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            ),
        }

    async def get_template(self, template_id: str):
        return self.templates.get(template_id)

    async def create_job(self, job: JobRecord) -> None:
        self.created.append(job)


class DummyStorage:
    def __init__(self, root=None) -> None:
        self.saved: list[str] = []
        self.root = root

    def save_job_document(self, job_id: str, filename: str, content: bytes):
        self.saved.append(filename)

    def job_dir(self, job_id: str):
        return self.root / job_id

    def preview_dir(self, job_id: str):
        return self.job_dir(job_id) / "preview"

    def planning_artifact_path(self, job_id: str, artifact: str):
        return self.job_dir(job_id) / "planning" / f"{artifact}.json"

    def template_dir(self, template_id: str):
        return self.root / "templates" / template_id


class DummyQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


class StatusStore:
    def __init__(self, job: JobRecord, outlines: list[SlideOutline] | None = None) -> None:
        self.job = job
        self.outlines = outlines or []
        self.updated_jobs: list[dict] = []

    async def get_job(self, job_id: str):
        return self.job if job_id == self.job.id else None

    async def list_slide_outlines(self, job_id: str):
        return self.outlines if job_id == self.job.id else []

    async def update_slide_outline(self, outline_id: str, **fields):
        self.outlines = [
            outline.model_copy(update=fields) if outline.id == outline_id else outline
            for outline in self.outlines
        ]

    async def update_job(self, job_id: str, **fields):
        if job_id != self.job.id:
            return
        self.updated_jobs.append(fields)
        self.job = self.job.model_copy(update=fields)


def _status_job() -> JobRecord:
    return JobRecord(
        id="status-job",
        template_id=FREEFORM_TEMPLATE_ID,
        instructions="Create a deck.",
        config_json={"generation_mode": "freeform"},
        status="done",
        progress=1.0,
        qa_rounds=1,
        warnings=[],
        result_file="/tmp/output.pptx",
        preview_dir="/tmp/preview",
        error_message=None,
        created_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:01:00Z",
    )


@pytest.mark.asyncio
async def test_create_freeform_job_without_template() -> None:
    store = DummyStore()
    queue = DummyQueue()

    job = await create_job(
        template_id="",
        generation_mode="freeform",
        planner_profile="fast",
        instructions="Create a deck about agentic software development.",
        documents=None,
        store=store,
        storage=DummyStorage(),
        job_queue=queue,
    )

    assert job.template_id == FREEFORM_TEMPLATE_ID
    assert job.config_json == {
        "generation_mode": "freeform",
        "planner_profile": "fast",
        "quality_profile": "balanced",
        "length_strategy": "auto",
        "run_visual_qa": True,
        "plan_only": False,
    }
    assert store.created == [job]
    assert queue.enqueued == [job.id]


@pytest.mark.asyncio
async def test_create_template_mode_requires_template() -> None:
    with pytest.raises(HTTPException) as exc:
        await create_job(
            template_id="",
            generation_mode="brand",
            planner_profile="fast",
            instructions="Create a branded deck.",
            documents=None,
            store=DummyStore(),
            storage=DummyStorage(),
            job_queue=DummyQueue(),
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_job_rejects_invalid_planner_profile() -> None:
    with pytest.raises(HTTPException) as exc:
        await create_job(
            template_id="",
            generation_mode="freeform",
            planner_profile="slow-but-mysterious",
            instructions="Create a deck.",
            documents=None,
            store=DummyStore(),
            storage=DummyStorage(),
            job_queue=DummyQueue(),
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_brand_job_uses_template_mode() -> None:
    store = DummyStore()
    queue = DummyQueue()

    job = await create_job(
        template_id="brand-template",
        generation_mode="brand",
        planner_profile="fast",
        instructions="Create a branded deck.",
        documents=None,
        store=store,
        storage=DummyStorage(),
        job_queue=queue,
    )

    assert job.template_id == "brand-template"
    assert job.config_json == {
        "generation_mode": "brand",
        "planner_profile": "fast",
        "quality_profile": "balanced",
        "length_strategy": "auto",
        "run_visual_qa": True,
        "plan_only": False,
    }
    assert queue.enqueued == [job.id]


@pytest.mark.asyncio
async def test_create_brand_job_accepts_deep_planner_profile() -> None:
    store = DummyStore()
    queue = DummyQueue()

    job = await create_job(
        template_id="brand-template",
        generation_mode="brand",
        planner_profile="deep",
        instructions="Create a branded deck.",
        documents=None,
        store=store,
        storage=DummyStorage(),
        job_queue=queue,
    )

    assert job.config_json == {
        "generation_mode": "brand",
        "planner_profile": "deep",
        "quality_profile": "balanced",
        "length_strategy": "auto",
        "run_visual_qa": True,
        "plan_only": False,
    }


@pytest.mark.asyncio
async def test_create_job_accepts_quality_and_length_controls() -> None:
    store = DummyStore()
    queue = DummyQueue()

    job = await create_job(
        template_id="",
        generation_mode="freeform",
        planner_profile="fast",
        quality_profile="showcase",
        length_strategy="expanded",
        run_visual_qa=False,
        instructions="Create a showcase deck.",
        documents=None,
        store=store,
        storage=DummyStorage(),
        job_queue=queue,
    )

    assert job.config_json == {
        "generation_mode": "freeform",
        "planner_profile": "fast",
        "quality_profile": "showcase",
        "length_strategy": "expanded",
        "run_visual_qa": False,
        "plan_only": False,
    }


@pytest.mark.asyncio
async def test_create_plan_only_job_sets_config_flag() -> None:
    store = DummyStore()
    queue = DummyQueue()

    job = await create_job(
        template_id="",
        generation_mode="freeform",
        planner_profile="fast",
        plan_only=True,
        instructions="Preview the plan first.",
        documents=None,
        store=store,
        storage=DummyStorage(),
        job_queue=queue,
    )

    assert job.config_json["plan_only"] is True
    assert queue.enqueued == [job.id]


@pytest.mark.asyncio
async def test_create_plan_only_rejects_strict_mode() -> None:
    with pytest.raises(HTTPException) as exc:
        await create_job(
            template_id="strict-template",
            generation_mode="strict",
            planner_profile="fast",
            plan_only=True,
            instructions="Preview the plan first.",
            documents=None,
            store=DummyStore(),
            storage=DummyStorage(),
            job_queue=DummyQueue(),
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_get_job_status_returns_latest_qa_issues_and_summary(tmp_path) -> None:
    storage = DummyStorage(tmp_path)
    qa_dir = storage.job_dir("status-job") / "qa"
    qa_dir.mkdir(parents=True)
    (qa_dir / "round-0.json").write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "severity": "WARNING",
                        "message": "Old warning.",
                        "slide_index": 0,
                        "category": "old",
                    }
                ],
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    (qa_dir / "round-1.json").write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "severity": "CRITICAL",
                        "message": "Slide text overflows.",
                        "slide_index": 1,
                        "category": "overflow_risk",
                    },
                    {
                        "severity": "INFO",
                        "message": "Used approximate preview rendering.",
                        "slide_index": None,
                        "category": "render_fallback",
                    },
                ],
                "passed": False,
            }
        ),
        encoding="utf-8",
    )

    status = await get_job_status(
        "status-job",
        store=StatusStore(_status_job()),
        storage=storage,
    )

    assert status.qa_summary == {"critical": 1, "warning": 0, "info": 1, "count": 2}
    assert [issue.message for issue in status.qa_issues or []] == [
        "Slide text overflows.",
        "Used approximate preview rendering.",
    ]
    assert status.qa_issues[0].slide_index == 1
    assert status.qa_issues[0].category == "overflow_risk"
    assert status.qa_history == [
        {
            "round": 0,
            "passed": True,
            "summary": {"critical": 0, "warning": 1, "info": 0, "count": 1},
        },
        {
            "round": 1,
            "passed": False,
            "summary": {"critical": 1, "warning": 0, "info": 1, "count": 2},
        },
    ]


def _review_outline() -> SlideOutline:
    return SlideOutline(
        id="outline-1",
        job_id="status-job",
        slide_index=0,
        mode="flexible",
        label="Old title",
        content_json={
            "action_title": "Old title",
            "title": "Old title",
            "subheading": "Old subheading",
            "narrative_role": "evidence",
            "archetype": "comparison_table",
            "exhibit_spec": {"type": "comparison_table"},
            "sources": ["Uploaded source: Section 1"],
            "source_refs": ["sec-1"],
            "speaker_notes": "Use this as the talk track.",
        },
        layout_json={"layout": "comparison_table"},
        qa_status="warning",
        qa_issues_json={"issues": [{"category": "title", "message": "Too generic"}]},
        created_at="2026-01-01T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_outline_endpoint_returns_review_safe_slide_data() -> None:
    status = await get_job_outline(
        "status-job",
        store=StatusStore(_status_job(), outlines=[_review_outline()]),
    )

    assert status["slides"] == [
        {
            "slide_index": 0,
            "mode": "flexible",
            "label": "Old title",
            "action_title": "Old title",
            "subheading": "Old subheading",
            "narrative_role": "evidence",
            "layout": "comparison_table",
            "archetype": "comparison_table",
            "exhibit_type": "comparison_table",
            "sources": ["Uploaded source: Section 1"],
            "source_refs": ["sec-1"],
            "speaker_notes": "Use this as the talk track.",
            "qa_status": "warning",
            "qa_issues": [{"category": "title", "message": "Too generic"}],
        }
    ]


@pytest.mark.asyncio
async def test_outline_patch_only_updates_planned_jobs() -> None:
    planned = _status_job().model_copy(update={"status": "planned"})
    store = StatusStore(planned, outlines=[_review_outline()])

    response = await update_job_outline(
        "status-job",
        OutlinePatchRequest(
            slides=[
                OutlineEdit(
                    slide_index=0,
                    action_title="New decisive action title",
                    subheading="New subheading",
                )
            ]
        ),
        store=store,
    )

    assert response["slides"][0]["action_title"] == "New decisive action title"
    assert response["slides"][0]["subheading"] == "New subheading"
    assert store.outlines[0].label == "New decisive action title"
    assert store.outlines[0].content_json["title"] == "New decisive action title"


@pytest.mark.asyncio
async def test_outline_patch_rejects_non_planned_jobs() -> None:
    with pytest.raises(HTTPException) as exc:
        await update_job_outline(
            "status-job",
            OutlinePatchRequest(slides=[OutlineEdit(slide_index=0, action_title="Nope")]),
            store=StatusStore(_status_job(), outlines=[_review_outline()]),
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_render_planned_job_marks_resume_config_and_enqueues() -> None:
    planned = _status_job().model_copy(
        update={
            "status": "planned",
            "config_json": {"generation_mode": "freeform", "plan_only": True},
            "result_file": "/tmp/old.pptx",
            "preview_dir": "/tmp/old-preview",
        }
    )
    store = StatusStore(planned)
    queue = DummyQueue()

    job = await render_planned_job("status-job", store=store, job_queue=queue)

    assert job.status == "queued"
    assert job.progress == 0.5
    assert job.config_json == {
        "generation_mode": "freeform",
        "plan_only": False,
        "render_from_plan": True,
    }
    assert job.result_file is None
    assert job.preview_dir is None
    assert queue.enqueued == ["status-job"]


@pytest.mark.asyncio
async def test_get_job_status_returns_planning_summary(tmp_path) -> None:
    storage = DummyStorage(tmp_path)
    planning_dir = storage.job_dir("status-job") / "planning"
    planning_dir.mkdir(parents=True)
    (planning_dir / "source-compression.json").write_text(
        json.dumps(
            {
                "section_count": 10,
                "included_section_count": 4,
                "omitted_section_count": 6,
                "estimated_tokens": 1200,
            }
        ),
        encoding="utf-8",
    )
    (planning_dir / "story-map.json").write_text(
        json.dumps({"status": "fallback", "fallback_reason": "timeout"}),
        encoding="utf-8",
    )
    (planning_dir / "spec-gate.json").write_text(
        json.dumps(
            {
                "status": "repaired",
                "issue_count": 3,
                "repaired_count": 3,
                "unresolved_count": 0,
            }
        ),
        encoding="utf-8",
    )

    status = await get_job_status(
        "status-job",
        store=StatusStore(_status_job()),
        storage=storage,
    )

    assert status.planning_summary == {
        "available": True,
        "artifacts": ["source-compression", "story-map", "spec-gate"],
        "story_map_status": "fallback",
        "story_map_fallback_reason": "timeout",
        "source_coverage": {
            "section_count": 10,
            "included_section_count": 4,
            "omitted_section_count": 6,
            "estimated_tokens": 1200,
        },
        "spec_gate": {
            "status": "repaired",
            "issue_count": 3,
            "repaired_count": 3,
            "unresolved_count": 0,
        },
    }


@pytest.mark.asyncio
async def test_get_planning_artifact_returns_json(tmp_path) -> None:
    storage = DummyStorage(tmp_path)
    planning_dir = storage.job_dir("status-job") / "planning"
    planning_dir.mkdir(parents=True)
    (planning_dir / "story-map.json").write_text(
        json.dumps({"status": "fallback", "beats": []}),
        encoding="utf-8",
    )

    response = await get_planning_artifact(
        "status-job",
        "story-map",
        store=StatusStore(_status_job()),
        storage=storage,
    )

    assert json.loads(response.body) == {"status": "fallback", "beats": []}


@pytest.mark.asyncio
async def test_get_job_status_returns_empty_qa_when_log_missing(tmp_path) -> None:
    status = await get_job_status(
        "status-job",
        store=StatusStore(_status_job()),
        storage=DummyStorage(tmp_path),
    )

    assert status.qa_summary == {"critical": 0, "warning": 0, "info": 0, "count": 0}
    assert status.qa_issues == []


@pytest.mark.asyncio
async def test_get_job_status_returns_empty_qa_when_latest_log_is_malformed(tmp_path) -> None:
    storage = DummyStorage(tmp_path)
    qa_dir = storage.job_dir("status-job") / "qa"
    qa_dir.mkdir(parents=True)
    (qa_dir / "round-0.json").write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "severity": "WARNING",
                        "message": "Old warning.",
                        "slide_index": 0,
                        "category": "old",
                    }
                ],
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    (qa_dir / "round-1.json").write_text("{not json", encoding="utf-8")

    status = await get_job_status(
        "status-job",
        store=StatusStore(_status_job()),
        storage=storage,
    )

    assert status.qa_summary == {"critical": 0, "warning": 0, "info": 0, "count": 0}
    assert status.qa_issues == []


@pytest.mark.asyncio
async def test_template_asset_endpoints_return_thumbnails_and_logo(tmp_path) -> None:
    store = DummyStore()
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(b"png")
    store.templates["brand-template"].brand = BrandDNA(logo={"path": logo_path.as_posix()})
    storage = DummyStorage(tmp_path)
    thumb_dir = storage.template_dir("brand-template") / "thumbnails"
    thumb_dir.mkdir(parents=True)
    thumb_path = thumb_dir / "slide-001.jpg"
    thumb_path.write_bytes(b"jpg")

    assets = await get_template_assets("brand-template", store=store, storage=storage)
    thumbnail = await get_template_thumbnail(
        "brand-template",
        "slide-001.jpg",
        store=store,
        storage=storage,
    )
    logo = await get_template_logo("brand-template", store=store)

    assert assets == {
        "template_id": "brand-template",
        "thumbnails": ["slide-001.jpg"],
        "logo_available": True,
    }
    assert thumbnail.path == thumb_path.as_posix()
    assert logo.path == logo_path.as_posix()


@pytest.mark.asyncio
async def test_template_asset_endpoints_return_clean_404s(tmp_path) -> None:
    store = DummyStore()
    storage = DummyStorage(tmp_path)

    with pytest.raises(HTTPException) as missing_thumb:
        await get_template_thumbnail(
            "brand-template",
            "missing.jpg",
            store=store,
            storage=storage,
        )
    with pytest.raises(HTTPException) as traversal:
        await get_template_thumbnail(
            "brand-template",
            "../secret.jpg",
            store=store,
            storage=storage,
        )
    with pytest.raises(HTTPException) as missing_logo:
        await get_template_logo("brand-template", store=store)

    assert missing_thumb.value.status_code == 404
    assert traversal.value.status_code == 404
    assert missing_logo.value.status_code == 404
