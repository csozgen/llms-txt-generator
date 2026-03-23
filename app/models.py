from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class CrawlRequest(BaseModel):
    url: HttpUrl
    max_pages: int = Field(default=50, ge=1, le=200)
    max_depth: int = Field(default=3, ge=1, le=10)


class PageData(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    h1: Optional[str] = None
    depth: int
    has_description: bool


class SkippedUrl(BaseModel):
    url: str
    reason: str


class JobStatus(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    job_id: str
    status: str  # pending | running | done | error | cancelled
    url: str
    # Request params
    max_pages: int = 50
    max_depth: int = 3
    # Progress tracking
    pages_crawled: int = 0
    pages_skipped: int = 0
    queue_size: int = 0
    total_known: int = 0
    sitemap_seeded: bool = False
    progress_pct: Optional[float] = None
    elapsed_seconds: Optional[float] = None
    duration_seconds: Optional[float] = None
    # Results
    llms_txt: Optional[str] = None
    page_count: Optional[int] = None
    error: Optional[str] = None
    skipped_urls: list[SkippedUrl] = Field(default_factory=list)
    # Internal state (not serialized to clients)
    cancelled: bool = False
    pages: list[PageData] = Field(default_factory=list, exclude=True)
    # Batch-specific (optional)
    batch_urls: list[str] = Field(default_factory=list, exclude=True)
    batch_results: list[Any] = Field(default_factory=list, exclude=True)
    parent_batch_id: Optional[str] = Field(default=None, exclude=True)
    # Timestamps
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class MetricsRecentJob(BaseModel):
    job_id: str
    url: str
    status: str
    pages_crawled: int
    pages_skipped: int
    duration_seconds: Optional[float]
    submitted_at: datetime


class MetricsResponse(BaseModel):
    active_jobs: int
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    total_pages_crawled: int
    total_pages_skipped: int
    recent_jobs: list[MetricsRecentJob]
