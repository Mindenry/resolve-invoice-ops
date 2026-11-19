"""Add missing secret/environment keys to .env without printing values."""

import secrets
from pathlib import Path

env_path = Path(".env")
text = env_path.read_text(encoding="utf-8")


def set_key(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    out = []
    found = False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    return "\n".join(out) + "\n"


existing = {
    line.split("=", 1)[0]: line.split("=", 1)[1]
    for line in text.splitlines()
    if "=" in line and not line.strip().startswith("#")
}

added = []
if not existing.get("N8N_ENCRYPTION_KEY") or existing["N8N_ENCRYPTION_KEY"].startswith("change"):
    text = set_key(text, "N8N_ENCRYPTION_KEY", secrets.token_urlsafe(48))
    added.append("N8N_ENCRYPTION_KEY")

if not existing.get("GRAFANA_PASSWORD") or existing["GRAFANA_PASSWORD"].startswith("change"):
    text = set_key(text, "GRAFANA_PASSWORD", "Aa1!" + secrets.token_urlsafe(24))
    added.append("GRAFANA_PASSWORD")

if not existing.get("N8N_WEBHOOK_SECRET") or existing["N8N_WEBHOOK_SECRET"].startswith("change"):
    text = set_key(text, "N8N_WEBHOOK_SECRET", secrets.token_urlsafe(40))
    added.append("N8N_WEBHOOK_SECRET")

for key, value in {
    "ALERTMANAGER_PORT": "9193",
    "GRAFANA_ADMIN_USER": "admin",
    "N8N_EXECUTIONS_MAX_AGE_HOURS": "168",
    "GENERIC_TIMEZONE": "Asia/Bangkok",
}.items():
    if key not in existing:
        text = set_key(text, key, value)
        added.append(key)

env_path.write_text(text, encoding="utf-8")
print("updated keys:", ", ".join(added) if added else "none")
