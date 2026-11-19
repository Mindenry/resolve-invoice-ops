"""Create the read-only RESOLVE automation account used by n8n.

The account has the VIEWER role: it can read analytics, cases and documents but
cannot approve, execute or mutate business data. Credentials are written to .env
(ignored by Git) and never printed.
"""

from __future__ import annotations

import secrets
from pathlib import Path

import httpx

BASE = "https://127.0.0.1:8180/api/v1"
VERIFY = "var/certs/rootCA.pem"
ADMIN_EMAIL = "admin@example.com"
ORG_SLUG = "northwind"
AUTOMATION_EMAIL = "automation@example.com"


def admin_password() -> str:
    for line in Path("var/secrets/demo-credentials.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{ADMIN_EMAIL}="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("admin password not found in var/secrets/demo-credentials.txt")


def env_value(key: str) -> str | None:
    text = Path(".env").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return None


def set_env(key: str, value: str) -> None:
    path = Path(".env")
    text = path.read_text(encoding="utf-8")
    lines = [
        f"{key}={value}" if line.startswith(f"{key}=") else line for line in text.splitlines()
    ]
    if not any(line.startswith(f"{key}=") for line in lines):
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def login(client: httpx.Client, email: str, password: str) -> dict:
    response = client.post(
        f"{BASE}/auth/login",
        json={"email": email, "password": password, "organization_slug": ORG_SLUG},
    )
    response.raise_for_status()
    return response.json()


def main() -> int:
    password = secrets.token_urlsafe(24) + "Aa1!"
    headers = {}
    client = httpx.Client(verify=VERIFY, timeout=30)
    admin = login(client, ADMIN_EMAIL, admin_password())
    headers = {
        "Authorization": f"Bearer {admin['access_token']}",
        "X-Organization-Id": admin["organization"]["id"],
    }

    existing = client.get(f"{BASE}/users", headers=headers, params={"limit": 200})
    existing.raise_for_status()
    members = existing.json().get("items", [])
    target = next((m for m in members if m.get("email") == AUTOMATION_EMAIL), None)

    if target:
        membership_id = target["id"]
        current = env_value("RESOLVE_AUTOMATION_PASSWORD") or password
        response = client.patch(
            f"{BASE}/users/{membership_id}",
            headers=headers,
            json={"role": "viewer", "is_active": True},
        )
        response.raise_for_status()
        password = current
        action = "updated"
    else:
        response = client.post(
            f"{BASE}/users",
            headers=headers,
            json={
                "email": AUTOMATION_EMAIL,
                "full_name": "RESOLVE Automation",
                "role": "viewer",
                "job_title": "n8n service account (read-only)",
                "temporary_password": password,
            },
        )
        response.raise_for_status()
        action = "created"

    # Verify the automation account can log in and read analytics.
    try:
        automation = login(client, AUTOMATION_EMAIL, password)
    except httpx.HTTPStatusError:
        # An existing account may have a rotated password that is no longer known.
        response = client.patch(
            f"{BASE}/users/{target['id']}",
            headers=headers,
            json={"is_active": False},
        )
        response.raise_for_status()
        print("existing automation account has an unknown password; deactivated instead")
        return 1

    org_id = automation["organization"]["id"]
    auto_headers = {
        "Authorization": f"Bearer {automation['access_token']}",
        "X-Organization-Id": org_id,
    }
    overview = client.get(f"{BASE}/analytics/overview", headers=auto_headers, params={"days": 1})
    overview.raise_for_status()

    set_env("RESOLVE_AUTOMATION_EMAIL", AUTOMATION_EMAIL)
    set_env("RESOLVE_AUTOMATION_PASSWORD", password)
    set_env("RESOLVE_ORGANIZATION_SLUG", ORG_SLUG)
    set_env("RESOLVE_AUTOMATION_ORG_ID", org_id)

    kpis = overview.json().get("data", {}).get("kpis", [])
    print(f"automation account {action}; login ok; analytics kpis={len(kpis)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
