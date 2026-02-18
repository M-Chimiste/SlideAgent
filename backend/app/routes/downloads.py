"""Download routes: serve generated PPTX files."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.dependencies import get_job_store, get_storage
from app.models.jobs import JobStatus
from app.storage.local import LocalStorage
from app.store.sqlite import SQLiteJobStore

router = APIRouter(tags=["downloads"])


@router.get("/jobs/{job_id}/download")
async def download_output(
    job_id: str,
    job_store: SQLiteJobStore = Depends(get_job_store),
    storage: LocalStorage = Depends(get_storage),
):
    job = await job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status != JobStatus.complete:
        raise HTTPException(status_code=409, detail=f"Job is not complete (status: {job.status})")

    if not job.output_url:
        raise HTTPException(status_code=404, detail="No output file available")

    try:
        output_bytes = await storage.read_bytes(job.output_url)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Output file not found in storage")

    return Response(
        content=output_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f'attachment; filename="output-{job_id[:8]}.pptx"',
        },
    )
