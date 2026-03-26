# Automated llms.txt Generator

A web application that automatically generates an `llms.txt` file for any given website by analyzing its structure and content.

## Overview

The [`llms.txt`](https://llmstxt.org/) file is a proposed standard designed to help Large Language Models better understand and interact with website content — similar to `robots.txt` for search engines. This tool crawls a target website, extracts relevant metadata (titles, descriptions, URLs), and structures the output to conform to the [llms.txt specification](https://llmstxt.org/).

## Features

- **Async web crawler** — Parallel async workers with queue-based crawl. Supports both sitemap-seeded and BFS crawl modes.
- **robots.txt compliance** — Reads `/robots.txt` and respects `Disallow` rules and `Sitemap` entries.
- **llms.txt generation** — Groups pages by URL path prefix into sections, moves pages without meta descriptions to `## Optional`.
- **Job-based API** — Submit a crawl, get a `job_id`, poll for progress. Supports job cancellation.
- **Deduplication & caching** — Concurrent requests for the same URL reuse the same job. Completed results are cached for 1 hour (configurable).
- **Batch mode** — Submit multiple URLs at once; crawled concurrently with incremental progress updates; download results as a ZIP.
- **Per-domain rate limiting** — Configurable semaphore caps concurrent requests to the same domain across all active jobs.
- **Metrics endpoint** — Live stats on job counts, pages crawled/skipped, recent job history.

## Getting Started

### Prerequisites

- Python >= 3.13
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Installation

```bash
git clone https://github.com/your-org/profound-llm.git
cd profound-llm
uv sync
```

### Run

```bash
uv run python main.py
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

### Configuration

All tunable parameters are in [`config.yaml`](config.yaml):

```yaml
server:
  host: "0.0.0.0"
  port: 8000

crawler:
  worker_count: 10          # concurrent async workers per crawl job
  request_timeout: 10.0     # seconds per HTTP request
  crawl_delay: 0.1          # polite delay between requests per worker
  max_connections: 50       # global connection cap across all active crawls
  default_max_pages: 50
  default_max_depth: 3
  max_pages_limit: 200      # hard ceiling for user-supplied max_pages
  max_concurrent_per_domain: 2  # max parallel requests to the same domain

retry:
  max_retries: 2
  backoff_base: 1.0         # exponential backoff base in seconds
  retry_after_default: 5.0  # seconds to wait on HTTP 429 without Retry-After header

cache:
  ttl_seconds: 3600         # how long completed crawl results are cached
```

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/jobs` | Submit a single-URL crawl job |
| `GET` | `/api/jobs` | List all top-level jobs |
| `GET` | `/api/jobs/{job_id}` | Poll job status and result |
| `DELETE` | `/api/jobs/{job_id}` | Cancel an in-progress job |
| `POST` | `/api/jobs/batch` | Submit a batch crawl job |
| `GET` | `/api/jobs/{job_id}/results` | Get batch job results |
| `GET` | `/api/metrics` | Aggregate stats |

### Example

```bash
# Submit
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "max_pages": 50}'
# → {"job_id": "abc123", "status": "pending"}

# Poll
curl http://localhost:8000/api/jobs/abc123
# → {"status": "done", "llms_txt": "# Example Domain\n...", "page_count": 23, ...}
```

## Project Structure

```
profound_llm/
├── main.py                  # Entry point (uvicorn)
├── config.yaml              # Runtime configuration
├── pyproject.toml           # Dependencies
├── app/
│   ├── api.py               # FastAPI routes, job store, caching
│   ├── config.py            # Config loader
│   ├── models.py            # Pydantic models
│   ├── crawler/
│   │   ├── crawler.py       # Async worker pool and crawl orchestration
│   │   ├── robots.py        # robots.txt + XML sitemap parsing
│   │   ├── extractor.py     # HTML metadata extraction
│   │   └── utils.py         # URL normalization, link extraction
│   ├── generator/
│   │   └── llmstxt.py       # llms.txt formatter
│   └── static/
│       └── index.html       # Web UI
└── tests/
    ├── test_extractor.py
    ├── test_generator.py
    └── test_api.py
```

## Resources

- llms.txt specification: https://llmstxt.org/
- llms.txt examples: https://llmstxt.site/
- Getting started guide: https://llmstxt.github.io/guides/getting-started-llms-txt

## License

This project is private. Source code in this repository is for internal evaluation purposes only and may not be forked, distributed, or used publicly without permission.
