# RESOLVE — Final deployment report

> **Historical document.** For the current verified state see `docs/FINAL_PRODUCTION_HARDENING_REPORT.md`.

**Date:** 2026-11-19 (Asia/Bangkok), post-reboot verification
**Host:** `KERNELOS-PC`, Windows 10 IoT Enterprise LTSC 22H2 (19045), i5-14500, 31.7 GB RAM,
RTX 4070 SUPER 12 GB, LAN `192.168.1.107/24`. Docker VM: 8 GB RAM / 4 CPUs.
**Repository:** `E:\Code\AI project` (existing project; native data untouched; the Docker demo
database was reseeded during verification).

Status legend: **VERIFIED** (executed and inspected), **PARTIALLY VERIFIED**, **NOT VERIFIED**,
**BLOCKED**, **REQUIRES USER ACTION**.

---

## 1. Final architecture and primary deployment

**Primary:** Docker Compose. **Rollback:** the previously verified native Windows services, kept
running on localhost only.

```
macOS/Windows browser
        │  https://192.168.1.107:8180  (single LAN entry point)
        ▼
nginx (resolve-web) ── /api, /health ──► FastAPI (resolve-api)
        │                                      │
        │ static SPA                           ├─ PostgreSQL 16.16 + pgvector 0.8.7
        ▼                                      ├─ Redis 7 (broker/result)
   apps/web/dist                               ├─ SeaweedFS 4.54 S3 (documents)
                                               ├─ Celery worker + beat
                                               └─ Ollama host 0.40.16 (Qwen2.5 7B + BGE-M3)
```

| Service | Container | Host binding | Status |
| --- | --- | --- | --- |
| Web / reverse proxy | `resolve-web-1` | `0.0.0.0:8180` | **healthy** |
| API | `resolve-api-1` | `127.0.0.1:8100` | **healthy** |
| PostgreSQL 16.16 + pgvector 0.8.7 | `resolve-postgres-1` | `127.0.0.1:5433` | **healthy** |
| Redis 7 | `resolve-redis-1` | `127.0.0.1:6380` | **healthy** |
| SeaweedFS S3 4.54 | `resolve-seaweedfs-1` | `127.0.0.1:9100` (S3), `127.0.0.1:9101` (console) | **healthy** |
| Celery worker | `resolve-worker-1` | internal | **up** |
| Celery beat | `resolve-beat-1` | internal | **up** |
| Mailpit 1.34.0 | `resolve-mailpit-1` | `127.0.0.1:8125`, SMTP `1126` | **healthy** |
| n8n 2.48.6 | `resolve-n8n-1` | `127.0.0.1:5679` | **up**, `/healthz` 200 |
| Prometheus | `resolve-prometheus-1` | `127.0.0.1:9190` | **up**, healthy endpoint 200 |
| Grafana 13.3.1 | `resolve-grafana-1` | `127.0.0.1:3101` | **up**, `/api/health` 200 |

Only **TCP 8180** is allowed through Windows Firewall (Private profile, `LocalSubnet`). Every other
container port is bound to `127.0.0.1`. PostgreSQL, Redis, S3 console, n8n, monitoring and Mailpit are
not reachable from the LAN. Native nginx now binds `127.0.0.1:8090` only, so there is one LAN entry
point.

## 2. URLs

| Purpose | URL |
| --- | --- |
| Windows UI | **https://localhost:8180** |
| macOS/LAN UI | **https://192.168.1.107:8180** |
| LAN health | **https://192.168.1.107:8180/health** |
| API readiness (local) | http://127.0.0.1:8100/health/ready |
| Mailpit (local) | http://127.0.0.1:8125 |
| n8n (local) | http://127.0.0.1:5679 |
| Grafana (local) | http://127.0.0.1:3101 |
| Prometheus (local) | http://127.0.0.1:9190 |
| Native rollback (local) | http://127.0.0.1:8090 |
| Native API (local) | http://127.0.0.1:8000 |

Demo users: `admin@example.com`, `manager@example.com`, `investigator@example.com`,
`approver@example.com`, `viewer@example.com` — password `the password in var/secrets/demo-credentials.txt` (demo workspace only; change
before any non-demo use).

## 3. Post-reboot Docker repair (actual events)

Docker was installed before the reboot, but the first post-reboot attempt was not healthy:

- WSL2/Hyper-V became active (`HyperVisorPresent=True`), but Docker Desktop's backend was not
  running and the engine returned HTTP 500.
- The resume task's readiness check falsely accepted the failing engine and its Compose call failed.
- Starting Docker Desktop from an agent shell was not durable; it was terminated when the shell
  session ended.
- MinIO's official images are no longer pullable (`pull access denied`), so the Compose stack was
  repaired to use the actively maintained **SeaweedFS S3** gateway (already imported by the
  deployment assets) with credentials from `.env`.
- Docker Desktop is now launched through Explorer and registered as a logon task, so it survives the
  launching shell and starts after login.
- `restart: unless-stopped` was added to PostgreSQL, Redis, SeaweedFS, n8n and monitoring services.
- A vector-column inconsistency (Alembic said `f7…` but `embedding_vec` was missing) was repaired by
  downgrading and re-applying only revision `f7b2c9d4a1e3`; data was preserved.
- Storage was switched to S3; the demo workspace was reseeded into SeaweedFS (42 objects) and the
  verification uploads were persisted to S3. Downloads and backup/restore were verified by SHA-256.

## 4. Database and pgvector — VERIFIED

- PostgreSQL **16.16** (Docker `pgvector/pgvector:pg16`).
- pgvector **0.8.7**; `document_chunks.embedding_vec vector(1024)`.
- HNSW index `ix_document_chunks_embedding_vec` (`vector_cosine_ops`).
- `EXPLAIN (ANALYZE, BUFFERS)` with `enable_seqscan=off` → **Index Scan using the HNSW index**
  (execution ~243 ms on the small demo set).
- Application retrieval returns **`hybrid+pgvector`** (live API query).
- Current Docker data after the seed, 27-step workflow and OCR verification: **4 organizations,
  106 invoices, 17 documents, 47 cases, 149 exceptions, 678 audit rows, 16 chunks / 16 vectors**.
- New uploads synchronize JSON embeddings into `embedding_vec`; upload/download verified.
- Cross-tenant access returns 404; second-tenant knowledge retrieval returns no foreign hits.

## 5. Local AI — VERIFIED

- Ollama **0.40.16**, `qwen2.5:7b-instruct` (4.7 GB), `bge-m3` (1.2 GB, 1024 dimensions), CUDA on the
  RTX 4070 SUPER.
- The API container reaches `http://host.docker.internal:11434/api/version` successfully.
- Live Docker workflow investigation: `COMPLETED`, provider `ollama`, validated evidence citations,
  root cause and recommendations; no AI execution or approval.
- Structured schema requires evidence/resolutions; an evidence-repair retry and validation guard
  prevent silent ungrounded answers.
- English and Thai direct model checks passed; prompt-injection text inside a document was ignored.
- Cold model load ~44 s; warm investigations seconds to ~50 s depending on context.

## 6. OCR — VERIFIED in Docker

- API image contains Tesseract 5.4 with **eng**, **tha**, **osd**.
- Live PNG invoice upload through the Docker API: `INDEXED`, **confidence 0.955**, total `1070.00`
  recognised, 7 fields extracted, page text 168 chars.
- Text PDF, DOCX, XLSX and CSV extraction covered by the same parser and tests.

## 7. Storage — VERIFIED

- SeaweedFS S3 gateway with generated identity file; the bucket is reachable through the application.
- Existing documents migrated to S3 under original keys; downloads matched SHA-256.
- New upload persisted to S3; object count increased and download content matched exactly.
- 65 objects currently in `resolve-documents` (seeded + workflow/OCR/manual verification uploads).
- Storage survives container restarts (volume `resolve_seaweedfs_data`).

## 8. Background jobs, mail and n8n

- Real Celery worker and beat are running; document processing, investigation, notifications and
  outbound email jobs executed.
- SMTP approval email delivered to Mailpit (`backend=smtp`, message ID recorded in workflow output).
- n8n 2.48.6 is up and `/healthz` returns 200. No workflows/credentials were imported/configured;
  n8n integration is **PARTIALLY VERIFIED** (service health only).
- Monitoring: Prometheus and Grafana are running and locally reachable. Dashboards/alerts were not
  customised for RESOLVE; monitoring is **PARTIALLY VERIFIED**.

## 9. Complete workflow — VERIFIED through Docker LAN

The 27-step script ran against the Docker API (`https://127.0.0.1:8180`, same nginx path as LAN):

login → vendor → purchase order → invoice PDF upload → processing → extraction (10 fields) →
correction → review → invoice creation (idempotent) → validation → 2 exceptions → case → assignment
→ real Ollama investigation → evidence validation → resolution proposal → approval queue → approval
→ SMTP execution → case state → 9 audit rows → 9 timeline entries → analytics.

Failure paths verified in the same run: viewer write 403, cross-tenant reads/mutations 404,
self-approval 403. Resolution executed **COMPLETED** with SMTP email; audit/analytics populated.

## 10. Tests — VERIFIED

| Check | Result |
| --- | --- |
| Host backend — PostgreSQL 18.6 | **134 passed** |
| Host backend — SQLite | **133 passed, 1 PG-only skip** |
| Docker container backend tests | **133 passed, 1 PG-only skip** |
| `ruff check apps/api` / `compileall` | pass |
| Alembic upgrade/check/downgrade | pass; Docker migration repaired and rechecked |
| Frontend `tsc` | pass |
| ESLint | 0 errors, 4 fast-refresh warnings |
| Vitest | 6 passed |
| Production build | pass |
| Playwright against Docker nginx `8180` | **10 passed** |
| Live Docker OCR upload | pass, confidence 0.934–0.955; total and invoice number recognised |
| Docker workflow | 27 steps verified |
| Docker backup/restore | verified, including vectors and 42 objects |

## 11. Backup and restore — VERIFIED

- Latest backup: `backups/compose-20261119-191134` (PostgreSQL dump + 64 objects + manifest), restored
  into `resolve_restore_20261119_191143` with organizations=4, invoices=106, documents=16, cases=47,
  audit_logs=656, chunks=16; 64 objects uploaded to `resolve-documents-restore`.
- Docker backup: `backups/compose-20261119-184900/database.dump` + 42 documents + manifest.
- Restored into **`resolve_restore_final`** (new database, never live):
  organizations=1, invoices=103, documents=11, cases=38, audit_logs=497, chunks=11.
- Restored database has pgvector 0.8.7, `vector(1024)`, HNSW index, 11/11 vectors.
- Documents restored to S3 bucket `resolve-documents-final` (42 objects); all 42 SHA-256 hashes
  matched the source backup.
- Native backup/restore remains available via `scripts/restore-resolve.ps1 -Native`.

## 12. LAN / macOS

- Detected private LAN IP: **192.168.1.107** (Ethernet, Private).
- Windows and LAN URL tested successfully; nginx binds `0.0.0.0:8180`.
- Firewall: only `RESOLVE Docker Web (TCP 8180)` enabled, Private, `LocalSubnet`. The old 8090 LAN
  rule is disabled; native nginx binds `127.0.0.1:8090`.
- **No physical Mac was available.** Mac login/refresh/upload/AI were simulated through the same LAN
  URL from Windows; exact macOS commands are in `docs/LAN_ACCESS_GUIDE.md`. Safari was not tested.
- Current LAN deployment is **HTTP** (`ENV=development`); no public CA/HTTPS was configured. Do not
  use real financial data over this HTTP endpoint.

## 13. Operations

```powershell
cd "E:\Code\AI project"
.\scripts\start-resolve.ps1
.\scripts\stop-resolve.ps1
.\scripts\restart-resolve.ps1
.\scripts\status-resolve.ps1
.\scripts\health-check.ps1 -Deep
.\scripts\backup-resolve.ps1
.\scripts\restore-resolve.ps1 -BackupDir .\backups\compose-YYYYMMDD-HHMMSS
```

`start-resolve.ps1` prefers Docker and falls back to native services if Docker is unavailable. Stop
preserves all volumes, databases and uploads. Native rollback: `start-resolve.ps1 -Mode native`.

## 14. Security result

- One LAN application port (8180); internal services loopback-only.
- Cross-tenant reads/mutations 404, viewer write 403, self-approval 403, approval/execute separation.
- Webhook signatures, encrypted integration credentials, upload size/type/ZIP guards, JWT rotation
  and session revocation remain in place.
- Docker `.env`, backups, runtime data, databases and uploads are ignored by Git.
- Demo credentials and HTTP mode are for evaluation only; see **KNOWN LIMITATIONS**.

## 15. Remaining limitations / user actions

1. Physical macOS Safari/Chrome was not tested (no Mac in session).
2. HTTPS/private CA for LAN is not configured; current deployment is HTTP.
3. Docker Desktop is per-user; logon tasks launch it through Explorer. A server deployment should use
   a Linux Docker host or Docker Engine service instead of Docker Desktop.
4. n8n is running but no production workflows/credentials were imported.
5. Prometheus/Grafana are running but RESOLVE-specific dashboards/alerts are not configured.
6. Local 7B AI can still produce imprecise prose; citations are validated, invalid ones flagged.
7. SeaweedFS single-node is not highly available; production should use managed S3/R2/B2.
8. Demo accounts/data remain. Change/remove them before non-demo use.
9. Git repository has **no commits** and no configured identity; working tree is intact. Configure
   identity and commit only after reviewing ignored files.

**Conclusion:** Docker Compose is now the verified primary deployment, with native Windows services
as rollback. Core application, database, pgvector, local AI, OCR, object storage, jobs, approvals,
audit, analytics, LAN access, backup/restore and operational scripts are working. The remaining items
are environment/product limitations, not deployment blockers.
