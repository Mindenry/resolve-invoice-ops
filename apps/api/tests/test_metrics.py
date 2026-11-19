"""Prometheus metrics endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import OrgFixture


def test_metrics_exposes_real_business_and_http_series(client: TestClient, org: OrgFixture) -> None:
    client.get("/health", headers=org.headers[next(iter(org.headers))])
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    for name in (
        "resolve_http_requests_total",
        "resolve_http_request_duration_seconds_bucket",
        "resolve_db_up",
        "resolve_cases_total",
        "resolve_approvals_pending",
        "resolve_chunk_vectors_total",
    ):
        assert name in body
    assert 'resolve_http_requests_total{method="GET",route="/health"' in body
