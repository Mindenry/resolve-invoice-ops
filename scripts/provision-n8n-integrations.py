"""Create or update the RESOLVE -> n8n integrations (idempotent).

Each integration subscribes to a narrow event filter and points at the matching
n8n production webhook. The HMAC signing secret is stored as an encrypted
integration credential; it is never printed.
"""

from __future__ import annotations

from pathlib import Path

import httpx

BASE = "https://127.0.0.1:8180/api/v1"
VERIFY = "var/certs/rootCA.pem"
ORG_SLUG = "northwind"

INTEGRATIONS = [
    {
        "name": "n8n New Exception Notification",
        "webhook_url": "http://n8n:5678/webhook/resolve/new-exception",
        "workflow_key": "new-exception-notification",
        "event_filter": ["exception.detected", "case.created"],
    },
    {
        "name": "n8n Critical Case Escalation",
        "webhook_url": "http://n8n:5678/webhook/resolve/critical-escalation",
        "workflow_key": "high-priority-escalation",
        "event_filter": ["case.escalated", "case.priority_changed"],
    },
    {
        "name": "n8n Document Processing Failure",
        "webhook_url": "http://n8n:5678/webhook/resolve/document-failure",
        "workflow_key": "document-processing-failure",
        "event_filter": ["document.failed"],
    },
]


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
    client = httpx.Client(verify=VERIFY, timeout=30)
    login = client.post(
        f"{BASE}/auth/login",
        json={"email": "admin@example.com", "password": admin_password(), "organization_slug": ORG_SLUG},
    )
    login.raise_for_status()
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Organization-Id": login.json()["organization"]["id"],
    }

    existing = client.get(f"{BASE}/integrations", headers=headers)
    existing.raise_for_status()
    by_name = {item["name"]: item for item in existing.json()}

    for spec in INTEGRATIONS:
        payload = {
            "name": spec["name"],
            "kind": "N8N",
            "config": {
                "webhook_url": spec["webhook_url"],
                "workflow_key": spec["workflow_key"],
                "base_url": "http://n8n:5678",
            },
            "event_filter": spec["event_filter"],
            "is_enabled": True,
            "credentials": {"signing_secret": values["N8N_WEBHOOK_SECRET"]},
        }
        current = by_name.get(spec["name"])
        if current:
            response = client.patch(
                f"{BASE}/integrations/{current['id']}",
                headers=headers,
                json={
                    "config": payload["config"],
                    "event_filter": payload["event_filter"],
                    "is_enabled": True,
                },
            )
            response.raise_for_status()
            creds = client.put(
                f"{BASE}/integrations/{current['id']}/credentials",
                headers=headers,
                json={"credentials": {"signing_secret": values["N8N_WEBHOOK_SECRET"]}},
            )
            creds.raise_for_status()
            print("updated integration:", spec["name"])
        else:
            response = client.post(f"{BASE}/integrations", headers=headers, json=payload)
            response.raise_for_status()
            print("created integration:", spec["name"])

    listed = client.get(f"{BASE}/integrations", headers=headers).json()
    for item in listed:
        if item["name"] in {spec["name"] for spec in INTEGRATIONS}:
            print(
                f"  {item['name']}: enabled={item['is_enabled']} "
                f"events={','.join(item['event_filter'])} creds={','.join(item['credential_keys'])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
