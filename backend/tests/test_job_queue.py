import asyncio

import pytest

from app.models.job import JobRecord
from app.services.job_queue import JobQueue


class DummyStore:
    def __init__(self) -> None:
        self.updated: list[tuple[str, dict]] = []
        self.jobs = [
            JobRecord(
                id="job-1",
                template_id="template-1",
                instructions=None,
                config_json=None,
                status="running",
                progress=0.2,
                qa_rounds=0,
                warnings=[],
                result_file=None,
                preview_dir=None,
                error_message=None,
                created_at="2026-01-01T00:00:00Z",
                completed_at=None,
            )
        ]

    async def list_jobs_by_status(self, statuses: set[str]) -> list[JobRecord]:
        return [job for job in self.jobs if job.status in statuses]

    async def update_job(self, job_id: str, **fields):
        self.updated.append((job_id, fields))


class DummyOrchestrator:
    def __init__(self) -> None:
        self.ran: list[str] = []

    async def run_job(self, job_id: str) -> None:
        self.ran.append(job_id)


@pytest.mark.asyncio
async def test_queue_recovers_and_runs_pending_jobs() -> None:
    store = DummyStore()
    orchestrator = DummyOrchestrator()
    queue = JobQueue(store=store, orchestrator=orchestrator, worker_concurrency=1)

    await queue.start()
    await asyncio.sleep(0.05)
    await queue.stop()

    assert "job-1" in orchestrator.ran
    assert any(update for update in store.updated if update[1].get("status") == "queued")
