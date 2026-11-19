"""Vendor listing, duplicate detection and JSON array filters."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.domain.enums import RoleCode
from tests.conftest import OrgFixture
from tests.factories import make_vendor


def test_risk_flag_filter_matches_exact_token(client: TestClient, org: OrgFixture, db) -> None:
    tagged = make_vendor(db, org.org.id, number=f"V-{uuid.uuid4().hex[:6]}", tax_id=None)
    other = make_vendor(db, org.org.id, number=f"V-{uuid.uuid4().hex[:6]}", tax_id=None)
    tagged.risk_flags = ["BANK_CHANGE"]
    other.risk_flags = ["BANK_CHANGE_REVIEW"]
    db.commit()

    response = client.get(
        "/api/v1/vendors",
        headers=org.headers[RoleCode.VIEWER],
        params={"risk_flag": "BANK_CHANGE", "page_size": 100},
    )
    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert str(tagged.id) in ids
    assert str(other.id) not in ids


def test_vendor_list_is_tenant_scoped(
    client: TestClient, org: OrgFixture, db, second_org: OrgFixture
) -> None:
    mine = make_vendor(db, org.org.id, number=f"V-{uuid.uuid4().hex[:6]}", tax_id=None)
    theirs = make_vendor(db, second_org.org.id, number=f"V-{uuid.uuid4().hex[:6]}", tax_id=None)
    db.commit()

    response = client.get("/api/v1/vendors", headers=org.headers[RoleCode.ORG_ADMIN], params={"page_size": 100})
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert str(mine.id) in ids
    assert str(theirs.id) not in ids

    detail = client.get(f"/api/v1/vendors/{theirs.id}", headers=org.headers[RoleCode.ORG_ADMIN])
    assert detail.status_code == 404
