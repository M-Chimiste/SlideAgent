import json

import pytest
from fastapi import HTTPException

from app.models.brand import BrandDNA
from app.models.job import FREEFORM_TEMPLATE_ID, JobRecord
from app.models.template import TemplateProfile
from app.routes.jobs import create_job, get_job_status, get_planning_artifact


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
            )
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


class DummyQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


class StatusStore:
    def __init__(self, job: JobRecord) -> None:
        self.job = job

    async def get_job(self, job_id: str):
        return self.job if job_id == self.job.id else None


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
    }


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
