from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.crawler.extractor import extract_page_data
from app.crawler.robots import fetch_robots, is_allowed, parse_sitemap
from app.crawler.utils import (
    extract_links,
    is_crawlable_url,
    is_same_domain,
    normalize_url,
)
from app.models import JobStatus, SkippedUrl

_USER_AGENT = "profound-llm/1.0"

# Global semaphore — shared across all concurrent crawl jobs
_connection_semaphore: asyncio.Semaphore | None = None

# Per-domain semaphores — limit concurrent requests to the same domain
_domain_semaphores: dict[str, asyncio.Semaphore] = {}


def _get_semaphore() -> asyncio.Semaphore:
    global _connection_semaphore
    if _connection_semaphore is None:
        _connection_semaphore = asyncio.Semaphore(settings.crawler.max_connections)
    return _connection_semaphore


def _get_domain_semaphore(url: str) -> asyncio.Semaphore:
    domain = urlparse(url).netloc
    if domain not in _domain_semaphores:
        _domain_semaphores[domain] = asyncio.Semaphore(settings.crawler.max_concurrent_per_domain)
    return _domain_semaphores[domain]


async def crawl(job: JobStatus) -> None:
    """
    Run a full crawl for the given job. Mutates `job` in place with progress
    and final results. Designed to run as a FastAPI BackgroundTask.
    """
    job.status = "running"
    job.started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    root_url = str(job.url)
    max_pages = job.max_pages
    max_depth = job.max_depth

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=settings.crawler.request_timeout,
        ) as client:
            # 1. Fetch robots.txt and discover sitemaps
            robots_text, sitemap_urls = await fetch_robots(client, root_url)

            # 2. Seed the queue
            queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
            visited: set[str] = set()
            results_lock = asyncio.Lock()

            if sitemap_urls:
                # Sitemap-seeded mode
                all_urls: list[str] = []
                for sm_url in sitemap_urls:
                    urls = await parse_sitemap(client, sm_url, max_pages - len(all_urls))
                    all_urls.extend(urls)
                    if len(all_urls) >= max_pages:
                        break

                # Always include root URL
                norm_root = normalize_url(root_url)
                if norm_root not in {normalize_url(u) for u in all_urls}:
                    all_urls.insert(0, root_url)

                all_urls = all_urls[:max_pages]
                job.sitemap_seeded = True
                job.total_known = len(all_urls)

                for url in all_urls:
                    await queue.put((url, 0))
            else:
                # BFS mode — seed with root URL only
                job.sitemap_seeded = False
                await queue.put((normalize_url(root_url), 0))
                job.total_known = 1

            # 3. Spin up worker pool
            worker_count = min(settings.crawler.worker_count, max_pages)
            workers = [
                asyncio.create_task(
                    _worker(
                        worker_id=i,
                        queue=queue,
                        visited=visited,
                        job=job,
                        client=client,
                        robots_text=robots_text,
                        root_url=root_url,
                        max_pages=max_pages,
                        max_depth=max_depth,
                        results_lock=results_lock,
                    )
                )
                for i in range(worker_count)
            ]

            await queue.join()

            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        return

    if job.status != "cancelled":
        job.status = "done"
    job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if job.started_at:
        job.duration_seconds = (job.completed_at - job.started_at).total_seconds()
    job.progress_pct = 100.0


async def _worker(
    worker_id: int,
    queue: asyncio.Queue[tuple[str, int]],
    visited: set[str],
    job: JobStatus,
    client: httpx.AsyncClient,
    robots_text: str | None,
    root_url: str,
    max_pages: int,
    max_depth: int,
    results_lock: asyncio.Lock,
) -> None:
    while True:
        try:
            url, depth = await queue.get()
        except asyncio.CancelledError:
            return

        try:
            # Drain queue on cancellation
            if job.cancelled:
                job.status = "cancelled"
                continue

            norm = normalize_url(url)

            async with results_lock:
                if norm in visited:
                    continue
                if job.pages_crawled >= max_pages:
                    continue
                visited.add(norm)

            # Guards
            if not is_same_domain(url, root_url):
                continue
            if not is_crawlable_url(url):
                continue
            if robots_text and not is_allowed(robots_text, url):
                async with results_lock:
                    job.skipped_urls.append(SkippedUrl(url=url, reason="disallowed by robots.txt"))
                    job.pages_skipped += 1
                continue

            # Fetch the page with retry — rate-limited per domain
            async with _get_domain_semaphore(url):
                html, error = await _fetch_with_retry(client, url)
                await asyncio.sleep(settings.crawler.crawl_delay)
            if error:
                async with results_lock:
                    job.skipped_urls.append(SkippedUrl(url=url, reason=error))
                    job.pages_skipped += 1

                # If this is the root URL, fail the whole job
                if normalize_url(url) == normalize_url(root_url) and job.pages_crawled == 0:
                    job.status = "error"
                    job.error = f"Could not reach {url}: {error}"
                continue

            # Extract page data
            page_data = extract_page_data(html, url, depth)

            async with results_lock:
                if job.pages_crawled < max_pages:
                    job.pages_crawled += 1
                    job.page_count = job.pages_crawled
                    job.pages.append(page_data)

            # BFS: enqueue new links
            if not job.sitemap_seeded and depth < max_depth:
                links = extract_links(html, url)
                async with results_lock:
                    for link in links:
                        norm_link = normalize_url(link)
                        if norm_link not in visited and is_same_domain(link, root_url):
                            await queue.put((link, depth + 1))
                            job.total_known = job.pages_crawled + queue.qsize()

            # Update queue_size and progress
            async with results_lock:
                job.queue_size = queue.qsize()
                if job.sitemap_seeded and job.total_known > 0:
                    job.progress_pct = min(
                        job.pages_crawled / job.total_known * 100, 99.0
                    )
                else:
                    job.progress_pct = None  # indeterminate for BFS

        finally:
            queue.task_done()


async def _fetch_with_retry(
    client: httpx.AsyncClient, url: str
) -> tuple[str | None, str | None]:
    """
    Fetch a URL with retry logic. Returns (html, error_message).
    html is None on failure; error_message is None on success.
    """
    cfg = settings.retry
    semaphore = _get_semaphore()

    last_error: str | None = None
    attempts = cfg.max_retries + 1

    for attempt in range(attempts):
        try:
            async with semaphore:
                resp = await client.get(url)

            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type:
                    return None, f"non-HTML content-type: {content_type.split(';')[0]}"
                return resp.text, None

            elif resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", cfg.retry_after_default))
                await asyncio.sleep(retry_after)
                last_error = "HTTP 429 (rate limited)"
                continue

            elif 400 <= resp.status_code < 500:
                # Permanent client error — don't retry
                return None, f"HTTP {resp.status_code}"

            else:
                # 5xx — retry with backoff
                last_error = f"HTTP {resp.status_code}"
                if attempt < attempts - 1:
                    await asyncio.sleep(cfg.backoff_base * (2**attempt))
                continue

        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_error = f"timeout after {attempt + 1} attempt(s)"
            if attempt < attempts - 1:
                await asyncio.sleep(cfg.backoff_base * (2**attempt))
            continue

        except Exception as exc:
            return None, str(exc)

    return None, last_error or "unknown error"
