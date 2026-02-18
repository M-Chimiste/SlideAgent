import json
from datetime import datetime, timezone

import aiosqlite

from app.models.jobs import JobError, JobRecord

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    template_version TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    current_stage TEXT,
    input_payload TEXT NOT NULL,
    outline TEXT,
    warnings TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    output_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ttl_expires_at TEXT NOT NULL
)
"""


def _row_to_job(row: aiosqlite.Row) -> JobRecord:
    return JobRecord(
        job_id=row["job_id"],
        template_id=row["template_id"],
        template_version=row["template_version"],
        mode=row["mode"],
        status=row["status"],
        progress=row["progress"],
        current_stage=row["current_stage"],
        input_payload=json.loads(row["input_payload"]),
        outline=json.loads(row["outline"]) if row["outline"] else None,
        warnings=json.loads(row["warnings"]),
        error=JobError.model_validate_json(row["error"]) if row["error"] else None,
        output_url=row["output_url"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        ttl_expires_at=datetime.fromisoformat(row["ttl_expires_at"]),
    )


def _serialize_value(key: str, value: object) -> str | int | None:
    if key in ("input_payload", "outline", "warnings"):
        return json.dumps(value) if value is not None else None
    if key == "error":
        return value.model_dump_json() if value is not None else None
    if isinstance(value, datetime):
        return value.isoformat()
    return value  # type: ignore[return-value]


class SQLiteJobStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(CREATE_TABLE_SQL)
        await self._db.commit()

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.initialize()
        assert self._db is not None
        return self._db

    async def create_job(self, job: JobRecord) -> None:
        db = await self._get_db()
        await db.execute(
            """INSERT INTO jobs (
                job_id, template_id, template_version, mode, status, progress,
                current_stage, input_payload, outline, warnings, error, output_url,
                created_at, updated_at, ttl_expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job.job_id,
                job.template_id,
                job.template_version,
                job.mode,
                job.status,
                job.progress,
                job.current_stage,
                json.dumps(job.input_payload),
                json.dumps(job.outline) if job.outline else None,
                json.dumps(job.warnings),
                job.error.model_dump_json() if job.error else None,
                job.output_url,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
                job.ttl_expires_at.isoformat(),
            ),
        )
        await db.commit()

    async def get_job(self, job_id: str) -> JobRecord | None:
        db = await self._get_db()
        cursor = await db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_job(row)

    async def update_job(self, job_id: str, **updates: object) -> JobRecord:
        db = await self._get_db()
        updates["updated_at"] = datetime.now(tz=timezone.utc)

        set_clauses = []
        values = []
        for key, value in updates.items():
            set_clauses.append(f"{key} = ?")
            values.append(_serialize_value(key, value))

        values.append(job_id)
        sql = f"UPDATE jobs SET {', '.join(set_clauses)} WHERE job_id = ?"
        await db.execute(sql, values)
        await db.commit()

        job = await self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found after update")
        return job

    async def list_jobs(self, limit: int = 50) -> list[JobRecord]:
        db = await self._get_db()
        cursor = await db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [_row_to_job(row) for row in rows]

    async def delete_expired_jobs(self) -> int:
        db = await self._get_db()
        now = datetime.now(tz=timezone.utc).isoformat()
        cursor = await db.execute(
            "DELETE FROM jobs WHERE ttl_expires_at < ?", (now,)
        )
        await db.commit()
        return cursor.rowcount

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
