# RESOLVE × n8n automation

n8n is a real automation tier in the RESOLVE stack, not a decorative container. It receives
HMAC-signed domain events from the RESOLVE transactional outbox, validates and deduplicates them,
and produces operational notifications (Mailpit in this environment). It never approves, executes or
mutates financial state — those actions stay inside RESOLVE's approval policy.

## 1. Service facts

| Item | Value |
| --- | --- |
| Image | `n8nio/n8n:2.48.6` |
| URL (host only) | <http://127.0.0.1:5679> |
| Exposure | loopback only; no LAN rule, no public access |
| Auth | n8n owner account (`N8N_OWNER_EMAIL`), no basic-auth, no anonymous access |
| Timezone | `Asia/Bangkok` (container `TZ` + every workflow `settings.timezone`) |
| Encryption key | `N8N_ENCRYPTION_KEY` in `.env`; the key already present in `n8n_data/config` was adopted so credentials survive restarts |
| Persistence | Docker volume `resolve_n8n_data` (SQLite DB, credentials, workflow static data) |
| Execution retention | pruning on, 168 hours (`N8N_EXECUTIONS_MAX_AGE_HOURS`) |
| Diagnostics/templates | disabled (`N8N_DIAGNOSTICS_ENABLED=false`, `N8N_TEMPLATES_ENABLED=false`) |
| Code node modules | only `crypto` is allowed (`NODE_FUNCTION_ALLOW_BUILTIN=crypto`) for HMAC verification |
| Env access in nodes | enabled for the trusted owner-authored workflows (`N8N_BLOCK_ENV_ACCESS_IN_NODE=false`); workflow authoring is restricted to the owner |

`N8N_BASIC_AUTH_ACTIVE=false` because n8n 2.x uses owner user management. The old basic-auth
variables are intentionally ignored.

## 2. Contracts between RESOLVE and n8n

Every outbound event is produced by `app.services.events.emit_event` into the `domain_events`
outbox, then published by the Celery beat task `resolve.maintenance.publish_events` (every minute).

Request shape (HTTP POST, JSON body, exact bytes are signed):

```json
{
  "id": "<domain event uuid>",
  "event_type": "case.created",
  "occurred_at": "2026-11-19T12:00:00+00:00",
  "entity_type": "CASE",
  "entity_id": "<uuid>",
  "data": { "...": "..." }
}
```

Headers:

| Header | Meaning |
| --- | --- |
| `X-Resolve-Signature` | hex HMAC-SHA256 of the raw body with `N8N_WEBHOOK_SECRET` |
| `X-Resolve-Event` | event type |
| `X-Resolve-Event-Id` | stable event id |
| `Idempotency-Key` | same event id (documented for consumers) |

n8n verifies the signature over the raw body (base64 binary output of the Webhook node), validates
the schema (`id`, `event_type` required) and rejects mismatches with an execution error (HTTP 500),
which makes RESOLVE retry the delivery.

### Durable idempotency

n8n 2.x executes Code nodes in a task runner, so `$getWorkflowStaticData()` is not persisted from
Code nodes. Instead every webhook workflow calls RESOLVE's internal claim store:

```
POST http://api:8000/api/v1/internal/automation/claims
X-Automation-Secret: <N8N_WEBHOOK_SECRET>
{"key":"<event id>"}
→ {"key":"...","claimed":true|false,"ttl_seconds":86400}
```

The endpoint is implemented in `apps/api/app/api/automation.py` and stores the claim in Redis with
`SET NX EX 86400`. It is reachable only on the Docker network (the API is loopback-only on the host)
and requires the shared secret. If Redis is unavailable the endpoint returns 503 and the workflow
fails closed, so a retry cannot double-notify.

## 3. Workflows

All five are imported from `infrastructure/n8n/workflows/resolve-*.json` and active.

### A — New exception and case notification

* Trigger: `POST /webhook/resolve/new-exception`
* Subscribed events: `exception.detected`, `case.created`
* Flow: Webhook → Verify signature → Claim event id → Merge claim → Duplicate? → Mailpit email → respond
* Responses: `{"status":"accepted"}`, `{"status":"duplicate"}` or HTTP 500 for a bad signature
* Workflow id: `resolve-a-new-exception`

### B — Critical case escalation

* Trigger: `POST /webhook/resolve/critical-escalation`
* Subscribed events: `case.escalated`, `case.priority_changed`
* Flow: verify → claim → log in as the read-only automation account → load the case from the API →
  confirm tenant ownership, urgency (`URGENT`/`HIGH`) or SLA breach and that the case is not closed →
  escalation email → respond `escalated` / `no_action` / `duplicate`
* Workflow id: `resolve-b-critical-escalation`

### C — Daily operations summary

* Trigger: Schedule, cron `0 8 * * *`, timezone `Asia/Bangkok`
* Flow: log in (read-only automation) → `GET /api/v1/analytics/overview?days=7` → build an aggregate
  summary (no personal data) → email to `ops@resolve.local`
* Workflow id: `resolve-c-daily-summary`

### D — Document processing failure

* Trigger: `POST /webhook/resolve/document-failure`
* Subscribed events: `document.failed` (emitted by the document worker when parsing/OCR fails)
* Flow: verify → claim → log in → load document → notify document owners with status, attempts,
  retry recommendation and the truncated error (never secrets) → respond
* Workflow id: `resolve-d-document-failure`

### E — Integration health monitor

* Trigger: Schedule every 5 minutes (`Asia/Bangkok` workflow timezone)
* Flow: sequential probes of `/health/ready`, Ollama `/api/version`, n8n `/healthz`, Prometheus
  `sum(celery_worker_up)` → aggregate verdict → email only when degraded
* Workflow id: `resolve-e-health-monitor`

## 4. RESOLVE integrations (outbox subscriptions)

| Integration | Kind | Event filter | Webhook |
| --- | --- | --- | --- |
| n8n New Exception Notification | N8N | `exception.detected`, `case.created` | `http://n8n:5678/webhook/resolve/new-exception` |
| n8n Critical Case Escalation | N8N | `case.escalated`, `case.priority_changed` | `http://n8n:5678/webhook/resolve/critical-escalation` |
| n8n Document Processing Failure | N8N | `document.failed` | `http://n8n:5678/webhook/resolve/document-failure` |

Each integration stores `signing_secret` as an encrypted integration credential (same value as
`N8N_WEBHOOK_SECRET`). Every delivery is recorded twice for audit: `webhook_events` (outbound HTTP
status, response code, error, idempotency key) and `workflow_executions` (workflow key, status,
attempts, result).

## 5. Automation account

`automation@example.com` with role `viewer` — read-only by design:

* allowed: `analytics:read`, `case:read`, `document:read` and the other read permissions
* denied: approvals, execution, case mutation, document reprocess, integration management

Credentials live in `.env` (`RESOLVE_AUTOMATION_EMAIL`, `RESOLVE_AUTOMATION_PASSWORD`,
`RESOLVE_AUTOMATION_ORG_ID`) and are passed only to the n8n container. They are never written to
Git, logs or prompts.

## 6. Verification evidence

| Check | Result |
| --- | --- |
| Signed event accepted (A/B/D) | PASS — HTTP 200 `accepted` / `escalated` / `notified` |
| Duplicate delivery suppressed | PASS — second POST returns `duplicate` |
| Invalid HMAC rejected | PASS — execution error, HTTP 500 |
| Mailpit delivery | PASS — subjects `RESOLVE exception.detected …`, `RESOLVE ESCALATION HIGH CASE-…`, `RESOLVE document processing failed …` |
| Real RESOLVE outbox → n8n | PASS — `case.created` and `case.escalated` outbound HTTP 200, emails received |
| Document failure end-to-end | PASS — reprocessed failed document emitted `document.failed`, delivered HTTP 200, email received |
| Daily summary scheduled run | PASS — workflow executed from the schedule trigger and emailed the summary |
| Restart persistence | PASS — workflows, credentials and owner session recovered after `docker compose restart n8n` |
| n8n UI access | loopback only, owner login |

Reproduce:

```powershell
.\.venv\Scripts\python.exe scripts\provision-n8n-owner.py
.\.venv\Scripts\python.exe scripts\provision-n8n-credential.py
.\.venv\Scripts\python.exe scripts\generate-n8n-workflows.py
# import + activate with the helper commands in section 8
.\.venv\Scripts\python.exe scripts\provision-n8n-integrations.py
.\.venv\Scripts\python.exe scripts\verify-n8n-workflows.py
.\.venv\Scripts\python.exe scripts\verify-resolve-n8n-e2e.py
.\.venv\Scripts\python.exe scripts\verify-document-failure-e2e.py
```

## 7. Failure handling

* **Signature failure** → execution error, HTTP 500, RESOLVE marks the outbound delivery failed and
  retries up to 5 attempts; after that the event is `FAILED` and visible in the Integration Hub.
* **Duplicate** → claim returns `false`, response `duplicate`, no email.
* **Mailpit down** → email node fails, n8n execution is `error`, visible in executions and alerts.
* **Redis down** → claim endpoint 503, workflow fails closed.
* **n8n down** → RESOLVE records `workflow_executions.status = FAILED` and `webhook_events.status =
  FAILED`, Prometheus `ResolveN8nUnavailable` fires.

n8n never creates cases, approves requests or executes resolutions. Escalations only notify humans;
the resolution still requires an approver in RESOLVE and the execution worker enforces the approval
record.

## 8. Operations

```powershell
# Import (workflows dir is mounted read-only at /workflows)
docker compose exec -T n8n n8n import:workflow --input=/workflows/resolve-a-new-exception.json
# ... repeat per file, then activate with the owner session
.\.venv\Scripts\python.exe scripts\activate-n8n-workflows.py

# Inspect
docker compose logs n8n --tail 100
# UI: http://127.0.0.1:5679 (owner credentials in .env)
```

Backup: `n8n_data` is included in the Docker volume backup described in
`docs/BACKUP_RESTORE_RUNBOOK.md`. Keep `N8N_ENCRYPTION_KEY` stable or imported credentials cannot be
decrypted.

## 9. Limitations

* Mailpit is a local sink; no external SMTP is configured, so no mail leaves this machine.
* n8n runs in regular mode (not queue mode). Schedule/webhook triggers are single-instance.
* Execution history is pruned after 7 days.
