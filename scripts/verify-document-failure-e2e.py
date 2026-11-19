"""Re-run processing on the known-failed document to prove Workflow D end to end."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

BASE = "https://127.0.0.1:8180/api/v1"
MAILPIT = "http://127.0.0.1:8125"
VERIFY = "var/certs/rootCA.pem"


def env() -> dict[str, str]:
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in Path(".env").read_text(encoding="utf-8").splitlines()
        if "=" in line
    }


def admin_password() -> str:
    for line in Path("var/secrets/demo-credentials.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("admin@example.com="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("admin password not found")


def main() -> int:
    values = env()
    document_id = values["RESOLVE_TEST_DOCUMENT_ID"]
    client = httpx.Client(verify=VERIFY, timeout=60)
    login = client.post(
        f"{BASE}/auth/login",
        json={
            "email": "admin@example.com",
            "password": admin_password(),
            "organization_slug": "northwind",
        },
    )
    login.raise_for_status()
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Organization-Id": login.json()["organization"]["id"],
    }

    before_mail = int(httpx.get(f"{MAILPIT}/api/v1/messages", timeout=20).json()["total"])
    reprocess = client.post(
        f"{BASE}/documents/{document_id}/reprocess",
        headers=headers,
        json={"reason": "Automation E2E verification of document failure handling"},
    )
    print("reprocess", reprocess.status_code)

    deadline = time.time() + 240
    delivered = None
    while time.time() < deadline:
        events = client.get(f"{BASE}/integrations/events", headers=headers, params={"limit": 100})
        events.raise_for_status()
        for item in events.json():
            if (
                item["direction"] == "OUTBOUND"
                and item["event_type"] == "document.failed"
                and (item.get("response_status") or 0) < 400
            ):
                delivered = item
                break
        if delivered:
            break
        time.sleep(10)

    print("document.failed outbound:", "delivered" if delivered else "NOT delivered")
    after_mail = int(httpx.get(f"{MAILPIT}/api/v1/messages", timeout=20).json()["total"])
    print("mail delta:", after_mail - before_mail)
    document = client.get(f"{BASE}/documents/{document_id}", headers=headers)
    print("document status:", document.json().get("status") if document.status_code == 200 else document.status_code)

    return 0 if delivered and after_mail > before_mail else 1


if __name__ == "__main__":
    raise SystemExit(main())
