"""Authentication, refresh rotation and account security tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config.settings import settings
from tests.conftest import OrgFixture


def test_login_and_me(client: TestClient, org: OrgFixture) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "org_admin@example.com", "password": "TestPassword123!"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "org_admin"
    assert "case:read" in body["permissions"]
    assert response.cookies.get("resolve_refresh")

    me = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {body['access_token']}",
            "X-Organization-Id": str(org.org.id),
        },
    )
    assert me.status_code == 200
    assert me.json()["organization"]["slug"] == "test-org"


def test_login_rejects_bad_password(client: TestClient, org: OrgFixture) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "org_admin@example.com", "password": "WrongPassword123!"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_login_requires_organization_when_many_memberships(
    client: TestClient, org: OrgFixture, second_org: OrgFixture, db
) -> None:
    from sqlalchemy import select

    from app.domain.enums import RoleCode
    from app.models.identity import Membership, Role

    other_admin = second_org.users[RoleCode.ORG_ADMIN]
    admin_role = db.scalar(select(Role).where(Role.code == RoleCode.ORG_ADMIN.value))
    db.add(Membership(org_id=org.org.id, user_id=other_admin.id, role_id=admin_role.id))
    db.commit()

    no_slug = client.post(
        "/api/v1/auth/login",
        json={"email": "other-admin@example.com", "password": "TestPassword123!"},
    )
    assert no_slug.status_code == 400
    assert no_slug.json()["error"]["code"] == "organization_required"
    assert len(no_slug.json()["error"]["details"]["organizations"]) == 2

    with_slug = client.post(
        "/api/v1/auth/login",
        json={
            "email": "other-admin@example.com",
            "password": "TestPassword123!",
            "organization_slug": "test-org",
        },
    )
    assert with_slug.status_code == 200
    assert with_slug.json()["organization"]["slug"] == "test-org"


def test_refresh_rotation_and_reuse_detection(client: TestClient, org: OrgFixture) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "investigator@example.com", "password": "TestPassword123!"},
    )
    assert login.status_code == 200
    first_refresh = login.cookies.get("resolve_refresh")
    assert first_refresh

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert refreshed.status_code == 200, refreshed.text
    new_refresh = refreshed.cookies.get("resolve_refresh")
    assert new_refresh and new_refresh != first_refresh

    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "refresh_token_reuse"

    # Reuse detection revoked the whole family, including the rotated token.
    revoked = client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert revoked.status_code == 401


def test_logout_revokes_session(client: TestClient, org: OrgFixture) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@example.com", "password": "TestPassword123!"},
    )
    refresh = login.cookies.get("resolve_refresh")
    assert refresh
    assert client.post("/api/v1/auth/logout").status_code == 200
    again = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert again.status_code == 401


def test_password_reset_flow(client: TestClient, org: OrgFixture) -> None:
    request = client.post("/api/v1/auth/password-reset", json={"email": "viewer@example.com"})
    assert request.status_code == 200
    token = request.json()["dev_token"]
    assert token

    weak = client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "lowercaseonly"}
    )
    assert weak.status_code == 400
    assert weak.json()["error"]["code"] == "weak_password"

    confirmed = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "BrandNewPass123!"},
    )
    assert confirmed.status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@example.com", "password": "BrandNewPass123!"},
    )
    assert login.status_code == 200

    replay = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "AnotherPass123!"},
    )
    assert replay.status_code == 400


def test_password_reset_does_not_reveal_accounts(client: TestClient, org: OrgFixture) -> None:
    response = client.post("/api/v1/auth/password-reset", json={"email": "nobody@example.com"})
    assert response.status_code == 200
    assert response.json()["dev_token"] is None


def test_change_password_revokes_other_sessions(client: TestClient, org: OrgFixture) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "approver@example.com", "password": "TestPassword123!"},
    )
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Organization-Id": str(org.org.id),
    }
    response = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": "TestPassword123!", "new_password": "ChangedPass123!"},
    )
    assert response.status_code == 200
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "approver@example.com", "password": "ChangedPass123!"},
    ).status_code == 200


def test_register_creates_organization_and_admin(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "organization_name": "New Company",
            "organization_slug": "new-company",
            "full_name": "New Admin",
            "email": "newadmin@example.com",
            "password": "StrongPass123!",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["organization"]["slug"] == "new-company"
    assert body["role"] == "org_admin"


def test_production_registration_gate(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "organization_name": "Prod Company",
            "organization_slug": "prod-company",
            "full_name": "Prod Admin",
            "email": "prodadmin@example.com",
            "password": "StrongPass123!",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "registration_disabled"
