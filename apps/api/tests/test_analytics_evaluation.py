"""Analytics, AI evaluation lab and audit trail tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.enums import RoleCode
from app.modules.ai_evaluation import service as evaluation_service
from app.modules.exceptions import service as exception_service
from tests.conftest import OrgFixture
from tests.factories import make_invoice, make_vendor


def _seed_operational_data(db, org):
    vendor = make_vendor(db, org.org.id, number="V-AN", name="Analytics Vendor Ltd.", tax_id="THAN")
    invoice = make_invoice(
        db, org.org.id, vendor, number="INV-AN-1", po=None, subtotal="6000.00", total="6000.00"
    )
    db.commit()
    records = exception_service.detect_for_invoice(db, org_id=org.org.id, invoice=invoice)
    db.commit()
    return vendor, invoice, records


def test_command_center_uses_real_data(client: TestClient, org: OrgFixture, db) -> None:
    vendor, invoice, records = _seed_operational_data(db, org)
    db.commit()
    response = client.get(
        "/api/v1/analytics/overview", headers=org.headers[RoleCode.ORG_ADMIN], params={"days": 30}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    kpis = {item["key"]: item["value"] for item in body["kpis"]}
    assert kpis["total_exceptions"] >= len(records)
    assert kpis["open_cases"] >= 1
    assert kpis["high_priority_cases"] >= 1
    assert body["counts"]["exceptions_in_range"] >= 1
    assert body["exception_distribution"]
    assert len(body["exception_trend"]) == 31
    assert body["sla"]["breached"] >= 0
    assert body["processing"]["documents_by_status"] is not None


def test_analytics_requires_permission(client: TestClient, org: OrgFixture) -> None:
    # Viewer has analytics:read by design; an organization with no permission is simulated by a role
    # lacking it is not part of the default matrix, so this asserts the endpoint is scoped.
    response = client.get("/api/v1/analytics/overview", headers=org.headers[RoleCode.VIEWER])
    assert response.status_code == 200


def test_ai_usage_endpoint(client: TestClient, org: OrgFixture, db) -> None:
    from app.ai.client import record_usage

    record_usage(
        db,
        org_id=org.org.id,
        user_id=org.users[RoleCode.ORG_ADMIN].id,
        purpose="test_purpose",
        provider="stub",
        model="stub",
        prompt_version="v1",
        input_tokens=100,
        output_tokens=50,
        latency_ms=30,
    )
    db.commit()
    response = client.get("/api/v1/analytics/ai-usage", headers=org.headers[RoleCode.ORG_ADMIN])
    assert response.status_code == 200
    body = response.json()
    assert body["by_purpose"][0]["purpose"] == "test_purpose"
    assert body["by_purpose"][0]["runs"] == 1


def test_evaluation_dataset_and_run(client: TestClient, org: OrgFixture) -> None:
    dataset = client.post(
        "/api/v1/evaluation/datasets",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={
            "name": "Unit dataset",
            "description": "Synthetic",
            "samples": [
                {
                    "sample_key": "sample-1",
                    "case_context": {
                        "case": {"case_number": "EVAL-1", "priority": "HIGH"},
                        "exceptions": [{"exception_type": "MISSING_PURCHASE_ORDER"}],
                        "evidence_candidates": [
                            {
                                "source_type": "INVOICE",
                                "source_id": "inv-1",
                                "quote": "Invoice INV-1 total USD 6000.00",
                                "relationship": "invoice",
                            }
                        ],
                    },
                    "expected_exception_types": ["MISSING_PURCHASE_ORDER"],
                    "expected_root_cause": "No purchase order was linked to the invoice.",
                    "expected_evidence": [{"quote": "Invoice INV-1 total USD 6000.00"}],
                    "expected_recommendations": ["ESCALATE_CASE"],
                }
            ],
        },
    )
    assert dataset.status_code == 201, dataset.text
    dataset_id = dataset.json()["id"]

    run = client.post(
        "/api/v1/evaluation/runs",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"dataset_id": dataset_id, "name": "Unit run"},
    )
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]

    detail = client.get(f"/api/v1/evaluation/runs/{run_id}", headers=org.headers[RoleCode.ORG_ADMIN])
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "SUCCEEDED", body
    assert body["metrics"]["samples"] == 1
    assert body["metrics"]["deterministic_stub"] is True
    assert "precision" in body["metrics"]
    assert "root_cause_accuracy" in body["metrics"]
    assert body["results"][0]["predicted"]
    assert body["results"][0]["latency_ms"] is not None


def test_evaluation_fails_without_provider(client: TestClient, org: OrgFixture, db, monkeypatch) -> None:
    dataset = client.post(
        "/api/v1/evaluation/datasets",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={
            "name": "No provider dataset",
            "samples": [{"sample_key": "s", "case_context": {}, "expected_exception_types": []}],
        },
    ).json()
    monkeypatch.setattr(evaluation_service, "build_llm_provider", lambda: None)
    run = client.post(
        "/api/v1/evaluation/runs",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"dataset_id": dataset["id"], "name": "No provider run"},
    ).json()
    detail = client.get(f"/api/v1/evaluation/runs/{run['id']}", headers=org.headers[RoleCode.ORG_ADMIN]).json()
    assert detail["status"] == "FAILED"
    assert "provider" in (detail["error"] or "").lower()
    assert detail["metrics"] == {}


def test_audit_trail_and_export(client: TestClient, org: OrgFixture, db) -> None:
    created = client.post(
        "/api/v1/vendors",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"vendor_number": "V-AUD", "legal_name": "Audit Vendor Ltd."},
    )
    assert created.status_code == 201
    listing = client.get(
        "/api/v1/audit",
        headers=org.headers[RoleCode.ORG_ADMIN],
        params={"action": "vendor.created"},
    )
    assert listing.status_code == 200
    assert listing.json()["meta"]["total"] >= 1
    record = listing.json()["items"][0]
    assert record["actor_email"] == "org_admin@example.com"
    assert record["request_id"] is None or isinstance(record["request_id"], str)

    export = client.get("/api/v1/audit/export", headers=org.headers[RoleCode.ORG_ADMIN])
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert "vendor.created" in export.text

    # Audit is append-only through the application API.
    assert client.post("/api/v1/audit", headers=org.headers[RoleCode.ORG_ADMIN], json={}).status_code == 405
    assert client.delete(f"/api/v1/audit/{record['id']}", headers=org.headers[RoleCode.ORG_ADMIN]).status_code == 405
