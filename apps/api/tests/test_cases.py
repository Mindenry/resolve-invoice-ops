"""Case lifecycle, SLA and collaboration tests."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.domain.enums import CaseStatus, Priority, RoleCode
from app.models.cases import Case
from app.modules.cases import service as case_service
from app.modules.exceptions import service as exception_service
from tests.conftest import OrgFixture
from tests.factories import make_invoice, make_vendor


def _create_case_with_exception(
    client: TestClient,
    org: OrgFixture,
    db,
    *,
    title: str = "Invoice exception case",
    tags: list[str] | None = None,
):
    vendor = make_vendor(db, org.org.id, number=f"V-{uuid.uuid4().hex[:6]}", tax_id=None)
    invoice = make_invoice(
        db, org.org.id, vendor, number=f"INV-{uuid.uuid4().hex[:8]}", po=None, subtotal="6000.00", total="6000.00"
    )
    db.commit()
    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    db.commit()
    response = client.post(
        "/api/v1/cases",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={
            "title": title,
            "description": "Created by test",
            "priority": "HIGH",
            "exception_ids": [str(record.id) for record in records],
            "invoice_id": str(invoice.id),
            "tags": tags if tags is not None else ["test"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), invoice, records


def test_case_creation_and_detail(client: TestClient, org: OrgFixture, db) -> None:
    case, invoice, records = _create_case_with_exception(client, org, db)
    assert case["case_number"].startswith("CASE-")
    assert case["status"] == "OPEN"
    assert case["priority"] == "HIGH"
    assert case["due_at"]
    assert case["exceptions"]
    assert case["links"]
    assert any(link["entity_type"] == "INVOICE" for link in case["links"])
    assert case["activities"][0]["activity_type"] == "CASE_CREATED"

    fetched = client.get(f"/api/v1/cases/{case['id']}", headers=org.headers[RoleCode.VIEWER])
    assert fetched.status_code == 200
    assert fetched.json()["case_number"] == case["case_number"]


def test_resolution_requires_summary(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, _records = _create_case_with_exception(client, org, db)
    response = client.post(
        f"/api/v1/cases/{case['id']}/transition",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"status": "RESOLVED"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "resolution_summary_required"


def test_invalid_status_transition_rejected(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, _records = _create_case_with_exception(client, org, db)
    # CLOSED can only be reached from RESOLVED (or from OPEN, but not directly from CANCELLED).
    client.post(
        f"/api/v1/cases/{case['id']}/transition",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"status": "CANCELLED"},
    )
    response = client.post(
        f"/api/v1/cases/{case['id']}/transition",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"status": "INVESTIGATING"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_case_transition"


def test_resolve_closes_linked_exceptions(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, records = _create_case_with_exception(client, org, db)
    response = client.post(
        f"/api/v1/cases/{case['id']}/resolve",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"resolution_summary": "Vendor confirmed and corrected the invoice.", "close": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "CLOSED"
    assert body["resolved_at"] and body["closed_at"]
    for record in records:
        db.refresh(record)
        assert record.status.value == "RESOLVED"


def test_assign_and_comment(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, _records = _create_case_with_exception(client, org, db)
    investigator = org.users[RoleCode.INVESTIGATOR]
    assigned = client.post(
        f"/api/v1/cases/{case['id']}/assign",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"user_id": str(investigator.id), "reason": "Needs investigation"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_user"]["id"] == str(investigator.id)

    comment = client.post(
        f"/api/v1/cases/{case['id']}/comments",
        headers=org.headers[RoleCode.INVESTIGATOR],
        json={"body": "Requested the vendor statement.", "visibility": "INTERNAL"},
    )
    assert comment.status_code == 201
    detail = client.get(f"/api/v1/cases/{case['id']}", headers=org.headers[RoleCode.VIEWER]).json()
    assert detail["comments"]
    assert detail["first_response_at"]

    invalid = client.post(
        f"/api/v1/cases/{case['id']}/assign",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"user_id": str(uuid.uuid4())},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_assignee"


def test_escalation_and_merge(client: TestClient, org: OrgFixture, db) -> None:
    target, _invoice, _ = _create_case_with_exception(client, org, db, title="Target case")
    source, _invoice2, source_exceptions = _create_case_with_exception(client, org, db, title="Source case")

    escalated = client.post(
        f"/api/v1/cases/{target['id']}/escalate",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"reason": "Vendor is unresponsive", "priority": "URGENT"},
    )
    assert escalated.status_code == 200
    assert escalated.json()["priority"] == "URGENT"

    merged = client.post(
        f"/api/v1/cases/{target['id']}/merge",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"source_case_id": source["id"], "note": "Same underlying invoice"},
    )
    assert merged.status_code == 200, merged.text
    merged_body = merged.json()
    assert merged_body["status"] in {"OPEN", "INVESTIGATING"}
    db.expire_all()
    merged_source = db.get(Case, uuid.UUID(source["id"]))
    assert merged_source.status == CaseStatus.CLOSED
    assert merged_source.merged_into_case_id == uuid.UUID(target["id"])
    for record in source_exceptions:
        db.refresh(record)
        assert record.case_id == uuid.UUID(target["id"])


def test_case_list_filters_and_pagination(client: TestClient, org: OrgFixture, db) -> None:
    _create_case_with_exception(client, org, db, title="Filterable alpha")
    _create_case_with_exception(client, org, db, title="Filterable beta")
    response = client.get(
        "/api/v1/cases",
        headers=org.headers[RoleCode.VIEWER],
        params={"search": "Filterable", "page_size": 1, "sort": "created_at", "order": "asc"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 2
    assert len(body["items"]) == 1
    assert body["meta"]["has_next"] is True


def test_invalid_case_number_conflict_is_retried(db, org) -> None:
    from datetime import timedelta

    from app.core.security import utcnow

    year = utcnow().year
    first = Case(
        org_id=org.org.id,
        case_number=f"CASE-{year}-0001",
        title="Existing case",
        status=CaseStatus.OPEN,
        priority=Priority.MEDIUM,
        sla_hours=48,
    )
    db.add(first)
    db.commit()
    case = case_service.create_case(
        db, org_id=org.org.id, actor_id=None, title="Second case", priority=Priority.LOW, notify_team=False
    )
    db.commit()
    assert case.case_number == f"CASE-{year}-0002"
    assert case.due_at > utcnow() + timedelta(hours=1)

def test_tag_filter_matches_exact_token(client: TestClient, org: OrgFixture, db) -> None:
    tagged, _invoice, _records = _create_case_with_exception(client, org, db, tags=["billing"])
    decoy, _invoice2, _records2 = _create_case_with_exception(client, org, db, tags=["billing_archive"])
    response = client.get(
        "/api/v1/cases",
        headers=org.headers[RoleCode.VIEWER],
        params={"tag": "billing", "page_size": 100},
    )
    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert tagged["id"] in ids
    assert decoy["id"] not in ids

def test_concurrent_case_numbers_are_unique(org: OrgFixture) -> None:
    import threading

    import pytest

    import app.db.session as session_module

    if session_module.engine.dialect.name != "postgresql":
        pytest.skip("Advisory-lock allocation is PostgreSQL-specific")

    barrier = threading.Barrier(5)
    numbers: list[str] = []
    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=15)
            with session_module.SessionLocal() as session:
                case = case_service.create_case(
                    session,
                    org_id=org.org.id,
                    actor_id=None,
                    title=f"Concurrent allocation {index}",
                    notify_team=False,
                )
                session.commit()
                numbers.append(case.case_number)
        except Exception as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    assert len(numbers) == 5
    assert len(set(numbers)) == 5
