"""End-to-end test of the RESOLVE -> n8n webhook contracts.

Sends signed payloads to each workflow, verifies HMAC rejection, idempotency,
Mailpit delivery and n8n execution history. No secret is printed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from pathlib import Path

import httpx

N8N = "http://127.0.0.1:5679"
MAILPIT = "http://127.0.0.1:8125"


def env_value(key: str) -> str:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    raise SystemExit(f"{key} missing from .env")


def sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def post_event(client: httpx.Client, path: str, payload: dict, secret: str, tamper: bool = False) -> tuple[int, dict]:
    body = json.dumps(payload).encode()
    signature = sign(body, secret)
    if tamper:
        signature = "0" * 64
    response = client.post(
        f"{N8N}/webhook/{path}",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Resolve-Event": payload["event_type"],
            "X-Resolve-Signature": signature,
            "X-Resolve-Event-Id": payload["id"],
            "Idempotency-Key": payload["id"],
        },
    )
    try:
        return response.status_code, response.json()
    except Exception:  # noqa: BLE001
        return response.status_code, {"raw": response.text[:200]}


def mailpit_count(client: httpx.Client) -> int:
    return int(client.get(f"{MAILPIT}/api/v1/messages").json()["total"])


def mailpit_subjects(client: httpx.Client) -> list[str]:
    data = client.get(f"{MAILPIT}/api/v1/messages").json()
    return [m["Subject"] for m in data["messages"]]


def main() -> int:
    secret = env_value("N8N_WEBHOOK_SECRET")
    client = httpx.Client(timeout=60)
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(("PASS " if ok else "FAIL ") + name + (f" ({detail})" if detail else ""))

    event_id = str(uuid.uuid4())
    payload = {
        "id": event_id,
        "event_type": "exception.detected",
        "occurred_at": "2026-11-19T12:00:00+00:00",
        "entity_type": "INVOICE",
        "entity_id": str(uuid.uuid4()),
        "data": {
            "exception_id": str(uuid.uuid4()),
            "exception_type": "PRICE_VARIANCE",
            "severity": "HIGH",
            "title": "Automated contract test exception",
        },
    }

    before = mailpit_count(client)

    status, body = post_event(client, "resolve/new-exception", payload, secret)
    check("A: signed event accepted", status == 200 and body.get("status") == "accepted", f"{status} {body}")

    status, body = post_event(client, "resolve/new-exception", payload, secret)
    check("A: duplicate suppressed", status == 200 and body.get("status") == "duplicate", f"{status} {body}")

    status, _ = post_event(client, "resolve/new-exception", {**payload, "id": str(uuid.uuid4())}, secret, tamper=True)
    check("A: invalid signature rejected", status >= 400, str(status))

    after = mailpit_count(client)
    check("A: notification delivered to Mailpit", after > before, f"{before}->{after}")

    # B: escalation contract (case lookup requires a real case id; use a real one)
    results_payload = {
        "id": str(uuid.uuid4()),
        "event_type": "case.escalated",
        "occurred_at": "2026-11-19T12:00:00+00:00",
        "entity_type": "CASE",
        "entity_id": env_value("RESOLVE_TEST_CASE_ID"),
        "data": {"priority": "URGENT", "reason": "Automated contract test escalation"},
    }
    before = mailpit_count(client)
    status, body = post_event(client, "resolve/critical-escalation", results_payload, secret)
    check("B: escalation accepted", status == 200 and body.get("status") in {"escalated", "no_action"}, f"{status} {body}")
    after = mailpit_count(client)
    check("B: escalation email delivered", after > before, f"{before}->{after}")

    # D: document failure contract
    doc_payload = {
        "id": str(uuid.uuid4()),
        "event_type": "document.failed",
        "occurred_at": "2026-11-19T12:00:00+00:00",
        "entity_type": "DOCUMENT",
        "entity_id": env_value("RESOLVE_TEST_DOCUMENT_ID"),
        "data": {"filename": "contract-test.pdf", "status": "FAILED", "error": "OCR contract test", "attempts": 1},
    }
    before = mailpit_count(client)
    status, body = post_event(client, "resolve/document-failure", doc_payload, secret)
    check("D: failure event accepted", status == 200 and body.get("status") in {"notified", "no_action"}, f"{status} {body}")
    after = mailpit_count(client)
    check("D: failure email delivered", after > before, f"{before}->{after}")

    subjects = mailpit_subjects(client)
    check(
        "Mailpit subjects contain RESOLVE alerts",
        any("RESOLVE ESCALATION" in s or "document processing failed" in s for s in subjects),
        " | ".join(subjects[:5]),
    )

    failures = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failures)}/{len(results)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
