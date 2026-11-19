"""Create the Mailpit SMTP credential in n8n (idempotent).

Mailpit is a local sink with no authentication; the credential exists so the
workflows use n8n's credential store rather than inline SMTP settings.
"""

from __future__ import annotations

from pathlib import Path

import httpx

BASE = "http://127.0.0.1:5679"
NAME = "RESOLVE Mailpit SMTP"
CRED_ID = "resolveMailpitSmtp"


def env_value(key: str) -> str | None:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return None


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30)
    login = client.post(
        "/rest/login",
        json={
            "emailOrLdapLoginId": env_value("N8N_OWNER_EMAIL"),
            "password": env_value("N8N_OWNER_PASSWORD"),
        },
    )
    login.raise_for_status()
    client.headers.update({"browser-id": "resolve-provisioning"})

    data = {
        "host": "mailpit",
        "port": 1025,
        "secure": False,
        "user": "",
        "password": "",
    }

    existing = client.get("/rest/credentials", params={"filter": {"type": ["smtp"]}})
    if existing.status_code == 200:
        for item in existing.json().get("data", []):
            if item.get("name") == NAME:
                print("smtp credential already present:", item.get("id"))
                return 0

    response = client.post(
        "/rest/credentials",
        json={"name": NAME, "type": "smtp", "data": data, "id": CRED_ID},
    )
    if response.status_code in (200, 201):
        body = response.json().get("data", {})
        print("created smtp credential:", body.get("id") or CRED_ID)
        return 0
    print("credential create failed", response.status_code, response.text[:300])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
