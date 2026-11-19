"""RBAC and organization isolation tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.enums import RoleCode
from tests.conftest import OrgFixture
from tests.factories import make_vendor


def test_viewer_cannot_create_vendor(client: TestClient, org: OrgFixture) -> None:
    response = client.post(
        "/api/v1/vendors",
        headers=org.headers[RoleCode.VIEWER],
        json={"vendor_number": "V-X", "legal_name": "Forbidden Vendor"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "missing_permission"
    assert "vendor:create" in response.json()["error"]["details"]["missing"]


def test_investigator_cannot_manage_users(client: TestClient, org: OrgFixture) -> None:
    response = client.post(
        "/api/v1/users",
        headers=org.headers[RoleCode.INVESTIGATOR],
        json={
            "email": "newuser@example.com",
            "full_name": "New User",
            "role": "viewer",
            "temporary_password": "SomePassword123!",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "missing_permission"


def test_org_admin_can_manage_users(client: TestClient, org: OrgFixture) -> None:
    response = client.get("/api/v1/users", headers=org.headers[RoleCode.ORG_ADMIN])
    assert response.status_code == 200
    assert response.json()["meta"]["total"] >= 5


def test_cross_organization_header_is_rejected(
    client: TestClient, org: OrgFixture, second_org: OrgFixture
) -> None:
    headers = dict(org.headers[RoleCode.ORG_ADMIN])
    headers["X-Organization-Id"] = str(second_org.org.id)
    response = client.get("/api/v1/vendors", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_organization_access_denied"


def test_resource_from_other_organization_is_not_found(
    client: TestClient, org: OrgFixture, second_org: OrgFixture, db
) -> None:
    foreign_vendor = make_vendor(
        db, second_org.org.id, number="V-OTHER", name="Foreign Vendor Ltd.", tax_id="TH999"
    )
    db.commit()
    response = client.get(
        f"/api/v1/vendors/{foreign_vendor.id}", headers=org.headers[RoleCode.ORG_ADMIN]
    )
    assert response.status_code == 404


def test_missing_token_is_unauthorized(client: TestClient) -> None:
    response = client.get("/api/v1/vendors")
    assert response.status_code == 401


def test_role_matrix_reflects_permissions(client: TestClient, org: OrgFixture) -> None:
    response = client.get("/api/v1/organizations/roles/matrix", headers=org.headers[RoleCode.ORG_ADMIN])
    assert response.status_code == 200
    matrix = response.json()["matrix"]
    assert "case:read" in matrix["viewer"]
    assert "document:upload" not in matrix["viewer"]
    assert "approval:decide" in matrix["approver"]
    assert "invoice:approve" in matrix["approver"]
    assert "user:manage" in matrix["org_admin"]


def test_last_admin_cannot_be_deactivated(client: TestClient, org: OrgFixture) -> None:
    members = client.get(
        "/api/v1/users", headers=org.headers[RoleCode.ORG_ADMIN], params={"role": "org_admin"}
    ).json()["items"]
    admin_member = members[0]
    response = client.delete(
        f"/api/v1/users/{admin_member['id']}", headers=org.headers[RoleCode.ORG_ADMIN]
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] in {"last_admin_protected", "cannot_deactivate_self"}


def test_member_role_escalation_denied(client: TestClient, org: OrgFixture) -> None:
    response = client.post(
        "/api/v1/users",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={
            "email": "super@example.com",
            "full_name": "Super Attempt",
            "role": "super_admin",
            "temporary_password": "SomePassword123!",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "role_not_grantable"
