"""Integration hub, webhook signature and honest failure tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

from fastapi.testclient import TestClient

from app.domain.enums import IntegrationKind, RoleCode
from app.models.automation import Integration, IntegrationCredential, WebhookEvent
from app.modules.integrations import service as integration_service
from tests.conftest import OrgFixture


def _create_integration(client: TestClient, org: OrgFixture, *, kind: str = "WEBHOOK", url: str = "") -> dict:
    response = client.post(
        "/api/v1/integrations",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={
            "name": f"Test {kind} {uuid.uuid4().hex[:4]}",
            "kind": kind,
            "config": {"webhook_url": url, "api_key": "super-secret-value"},
            "event_filter": [],
            "is_enabled": True,
            "credentials": {"signing_secret": "shared-secret"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_integration_credentials_encrypted_and_redacted(client: TestClient, org: OrgFixture, db) -> None:
    created = _create_integration(client, org)
    # Secret-like config values are extracted into encrypted credentials, never echoed.
    assert "api_key" not in created["config"]
    assert "api_key" in created["credential_keys"]
    assert "signing_secret" in created["credential_keys"]
    rows = (
        db.query(IntegrationCredential)
        .filter(IntegrationCredential.integration_id == uuid.UUID(created["id"]))
        .all()
    )
    by_key = {row.key: row for row in rows}
    assert set(by_key) >= {"api_key", "signing_secret"}
    assert "shared-secret" not in by_key["signing_secret"].encrypted_value
    assert "super-secret-value" not in by_key["api_key"].encrypted_value
    from app.core.crypto import decrypt_secret

    assert decrypt_secret(by_key["signing_secret"].encrypted_value) == "shared-secret"
    assert decrypt_secret(by_key["api_key"].encrypted_value) == "super-secret-value"


def test_inbound_webhook_requires_valid_signature(client: TestClient, org: OrgFixture, db) -> None:
    created = _create_integration(client, org)
    body = json.dumps({"event_type": "integration.ping"}).encode()
    response = client.post(
        f"/api/v1/webhooks/{created['id']}",
        content=body,
        headers={"X-Resolve-Signature": "deadbeef", "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_webhook_signature"


def test_inbound_webhook_processed(client: TestClient, org: OrgFixture, db) -> None:
    created = _create_integration(client, org)
    body = json.dumps({"event_type": "integration.ping", "id": "evt-ping-1"}).encode()
    signature = hmac.new(b"shared-secret", body, hashlib.sha256).hexdigest()
    response = client.post(
        f"/api/v1/webhooks/{created['id']}",
        content=body,
        headers={"X-Resolve-Signature": signature, "Content-Type": "application/json"},
    )
    assert response.status_code == 202, response.text
    event_id = response.json()["id"]
    db.expire_all()
    events = client.get(
        "/api/v1/integrations/events", headers=org.headers[RoleCode.ORG_ADMIN]
    ).json()
    event = next(item for item in events if item["id"] == event_id)
    assert event["status"] == "PROCESSED"
    assert event["signature_valid"] is True


def test_workflow_without_n8n_fails_honestly(client: TestClient, org: OrgFixture) -> None:
    response = client.post(
        "/api/v1/workflows/case-resolution-notification/trigger",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"payload": {"note": "test"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FAILED"
    assert "n8n" in body["error"].lower()


def test_webhook_delivery_failure_is_persisted(monkeypatch, db, org) -> None:
    from app.models.audit import DomainEvent

    integration = Integration(
        org_id=org.org.id,
        name="Broken webhook",
        kind=IntegrationKind.WEBHOOK,
        is_enabled=True,
        config={"webhook_url": "https://example.com/broken"},
        event_filter=[],
    )
    db.add(integration)
    db.add(
        DomainEvent(
            org_id=org.org.id,
            event_type="case.created",
            entity_type="CASE",
            entity_id=str(uuid.uuid4()),
            payload={"case_number": "CASE-X"},
            status="PENDING",
        )
    )
    db.commit()

    class FakeResponse:
        status_code = 500
        text = "server error"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(integration_service.httpx, "Client", FakeClient)
    result = integration_service.publish_pending_events(org.org.id)
    assert result["failed"] == 1
    db.expire_all()
    event = db.query(DomainEvent).filter(DomainEvent.event_type == "case.created").one()
    assert event.status in {"PENDING", "FAILED"}
    webhook = db.query(WebhookEvent).filter(WebhookEvent.integration_id == integration.id).one()
    assert webhook.status.value == "FAILED"
    assert webhook.response_status == 500


def test_publish_without_integrations_marks_skipped(db, org) -> None:
    from app.models.audit import DomainEvent

    db.add(
        DomainEvent(
            org_id=org.org.id,
            event_type="case.created",
            entity_type="CASE",
            entity_id=str(uuid.uuid4()),
            payload={},
            status="PENDING",
        )
    )
    db.commit()
    result = integration_service.publish_pending_events(org.org.id)
    assert result["skipped"] == 1
    db.expire_all()
    event = db.query(DomainEvent).filter(DomainEvent.event_type == "case.created").one()
    assert event.status == "SKIPPED"


def test_integration_endpoints_require_manage_permission(client: TestClient, org: OrgFixture) -> None:
    response = client.post(
        "/api/v1/integrations",
        headers=org.headers[RoleCode.VIEWER],
        json={"name": "Nope", "kind": "WEBHOOK"},
    )
    assert response.status_code == 403

    read = client.get("/api/v1/integrations", headers=org.headers[RoleCode.VIEWER])
    assert read.status_code == 200

def test_disabled_integration_rejects_inbound_webhook(client: TestClient, org: OrgFixture) -> None:
    response = client.post(
        "/api/v1/integrations",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={
            "name": f"Disabled {uuid.uuid4().hex[:4]}",
            "kind": "WEBHOOK",
            "config": {"webhook_url": "https://example.com/hook"},
            "event_filter": [],
            "is_enabled": False,
            "credentials": {"signing_secret": "shared-secret"},
        },
    )
    assert response.status_code == 201, response.text
    integration_id = response.json()["id"]
    body = json.dumps({"event_type": "integration.ping"}).encode()
    signature = hmac.new(b"shared-secret", body, hashlib.sha256).hexdigest()
    delivery = client.post(
        f"/api/v1/webhooks/{integration_id}",
        content=body,
        headers={"X-Resolve-Signature": signature, "Content-Type": "application/json"},
    )
    assert delivery.status_code == 400
    assert delivery.json()["error"]["code"] == "integration_disabled"


def test_integration_rejects_non_http_url(client: TestClient, org: OrgFixture) -> None:
    response = client.post(
        "/api/v1/integrations",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={
            "name": f"Bad URL {uuid.uuid4().hex[:4]}",
            "kind": "WEBHOOK",
            "config": {"webhook_url": "file:///etc/passwd"},
            "event_filter": [],
            "is_enabled": True,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_integration_url"


def test_oversized_inbound_webhook_rejected(client: TestClient, org: OrgFixture) -> None:
    created = _create_integration(client, org)
    body = b"x" * 1_000_001
    response = client.post(
        f"/api/v1/webhooks/{created['id']}",
        content=body,
        headers={"X-Resolve-Signature": "ignored", "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "webhook_payload_too_large"


def test_outbound_webhook_uses_integration_signing_secret(monkeypatch, db, org) -> None:
    from app.core.crypto import encrypt_secret
    from app.models.audit import DomainEvent

    integration = Integration(
        org_id=org.org.id,
        name="Signed webhook",
        kind=IntegrationKind.WEBHOOK,
        is_enabled=True,
        config={"webhook_url": "https://example.com/hook"},
        event_filter=[],
    )
    db.add(integration)
    db.flush()
    db.add(
        IntegrationCredential(
            integration_id=integration.id,
            key="signing_secret",
            encrypted_value=encrypt_secret("per-integration-secret"),
        )
    )
    db.add(
        DomainEvent(
            org_id=org.org.id,
            event_type="case.created",
            entity_type="CASE",
            entity_id=str(uuid.uuid4()),
            payload={"case_number": "CASE-SIGNED"},
            status="PENDING",
        )
    )
    db.commit()

    captured = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, *, content=b"", headers=None, **kwargs):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers or {}
            return FakeResponse()

    monkeypatch.setattr(integration_service.httpx, "Client", FakeClient)
    result = integration_service.publish_pending_events(org.org.id)
    assert result["published"] == 1
    expected = hmac.new(b"per-integration-secret", captured["content"], hashlib.sha256).hexdigest()
    assert captured["headers"]["X-Resolve-Signature"] == expected

def test_n8n_connection_uses_health_without_api_key(monkeypatch, db, org) -> None:
    """Webhook-only n8n setups have no public API key; the probe must not fail with 401."""
    integration = Integration(
        org_id=org.org.id,
        name="n8n webhook mode",
        kind=IntegrationKind.N8N,
        is_enabled=True,
        config={"base_url": "http://n8n:5678", "webhook_url": "http://n8n:5678/webhook/resolve/test"},
        event_filter=[],
    )
    db.add(integration)
    db.commit()

    calls: list[str] = []

    class FakeResponse:
        status_code = 200
        text = "ok"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, **kwargs):
            calls.append(url)
            return FakeResponse()

    monkeypatch.setattr(integration_service.httpx, "Client", FakeClient)
    monkeypatch.setattr(integration_service.settings, "N8N_API_KEY", "")

    result = integration_service.test_connection(
        db, org_id=org.org.id, integration_id=integration.id
    )

    assert result["ok"] is True
    assert result["status"] == "CONNECTED"
    assert calls and calls[0].endswith("/healthz")
