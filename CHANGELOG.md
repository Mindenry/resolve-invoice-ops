# Changelog

All notable changes to RESOLVE. Dates are ISO-8601.

## [1.0.0] — 2026-11-19

### Final closure: acceptance, demo environment, portfolio, release

- **Concurrency fix (real defect):** two simultaneous approvals could both succeed. Approval decisions
  now use an atomic conditional `UPDATE ... WHERE status='PENDING'` and require `rowcount = 1`; the
  loser receives 409 and writes no decision, audit row or execution. Regression test
  `test_second_decision_is_a_conflict` added; live concurrent requests verified as one 200 / one 409.
- **Frontend fix (real defect):** the shared `Button` rendered `Slot` with multiple children when
  `asChild` was used, which crashed the invoice detail page. `asChild` now renders exactly one child;
  the invoice detail and every route were re-verified with zero app console errors.
- **Final acceptance suite:** 26/26 cases covering six roles plus the automation account and 25
  financial/security scenarios (duplicates, tolerance, VAT, currency, partial invoices, low OCR
  confidence, corrupt/large/invalid uploads, duplicate and forged webhooks, concurrent and expired
  approvals, self-approval, unauthorized execution, cross-tenant access, retry after failure).
  Evidence: `docs/FINAL_ACCEPTANCE_RESULTS.md`.
- **Demo environment:** added a platform super administrator with a random password stored outside
  Git; the demo tenant fixture was rotated and stale test users deactivated; the retired demo password
  remains rejected.
- **Portfolio package:** `portfolio/` with project overview, architecture (nine Mermaid diagrams), tech
  stack, security design, AI architecture, database design, testing, deployment, honest limitations,
  demo script, scenarios, interview Q&A, live screenshots and a responsive/console QA report.
- **Release hygiene:** tests re-run (backend 137 passed + 1 skip, frontend typecheck/lint/Vitest/build,
  Playwright 10/10, 28-step workflow), full stack restart persistence verified, secret scan clean,
  final commit and annotated `v1.0.0` tag.
- Documentation: `docs/FINAL_PROJECT_CLOSURE_REPORT.md`, refreshed README/security/release notes.

## [1.0.0-rc.1] — 2026-11-19

### Production hardening: HTTPS, security, automation, observability, release baseline

- **HTTPS/LAN:** nginx serves TLS 1.2/1.3 on port 8180 using a local mkcert CA with SANs
  `resolve.local`, `192.168.1.107`, `localhost`, `127.0.0.1` (valid to 2029-02-19). HTTP is a
  localhost-only redirect on 8081. HSTS, CSP-adjacent headers and single-valued security headers are
  enforced; only TCP 8180 is allowed from `LocalSubnet` on the Private profile.
- **Credential rotation:** every demo account password was rotated to a strong random value stored in
  `var/secrets/demo-credentials.txt` (Git-ignored, ACL-restricted). The previously published demo
  password is rejected (401). The login UI no longer prints or autofills any demo password, and
  self-service registration is disabled in production.
- **Production config:** `ENV=production`, `DEBUG=false`, `DEMO_MODE=false`, secure/HttpOnly/Lax
  refresh cookies, CORS restricted to the HTTPS origins, generic error envelopes, Argon2 password
  hashing, per-IP login rate limiting (20/minute) and 600/minute default limits.
- **n8n:** owner auth with a stable encryption key preserved from the existing volume, Asia/Bangkok
  timezone, execution pruning (7 days), and five real workflows (A new exception/case, B critical
  escalation, C daily summary, D document failure, E integration health) with HMAC verification and
  Redis-backed idempotency. Three outbox integrations deliver signed events; verification covered
  duplicate suppression, invalid-signature rejection, Mailpit delivery, document-failure reprocessing
  and scheduled runs.
- **Observability:** API `/metrics` with real HTTP/business series, Prometheus (15-day retention) with
  13 targets and 20 alert rules, Alertmanager → Mailpit, and four provisioned Grafana dashboards
  (overview, database/storage, AI/documents, business). A controlled alert and a real database-down
  alert both delivered to Mailpit.
- **New internal endpoint:** `POST /api/v1/internal/automation/claims` (shared-secret protected,
  Redis `SET NX EX`) provides durable idempotency for automation consumers.
- **Document events:** `document.failed` is now emitted by the processing worker with a redacted error
  context.
- **Tests:** backend 136 passed + 1 skip (PostgreSQL and SQLite), frontend typecheck/lint/Vitest
  (6/6)/build, Playwright 10/10 over HTTPS, 28-step end-to-end workflow (vendor → PO → upload → OCR →
  extraction → exceptions → case → Ollama investigation → proposal → approval → execution → audit →
  analytics), 16/16 security checks.
- **Backup/restore:** `backups/compose-20261119-205946` (65 objects, 106 invoices, 48 cases, 17
  documents, 16 chunks) restored into the isolated database
  `resolve_restore_hardening_20261119_210117` and bucket `resolve-documents-restore-hardening`; counts,
  `vector(1024)`, the HNSW index, retrieval and one object's SHA-256 were verified.
- **Operations:** Docker watchdog scheduled task, Docker-first start/stop/restart/status/health
  scripts, and a backup timestamp exported to Prometheus through the node-exporter textfile collector.

## [0.3.0] — 2026-11-19

### Compose runtime and S3 storage verified after reboot

- **Docker Compose now runs and is verified** after the required Windows reboot: PostgreSQL 16 +
  pgvector, Redis, API, worker, beat, nginx, Mailpit, n8n and the optional Prometheus/Grafana profile
  all start healthy.
- Replaced the retired MinIO images with **SeaweedFS 4.54**. The gateway generates an identity file
  from `S3_ACCESS_KEY`/`S3_SECRET_KEY`, rejects anonymous access, uses path-style S3 addressing and
  is capped at 64 × 1 GB volumes so new buckets can be allocated after restarts.
- Bound PostgreSQL, Redis, API, S3, Mailpit, n8n and monitoring ports to `127.0.0.1`; only the web
  port (8180) is reachable from other hosts.
- Fixed nginx caching the API container IP: the proxy now re-resolves Docker DNS, so recreating the
  API no longer leaves the web tier returning 502.
- Added `app/scripts/s3_sync.py` (boto3 mirror with bucket creation, deletion and path-traversal
  guards) because AWS CLI v2 streaming-checksum uploads are rejected by SeaweedFS. Backup/restore
  scripts now use it.
- Verified backup/restore end to end: 42 objects plus the PostgreSQL dump restored into a new
  database and bucket; all 42 SHA-256 hashes matched and row counts were identical.
- Verified the live Compose workflow: demo seed (103 invoices, 143 exceptions, 30 cases), a new
  upload processed to `INDEXED` and downloaded, and 10/10 Playwright tests against the nginx bundle
  including a real Ollama investigation.
- Added 7 S3 regression tests (path/virtual addressing, bucket-creation race, sync prefix/delete,
  path traversal). Backend: **134 passed on PostgreSQL; 133 passed + 1 skip on SQLite**.
- Capped WSL2 at 8 GB / 4 CPUs after repeated Docker engine restarts under host memory pressure.

## [0.2.0] — 2026-11-19

### One-run Windows deployment, local AI and LAN access

- Added native Windows service deployment (`resolvepgtest`, `Memurai`, `RESOLVE-API`,
  `RESOLVE-Worker`, `RESOLVE-Beat`, `RESOLVE-Web`, `RESOLVE-Ollama`, `RESOLVE-Mailpit`) with
  auto-start, NSSM restart policy and log rotation.
- Added `scripts/start-resolve.ps1`, `stop-resolve.ps1`, `status-resolve.ps1`, `health-check.ps1`,
  `backup-resolve.ps1`, `restore-resolve.ps1` and `resume-after-reboot.ps1`.
- Installed and verified **Ollama 0.40.16** with `qwen2.5:7b-instruct` and multilingual `bge-m3`
  embeddings (1024 dims); real investigations now complete with validated citations.
- Added strict provider schemas requiring evidence/recommendations, an evidence-repair retry and a
  visible limitation when a local model still omits citations.
- Compiled **pgvector 0.8.1** for PostgreSQL 18.6 from official source; added migration
  `f7b2c9d4a1e3` for configured dimensions, JSON backfill and the HNSW index. New chunks sync their
  vectors; retrieval reports `hybrid+pgvector`; `EXPLAIN ANALYZE` shows an index scan.
- Served the production SPA through Windows nginx on `0.0.0.0:8090`, with `/api` and `/health`
  proxied to the loopback API. Exposed only TCP 8090 to `LocalSubnet` on the Private profile.
- Verified the full 27-step workflow through the LAN URL, including real AI investigation, approval,
  SMTP execution (Mailpit), audit and analytics.
- Live OCR verified through the API (PNG invoice, confidence 0.93).
- Backup/restore verified into an isolated database, including document chunks and vector rows.
- Docker Desktop and WSL2 components installed; WSL2/Hyper-V features enabled and a post-reboot logon
  task registered. **The Docker engine still requires one reboot**, so Compose runtime is not claimed
  as verified.
- MinIO official Windows binaries are no longer distributed (archived upstream); the native
  deployment uses the verified local storage backend and production guidance recommends managed S3.
- Tests: 127 pass on PostgreSQL, 126+1 skip on SQLite; Playwright 10/10 against the LAN production
  bundle; TypeScript/ESLint/Vitest/build pass.

## [0.1.0] — 2026-11-19

### Verification and hardening pass

This release records the independent verification pass and every defect fixed during it. See
[`docs/FINAL_VERIFICATION_REPORT.md`](docs/FINAL_VERIFICATION_REPORT.md) for evidence.

### Fixed

- **PostgreSQL:** optional pgvector probing no longer aborts the surrounding transaction; AI
  investigations now complete on PostgreSQL without pgvector instead of remaining `QUEUED`.
- **PostgreSQL:** case/vendor JSON array filters now compile to `JSONB @>` instead of the invalid
  `json @> json` operator.
- **Concurrency:** case-number allocation is serialized with a transaction-scoped advisory lock;
  simultaneous invoice submissions no longer return HTTP 500.
- **Tenancy:** invoice creation validates the linked document's organization and type; document →
  invoice creation rejects foreign/unknown vendors and purchase orders instead of silently ignoring
  them.
- **Secrets:** secret-like integration config values are moved into encrypted credentials; redaction
  is recursive.
- **Webhooks:** disabled integrations and payloads over 1 MB are rejected; outbound deliveries are
  signed with the integration's own signing secret; URLs must be absolute HTTP(S).
- **AI evidence:** fabricated/nonexistent document IDs are stored as invalid evidence with a
  validation error (and a NULL FK) instead of violating the foreign key.
- **Approvals:** assigned approvers must be active members with `approval:decide`; rejected,
  cancelled and expired resolutions can be re-proposed.
- **Evidence validation:** malformed chunk UUIDs produce a validation error rather than a crash.
- **Documents:** upload limit is configuration-driven; DOCX/XLSX archives are checked for ZIP bombs;
  OCR has a timeout; document detail text is bounded; upload size limit is enforced consistently.
- **OCR:** Tesseract binary is auto-detected on Windows; requested languages fall back to installed
  traineddata and log `ocr_language_fallback`.
- **Performance:** case and exception lists batch assignee/case lookups instead of N+1 queries.
- **Docker:** worker and beat no longer race migrations (`RUN_MIGRATIONS=false`); the Vite dev
  container honours `VITE_API_PROXY`; MinIO backup scripts mount the destination volume correctly.
- **Accessibility:** pagination buttons have accessible names; form labels are associated with their
  controls.

### Added

- PostgreSQL test backend (schema per test) via `RESOLVE_TEST_DATABASE_URL`; tests also run the
  PostgreSQL dialect code paths.
- Real OCR tests (PNG and scanned PDF) that skip honestly when Tesseract is absent; DOCX/XLSX/CSV
  extraction tests; upload-limit, ZIP-bomb and bounded-detail tests.
- OpenAI-compatible provider tests over real HTTP against a local fake server (retries, rate limits,
  invalid JSON repair, schema exhaustion, embeddings, health).
- Vendor risk-flag/tenant tests, invoice document-link validation tests, integration hardening tests.
- PostgreSQL concurrency test for case numbers.
- Verification scripts: `verify_ocr.py`, `verify_workflow_e2e.py`, `verify_concurrency.py`,
  `verify_celery.py`.
- Expanded Playwright suite covering every navigation route, pagination, viewer read-only
  permissions and API error/retry, with console-error assertions.

### Changed

- Alembic initial migration treats pgvector as optional (SAVEPOINT + capability check).
- `docs/PROJECT_PLAN.md`, `README.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY`, `docs/DEPLOYMENT`,
  `docs/testing/README.md` updated with verified figures and honest limitations.

### Known limitations

- Docker image builds and Compose runtime are not verified in this environment.
- pgvector ANN/HNSW was unverified on the native PostgreSQL build used for testing (resolved in 0.2.0).
- Real LLM output quality requires provider credentials; only the wire protocol is verified.
