"""Activate the imported RESOLVE n8n workflows via the authenticated REST API.

n8n 2.x refuses CLI activation in regular (non-queue) mode, so activation must go
through the owner session.
"""

from __future__ import annotations

from pathlib import Path

import httpx

BASE = "http://127.0.0.1:5679"
TARGETS = [
    "RESOLVE A - New exception and case notification",
    "RESOLVE B - Critical case escalation",
    "RESOLVE C - Daily operations summary",
    "RESOLVE D - Document processing failure",
    "RESOLVE E - Integration health monitor",
]


def env_value(key: str) -> str:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    raise SystemExit(f"{key} missing from .env")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=60)
    client.post(
        "/rest/login",
        json={
            "emailOrLdapLoginId": env_value("N8N_OWNER_EMAIL"),
            "password": env_value("N8N_OWNER_PASSWORD"),
        },
    ).raise_for_status()
    client.headers.update({"browser-id": "resolve-activation"})

    listing = client.get("/rest/workflows", params={"limit": 100})
    listing.raise_for_status()
    by_name = {item["name"]: item for item in listing.json().get("data", [])}

    failures = 0
    for name in TARGETS:
        item = by_name.get(name)
        if item is None:
            print("missing workflow:", name)
            failures += 1
            continue
        wid = item["id"]
        if item.get("active"):
            print("already active:", name)
            continue
        response = client.post(
            f"/rest/workflows/{wid}/activate", json={"versionId": item.get("versionId")}
        )
        if response.status_code >= 400:
            print("activation failed:", name, response.status_code, response.text[:300])
            failures += 1
        else:
            print("activated:", name)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
