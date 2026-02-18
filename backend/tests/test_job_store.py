from datetime import datetime, timedelta, timezone

import pytest

from app.models.jobs import JobError, JobRecord, JobStatus
from app.store.sqlite import SQLiteJobStore

NOW = datetime.now(tz=timezone.utc)


def _make_job(job_id: str = "test-123", status: JobStatus = JobStatus.queued, **kwargs) -> JobRecord:
    defaults = dict(
        job_id=job_id,
        template_id="test-template",
        template_version="1.0.0",
        mode="mode1",
        status=status,
        input_payload={"project_name": "Test"},
        created_at=NOW,
        updated_at=NOW,
        ttl_expires_at=NOW + timedelta(hours=24),
    )
    defaults.update(kwargs)
    return JobRecord(**defaults)


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = SQLiteJobStore(db_path)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_create_and_get(store):
    job = _make_job()
    await store.create_job(job)
    retrieved = await store.get_job("test-123")
    assert retrieved is not None
    assert retrieved.job_id == "test-123"
    assert retrieved.status == JobStatus.queued
    assert retrieved.input_payload == {"project_name": "Test"}


@pytest.mark.asyncio
async def test_get_missing_returns_none(store):
    result = await store.get_job("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_update_job(store):
    await store.create_job(_make_job())
    updated = await store.update_job(
        "test-123",
        status=JobStatus.parsing,
        progress=25,
        current_stage="parsing",
    )
    assert updated.status == JobStatus.parsing
    assert updated.progress == 25
    assert updated.current_stage == "parsing"
    assert updated.updated_at > NOW


@pytest.mark.asyncio
async def test_update_job_with_error(store):
    await store.create_job(_make_job())
    error = JobError(stage="parsing", message="Field not found", retryable=False)
    updated = await store.update_job("test-123", status=JobStatus.failed, error=error)
    assert updated.error is not None
    assert updated.error.stage == "parsing"
    assert updated.error.message == "Field not found"


@pytest.mark.asyncio
async def test_update_job_with_warnings(store):
    await store.create_job(_make_job())
    updated = await store.update_job("test-123", warnings=["truncated field X"])
    assert updated.warnings == ["truncated field X"]


@pytest.mark.asyncio
async def test_update_nonexistent_raises(store):
    with pytest.raises(ValueError, match="not found"):
        await store.update_job("nonexistent", status=JobStatus.failed)


@pytest.mark.asyncio
async def test_list_jobs(store):
    for i in range(3):
        await store.create_job(_make_job(job_id=f"job-{i}"))
    jobs = await store.list_jobs(limit=10)
    assert len(jobs) == 3


@pytest.mark.asyncio
async def test_list_jobs_limit(store):
    for i in range(5):
        await store.create_job(_make_job(job_id=f"job-{i}"))
    jobs = await store.list_jobs(limit=2)
    assert len(jobs) == 2


@pytest.mark.asyncio
async def test_delete_expired_jobs(store):
    # Create an expired job
    expired = _make_job(
        job_id="expired-1",
        ttl_expires_at=NOW - timedelta(hours=1),
    )
    await store.create_job(expired)

    # Create a non-expired job
    active = _make_job(job_id="active-1")
    await store.create_job(active)

    deleted = await store.delete_expired_jobs()
    assert deleted == 1

    assert await store.get_job("expired-1") is None
    assert await store.get_job("active-1") is not None
