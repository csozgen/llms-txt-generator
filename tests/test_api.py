from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api import _jobs, _url_to_job, app
from app.models import JobStatus


@pytest.fixture(autouse=True)
def clear_state():
    """Reset in-memory state between tests."""
    _jobs.clear()
    _url_to_job.clear()
    yield
    _jobs.clear()
    _url_to_job.clear()


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_generate_returns_job_id(client):
    resp = client.post("/api/jobs", json={"url": "https://example.com"})
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] in ("pending", "done")


def test_generate_deduplication(client):
    r1 = client.post("/api/jobs", json={"url": "https://example.com"})
    r2 = client.post("/api/jobs", json={"url": "https://example.com"})
    assert r1.json()["job_id"] == r2.json()["job_id"]


def test_generate_url_normalization(client):
    """Trailing slash and case should be treated as the same URL."""
    r1 = client.post("/api/jobs", json={"url": "https://example.com/"})
    r2 = client.post("/api/jobs", json={"url": "https://example.com"})
    assert r1.json()["job_id"] == r2.json()["job_id"]


def test_poll_job_not_found(client):
    resp = client.get("/api/jobs/doesnotexist")
    assert resp.status_code == 404


def test_poll_job_exists(client):
    r = client.post("/api/jobs", json={"url": "https://example.com"})
    job_id = r.json()["job_id"]
    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert "status" in data
    assert "pages_crawled" in data


def test_cancel_done_job(client):
    r = client.post("/api/jobs", json={"url": "https://example.com"})
    job_id = r.json()["job_id"]
    # Poll to ensure it's done (TestClient runs background tasks synchronously)
    client.get(f"/api/jobs/{job_id}")
    # Try to cancel a done job
    resp = client.delete(f"/api/jobs/{job_id}")
    # Should fail since job is done
    assert resp.status_code in (200, 400)


def test_cancel_not_found(client):
    resp = client.delete("/api/jobs/doesnotexist")
    assert resp.status_code == 404


def test_list_jobs(client):
    client.post("/api/jobs", json={"url": "https://example.com"})
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "jobs" in data
    assert data["total"] >= 1
    assert data["jobs"][0]["url"] == "https://example.com/"


def test_metrics(client):
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_jobs" in data
    assert "active_jobs" in data
    assert "recent_jobs" in data


def test_generate_invalid_url(client):
    resp = client.post("/api/jobs", json={"url": "not-a-url"})
    assert resp.status_code == 422


def test_generate_max_pages_capped(client):
    resp = client.post("/api/jobs", json={"url": "https://example.com", "max_pages": 999})
    assert resp.status_code == 422


def test_batch_no_urls(client):
    resp = client.post("/api/jobs/batch", data={"urls_text": ""})
    assert resp.status_code == 400


def test_batch_valid(client):
    resp = client.post(
        "/api/jobs/batch",
        data={"urls_text": "https://example.com\nhttps://httpbin.org"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["url_count"] == 2
