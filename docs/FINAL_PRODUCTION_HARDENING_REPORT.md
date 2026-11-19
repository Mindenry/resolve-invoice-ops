# RESOLVE — Final production hardening report

**Date:** 2026-11-19
**Host:** Windows 10 LTSC 19045, Docker Desktop 4.99.0 / Engine 29.9.3 / Compose 5.7.0, WSL2 (8 GB / 4 CPU)
**Baseline:** verified source commit `1d7478a74af6d46d005ee414ae326b0785271344`; the release tag
`v1.0.0-rc.1` includes this report and the final runbooks on top of that baseline.
**Deployment under test:** Docker Compose; native Windows services remain a loopback-only rollback.

Every claim below was executed on this machine. Where something could not be tested, it is marked
**BLOCKED** or **NOT TESTED** rather than implied as working.

## Status summary

| Area | Status | Evidence |
| --- | --- | --- |
| HTTPS/LAN (Windows) | **VERIFIED** | mkcert chain, HSTS, cookies, Playwright 10/10 |
| macOS trust | **BLOCKED** (no Mac) | certificate + detailed commands provided, not executed |
| Credential rotation | **VERIFIED** | old password 401, new 200, 6 accounts rotated |
| Production config | **VERIFIED** | `ENV=production`, `DEBUG=false`, `DEMO_MODE=false`, registration disabled |
| Authentication/RBAC/tenancy | **VERIFIED** | 28-step E2E + 16/16 security checks |
| n8n workflows A–E | **VERIFIED** | 5 active workflows, 9/9 contract checks, real outbox deliveries |
| Prometheus | **VERIFIED** | 13/13 targets up, 20 rules, real metrics |
| Grafana | **VERIFIED** | 4 provisioned dashboards, datasource healthy |
| Alerts | **VERIFIED** | controlled alert and a real DB-down alert delivered to Mailpit |
| Git baseline | **COMPLETED** | commit + annotated tag, no secrets |
| Backup | **VERIFIED** | `backups/compose-20261119-205946`, 65 objects |
| Restore | **VERIFIED** | isolated DB + bucket, counts, vectors, HNSW, SHA-256 |
| Application workflow | **VERIFIED** | 28 steps over HTTPS with real Ollama |
| Restart persistence | **VERIFIED** | data, workflows, dashboards, certs, login |
| Documentation | **COMPLETED** | README + 11 runbooks/reports updated |
| Docker engine resilience | **PARTIALLY COMPLETED** | watchdog task; Linux engine still recommended |
| Real mail / external DNS / domain | **BLOCKED** | no external SMTP, domain or DNS available |

## Live container status (Docker, 18 services)

```
resolve-alertmanager-1      Up
resolve-api-1               Up (healthy)
resolve-beat-1              Up
resolve-blackbox-exporter-1 Up
resolve-celery-exporter-1   Up
resolve-grafana-1           Up
resolve-mailpit-1           Up (healthy)
resolve-n8n-1               Up (healthy)
resolve-nginx-exporter-1    Up
resolve-node-exporter-1     Up
resolve-postgres-1          Up (healthy)
resolve-postgres-exporter-1 Up
resolve-prometheus-1        Up
resolve-redis-1             Up (healthy)
resolve-redis-exporter-1    Up
resolve-seaweedfs-1         Up (healthy)
resolve-web-1               Up (healthy)
resolve-worker-1            Up
```

## 1. What the five workstreams achieved

1. **HTTPS & LAN security** — nginx serves TLS 1.2/1.3 on 8180 with a local mkcert CA
   (`resolve.local`, `192.168.1.10`, `localhost`, `127.0.0.1`; valid to 2029-02-19). HTTP is a
   loopback redirect. Only TCP 8180 is allowed from `LocalSubnet`. All management ports are loopback
   or Docker-internal. Verified with curl, PowerShell, httpx and Playwright.
2. **Demo risk removal & production config** — six accounts rotated to one strong random password in
   an ACL-restricted, Git-ignored file; the retired password is rejected; the login UI no longer
   prints or autofills it; registration is disabled; production startup validation, secure cookies,
   CORS allow-list, Argon2, rate limits and generic error envelopes are active.
3. **n8n as a real automation platform** — owner auth with a preserved encryption key, Asia/Bangkok
   timezone, execution pruning, five workflows (A–E) with HMAC verification, schema validation,
   Redis-backed idempotency, retries and Mailpit notifications; three outbox integrations deliver
   real events and every delivery is auditable in `webhook_events` and `workflow_executions`.
4. **Observability** — API `/metrics` with real HTTP and business series, Prometheus (13 targets,
   20 rules, 15-day retention), Alertmanager→Mailpit, and four Grafana dashboards provisioned from
   Git. A controlled alert and a genuine database-down alert both reached Mailpit.
5. **Git baseline & release** — `.gitignore` audited, secret scan clean, repo-local identity
   `RESOLVE Project <resolve@localhost>`, initial commit `1d7478a` and tag `v1.0.0-rc.1`. No remote,
   no push.

## 2. Files changed (grouped)

* **Compose/infra:** `docker-compose.yml` (HTTPS port, required secrets, n8n owner/encryption,
  exporters, Alertmanager, Grafana provisioning, node textfile collector),
  `infrastructure/docker/nginx.conf`, `apps/web/Dockerfile`, `apps/api/Dockerfile`,
  `infrastructure/scripts/backup.ps1`.
* **API:** `app/api/metrics.py` (new), `app/api/automation.py` (new idempotency claim endpoint),
  `app/main.py`, `app/core/errors.py` (`ServiceUnavailableError`), `app/domain/enums.py`
  (`document.failed`), `app/modules/documents/service.py` (failure event), `pyproject.toml`
  (`prometheus-client`), tests `test_metrics.py` and `test_automation_claims.py`.
* **Web:** `src/pages/auth/LoginPage.tsx` and `src/i18n/index.tsx` (removed hard-coded demo
  credentials), `e2e/*.spec.ts` (password from environment), `scripts/capture.mjs`.
* **Monitoring:** `infrastructure/monitoring/prometheus.yml`, `alerts.yml`, `alertmanager.yml`,
  `blackbox.yml`, `grafana/provisioning/*`, `grafana/dashboards/*.json`.
* **n8n:** `infrastructure/n8n/workflows/resolve-a…e.json` (five real workflows).
* **Operations:** `scripts/watchdog-docker.ps1`, `install-docker-watchdog.ps1`, Docker-first
  start/stop/restart/status/health scripts, plus provisioning and verification scripts
  (`provision-n8n-owner.py`, `provision-n8n-credential.py`, `generate-n8n-workflows.py`,
  `activate-n8n-workflows.py`, `provision-n8n-integrations.py`, `provision-automation-user.py`,
  `prepare-tenant-fixture.py`, `generate-grafana-dashboards.py`, `ensure-monitoring-env.py`,
  `verify-n8n-workflows.py`, `verify-resolve-n8n-e2e.py`, `verify-document-failure-e2e.py`,
  `verify-security.py`, `verify-restored-object.py`).
* **Docs:** `README.md`, `CHANGELOG.md`, `VERSION`, `RELEASE_NOTES.md`, `docs/HTTPS_LAN_SETUP.md`,
  `docs/PRODUCTION_SECURITY_HARDENING.md`, `docs/N8N_RESOLVE_AUTOMATION.md`,
  `docs/OBSERVABILITY_RUNBOOK.md`, `docs/RELEASE_MANAGEMENT.md`, `docs/LAN_ACCESS_GUIDE.md`, and
  updated readiness/limitations/runbooks.

## 3. Services actually running

FastAPI + uvicorn, Celery worker and beat, React SPA behind nginx, PostgreSQL 16.16 + pgvector 0.8.7,
Redis 7, SeaweedFS 4.54, Mailpit 1.34.0, n8n 2.48.6, Prometheus v3.1.0, Alertmanager v0.28.0,
Grafana 13.3.1, nginx/redis/postgres/celery/blackbox/node exporters. Ollama runs on the host
(`qwen2.5:7b-instruct` and `bge-m3`) and is reached from containers via `host.docker.internal`.

## 4. How HTTPS works

* `mkcert -install` created a local CA trusted by Windows; the server certificate is issued for the
  four SANs and stored in `var/certs/` with an ACL restricted to Administrators and SYSTEM.
* nginx terminates TLS on 8180, proxies `/api`, `/health`, `/docs` to the API with
  `X-Forwarded-Proto https`, and serves the SPA. HTTP 8081 redirects to HTTPS and is loopback-only.
* Verified: valid chain, correct SAN, HTTP→HTTPS redirect, Secure/HttpOnly/SameSite=Lax cookies,
  HSTS and security headers, no mixed content, no validation error in Chrome/Playwright.
* Windows `curl` needs `--ssl-no-revoke` because mkcert has no CRL/OCSP endpoint; the certificate
  itself validates. Chrome, PowerShell, Python and Playwright trust the CA normally.

## 5. Client URLs

| Client | URL |
| --- | --- |
| Windows | `https://localhost:8180` |
| Windows (LAN IP) | `https://192.168.1.10:8180` |
| macOS/LAN | `https://192.168.1.10:8180` after trusting `var/certs/rootCA.pem` |
| Optional name | `https://resolve.local:8180` (add a hosts/DNS entry) |
| Health | `https://192.168.1.10:8180/health` |

macOS trust steps (copy the CA, `security add-trusted-cert -d -r trustRoot …`, verify with
`security verify-cert`) are in `docs/HTTPS_LAN_SETUP.md` and `docs/LAN_ACCESS_GUIDE.md`.
**No physical Mac was available; Safari/Keychain trust is NOT TESTED.**

## 6. n8n workflows

| ID | Trigger | Purpose |
| --- | --- | --- |
| `resolve-a-new-exception` | webhook `resolve/new-exception` | signed exception/case events → operations email |
| `resolve-b-critical-escalation` | webhook `resolve/critical-escalation` | URGENT/HIGH or SLA breach → duty-manager email |
| `resolve-c-daily-summary` | cron `0 8 * * *` Asia/Bangkok | aggregate analytics email |
| `resolve-d-document-failure` | webhook `resolve/document-failure` | OCR/parse failure → owner email with retry guidance |
| `resolve-e-health-monitor` | cron `*/5 * * * *` | API/DB/Redis/storage/workers/Ollama/n8n probes → alert email |

All five are active. Duplicate delivery is suppressed through
`POST /api/v1/internal/automation/claims` (Redis `SET NX EX`), invalid HMAC is rejected, and n8n
never approves or executes resolutions.

## 7. Grafana dashboards

1. **RESOLVE — System Overview** — API/DB/Redis/storage up, request rate, 5xx ratio, p95 latency,
   per-route rate.
2. **RESOLVE — Database & Storage** — Postgres up/connections/size/cache hit, Redis memory/clients/
   ops, chunk/vector counts, vector dimension.
3. **RESOLVE — AI & Document Processing** — AI configured, Ollama/n8n probes, documents, embeddings,
   document endpoint rate, latency.
4. **RESOLVE — Business Operations** — total/open/critical/overdue cases, open exceptions, invoices,
   pending approvals, resolved cases.

## 8. Alert test

A temporary `ResolveControlledAlertTest` rule was loaded, Alertmanager reported it active, and Mailpit
received `[RESOLVE ALERT] ResolveControlledAlertTest` at `ops@resolve.local`; the rule was then
removed and Prometheus reloaded. A real `ResolveDatabaseDown` alert also fired during development
(caused by a metrics bug), delivered, and resolved after the fix. **VERIFIED.**

## 9. Git commit

```
1d7478a74af6d46d005ee414ae326b0785271344
chore: establish RESOLVE verified deployment baseline
```

## 10. Release tag

`v1.0.0-rc.1` (annotated). No remote was added and nothing was pushed.

## 11. Backup location

`backups/compose-20261119-205946/` — `database.dump` (SHA-256 in the manifest), `documents/` mirror
(65 objects), `manifest.json`, `database.toc.txt`. Snapshot counts: 4 organizations, 9 users, 14
vendors, 23 purchase orders, 106 invoices, 17 documents, 48 cases, 149 exceptions, 741 audit rows,
16 chunks.

A second backup produced through the installed scheduled path —
`backups/compose-20261119-213454` — contains 69 objects, 110 invoices, 59 cases, 21 documents, 157
exceptions, 892 audit rows and 20 chunks. The `RESOLVE-Daily-Backup` task runs it daily at 02:30 and
the freshness metric is scraped by Prometheus.

Current live counts after later verification runs: 110 invoices, 59 cases, 21 documents, 157
exceptions, 889 audit rows, 20 chunks, 69 S3 objects.

## 12. Restore result

Restored into the isolated database `resolve_restore_hardening_20261119_210117` and bucket
`resolve-documents-restore-hardening` (65 objects). Verified: row counts identical, 16 vector rows at
dimension **1024**, index `ix_document_chunks_embedding_vec` (HNSW), a nearest-neighbour query
returned 3 rows, and one object's SHA-256 matched the backup mirror byte-for-byte. Production data
was not overwritten.

## 13. Security tests

**16/16 passed** (`scripts/verify-security.py`): retired password 401, rotated password 200, viewer
write 403, unauthenticated mutation 401, forged org header 403, login 429 after the limit, cookie
flags, HSTS, security headers, `no-store`, `/metrics` not served on LAN, n8n/Grafana/Prometheus/API
unreachable on LAN, and no internals in error responses. The end-to-end suite adds cross-tenant 404s,
self-approval 403 and registration-disabled 403.

## 14. Full workflow

**Passed — 28 steps** over HTTPS against the Docker stack: login, profile, vendor, purchase order,
upload, extraction (10 fields), field correction, extraction approval, invoice creation + idempotency,
validation, exception generation, case creation/assignment, real Ollama investigation with 4 validated
evidence citations, resolution proposal, approval queue, decision, execution (Mailpit SMTP), audit
trail (9 rows), timeline (9 entries), analytics, viewer denial, registration denial, cross-tenant
reads/mutations denied, self-approval denied, and direct PostgreSQL assertions.

## 15. Remaining limitations

* **No physical Mac** — trust steps documented, Safari untested (**BLOCKED**).
* **No external DNS/domain** — HTTPS uses an IP and a local CA (**BLOCKED** by environment).
* **No external SMTP** — Mailpit only; no mail leaves the machine (**BLOCKED** by environment).
* **Docker Desktop** — the engine occasionally exits; a watchdog runs every minute and Compose has
  restart policies, but a Linux Docker Engine is recommended (**PARTIALLY COMPLETED**).
* **Single-node SeaweedFS** — no replication or HA.
* **Rate limiting** — the Docker userland proxy collapses client IPs to one gateway address, so the
  login bucket is shared across LAN clients; limits still fire (observed 429 at request 18–21).
  Rate-limit storage is in-process memory; move to Redis before scaling the API.
* **Demo workspace** — still present with synthetic data; must be removed or re-keyed before real
  data.
* **Backup retention** — the daily task (`RESOLVE-Daily-Backup`, 02:30) runs and has produced a
  verified backup, and a 26-hour staleness alert exists. Retention/pruning is intentionally manual so
  no backup is deleted automatically; copy backups off-host.
* Prometheus holds 15 days; metrics history is not backed up.

## 16. Required before real financial data

1. Delete or fully re-key the demo workspace and accounts; keep only named users with MFA at the
   identity provider if one is introduced.
2. Replace Mailpit with a real SMTP relay over TLS and configure SPF/DKIM/DMARC.
3. Obtain a real domain + internal DNS and replace the mkcert CA with a managed certificate.
4. Move to a Linux Docker Engine (or managed container host) with automated OS patching.
5. Make SeaweedFS/PostgreSQL HA or use managed services; enable PITR for PostgreSQL.
6. Install and verify the daily backup scheduled task, off-host copy, and restore drills.
7. Confirm retention/legal requirements for documents and audit logs.
8. Complete a UAT sign-off with real operational roles and an external penetration test.
9. Review rate-limit topology (real client IPs) and move limiter storage to Redis.
10. Confirm the approval policy, thresholds and segregation-of-duties rules with finance.

## Reproduce the verification

```powershell
$env:SSL_CERT_FILE = (Resolve-Path "var\certs\rootCA.pem").Path
$env:RESOLVE_DEMO_PASSWORD = ((Get-Content var\secrets\demo-credentials.txt |
  Select-String "^admin@example.com=").Line.Split("=",2)[1]).Trim()

docker compose --env-file .env --profile monitoring ps
curl --ssl-no-revoke https://192.168.1.10:8180/health

.\.venv\Scripts\python.exe scripts\verify-security.py
.\.venv\Scripts\python.exe scripts\verify-n8n-workflows.py
.\.venv\Scripts\python.exe scripts\verify-resolve-n8n-e2e.py
.\.venv\Scripts\python.exe apps\api\scripts\verify_workflow_e2e.py --base-url https://192.168.1.10:8180
cd apps\web; $env:RESOLVE_WEB_URL="https://192.168.1.10:8180"; npx playwright test
```

No secrets are included in this report. Credentials live in `var/secrets/demo-credentials.txt`;
service secrets live in `.env`; both are Git-ignored and ACL-restricted.
