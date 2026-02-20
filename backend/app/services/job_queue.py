import asyncio
from contextlib import suppress

from app.infra.sqlite_store import SQLiteStore
from app.services.orchestrator import JobOrchestrator


ACTIVE_JOB_STATUSES = {"queued", "running", "analyzing", "planning", "generating", "qa"}


class JobQueue:
    def __init__(
        self,
        store: SQLiteStore,
        orchestrator: JobOrchestrator,
        worker_concurrency: int = 1,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.worker_concurrency = max(1, worker_concurrency)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._known_jobs: set[str] = set()
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        await self._enqueue_recoverable_jobs()
        for index in range(self.worker_concurrency):
            worker = asyncio.create_task(self._worker_loop(index))
            self._workers.append(worker)

    async def stop(self) -> None:
        self._stopping = True
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            with suppress(asyncio.CancelledError):
                await worker
        self._workers.clear()
        self._known_jobs.clear()

    async def enqueue(self, job_id: str) -> None:
        if job_id in self._known_jobs:
            return
        self._known_jobs.add(job_id)
        await self._queue.put(job_id)

    async def _enqueue_recoverable_jobs(self) -> None:
        recoverable = await self.store.list_jobs_by_status(ACTIVE_JOB_STATUSES)
        for job in recoverable:
            if job.status != "queued":
                await self.store.update_job(job.id, status="queued")
            await self.enqueue(job.id)

    async def _worker_loop(self, worker_index: int) -> None:
        while not self._stopping:
            job_id = await self._queue.get()
            try:
                await self.store.update_job(job_id, status="running")
                await self.orchestrator.run_job(job_id)
            finally:
                self._known_jobs.discard(job_id)
                self._queue.task_done()
