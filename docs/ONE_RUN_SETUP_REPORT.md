# RESOLVE — One-run setup and deployment report

> **Historical document.** For the current verified state see `docs/FINAL_PRODUCTION_HARDENING_REPORT.md`.

> **Post-reboot update:** Docker Compose is now the verified primary deployment on
> `https://192.168.1.10:8180` with PostgreSQL 16 + pgvector 0.8.7, SeaweedFS S3, local Ollama, and the
> full workflow. The native services remain as a **localhost rollback** (`127.0.0.1:8090`). See
> [`FINAL_DEPLOYMENT_REPORT.md`](FINAL_DEPLOYMENT_REPORT.md) and
> [`DOCKER_DEPLOYMENT.md`](DOCKER_DEPLOYMENT.md) for the authoritative post-reboot results. The
> sections below describe the native deployment and the pre-reboot state; they are retained as
> historical evidence.

**Date:** 2026-11-19 (Asia/Bangkok)
**Host:** `KERNELOS-PC` — Windows 10 IoT Enterprise LTSC 22H2 (10.0.19045), Intel i5-14500
(14C/20T), 31.7 GB RAM, NVIDIA RTX 4070 SUPER 12 GB, 239 GB free.
**LAN:** `192.168.1.10/24`, gateway `192.168.1.1`, network profile now **Private**.
**Repository:** `C:\path\to\resolve` (existing RESOLVE; native data untouched; Docker demo data was
reseeded during post-reboot verification).

Status legend: **VERIFIED** = executed and inspected here; **PARTIALLY VERIFIED** = part of it
executed, or only one side of a client/server pair could be tested; **NOT VERIFIED** = not
executed; **BLOCKED** = cannot proceed in this session without a reboot or external hardware.

### Compose addendum (2026-11-19, after reboot)

The reboot happened and the Docker path is now **VERIFIED**. This supersedes the "Docker blocked"
and "MinIO archived" rows later in this historical report.

- Docker Desktop 29.9.3 runs WSL2 3.0.1; `HyperVisorPresent=True`.
- Core Compose services are healthy: PostgreSQL 16 + pgvector, Redis, API, worker, beat, nginx web,
  Mailpit and SeaweedFS S3. n8n and the optional Prometheus/Grafana profile start and return 200 on
  their health endpoints.
- MinIO was replaced by **SeaweedFS 4.54** (authenticated path-style S3, generated credentials,
  64 × 1 GB volume cap). The demo seed wrote 42 objects; a new upload reached `INDEXED` and
  downloaded byte-for-byte.
- Backup/restore was verified end to end: PostgreSQL dump + 42 objects restored into a new database
  and bucket, row counts matched and all 42 SHA-256 hashes matched.
- Playwright 10/10 passed against `https://127.0.0.1:8180`, including a real Ollama investigation.
- Only web 8180 is exposed beyond the host; all other Compose ports bind to `127.0.0.1`.
- WSL2 was capped at 8 GB / 4 CPUs after Docker restarts under host memory pressure.
- Backend tests: **134 passed on PostgreSQL**, **133 passed + 1 skip on SQLite**.

---

## 1. Final status

| Area | Status | Evidence |
| --- | --- | --- |
| **Docker Compose (primary)** | **VERIFIED** | 11 containers; API/web/PostgreSQL/Redis/SeaweedFS/Mailpit healthy; n8n and monitoring 200 |
| PostgreSQL 16.16 (Compose) | **VERIFIED** | `pgvector/pgvector:pg16`; migrations; backup/restore |
| pgvector 0.8.7 | **VERIFIED** | `vector(1024)`, backfill, HNSW index, real `Index Scan` |
| SeaweedFS S3 4.54 | **VERIFIED** | authenticated S3, 64 objects, upload/download hashes |
| Local AI (Ollama) | **VERIFIED** | Qwen2.5 7B + BGE-M3, CUDA; container→host reached |
| Real AI investigation | **VERIFIED (quality limited)** | provider=ollama; validated citations; no AI execution |
| OCR in Docker | **VERIFIED** | Tesseract 5.4 eng/tha; live confidence 0.934 |
| Full 27-step workflow | **VERIFIED** | through nginx/LAN; approval, SMTP, audit, analytics |
| Frontend (production bundle) | **VERIFIED** | Playwright 10/10 via `https://192.168.1.10:8180` |
| LAN listener | **VERIFIED** | nginx `0.0.0.0:8180`; only 8180 firewall rule enabled |
| macOS client | **PARTIALLY VERIFIED** | no physical Mac; LAN path tested from Windows; macOS commands provided |
| Firewall | **VERIFIED** | Private + LocalSubnet, TCP 8180 only; 8090 rule disabled |
| Backup + restore | **VERIFIED** | separate DB + bucket; 64 objects/11-16 vectors verified |
| Start/stop/restart/status/health | **VERIFIED** | Docker-first wrappers; stop→start data preserved |
| Native Windows rollback | **VERIFIED (localhost)** | services running; `127.0.0.1:8090` |
| n8n / Prometheus / Grafana | **VERIFIED (health only)** | services and health endpoints 200; no workflows/dashboards configured |
| MinIO | **REPLACED** | retired upstream; SeaweedFS S3 verified |

No reboot remains. The Docker path is primary; native services are a localhost rollback.

---

## 2. What is running now

**Primary Docker Compose:** nginx web (`0.0.0.0:8180`), API (`127.0.0.1:8100`), worker, beat,
PostgreSQL 16.16 (`127.0.0.1:5433`), Redis (`127.0.0.1:6380`), SeaweedFS S3 (`127.0.0.1:9100`,
console 9101), Mailpit (`8125`/`1126`), n8n (`5679`), Prometheus (`9190`), Grafana (`3101`).

**Native rollback:** PostgreSQL 18.6 (`127.0.0.1:55432`), Memurai (`6379`), Ollama (`11434`),
Mailpit (`1025`/`8025`), API (`127.0.0.1:8000`), nginx (`127.0.0.1:8090`), worker/beat services.
The pre-existing system PostgreSQL on 5432 was not modified.

## 3. URLs

| Purpose | URL |
| --- | --- |
| Windows UI (Docker) | `https://localhost:8180` |
| macOS/LAN UI | `https://192.168.1.10:8180` |
| LAN health | `https://192.168.1.10:8180/health` |
| API readiness (local) | `http://127.0.0.1:8100/health/ready` |
| Mailpit (local) | `http://127.0.0.1:8125` |
| n8n (local) | `http://127.0.0.1:5679` |
| Grafana / Prometheus (local) | `http://127.0.0.1:3101` / `9190` |
| Native rollback (local) | `http://127.0.0.1:8090` |
| Native API docs (local) | `http://127.0.0.1:8000/docs` |

Demo accounts (demo workspace only): `admin@example.com`, `manager@example.com`,
`investigator@example.com`, `approver@example.com`, `viewer@example.com` — password `the password in var/secrets/demo-credentials.txt`.

## 4. AI configuration (real, not a stub)

- Provider: **Ollama** at `http://127.0.0.1:11434` (native) / `http://host.docker.internal:11434`
  (Compose after reboot).
- Instruction model: **`qwen2.5:7b-instruct`** (4.7 GB, Q4, fits the 12 GB RTX 4070 SUPER fully).
- Embedding model: **`bge-m3`** (1.2 GB, 1024 dimensions, multilingual including Thai).
- `AI_EMBEDDING_DIM=1024`; the pgvector column and HNSW index use the same dimension.
- Structured output is schema-constrained. The provider schema requires evidence and a suggested
  resolution; Pydantic validation, citation validation and a repair attempt prevent silent empty
  investigations. Prompt version is now `investigation.v2`.

Verified real calls:

| Test | Result |
| --- | --- |
| English invoice analysis | valid JSON, risk HIGH, confidence 0.95, injection instruction ignored |
| Thai-only prompt | Thai JSON answer (91 Thai characters in the summary) |
| Injection attempt inside document | not followed (“approve payment immediately” ignored) |
| Live API investigation | `COMPLETED`, provider `ollama`, 3 evidence items, 2 validated, 2 suggestions |
| Second live investigation | `COMPLETED`, 49 s first-load latency, evidence and root cause populated |
| First token/model load | 44 s cold; subsequent investigations ~2–13 s |
| Embeddings | 2 texts → 1024-dim vectors |
| Invalid JSON/rate-limit/retry/timeout | covered by the local fake-provider HTTP suite (8 tests) |

AI cannot execute anything: accepting a suggestion creates a normal resolution proposal with
`executed_at=null` and no execution rows; approval and execution remain separate human steps.

## 5. pgvector verification (native build)

Official pgvector **v0.8.1** was compiled with the installed Visual Studio C++ toolchain against
PostgreSQL 18.6 and installed into the PostgreSQL directory.

- `CREATE EXTENSION vector` → version **0.8.1**
- `document_chunks.embedding_vec` → `vector(1024)` (migration `f7b2c9d4a1e3`)
- Backfill from portable JSON embeddings → **20/20 chunks at migration time** (22/22 after later uploads)
- HNSW index `ix_document_chunks_embedding_vec` (`vector_cosine_ops`)
- `EXPLAIN (ANALYZE, BUFFERS)` with `enable_seqscan=off` → **Index Scan using the HNSW index**
- Application retrieval reports **`hybrid+pgvector`**
- New uploads synchronize JSON embeddings into `embedding_vec` (`sync_embedding_vectors`), verified
  with a new document (2/2 chunks vectorized)
- Tenant isolation: a second organization gets 0 knowledge hits and 404 for a foreign document

## 6. Database, backup and restore

Live snapshot after the verification runs (includes test tenants/documents created during testing):
5 organizations, 9 users, 18 vendors, 112 invoices, 21 documents, 54 cases, 162 exceptions,
22 document chunks and **22/22 vector rows**.

Backup created at `backups/resolve-20261119-174236`:

- `database.dump` — custom-format `pg_dump`, SHA-256 recorded in `manifest.json`
- `documents/` — local storage copy
- `api.env` / `compose.env` — configuration and encryption key material (folder ACL restricted to
  Administrators/SYSTEM; never commit it)
- `database.toc.txt` — `pg_restore --list` proof of readability

Restore was performed into a **separate** database, never over live data:

```
organizations=3 invoices=106 documents=18 cases=46 audit_logs=617
document_chunks=19 chunk_vectors=19
```

The live DB gained one document after that backup, hence 19 documents/chunks in the current snapshot.

## 7. End-to-end verification

The 27-step workflow ran through the **LAN URL** (`http://192.168.1.10:8090`):

login → vendor → PO → PDF upload → processing → extraction (10 fields) → correction → review →
invoice creation (idempotent) → validation → 2 exceptions → case → assignment → real Ollama
investigation → resolution proposal → approval queue → approval → SMTP execution → audit (9 rows) →
timeline (9) → analytics.

Failure paths in the same run: viewer write 403, cross-tenant reads/mutations 404, self-approval 403.
The executed resolution completed with an email captured by Mailpit (`backend=smtp`).

## 8. Test results

| Check | Result |
| --- | --- |
| Backend tests - PostgreSQL 18.6 | **134 passed** |
| Backend tests - SQLite | **133 passed, 1 PostgreSQL-only skip** |
| `ruff check apps/api` | pass |
| `compileall` | pass |
| Alembic upgrade/check/downgrade | pass (SQLite and PostgreSQL; fresh PG creates `vector(1024)` + HNSW) |
| Frontend `tsc` | pass |
| ESLint | 0 errors, 4 fast-refresh warnings |
| Vitest | 6 passed |
| Production build | pass |
| Playwright via nginx/LAN | **10 passed**, including a real AI investigation and no console errors |
| OCR script | PNG/JPG/scanned PDF/PDF/DOCX/XLSX/CSV pass |
| Live OCR upload | `REQUIRES_REVIEW`, confidence 0.93, total `1284.00` recognised |
| Live workflow | 27 steps verified |
| Backup/restore | verified into an isolated DB |
| Health script (deep AI) | pass |

## 9. Network and firewall

- The Ethernet profile was changed from **Public** to **Private** (trusted home/office LAN).
- Inbound firewall rule **`RESOLVE LAN Web (TCP 8090)`**: TCP 8090, Private profile only,
  `RemoteAddress=LocalSubnet`.
- Only the web port is reachable from the LAN. PostgreSQL (5432/55432), Redis (6379), API (8000),
  MinIO (9000/9001), n8n (5678), Mailpit (1025/8025) and Ollama (11434) have **no inbound allow rule**.
- The system PostgreSQL still listens on 0.0.0.0:5432, but Windows Firewall has no allow rule for it.
  It was not stopped or reset because it is pre-existing user infrastructure.
- No public IP, port forwarding or Internet exposure was configured.

## 10. Docker / WSL2

Performed:

- Enabled `Microsoft-Windows-Subsystem-Linux` and `VirtualMachinePlatform` (`dism`, `/norestart`).
- Installed the WSL2 kernel update MSI.
- Installed **Docker Desktop 29.9.3** (client; Compose v2 included).
- Validated `docker compose --env-file .env config` → exit 0.
- Isolated Compose host ports to avoid clashing with the native stack:
  web 8180, API 8100, PostgreSQL 5433, Redis 6380, MinIO 9100/9101, Mailpit 8125/1126, n8n 5679.
- Set `AI_BASE_URL=http://host.docker.internal:11434` and Ollama binds `0.0.0.0:11434` for containers.
- Registered logon task `RESOLVE-PostReboot-Docker`.

Blocker: `HyperVisorPresent=False` and the engine returns HTTP 500
(`dockerDesktopLinuxEngine`) because the Windows features require a reboot. Docker images were
therefore **not built or started**, and no Docker service health is claimed.

## 11. Remaining limitations

1. **Reboot required** for WSL2/Docker. The resume task finishes the Compose path; until then only the
   native stack is running.
2. **No physical Mac** was available. The LAN listener, firewall scope and full workflow were tested
   from the Windows host against `192.168.1.10`; macOS commands are provided in
   `docs/LAN_ACCESS_GUIDE.md`. Safari was not tested.
3. **HTTP on the LAN** means refresh cookies are not `Secure` in this development-mode deployment.
   Put nginx behind HTTPS (self-signed for LAN or a real certificate) before using real data.
4. **MinIO is archived upstream** (images return pull access denied). Compose now uses SeaweedFS S3;
   production should use managed S3/R2/B2. See the post-reboot addendum.
5. **AI quality** is model-dependent. Citations are validated, but a 7B local model can still omit or
   misattribute context; invalid citations are persisted and flagged, never treated as support.
6. **n8n / Prometheus / Grafana** were not started.
7. Demo credentials and demo data are present; do not expose this workspace to the Internet.

## 12. Commands

```powershell
# First-time service installation (already done on this host)
.\scripts\install-windows-services.ps1
.\scripts\install-docker-resume-task.ps1

# Start / stop / status / health
.\scripts\start-resolve.ps1
.\scripts\start-resolve.ps1 -SkipMigrations
.\scripts\stop-resolve.ps1
.\scripts\stop-resolve.ps1 -IncludeAuxiliary
.\scripts\status-resolve.ps1
.\scripts\health-check.ps1
.\scripts\health-check.ps1 -Deep

# Backup / restore
.\scripts\backup-resolve.ps1
.\scripts\restore-resolve.ps1 -BackupDir .\backups\resolve-YYYYMMDD-HHMMSS

# Service control
Get-Service RESOLVE-*, resolvepgtest, Memurai
Restart-Service RESOLVE-API,RESOLVE-Worker
```

After the reboot, inspect `var\logs\post-reboot-docker.log`; the Docker UI will be on
`https://localhost:8180` (LAN `https://192.168.1.10:8180` after adding a Private-profile 8180 rule).
