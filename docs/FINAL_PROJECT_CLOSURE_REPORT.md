# RESOLVE — Final project closure report

**Date:** 2026-11-19
**Release:** v1.0.0
**Source baseline commit:** `466d923467081c55e29b86081598b1e362116555`
**Release tag:** `v1.0.0` (annotated; the tag commit also contains this report)
**Deployment:** Docker Compose, `https://192.168.1.107:8180` and `https://localhost:8180`
**Status:** **FINALIZED** for portfolio/demo use and controlled LAN evaluation. Not approved for real
financial data until the external items in section 17 are closed.

## 1. Final project status

All software work under the control of this machine is complete, tested and committed. The product
runs as an 18-service Docker deployment with HTTPS, local AI, OCR, n8n automation, monitoring,
backup/restore and a portfolio package. Two real defects were found during final acceptance, fixed and
regression-tested:

1. **Concurrent approval race** — two simultaneous approvals could both succeed. Fixed with an atomic
   conditional claim; live result is one 200 and one 409.
2. **Invoice detail crash** — Radix `Slot` received multiple children from the shared Button. Fixed;
   the app now records zero console errors across the verified routes.

## 2. Final release version

`1.0.0` (`VERSION`), tag `v1.0.0`. The previous hardening candidate remains available as
`v1.0.0-rc.1`.

## 3. Commit hash

Source baseline: `466d923467081c55e29b86081598b1e362116555`.
The annotated tag `v1.0.0` points at the documentation closure commit; resolve it with
`git rev-parse v1.0.0`. Working tree is clean.

## 4. Release tag

`v1.0.0` (annotated, repository-local identity `RESOLVE Project <resolve@localhost>`). No remote and
no push.

## 5. Docker status

18 services running after a full `docker compose restart`:

```
alertmanager, api (healthy), beat, blackbox-exporter, celery-exporter,
grafana, mailpit (healthy), n8n (healthy), nginx-exporter, node-exporter,
postgres (healthy), postgres-exporter, prometheus, redis (healthy),
redis-exporter, seaweedfs (healthy), web (healthy), worker
```

Post-restart verification: 1,822 audit rows, 183 invoices, 158 cases, 39 documents, 33 chunks / 33
vectors, 5 active n8n workflows, 4 Grafana dashboards, 13/13 Prometheus targets, HTTPS 200 and login
successful.

## 6. Application test results

| Suite | Result |
| --- | --- |
| Backend (pytest) | **137 passed, 1 skipped** |
| Frontend typecheck / lint | pass / 0 errors (4 pre-existing warnings) |
| Frontend unit (Vitest) | **6/6** |
| Production build | pass |
| Playwright over HTTPS | **10/10** |
| Full workflow over HTTPS | **28 steps** |
| Final acceptance | **26/26** |

The 28-step workflow covered vendor, PO, upload, OCR, extraction, correction, extraction approval,
invoice creation (idempotent), validation, exceptions, case, assignment, real Ollama investigation
with validated evidence, proposal, approval queue, decision, execution (Mailpit), audit, timeline,
analytics, viewer denial, registration denial, cross-tenant denial, self-approval denial and direct
PostgreSQL assertions.

## 7. Security test results

**16/16** live checks: retired password 401, rotated password 200, viewer write 403, unauthenticated
mutation 401, forged organization header 403, login rate limit 429, secure/HttpOnly/SameSite cookie,
HSTS, single-valued security headers, `no-store`, `/metrics` not served on the LAN port,
n8n/Grafana/Prometheus/API refused on the LAN, and no internals in error responses. The acceptance
suite adds cross-tenant 404, self-approval 403 and registration-disabled 403.

## 8. Financial edge-case results

**26/26**, full evidence in `docs/FINAL_ACCEPTANCE_RESULTS.md`:

| Area | Cases | Result |
| --- | --- | --- |
| Duplicates and vendor identity | duplicate invoice; same number different vendor; vendor mismatch; invalid tax identity | PASS |
| Amount and tax | amount mismatch; VAT error; currency mismatch; partial invoice; multi-line precision | PASS |
| Missing data and dates | missing PO; missing documents; future invoice date | PASS |
| Documents | duplicate upload (409); low OCR confidence (0.52 → review); invalid format (422); corrupt PDF (FAILED); 26 MB upload (422) | PASS |
| Webhooks | duplicate event (same id); invalid HMAC (400) | PASS |
| Approvals | concurrent (one 200, one 409); expired (409); self-approval (403); viewer execution (403) | PASS |
| Tenancy and recovery | cross-tenant read (404); retry after processing failure (200, re-evaluated) | PASS |
| Roles | six roles + automation account boundaries | PASS |

Decimal precision was asserted through the API and direct SQL (`NUMERIC(18,4)`).

## 9. AI test results

- Provider: local Ollama, `qwen2.5:7b-instruct`, `bge-m3` embeddings (1024 dimensions).
- A live investigation completed with **3–4 validated evidence items** (invoice, contract chunk,
  historical case), 85% heuristic confidence, 3,056 tokens and ~12.4 s latency.
- Citations are resolved to real organization-scoped rows; invalid citations are flagged and the run
  can end in `NEEDS_REVIEW`.
- The model has no tools and cannot approve or execute.
- Stored investigation reproduced in the portfolio screenshots and used in the E2E suite.

## 10. OCR test results

- Tesseract 5.4 with English + Thai inside the container.
- Thai and English documents processed in the live workflow; extraction produced 10 fields with
  per-field confidence and page anchors.
- Low-quality image produced OCR confidence **0.52** and correctly set `REQUIRES_REVIEW`.
- Corrupt PDF failed safely with a redacted error and a `document.failed` event.
- 26 MB upload and invalid formats rejected at the boundary.

## 11. n8n test results

- Five workflows active: A new exception/case, B critical escalation, C daily summary, D document
  failure, E integration health.
- Contract suite **9/9**: signed event accepted, duplicate suppressed, invalid HMAC rejected, Mailpit
  delivery for A/B/D.
- Real outbox deliveries `case.created` and `case.escalated` returned HTTP 200; a reprocessed failed
  document delivered `document.failed` and produced the owner email.
- Daily summary executed from its cron; health monitor runs every five minutes with success, and a
  controlled degraded run delivered an alert email.
- Workflows, credentials and owner session survived restarts.

## 12. Monitoring test results

- Prometheus **13/13 targets up**, 20 alert rules loaded, 15-day retention.
- Alertmanager → Mailpit: a controlled alert and a real database-down alert were both delivered and
  resolved.
- Four Grafana dashboards provisioned from Git with live data (system, database/storage,
  AI/documents, business).
- Backup freshness exported as `resolve_backup_last_success_timestamp_seconds`.

## 13. Backup / restore results

- Backups: `backups/compose-20261119-205946` (65 objects) and `backups/compose-20261119-213454`
  (69 objects, produced by the scheduled task).
- Restore: `resolve_restore_hardening_20261119_210117` + bucket
  `resolve-documents-restore-hardening` (65 objects).
- Verified: row counts, `vector(1024)`, HNSW index, nearest-neighbour query, and one object's SHA-256
  matched byte-for-byte.
- Live data was never overwritten.
- `RESOLVE-Daily-Backup` runs daily at 02:30 and has completed through the scheduled path.

## 14. Deployment URLs

| Purpose | URL |
| --- | --- |
| Windows / LAN application | `https://192.168.1.107:8180` |
| Host loopback | `https://localhost:8180` |
| Optional name | `https://resolve.local:8180` (add a hosts entry) |
| Health | `https://192.168.1.107:8180/health` |
| n8n (host only) | `http://127.0.0.1:5679` |
| Grafana (host only) | `http://127.0.0.1:3101` |
| Prometheus (host only) | `http://127.0.0.1:9190` |
| Mailpit (host only) | `http://127.0.0.1:8125` |
| Native rollback (host only) | `http://127.0.0.1:8090` |

Only TCP 8180 is reachable from the LAN (Private profile, `LocalSubnet`).

## 15. Portfolio deliverables

`portfolio/` contains:

- `PROJECT_OVERVIEW.md`, `TECHNICAL_ARCHITECTURE.md`, `ARCHITECTURE_DIAGRAMS.md` (nine Mermaid
  diagrams), `SYSTEM_FEATURES.md`, `TECH_STACK.md`, `SECURITY_DESIGN.md`, `AI_ARCHITECTURE.md`,
  `DATABASE_DESIGN.md`, `TESTING_AND_QUALITY.md`, `DEPLOYMENT_OVERVIEW.md`, `KNOWN_LIMITATIONS.md`,
  `DEMO_SCRIPT.md`, `DEMO_SCENARIOS.md`, `INTERVIEW_QA.md`, `README.md`.
- `portfolio/screenshots/` with 16 captures from the live system: login, dashboard, invoices, invoice
  detail, document review, exceptions, case workspace, AI investigation, approvals, analytics, audit,
  n8n workflows and canvas, and three Grafana dashboards.
- `portfolio/qa/UX_REPORT.md` with responsive and console-error results.

All screenshots were captured from the running HTTPS deployment; none are mock-ups. No passwords,
tokens or personal data are visible.

## 16. Demo instructions

1. `.\scripts\start-resolve.ps1` then `.\scripts\health-check.ps1 -Deep`.
2. Open `https://192.168.1.107:8180` and confirm the certificate.
3. Use the credentials from `var/secrets/demo-credentials.txt` (never from slides): admin, approver,
   viewer, plus the six-role demo accounts.
4. Follow `portfolio/DEMO_SCRIPT.md` (5–10 minutes) or `portfolio/DEMO_SCENARIOS.md`.
5. Optional operations segment: Grafana `127.0.0.1:3101`, n8n `127.0.0.1:5679`, Mailpit
   `127.0.0.1:8125`.

## 17. Remaining external blockers

| Blocker | Impact | Prepared work |
| --- | --- | --- |
| Physical Mac / Safari | macOS trust not executed | CA + exact `security` commands in `docs/HTTPS_LAN_SETUP.md` |
| Public domain / DNS | HTTPS uses IP + local CA | SANs and renewal procedure documented |
| External SMTP | Mailpit only; no external mail | SMTP settings and runbook ready |
| Off-host backup storage | backups are local | manifest, SHA-256 and transfer guidance ready |
| Server-grade Linux host | Docker Desktop on Windows | Compose file is portable; watchdog installed |
| Malware scanning | uploads not antivirus-scanned | integration point identified |
| Independent penetration test | not performed | threat model and 16-check suite available |
| Business UAT | not performed | demo script and acceptance matrix ready |

None of these are software defects; all are environmental or organizational.

## 18. Production readiness assessment

| Gate | Status |
| --- | --- |
| Docker deployment | PASS |
| HTTPS | PASS (Windows/LAN); macOS BLOCKED (no device) |
| Authentication / RBAC | PASS |
| Multi-tenant isolation | PASS |
| Financial validation | PASS (26 cases) |
| Document processing / OCR | PASS |
| AI investigation / citations | PASS |
| Approval workflow | PASS (including concurrency) |
| Audit trail | PASS |
| n8n workflows | PASS |
| Monitoring / alerting | PASS |
| Backup / restore | PASS |
| Restart persistence | PASS |
| Regression tests | PASS (137 + 1 skip, 10 E2E, 6 unit) |
| Security tests | PASS (16/16) |
| Demo environment | READY |
| Portfolio package | READY |
| Screenshots / diagrams / demo script | READY |
| Git tree / release tag | CLEAN / `v1.0.0` |

**What the system does:** detects and explains invoice exceptions, investigates them with grounded
local AI, resolves them through a human approval policy it cannot bypass, and proves every step with an
audit trail — all running on a real HTTPS deployment with monitoring and verified backups.

**What it is not:** a system approved for real money, a high-availability production service, or a
replacement for a bank/ERP integration. Those boundaries are explicit in
`portfolio/KNOWN_LIMITATIONS.md`.

**Portfolio suitability:** yes — the screenshots, tests, diagrams and demo path are real and
reproducible, and the two defects found during closure are a stronger story than a flawless claim.

**Final state:** development stops here. No new features were added in this round; the release is
frozen at `v1.0.0`.
