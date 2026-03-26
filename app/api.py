from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.crawler.crawler import crawl
from app.crawler.utils import normalize_url
from app.generator.llmstxt import generate_llms_txt
from app.models import (
    CrawlRequest,
    JobStatus,
    MetricsRecentJob,
    MetricsResponse,
    SkippedUrl,
)

app = FastAPI(title="profound-llm", version="0.1.0")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

# job_id -> JobStatus
_jobs: dict[str, JobStatus] = {}

# normalized_url -> job_id (for dedup + cache)
_url_to_job: dict[str, str] = {}


def _make_job_id() -> str:
    return uuid.uuid4().hex


def _get_cached_job(norm_url: str) -> JobStatus | None:
    job_id = _url_to_job.get(norm_url)
    if not job_id:
        return None
    job = _jobs.get(job_id)
    if not job:
        return None
    # Active (running/pending) — return regardless of TTL
    if job.status in ("pending", "running"):
        return job
    # Completed — check TTL
    if job.status == "done" and job.completed_at:
        age = (datetime.now(timezone.utc).replace(tzinfo=None) - job.completed_at).total_seconds()
        if age < settings.cache.ttl_seconds:
            return job
    return None


# ---------------------------------------------------------------------------
# Background task wrapper
# ---------------------------------------------------------------------------

async def _run_crawl(job: JobStatus) -> None:
    """Run the crawl and then finalize llms_txt on the job."""
    await crawl(job)
    if job.status == "done":
        pages = job.pages
        job.llms_txt = generate_llms_txt(job.url, pages)
        job.page_count = job.pages_crawled


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


@app.post("/api/jobs", status_code=202)
async def create_job(request: CrawlRequest, background_tasks: BackgroundTasks) -> dict:
    norm_url = normalize_url(str(request.url))

    # Dedup / cache check
    cached = _get_cached_job(norm_url)
    if cached:
        return {"job_id": cached.job_id, "status": cached.status}

    job_id = _make_job_id()
    job = JobStatus(
        job_id=job_id,
        status="pending",
        url=str(request.url),
        max_pages=request.max_pages,
        max_depth=request.max_depth,
    )

    _jobs[job_id] = job
    _url_to_job[norm_url] = job_id

    background_tasks.add_task(_run_crawl, job)
    return {"job_id": job_id, "status": "pending"}


@app.get("/api/jobs")
async def list_jobs() -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    jobs = sorted(
        (j for j in _jobs.values() if j.parent_batch_id is None),
        key=lambda j: j.submitted_at,
        reverse=True,
    )
    return {
        "total": len(jobs),
        "jobs": [
            {
                "job_id": j.job_id,
                "url": j.url,
                "status": j.status,
                "pages_crawled": j.pages_crawled,
                "pages_skipped": j.pages_skipped,
                "progress_pct": j.progress_pct,
                "duration_seconds": j.duration_seconds,
                "elapsed_seconds": (
                    (j.completed_at or now) - j.started_at
                ).total_seconds() if j.started_at else None,
                "submitted_at": j.submitted_at.isoformat(),
                "is_batch": bool(j.batch_urls),
                "batch_url_count": len(j.batch_urls),
            }
            for j in jobs
        ],
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found. Server may have restarted — please resubmit.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    elapsed: float | None = None
    if job.started_at:
        if job.completed_at:
            elapsed = (job.completed_at - job.started_at).total_seconds()
        else:
            elapsed = (now - job.started_at).total_seconds()

    return {
        "job_id": job.job_id,
        "status": job.status,
        "url": job.url,
        "pages_crawled": job.pages_crawled,
        "pages_skipped": job.pages_skipped,
        "queue_size": job.queue_size,
        "total_known": job.total_known,
        "sitemap_seeded": job.sitemap_seeded,
        "progress_pct": job.progress_pct,
        "elapsed_seconds": elapsed,
        "duration_seconds": job.duration_seconds,
        "llms_txt": job.llms_txt if job.status == "done" else None,
        "page_count": job.page_count if job.status == "done" else None,
        "error": job.error,
        "skipped_urls": [s.model_dump() for s in job.skipped_urls],
    }


@app.delete("/api/jobs/{job_id}", status_code=200)
async def cancel_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"Job is already {job.status}.")
    job.cancelled = True
    return {"job_id": job_id, "status": "cancelling"}


@app.post("/api/jobs/batch", status_code=202)
async def create_batch_job(
    background_tasks: BackgroundTasks,
    urls_text: str = Form(default=""),
    file: Optional[UploadFile] = File(default=None),
    max_pages: int = Form(default=50),
    max_depth: int = Form(default=3),
) -> dict:
    urls: list[str] = []

    # Parse file if provided
    if file and file.filename:
        content = await file.read()
        text = content.decode("utf-8", errors="replace")
        urls.extend(_parse_url_list(text))

    # Parse text field
    if urls_text.strip():
        urls.extend(_parse_url_list(urls_text))

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_urls: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    if not unique_urls:
        raise HTTPException(status_code=400, detail="No valid URLs provided.")

    # Create a batch job that wraps multiple crawls sequentially
    batch_job_id = _make_job_id()
    batch_job = JobStatus(
        job_id=batch_job_id,
        status="pending",
        url=unique_urls[0],  # representative URL
        max_pages=min(max_pages, settings.crawler.max_pages_limit),
        max_depth=max_depth,
        batch_urls=unique_urls,
    )

    _jobs[batch_job_id] = batch_job
    background_tasks.add_task(_run_batch_crawl, batch_job)

    return {"job_id": batch_job_id, "status": "pending", "url_count": len(unique_urls)}


@app.get("/api/metrics")
async def metrics() -> MetricsResponse:
    all_jobs = list(_jobs.values())
    active = sum(1 for j in all_jobs if j.status in ("pending", "running"))
    completed = sum(1 for j in all_jobs if j.status == "done")
    failed = sum(1 for j in all_jobs if j.status == "error")
    cancelled = sum(1 for j in all_jobs if j.status == "cancelled")
    total_crawled = sum(j.pages_crawled for j in all_jobs)
    total_skipped = sum(j.pages_skipped for j in all_jobs)

    recent = sorted(all_jobs, key=lambda j: j.submitted_at, reverse=True)[:10]
    recent_jobs = [
        MetricsRecentJob(
            job_id=j.job_id,
            url=j.url,
            status=j.status,
            pages_crawled=j.pages_crawled,
            pages_skipped=j.pages_skipped,
            duration_seconds=j.duration_seconds,
            submitted_at=j.submitted_at,
        )
        for j in recent
    ]

    return MetricsResponse(
        active_jobs=active,
        total_jobs=len(all_jobs),
        completed_jobs=completed,
        failed_jobs=failed,
        cancelled_jobs=cancelled,
        total_pages_crawled=total_crawled,
        total_pages_skipped=total_skipped,
        recent_jobs=recent_jobs,
    )


# ---------------------------------------------------------------------------
# Batch crawl runner
# ---------------------------------------------------------------------------

async def _run_batch_crawl(batch_job: JobStatus) -> None:
    batch_job.status = "running"
    batch_job.started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    urls = batch_job.batch_urls
    results = batch_job.batch_results

    # Build sub-jobs, reusing cache where possible
    sub_jobs: list[JobStatus] = []
    for url in urls:
        norm_url = normalize_url(url)
        cached = _get_cached_job(norm_url)
        if cached and cached.status == "done":
            results.append({
                "url": url,
                "job_id": cached.job_id,
                "status": "done",
                "llms_txt": cached.llms_txt,
                "page_count": cached.page_count,
                "error": None,
            })
            continue

        sub_job_id = _make_job_id()
        sub_job = JobStatus(
            job_id=sub_job_id, status="pending", url=url,
            max_pages=batch_job.max_pages, max_depth=batch_job.max_depth,
            parent_batch_id=batch_job.job_id,
        )
        _jobs[sub_job_id] = sub_job
        _url_to_job[norm_url] = sub_job_id
        sub_jobs.append(sub_job)

    # Crawl all sub-jobs concurrently, appending results as each one finishes
    async def _crawl_and_collect(sub_job: JobStatus) -> None:
        await _run_crawl(sub_job)
        results.append({
            "url": sub_job.url,
            "job_id": sub_job.job_id,
            "status": sub_job.status,
            "llms_txt": sub_job.llms_txt,
            "page_count": sub_job.page_count,
            "error": sub_job.error,
        })
        batch_job.pages_crawled += sub_job.pages_crawled
        batch_job.pages_skipped += sub_job.pages_skipped

    await asyncio.gather(*[_crawl_and_collect(sub_job) for sub_job in sub_jobs])

    if batch_job.cancelled:
        batch_job.status = "cancelled"

    if batch_job.status == "running":
        batch_job.status = "done"
    batch_job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if batch_job.started_at:
        batch_job.duration_seconds = (batch_job.completed_at - batch_job.started_at).total_seconds()
    batch_job.llms_txt = None  # batch results are in batch_results list


# Override get_job for batch jobs to include batch_results
@app.get("/api/jobs/{job_id}/results")
async def get_batch_results(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if not job.batch_urls:
        raise HTTPException(status_code=400, detail="Not a batch job.")
    return {
        "job_id": job_id,
        "status": job.status,
        "results": job.batch_results,
        "url_count": len(job.batch_urls),
        "completed_count": len(job.batch_results),
    }


# ---------------------------------------------------------------------------
# Static files (must be mounted after all routes)
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")


def _parse_url_list(text: str) -> list[str]:
    """Parse newline or comma-separated URLs, filtering out blanks."""
    import re
    # Split on newlines or commas
    raw = re.split(r"[\n,]+", text)
    urls: list[str] = []
    for raw_url in raw:
        u = raw_url.strip()
        if u and (u.startswith("http://") or u.startswith("https://")):
            urls.append(u)
    return urls
