# RESOLVE — Project plan and delivery status

## 1. Scope decision

The first release is a **complete invoice exception management vertical**. The platform is
extensible, but only the invoice domain is implemented end to end. No accounting payments are
started; the system prepares records for downstream export.

### In scope

- Multi-tenant identity, RBAC and org isolation
- Document upload, secure storage, real parsing/OCR, versioning and review
- Invoice, vendor and purchase-order records with deterministic validation
- Ten versioned exception rules with deduplication and case grouping
- Case lifecycle with SLA, assignment, comments and merge
- Evidence-grounded AI investigation with hybrid retrieval and validated citations
- Resolution action registry, approval policy and audited execution
- Integration registry, signed webhooks, optional n8n workflows
- Notifications, background jobs, analytics, audit, AI evaluation
- Demo mode, seed/reset scripts, Docker Compose, CI, documentation

### Explicitly out of scope

- Real payment initiation, bank connectivity or ERP write-back
- Vendor self-service portal
- SSO/SAML/SCIM
- Multi-currency conversion (currency is validated, never converted)
- Full financial period close and ledger posting

## 2. Phases and status

| Phase | Deliverable | Status |
| --- | --- | --- |
| 0 | Discovery, plan, architecture, requirements, decisions | Complete |
| 1 | Monorepo foundation, config, logging, health, migrations, Docker, CI | Complete (Compose runtime verified 2026-11-19 after the required reboot) |
| 2 | Auth, users, organizations, RBAC, isolation, audit, tests | Complete |
| 3 | Documents: upload, storage, parsing, OCR, extraction, review, retrieval | Complete (real Tesseract 5.4 OCR verified on PNG/JPG/scanned PDF) |
| 4 | Vendors, purchase orders, invoices, matching, validation | Complete |
| 5 | Exception rules, dedupe, case creation, case management, SLA | Complete (concurrent case-number allocation hardened) |
| 6 | AI provider abstraction, investigation, RAG, evidence validation | Complete (real local Ollama verified end-to-end; external provider credentials unverified) |
| 7 | Resolutions, policy engine, approvals, idempotent execution | Complete |
| 8 | Integrations, webhooks, n8n templates, notifications, jobs | Complete (Celery worker + Redis verified; n8n templates require a live n8n) |
| 9 | Frontend: 20+ routes, real API wiring, i18n, themes, responsive | Complete (10 Playwright tests, all 14 nav destinations) |
| 10 | Evaluation lab, tests, E2E, security review, docs | Complete |
| 11 | README, screenshots, final verification, report | Complete — see `docs/FINAL_VERIFICATION_REPORT.md` |
| 12 | Compose runtime, S3 storage, backup/restore, optional services | Complete (verified 2026-11-19 after reboot; SeaweedFS replaces archived MinIO) |

## 3. Definition of done (verified)

- Backend lints clean (`ruff check apps/api`).
- Backend tests pass on **SQLite** (133 passed, 1 PostgreSQL-only skip) and on **real PostgreSQL
  18.6** (134 passed), including RBAC, cross-org isolation, rules, approvals, AI validation
  failures, webhook signatures, concurrency, analytics and the new S3 client/sync tests.
- Alembic initial migration applies, downgrades and re-applies; `alembic check` reports no pending
  operations on PostgreSQL and SQLite.
- Frontend typechecks, lints (0 errors) and builds; Vitest (6) and Playwright (10) pass.
- Real OCR verified for PNG, JPG and scanned PDF; PDF/DOCX/XLSX/CSV parsing verified.
- Live 27-step business workflow verified against a seeded PostgreSQL database.
- Celery worker + Redis verified with real jobs against PostgreSQL.
- **Compose stack verified after reboot**: PostgreSQL 16 + pgvector, Redis, SeaweedFS S3, API,
  worker, beat, nginx web, Mailpit, n8n and the optional Prometheus/Grafana profile all start and
  report healthy; n8n `/healthz` and monitoring health endpoints return 200.
- **S3 path verified in Compose**: the demo seed wrote 42 objects to SeaweedFS with authenticated,
  path-style requests; a new upload processed to `INDEXED` and downloaded byte-for-byte.
- **Backup/restore verified**: 42 objects plus the PostgreSQL dump were captured, restored into a new
  database and bucket, and all 42 SHA-256 hashes matched. Row counts matched the source.
- **nginx re-resolution verified**: recreating the API container no longer leaves the web tier on a
  stale IP; `/health` stays 200 without restarting nginx.
- Screenshots captured without console errors.
- No secrets committed; `.env.example` documents every setting.

## 4. Environment constraints recorded

- Native Windows deployment is running (see `docs/ONE_RUN_SETUP_REPORT.md`): PostgreSQL 18.6 +
  pgvector 0.8.1 on 55432, Memurai/Redis, Celery worker+beat, Ollama (Qwen2.5 7B + BGE-M3), Mailpit,
  FastAPI and native nginx on localhost:8090. The primary LAN deployment is Docker Compose at
  `https://192.168.1.10:8180`.
- Tesseract is installed and verified. `tha` traineddata is installed; OCR falls back to available
  languages when a requested one is missing.
- Real local AI is configured and verified; no external LLM credentials were used. A 7B model still
  has quality limits, so citations are validated and every action remains human-approved.
- pgvector was compiled from official source for PostgreSQL 18.6; vector(1024), backfill, HNSW and
  an index scan are verified.
- **Docker Desktop/WSL2 now runs after the reboot.** Compose was verified end to end on 2026-11-19.
  Only the web port (`8180`) is bound to all interfaces; PostgreSQL (5433), Redis (6380), API (8100),
  SeaweedFS S3 (9100) and its master UI (9101), Mailpit (8125/1126), n8n (5679), Prometheus (9190)
  and Grafana (3101) are bound to `127.0.0.1`.
- MinIO's official images were retired upstream and `minio/mc` no longer pulls. Compose now uses
  **SeaweedFS 4.54** as the local S3-compatible store. Its gateway is started with an identity file
  generated from `S3_ACCESS_KEY`/`S3_SECRET_KEY`, so anonymous access is rejected, and it is capped
  at 64 volumes with 1 GB volume size so new buckets/collections can be allocated.
- Compose backup/restore uses a boto3 sync helper (`app.scripts.s3_sync`) rather than the AWS CLI v2,
  whose streaming-checksum uploads this SeaweedFS build rejects. The scripts restore into a new
  database and bucket by default and verify SHA-256 hashes.
- WSL2 was capped at 8 GB / 4 CPUs via `%USERPROFILE%\.wslconfig` because the host repeatedly hit
  memory pressure while Docker was building images. The core Compose stack uses well under 1 GB;
  the optional monitoring/n8n profile adds roughly 0.7 GB.
- Local development can still use SQLite; production configuration is refused when SQLite is selected.

## 5. Post-release backlog

1. Add HTTPS (private CA/mkcert or controlled reverse proxy) and switch the LAN deployment to
   `ENV=production`.
2. Real provider evaluation with the labelled synthetic dataset and provider price calibration.
3. IMAP/Graph email ingestion and vendor portal.
4. Rules DSL + visual editor.
5. SSO, SCIM, field-level permissions, malware scanning and data-retention automation.
6. Import and run the n8n workflow templates against a real n8n instance; exercise the Prometheus
   rules and Grafana dashboards with production traffic.
7. Test the LAN path from a physical macOS/Safari client (the network path was tested from Windows).
