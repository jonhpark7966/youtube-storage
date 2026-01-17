"""Background job runner for video processing."""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from .config import settings


class JobStatus(str, Enum):
    """Job status enum."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """Represents a video processing job."""

    id: str
    video_url: str
    video_id: str
    status: JobStatus = JobStatus.PENDING
    current_step: int = 0  # 0-4
    step_name: str = "Initializing"
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    result: dict | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)


# In-memory job storage
jobs: dict[str, Job] = {}


def get_video_id_from_url(url: str) -> str:
    """Extract video ID from YouTube URL using yt-dlp."""
    proc = subprocess.run(
        ["yt-dlp", "--no-playlist", "--quiet", "--no-warnings", "--print", "%(id)s", "--skip-download", url],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ValueError(f"Failed to extract video ID: {proc.stderr}")
    video_id = proc.stdout.strip().splitlines()[-1].strip()
    if not video_id:
        raise ValueError("Failed to extract video ID")
    return video_id


def create_job(video_url: str) -> Job:
    """Create a new job for video processing."""
    video_id = get_video_id_from_url(video_url)
    job_id = f"{video_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    job = Job(
        id=job_id,
        video_url=video_url,
        video_id=video_id,
    )
    jobs[job_id] = job
    return job


def parse_step_from_line(line: str) -> tuple[int, str] | None:
    """Parse step number and name from log line."""
    step_patterns = [
        (1, r"Step 1.*subtitle", "Generating subtitles"),
        (2, r"Step 2.*[Bb]urn", "Burning in subtitles"),
        (3, r"Step 3.*[Mm]arkdown", "Generating markdown"),
        (4, r"Step 4.*web|Claude", "Adding to web archive"),
    ]
    for step_num, pattern, step_name in step_patterns:
        if re.search(pattern, line, re.IGNORECASE):
            return step_num, step_name
    return None


async def run_job(job: Job) -> None:
    """Run the video processing job asynchronously."""
    job.status = JobStatus.RUNNING
    job.started_at = datetime.now()

    cmd = [
        sys.executable,
        str(settings.process_script),
        job.video_url,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(settings.videos_dir.parent),
        )

        upload_url = None
        pr_url = None

        async for line in proc.stdout:
            decoded = line.decode("utf-8").rstrip()
            if decoded:
                job.logs.append(decoded)

                # Parse step progress
                step_info = parse_step_from_line(decoded)
                if step_info:
                    job.current_step, job.step_name = step_info

                # Extract upload URL
                if "Uploaded:" in decoded:
                    match = re.search(r"https://[^\s]+youtube[^\s]+", decoded)
                    if match:
                        upload_url = match.group(0)

                # Extract PR URL
                if "PR:" in decoded or "pull/" in decoded:
                    match = re.search(r"https://github\.com/[^\s]+/pull/\d+", decoded)
                    if match:
                        pr_url = match.group(0)

        await proc.wait()

        if proc.returncode == 0:
            job.status = JobStatus.COMPLETED
            job.current_step = 4
            job.step_name = "Completed"
            job.result = {
                "video_id": job.video_id,
                "output_dir": str(settings.videos_dir / job.video_id),
                "upload_url": upload_url,
                "pr_url": pr_url,
            }
        else:
            job.status = JobStatus.FAILED
            job.error = f"Process exited with code {proc.returncode}"

    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = str(e)

    job.completed_at = datetime.now()


def get_job(job_id: str) -> Job | None:
    """Get a job by ID."""
    return jobs.get(job_id)


def list_jobs(status: JobStatus | None = None) -> list[Job]:
    """List all jobs, optionally filtered by status."""
    if status:
        return [j for j in jobs.values() if j.status == status]
    return list(jobs.values())
