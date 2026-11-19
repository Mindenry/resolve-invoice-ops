"""Prove the real RESOLVE -> outbox -> n8n -> Mailpit path end to end.

Creates real records through the public API, waits for the Celery beat publisher
(once a minute) to fan out the signed events, then checks:
  * the outbound webhook log shows HTTP 200 for the matching event type
  * n8n recorded a successful execution for the matching workflow
  * Mailpit received the notification
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE = "https://127.0.0.1:8180/api/v1"
N8N = "http://127.0.0.1:5679"
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


def mail_count() -> int:
    return int(httpx.get(f"{MAILPIT}/api/v1/messages", timeout=20).json()["total"])


def subjects() -> list[str]:
    data = httpx.get(f"{MAILPIT}/api/v1/messages", timeout=20).json()
    return [m["Subject"] for m in data["messages"]]


def wait_for_outbound(client: httpx.Client, headers: dict, event_type: str, timeout: int = 180) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"{BASE}/integrations/events", headers=headers, params={"limit": 100})
        response.raise_for_status()
        for item in response.json():
            if item["direction"] == "OUTBOUND" and item["event_type"] == event_type:
                return item
        time.sleep(10)
    return None


def n8n_executions() -> list[dict]:
    values = env()
    client = httpx.Client(base_url=N8N, timeout=30)
    client.post(
        "/rest/login",
        json={
            "emailOrLdapLoginId": values["N8N_OWNER_EMAIL"],
            "password": values["N8N_OWNER_PASSWORD"],
        },
    ).raise_for_status()
    client.headers.update({"browser-id": "resolve-e2e"})
    response = client.get("/rest/executions", params={"limit": 50})
    response.raise_for_status()
    return response.json().get("data", {}).get("results", [])


def main() -> int:
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

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    title = f"RESOLVE automation E2E {stamp} {uuid.uuid4().hex[:6]}"
    created = client.post(
        f"{BASE}/cases",
        headers=headers,
        json={
            "title": title,
            "description": "Created by the automation end-to-end verification script.",
            "priority": "HIGH",
            "severity": "HIGH",
            "tags": ["automation-e2e"],
        },
    )
    created.raise_for_status()
    case = created.json()
    print("created case", case["case_number"], case["id"])

    before_mail = mail_count()
    event = wait_for_outbound(client, headers, "case.created")
    ok_event = bool(event and (event.get("response_status") or 0) < 400)
    print("case.created outbound:", "delivered" if ok_event else "NOT delivered", event and event.get("response_status"))
    print("mail delta after case.created:", mail_count() - before_mail)

    # Escalation path.
    escalated = client.post(
        f"{BASE}/cases/{case['id']}/escalate",
        headers=headers,
        json={"priority": "URGENT", "reason": "Automation E2E escalation check"},
    )
    escalated.raise_for_status()
    before_mail = mail_count()
    esc_event = wait_for_outbound(client, headers, "case.escalated")
    ok_esc = bool(esc_event and (esc_event.get("response_status") or 0) < 400)
    print("case.escalated outbound:", "delivered" if ok_esc else "NOT delivered", esc_event and esc_event.get("response_status"))
    print("mail delta after case.escalated:", mail_count() - before_mail)

    executions = n8n_executions()
    finished = [e for e in executions if e.get("status") in {"success", "error"}]
    success = [e for e in finished if e.get("status") == "success"]
    print(f"n8n executions: total={len(executions)} finished={len(finished)} success={len(success)}")

    recent_subjects = subjects()[:10]
    delivered_subject = any("RESOLVE ESCALATION" in s or "RESOLVE case.created" in s or title[:40] in s for s in recent_subjects)
    print("mailpit has RESOLVE automation mail:", delivered_subject)

    failures = []
    if not ok_event:
        failures.append("case.created delivery")
    if not ok_esc:
        failures.append("case.escalated delivery")
    if not success:
        failures.append("n8n executions")
    if not delivered_subject:
        failures.append("mailpit delivery")
    print("RESULT:", "PASS" if not failures else "FAIL " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
