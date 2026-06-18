import pytest
from fastapi import HTTPException

from app.models.brand import BrandDNA
from app.models.job import FREEFORM_TEMPLATE_ID, JobRecord
from app.models.template import TemplateProfile
from app.routes.jobs import create_job


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
    def __init__(self) -> None:
        self.saved: list[str] = []

    def save_job_document(self, job_id: str, filename: str, content: bytes):
        self.saved.append(filename)


class DummyQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


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
