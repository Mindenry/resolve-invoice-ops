"""Idempotency claim endpoint tests (Redis is replaced with an in-memory fake)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import automation
from app.config.settings import settings


class FakeRedis:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool | None:  # noqa: ARG002
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        return True


def test_claim_requires_secret(client: TestClient) -> None:
    response = client.post(
        "/api/v1/internal/automation/claims",
        json={"key": "event-0001-abcdef"},
        headers={"X-Automation-Secret": "wrong"},
    )
    assert response.status_code == 401


def test_claim_is_idempotent(client: TestClient, monkeypatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(automation, "_redis", lambda: fake)
    headers = {"X-Automation-Secret": settings.N8N_WEBHOOK_SECRET}
    body = {"key": "event-0001-abcdef"}

    first = client.post("/api/v1/internal/automation/claims", json=body, headers=headers)
    second = client.post("/api/v1/internal/automation/claims", json=body, headers=headers)

    assert first.status_code == 200
    assert first.json()["claimed"] is True
    assert second.json()["claimed"] is False
