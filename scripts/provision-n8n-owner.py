"""Create the n8n owner account on first run and verify authenticated access.

The generated password is written to .env (ignored by Git) and never printed.
Uses the loopback n8n port only.
"""

from __future__ import annotations

import secrets
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:5679"
EMAIL = "owner@resolve.local"


def env_value(key: str) -> str | None:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return None


def set_env(key: str, value: str) -> None:
    path = Path(".env")
    lines = path.read_text(encoding="utf-8").splitlines()
    out = [f"{key}={value}" if line.startswith(f"{key}=") else line for line in lines]
    if not any(line.startswith(f"{key}=") for line in out):
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30)
    settings = client.get("/rest/settings").json()["data"]
    password = env_value("N8N_OWNER_PASSWORD")

    if settings["userManagement"].get("showSetupOnFirstLoad"):
        password = password or (secrets.token_urlsafe(24) + "Aa1!")
        response = client.post(
            "/rest/owner/setup",
            json={
                "email": EMAIL,
                "firstName": "RESOLVE",
                "lastName": "Owner",
                "password": password,
                "agree": True,
            },
        )
        if response.status_code >= 400 and "already" not in response.text.lower():
            print("owner setup failed", response.status_code, response.text[:300])
            return 1
        print("owner account created")

    if not password:
        print("N8N_OWNER_PASSWORD missing in .env but owner exists")
        return 1

    login = client.post(
        "/rest/login", json={"emailOrLdapLoginId": EMAIL, "password": password}
    )
    if login.status_code >= 400:
        print("login failed", login.status_code, login.text[:200])
        return 1
    print("n8n login ok; cookie set:", "n8n-auth" in client.cookies)

    workflows = client.get("/rest/workflows", params={"limit": 5})
    print("workflows endpoint", workflows.status_code)

    set_env("N8N_OWNER_EMAIL", EMAIL)
    set_env("N8N_OWNER_PASSWORD", password)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
