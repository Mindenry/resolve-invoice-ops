"""Resolution proposal, approval and execution tests."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.domain.enums import Priority, RoleCode
from app.modules.cases.service import create_case
from app.modules.exceptions import service as exception_service
from tests.conftest import OrgFixture
from tests.factories import make_invoice, make_po, make_vendor


def _case(db, org, *, with_po: bool = False):
    vendor = make_vendor(
        db, org.org.id, number=f"V-{uuid.uuid4().hex[:5]}", name="Resolution Vendor Ltd.", tax_id="THRES"
    )
    po = make_po(db, org.org.id, vendor, unit_price="900.00") if with_po else None
    invoice = make_invoice(
        db, org.org.id, vendor, number=f"INV-{uuid.uuid4().hex[:6]}", po=po, subtotal="900.00", total="900.00"
    )
    db.commit()
    exceptions = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    db.commit()
    case = create_case(
        db,
        org_id=org.org.id,
        actor_id=org.users[RoleCode.ORG_ADMIN].id,
        title="Resolution test case",
        priority=Priority.HIGH,
        links=[("INVOICE", invoice.id, invoice.invoice_number)],
        exception_ids=[record.id for record in exceptions],
        notify_team=False,
    )
    db.commit()
    return case, invoice, vendor


def _propose(client: TestClient, org: OrgFixture, case, vendor, *, requester=RoleCode.OPERATIONS_MANAGER, approver=None, request_approval=True):
    return client.post(
        f"/api/v1/cases/{case.id}/resolutions",
        headers=org.headers[requester],
        json={
            "action_type": "REQUEST_VENDOR_CONFIRMATION",
            "description": "Ask the vendor to confirm the invoice details.",
            "parameters": {
                "vendor_id": str(vendor.id),
                "message": "Please confirm the invoice amount.",
            },
            "evidence": [{"source_type": "INVOICE", "quote": "Invoice total 900.00"}],
            "request_approval": request_approval,
            "approver_id": str(org.users[RoleCode.APPROVER].id) if approver is None else str(approver),
            "note": "Please review",
        },
    )


def test_external_action_requires_approval(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, vendor = _case(db, org)
    response = _propose(client, org, case, vendor)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["requires_approval"] is True
    assert body["status"] == "AWAITING_APPROVAL"
    assert body["approval"]["status"] == "PENDING"


def test_approve_and_execute_with_audit(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, vendor = _case(db, org)
    resolution = _propose(client, org, case, vendor).json()
    approval_id = resolution["approval"]["id"]

    approvals = client.get("/api/v1/approvals", headers=org.headers[RoleCode.APPROVER]).json()
    approval = next(item for item in approvals["items"] if item["id"] == approval_id)
    assert approval["can_decide"] is True
    assert approval["risk_level"] == "MEDIUM"

    decision = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        headers=org.headers[RoleCode.APPROVER],
        json={"comment": "Looks correct", "execute_after_approval": True},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["approval"]["status"] == "APPROVED"
    assert decision.json()["resolution_status"] == "COMPLETED"

    detail = client.get(f"/api/v1/resolutions/{resolution['id']}", headers=org.headers[RoleCode.APPROVER]).json()
    assert detail["status"] == "COMPLETED"
    assert detail["execution_result"]["email_to"] == "vendor@example.com"
    assert len(detail["executions"]) == 1

    # Idempotent execution: no second side effect and no duplicate execution row.
    again = client.post(
        f"/api/v1/resolutions/{resolution['id']}/execute", headers=org.headers[RoleCode.APPROVER]
    )
    assert again.status_code == 200
    assert len(again.json()["executions"]) == 1

    audit = client.get(
        "/api/v1/audit",
        headers=org.headers[RoleCode.ORG_ADMIN],
        params={"action": "resolution.executed"},
    ).json()
    assert audit["meta"]["total"] == 1


def test_self_approval_is_denied(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, vendor = _case(db, org)
    resolution = _propose(
        client, org, case, vendor, requester=RoleCode.ORG_ADMIN, approver=org.users[RoleCode.ORG_ADMIN].id
    ).json()
    approval_id = resolution["approval"]["id"]
    response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"comment": "Self approval attempt"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "self_approval_denied"


def test_rejection_requires_reason(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, vendor = _case(db, org)
    resolution = _propose(client, org, case, vendor).json()
    approval_id = resolution["approval"]["id"]
    response = client.post(
        f"/api/v1/approvals/{approval_id}/reject",
        headers=org.headers[RoleCode.APPROVER],
        json={},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "rejection_reason_required"

    rejected = client.post(
        f"/api/v1/approvals/{approval_id}/reject",
        headers=org.headers[RoleCode.APPROVER],
        json={"comment": "Vendor already confirmed by phone"},
    )
    assert rejected.status_code == 200
    detail = client.get(f"/api/v1/resolutions/{resolution['id']}", headers=org.headers[RoleCode.APPROVER]).json()
    assert detail["status"] == "REJECTED"


def test_execute_before_approval_is_blocked(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, vendor = _case(db, org)
    resolution = _propose(client, org, case, vendor).json()
    response = client.post(
        f"/api/v1/resolutions/{resolution['id']}/execute",
        headers=org.headers[RoleCode.APPROVER],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "approval_required"


def test_low_risk_action_needs_no_approval(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, _vendor = _case(db, org)
    created = client.post(
        f"/api/v1/cases/{case.id}/resolutions",
        headers=org.headers[RoleCode.OPERATIONS_MANAGER],
        json={
            "action_type": "UPDATE_CASE_PRIORITY",
            "description": "Raise priority because the SLA is close.",
            "parameters": {"priority": "URGENT"},
            "evidence": [],
            "request_approval": False,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["requires_approval"] is False
    assert body["status"] == "VALIDATED"

    executed = client.post(
        f"/api/v1/resolutions/{body['id']}/execute", headers=org.headers[RoleCode.OPERATIONS_MANAGER]
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "COMPLETED"
    refreshed = client.get(f"/api/v1/cases/{case.id}", headers=org.headers[RoleCode.OPERATIONS_MANAGER]).json()
    assert refreshed["priority"] == "URGENT"


def test_invalid_parameters_rejected(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, _vendor = _case(db, org)
    response = client.post(
        f"/api/v1/cases/{case.id}/resolutions",
        headers=org.headers[RoleCode.OPERATIONS_MANAGER],
        json={
            "action_type": "UPDATE_CASE_PRIORITY",
            "description": "Invalid priority",
            "parameters": {"priority": "SUPER_URGENT"},
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_action_parameters"


def test_viewer_cannot_execute(client: TestClient, org: OrgFixture, db) -> None:
    case, _invoice, _vendor = _case(db, org)
    created = client.post(
        f"/api/v1/cases/{case.id}/resolutions",
        headers=org.headers[RoleCode.OPERATIONS_MANAGER],
        json={
            "action_type": "UPDATE_CASE_PRIORITY",
            "description": "Raise priority",
            "parameters": {"priority": "HIGH"},
            "request_approval": False,
        },
    ).json()
    response = client.post(
        f"/api/v1/resolutions/{created['id']}/execute", headers=org.headers[RoleCode.VIEWER]
    )
    assert response.status_code == 403


def test_action_catalog_exposes_policy_metadata(client: TestClient, org: OrgFixture) -> None:
    response = client.get("/api/v1/resolutions/actions", headers=org.headers[RoleCode.VIEWER])
    assert response.status_code == 200
    actions = {item["action_type"]: item for item in response.json()}
    assert actions["MARK_DUPLICATE"]["financial_impact"] is True
    assert actions["MARK_DUPLICATE"]["default_risk"] == "HIGH"
    assert actions["UPDATE_CASE_PRIORITY"]["parameters_schema"]["properties"]["priority"]


def test_resolution_idempotency_key_prevents_duplicates(db, org) -> None:
    from app.modules.resolutions.service import create_resolution

    case, _invoice, vendor = _case(db, org)
    first = create_resolution(
        db,
        case=case,
        actor_id=org.users[RoleCode.OPERATIONS_MANAGER].id,
        action_type="UPDATE_CASE_PRIORITY",
        description="Same",
        parameters={"priority": "HIGH"},
        evidence=[],
    )
    second = create_resolution(
        db,
        case=case,
        actor_id=org.users[RoleCode.OPERATIONS_MANAGER].id,
        action_type="UPDATE_CASE_PRIORITY",
        description="Same",
        parameters={"priority": "HIGH"},
        evidence=[],
    )
    db.commit()
    assert first.id == second.id

def test_second_decision_is_a_conflict(client: TestClient, org: OrgFixture, db) -> None:
    """A decided approval cannot be decided twice (atomic claim guard)."""
    case, _invoice, vendor = _case(db, org)
    resolution = _propose(client, org, case, vendor).json()
    approval_id = resolution["approval"]["id"]

    first = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        headers=org.headers[RoleCode.APPROVER],
        json={"comment": "First decision", "execute_after_approval": False},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        headers=org.headers[RoleCode.APPROVER],
        json={"comment": "Second decision", "execute_after_approval": False},
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] in {"approval_already_decided", "approval_not_pending"}

    detail = client.get(
        f"/api/v1/approvals/{approval_id}", headers=org.headers[RoleCode.APPROVER]
    ).json()
    assert detail["status"] == "APPROVED"

    audit = client.get(
        "/api/v1/audit",
        headers=org.headers[RoleCode.ORG_ADMIN],
        params={"action": "approval.decided"},
    ).json()
    assert audit["meta"]["total"] == 1
