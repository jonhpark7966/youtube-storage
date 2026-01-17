"""FastAPI server for YouTube video processing."""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from .config import settings
from .job_runner import Job, JobStatus, create_job, get_job, list_jobs, run_job

app = FastAPI(
    title="YouTube Storage API",
    description="API for processing YouTube videos with subtitles, burn-in, and archiving",
    version="1.0.0",
)


# Request/Response models
class ProcessRequest(BaseModel):
    """Request to process a video."""

    url: str


class JobResponse(BaseModel):
    """Job status response."""

    id: str
    video_url: str
    video_id: str
    status: str
    current_step: int
    step_name: str
    started_at: datetime
    completed_at: datetime | None = None
    result: dict | None = None
    error: str | None = None

    @classmethod
    def from_job(cls, job: Job) -> "JobResponse":
        return cls(
            id=job.id,
            video_url=job.video_url,
            video_id=job.video_id,
            status=job.status.value,
            current_step=job.current_step,
            step_name=job.step_name,
            started_at=job.started_at,
            completed_at=job.completed_at,
            result=job.result,
            error=job.error,
        )


class ProcessResponse(BaseModel):
    """Response for process request."""

    job_id: str
    message: str


# Endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/api/youtube/process", response_model=ProcessResponse)
async def process_video(request: ProcessRequest, background_tasks: BackgroundTasks):
    """Start processing a YouTube video."""
    try:
        job = create_job(request.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Run job in background
    asyncio.create_task(run_job(job))

    return ProcessResponse(
        job_id=job.id,
        message=f"Processing started for video {job.video_id}",
    )


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str):
    """Get the status of a job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.from_job(job)


@app.get("/api/jobs", response_model=list[JobResponse])
async def list_all_jobs(status: str | None = None):
    """List all jobs, optionally filtered by status."""
    job_status = None
    if status:
        try:
            job_status = JobStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    return [JobResponse.from_job(j) for j in list_jobs(job_status)]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
