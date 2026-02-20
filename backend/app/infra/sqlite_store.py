import json
from datetime import datetime
from typing import Any, Iterable, Optional

import aiosqlite

from app.config import Settings
from app.models.document import DocumentRecord
from app.models.job import JobRecord
from app.models.outline import SlideOutline
from app.models.template import TemplateProfile, TemplateUpdateRequest


def utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


class SQLiteStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_dirs()

    async def _connect(self) -> aiosqlite.Connection:
        return await aiosqlite.connect(self.settings.sqlite_path.as_posix())

    async def init(self) -> None:
        async with await self._connect() as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    brand_json TEXT NOT NULL,
                    slides_json TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL,
                    instructions TEXT,
                    config_json TEXT,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL,
                    qa_rounds INTEGER NOT NULL,
                    warnings_json TEXT,
                    result_file TEXT,
                    preview_dir TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS job_documents (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    markdown_content TEXT,
                    structured_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS slide_outlines (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    slide_index INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    label TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    layout_json TEXT NOT NULL,
                    pptxgenjs_code TEXT,
                    qa_status TEXT,
                    qa_issues_json TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            await db.commit()

    async def create_template(self, profile: TemplateProfile) -> None:
        async with await self._connect() as db:
            await db.execute(
                """
                INSERT INTO templates (id, name, type, brand_json, slides_json, source_file, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.id,
                    profile.name,
                    profile.type,
                    profile.brand.model_dump_json(),
                    json.dumps([slide.model_dump() for slide in profile.slides]),
                    profile.source_file,
                    profile.created_at,
                    profile.updated_at,
                ),
            )
            await db.commit()

    async def update_template(
        self, template_id: str, update: TemplateUpdateRequest
    ) -> Optional[TemplateProfile]:
        profile = await self.get_template(template_id)
        if not profile:
            return None
        update_data = update.model_dump(exclude_unset=True)
        updated = profile.model_copy(update=update_data)
        updated.updated_at = utc_now()
        async with await self._connect() as db:
            await db.execute(
                """
                UPDATE templates
                SET name = ?, brand_json = ?, slides_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.name,
                    updated.brand.model_dump_json(),
                    json.dumps([slide.model_dump() for slide in updated.slides]),
                    updated.updated_at,
                    template_id,
                ),
            )
            await db.commit()
        return updated

    async def list_templates(self) -> list[TemplateProfile]:
        async with await self._connect() as db:
            cursor = await db.execute(
                "SELECT id, name, type, brand_json, slides_json, source_file, created_at, updated_at FROM templates"
            )
            rows = await cursor.fetchall()
        return [self._row_to_template(row) for row in rows]

    async def get_template(self, template_id: str) -> Optional[TemplateProfile]:
        async with await self._connect() as db:
            cursor = await db.execute(
                """
                SELECT id, name, type, brand_json, slides_json, source_file, created_at, updated_at
                FROM templates
                WHERE id = ?
                """,
                (template_id,),
            )
            row = await cursor.fetchone()
        return self._row_to_template(row) if row else None

    async def delete_template(self, template_id: str) -> None:
        async with await self._connect() as db:
            await db.execute("DELETE FROM templates WHERE id = ?", (template_id,))
            await db.commit()

    async def create_job(self, job: JobRecord) -> None:
        async with await self._connect() as db:
            await db.execute(
                """
                INSERT INTO jobs (
                    id, template_id, instructions, config_json, status, progress, qa_rounds,
                    warnings_json, result_file, preview_dir, error_message, created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.template_id,
                    job.instructions,
                    json.dumps(job.config_json) if job.config_json else None,
                    job.status,
                    job.progress,
                    job.qa_rounds,
                    json.dumps(job.warnings),
                    job.result_file,
                    job.preview_dir,
                    job.error_message,
                    job.created_at,
                    job.completed_at,
                ),
            )
            await db.commit()

    async def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        set_clause = ", ".join([f"{key} = ?" for key in fields.keys()])
        values = [self._serialize_field(key, value) for key, value in fields.items()]
        values.append(job_id)
        async with await self._connect() as db:
            await db.execute(
                f"UPDATE jobs SET {set_clause} WHERE id = ?",
                values,
            )
            await db.commit()

    async def list_jobs(self) -> list[JobRecord]:
        async with await self._connect() as db:
            cursor = await db.execute(
                """
                SELECT id, template_id, instructions, config_json, status, progress, qa_rounds,
                       warnings_json, result_file, preview_dir, error_message, created_at, completed_at
                FROM jobs
                ORDER BY created_at DESC
                """
            )
            rows = await cursor.fetchall()
        return [self._row_to_job(row) for row in rows]

    async def list_jobs_by_status(self, statuses: set[str]) -> list[JobRecord]:
        if not statuses:
            return []
        placeholders = ", ".join(["?"] * len(statuses))
        async with await self._connect() as db:
            cursor = await db.execute(
                f"""
                SELECT id, template_id, instructions, config_json, status, progress, qa_rounds,
                       warnings_json, result_file, preview_dir, error_message, created_at, completed_at
                FROM jobs
                WHERE status IN ({placeholders})
                ORDER BY created_at ASC
                """,
                tuple(statuses),
            )
            rows = await cursor.fetchall()
        return [self._row_to_job(row) for row in rows]

    async def get_job(self, job_id: str) -> Optional[JobRecord]:
        async with await self._connect() as db:
            cursor = await db.execute(
                """
                SELECT id, template_id, instructions, config_json, status, progress, qa_rounds,
                       warnings_json, result_file, preview_dir, error_message, created_at, completed_at
                FROM jobs
                WHERE id = ?
                """,
                (job_id,),
            )
            row = await cursor.fetchone()
        return self._row_to_job(row) if row else None

    async def add_job_document(self, record: DocumentRecord) -> None:
        async with await self._connect() as db:
            await db.execute(
                """
                INSERT INTO job_documents (
                    id, job_id, filename, file_path, markdown_content, structured_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.job_id,
                    record.filename,
                    record.file_path,
                    record.markdown_content,
                    json.dumps(record.structured_json) if record.structured_json else None,
                    record.created_at,
                ),
            )
            await db.commit()

    async def list_job_documents(self, job_id: str) -> list[DocumentRecord]:
        async with await self._connect() as db:
            cursor = await db.execute(
                """
                SELECT id, job_id, filename, file_path, markdown_content, structured_json, created_at
                FROM job_documents
                WHERE job_id = ?
                """,
                (job_id,),
            )
            rows = await cursor.fetchall()
        return [self._row_to_document(row) for row in rows]

    async def add_slide_outlines(self, outlines: Iterable[SlideOutline]) -> None:
        async with await self._connect() as db:
            await db.executemany(
                """
                INSERT INTO slide_outlines (
                    id, job_id, slide_index, mode, label, content_json, layout_json,
                    pptxgenjs_code, qa_status, qa_issues_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        outline.id,
                        outline.job_id,
                        outline.slide_index,
                        outline.mode,
                        outline.label,
                        json.dumps(outline.content_json),
                        json.dumps(outline.layout_json),
                        outline.pptxgenjs_code,
                        outline.qa_status,
                        json.dumps(outline.qa_issues_json)
                        if outline.qa_issues_json
                        else None,
                        outline.created_at,
                    )
                    for outline in outlines
                ],
            )
            await db.commit()

    async def update_slide_outline(
        self, outline_id: str, **fields: Any
    ) -> None:
        if not fields:
            return
        set_clause = ", ".join([f"{key} = ?" for key in fields.keys()])
        values = [self._serialize_field(key, value) for key, value in fields.items()]
        values.append(outline_id)
        async with await self._connect() as db:
            await db.execute(
                f"UPDATE slide_outlines SET {set_clause} WHERE id = ?",
                values,
            )
            await db.commit()

    async def list_slide_outlines(self, job_id: str) -> list[SlideOutline]:
        async with await self._connect() as db:
            cursor = await db.execute(
                """
                SELECT id, job_id, slide_index, mode, label, content_json, layout_json,
                       pptxgenjs_code, qa_status, qa_issues_json, created_at
                FROM slide_outlines
                WHERE job_id = ?
                ORDER BY slide_index ASC
                """,
                (job_id,),
            )
            rows = await cursor.fetchall()
        return [self._row_to_outline(row) for row in rows]

    def _row_to_template(self, row: aiosqlite.Row) -> TemplateProfile:
        return TemplateProfile(
            id=row[0],
            name=row[1],
            type=row[2],
            brand=json.loads(row[3]),
            slides=json.loads(row[4]),
            source_file=row[5],
            created_at=row[6],
            updated_at=row[7],
        )

    def _row_to_job(self, row: aiosqlite.Row) -> JobRecord:
        return JobRecord(
            id=row[0],
            template_id=row[1],
            instructions=row[2],
            config_json=json.loads(row[3]) if row[3] else None,
            status=row[4],
            progress=row[5],
            qa_rounds=row[6],
            warnings=json.loads(row[7]) if row[7] else [],
            result_file=row[8],
            preview_dir=row[9],
            error_message=row[10],
            created_at=row[11],
            completed_at=row[12],
        )

    def _row_to_document(self, row: aiosqlite.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row[0],
            job_id=row[1],
            filename=row[2],
            file_path=row[3],
            markdown_content=row[4],
            structured_json=json.loads(row[5]) if row[5] else None,
            created_at=row[6],
        )

    def _row_to_outline(self, row: aiosqlite.Row) -> SlideOutline:
        return SlideOutline(
            id=row[0],
            job_id=row[1],
            slide_index=row[2],
            mode=row[3],
            label=row[4],
            content_json=json.loads(row[5]),
            layout_json=json.loads(row[6]),
            pptxgenjs_code=row[7],
            qa_status=row[8],
            qa_issues_json=json.loads(row[9]) if row[9] else None,
            created_at=row[10],
        )

    def _serialize_field(self, key: str, value: Any) -> Any:
        if key in {"warnings_json", "warnings"}:
            return json.dumps(value)
        if key.endswith("_json"):
            return json.dumps(value) if value is not None else None
        if key == "config_json":
            return json.dumps(value) if value is not None else None
        return value
