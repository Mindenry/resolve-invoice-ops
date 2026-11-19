# RESOLVE — Final independent verification report

> **Historical document.** For the current verified state see `docs/FINAL_PRODUCTION_HARDENING_REPORT.md`.

**Date:** 2026-11-19
**Scope:** independent audit of the existing repository at `C:\path\to\resolve`, defect fixing, and
verification against real PostgreSQL, real OCR, a real Celery worker, live HTTP APIs and a real
browser.
**Verdict:** core product is functional and independently verified on PostgreSQL. The initial audit
resolved **pgvector** and **real local AI**; the post-reboot pass resolved **Docker Compose**, which is
now the primary LAN deployment at `https://192.168.1.10:8180`. The native stack remains as a
localhost rollback. A physical macOS client was not available for direct testing.

### Deployment addendum (2026-11-19)

- Native Windows services are running: PostgreSQL 18.6 + **pgvector 0.8.1**, Memurai/Redis, Celery
  worker/beat, Ollama (Qwen2.5 7B + BGE-M3), Mailpit, FastAPI and nginx on the LAN at `192.168.1.10:8090`.
- A real 27-step workflow ran through the LAN URL with a **real Ollama investigation**, approval and
  SMTP execution; Playwright 10/10 passed against the production nginx bundle.
- pgvector: `vector(1024)`, JSON backfill, HNSW index and an actual `Index Scan` verified; new uploads
  sync into `embedding_vec`; retrieval reports `hybrid+pgvector`.
- Backup/restore was verified into an isolated database, including vector rows.
- Docker Desktop/WSL2 were installed before the reboot; the Compose runtime is now verified (see the
  Compose addendum and `FINAL_DEPLOYMENT_REPORT.md`).
- No physical Mac was present; LAN/firewall/session/upload/investigation were tested from Windows
  against the LAN address. macOS commands are in `docs/LAN_ACCESS_GUIDE.md`.

### Compose addendum (2026-11-19, after reboot)

- The required reboot completed; `HyperVisorPresent=True` and Docker Desktop 29.9.3 runs WSL2.
- The full Compose stack starts and is healthy: PostgreSQL 16 + pgvector, Redis, SeaweedFS S3, API,
  Celery worker, beat, nginx web and Mailpit. n8n and the optional Prometheus/Grafana profile also
  start, and their health endpoints return 200.
- Archived MinIO was replaced by **SeaweedFS 4.54** with an authenticated, path-style S3 gateway.
  The Compose demo seed wrote **42 objects**. A new upload processed to `INDEXED` and downloaded
  byte-for-byte; the API reports `storage.backend=s3`.
- Backup/restore was re-verified against Compose: the PostgreSQL dump plus 42 documents were
  restored into a new database and bucket; restored row counts matched and **42/42 SHA-256 hashes**
  matched the source.
- Backend tests are now **134 passed on PostgreSQL 18.6** and **133 passed + 1 PostgreSQL-only skip
  on SQLite** (7 new S3 client/sync tests). Ruff is clean.
- Playwright **10/10** passed against `https://127.0.0.1:8180`, including a real Ollama investigation.
- A stale-upstream defect was found and fixed: nginx cached the API container IP and returned 502
  after the API was recreated. The proxy now re-resolves Docker DNS; recreating the API leaves
  `/health` at 200 without restarting nginx.
- Only web 8180 is published to all interfaces; PostgreSQL, Redis, API, S3, Mailpit, n8n and
  monitoring are bound to `127.0.0.1`.
- WSL2 is capped at 8 GB / 4 CPUs because unbounded memory caused Docker engine restarts during
  builds. Long-running HA behavior and container upgrades remain outside this verification.

Every result below is backed by a command, an HTTP response or a database query from this session.
Earlier completion claims were not trusted. Sections written before the Compose addendum describe
the native stack and remain accurate for that stack.

---

## 1. Executive summary

- The prior "fully implemented" claim was **substantially true but overstated** in three places:
  PostgreSQL compatibility, OCR availability, and concurrency behaviour.
- Backend: **134 passed on PostgreSQL 18.6; 133 passed + 1 intentional PostgreSQL-only skip on
  SQLite** (the 7 S3 regression tests were added in the Compose addendum). `ruff` is clean.
- The complete 27-step business workflow (login → vendor → PO → upload → extract → correct →
  review → invoice → validate → exceptions → case → assign → AI investigation → evidence →
  approval → execution → audit → analytics) ran against a live API on a seeded PostgreSQL database
  and was verified in the database.
- Real Tesseract 5.4 OCR was installed and verified on generated PNG, JPG and scanned PDF files,
  in addition to PDF/DOCX/XLSX/CSV parsing.
- A real Celery worker connected to Redis/Memurai processed real jobs (maintenance + AI
  investigation) against PostgreSQL.
- Frontend: typecheck, lint, Vitest, production build and **10 Playwright tests** pass, including
  all 14 navigation destinations, pagination, read-only permissions, API error/retry state, Thai
  locale and dark theme, with zero browser console errors.
- 17 real defects were found and fixed (database, security, concurrency, OCR, accessibility,
  deployment). The most serious were a PostgreSQL transaction-poisoning bug that made AI
  investigations fail, broken PostgreSQL JSON filters, plaintext integration secrets in config,
  and a case-number race that returned HTTP 500 under concurrency.
- Initial pass: Docker runtime, pgvector ANN and real LLM quality were unverified.
  **Follow-up:** pgvector, real Ollama AI and Docker Compose are now verified; Docker is primary.
  See the deployment addendum and `docs/ONE_RUN_SETUP_REPORT.md`.

## 2. Actual project architecture

| Layer | Reality (verified in source) |
| --- | --- |
| Backend | FastAPI 0.11x modular monolith, **19 functional modules** under `apps/api/app/modules` |
| Database | SQLAlchemy 2 ORM, Alembic; **49 domain tables** (+ `alembic_version`), 660 columns |
| Frontend | React 18 + Vite 5 + Tailwind 4, 18 page components, 24 route entries, EN/TH i18n |
| Jobs | Celery 5.7 with Redis broker; local bounded thread pool or inline runner when Celery is not configured |
| AI | Provider abstraction (`openai`-compatible, `ollama`, deterministic `stub`, `none`), structured output, retries, token/cost tracking |
| Documents | PyMuPDF, python-docx, openpyxl, CSV, Pillow, pytesseract; SHA-256 dedupe; local/S3 storage |
| Retrieval | JSON embeddings + exact cosine, keyword hybrid; optional pgvector path detected at runtime |
| Automation | Integration registry, encrypted credentials, HMAC webhooks, outbox, n8n templates |
| Deployment | Docker Compose (PostgreSQL+pgvector, Redis, SeaweedFS S3, API, worker, beat, nginx SPA, n8n, Mailpit, monitoring); native services as localhost rollback |

## 3. Verified features

| Area | Evidence |
| --- | --- |
| Authentication | Login, `/users/me`, refresh rotation/reuse family revocation, logout, reset flow, session revocation — API tests and live login |
| RBAC and tenancy | Viewer mutation → 403; cross-tenant vendor/case/document reads and document mutation → 404; cross-org invoice links rejected; tests pass on both databases |
| Vendors / POs / invoices | Create, list, filter (including new portable JSON tag/risk-flag filters), validate, match, totals/variance |
| Documents | Upload validation, SHA-256 dedupe (409), storage, versioning, page extraction, field correction, review, invoice creation (idempotent per document), bounded detail payload |
| OCR | Tesseract 5.4.0 (`eng` + installed `tha`), PNG/JPG/scanned PDF OCR with confidence and has_text_layer=false; honest failure when unavailable |
| Exception engine | Deterministic rules produced 2 exceptions for an over-tolerance invoice; re-scan is idempotent by fingerprint; duplicate invoices surfaced |
| Cases | Numbering, SLA, assignment, comments, timeline, transitions, resolve/close, concurrent number allocation unique |
| AI investigation (stub) | Completed with 4/4 evidence items validated, 2 suggestions; fabricated document IDs downgraded and preserved as validation errors; accepting a suggestion creates an unexecuted resolution proposal |
| Approval and execution | Approval queue, assigned approver, self-approval 403, approval decision, audited email-sink execution, idempotency |
| Audit / analytics | 9 audit rows for the created case+resolution; case timeline 9 entries; analytics overview returns live SQL aggregates |
| Integrations | Secrets encrypted and removed from config, recursive redaction, per-integration HMAC signing, URL validation, disabled-integration and oversized-payload rejection |
| Background processing | Real Celery worker: maintenance job SUCCEEDED; investigation COMPLETED; worker job SUCCEEDED |
| Frontend | All nav routes render with live data and no console errors; filters/details/pagination; role-aware read-only settings; error+retry; themes/locales |

## 4. Features that required fixes

1. **Investigations failed on PostgreSQL.** The pgvector probe issued a failing statement inside the
   request transaction. PostgreSQL aborted the transaction; subsequent evidence/usage writes failed
   and the investigation stayed `QUEUED`. Fixed with a SAVEPOINT-protected capability probe, cached
   availability, and rollback+reload in the investigation context failure path.
2. **Case tag and vendor risk-flag filters were broken on PostgreSQL.** SQLAlchemy `JSON.contains`
   emitted `json @> json`, which PostgreSQL rejects. Added a dialect-aware JSON-array predicate
   (`JSONB @>` on PostgreSQL, quoted-token match on SQLite) and tests.
3. **Concurrent invoice submissions returned HTTP 500.** Each request auto-created a case; concurrent
   MAX+1 allocation collided. Added a transaction-scoped PostgreSQL advisory lock per organization.
   Live concurrency test now returns 5/5 HTTP 201 with unique case numbers.
4. **Invoice/document linking was under-validated.** Invoice creation accepted foreign documents;
   document→invoice silently ignored an unknown vendor/PO. Both now return 400 with explicit codes.
5. **Integration secrets were stored in plaintext config** when supplied inside `config`, and
   redaction was shallow. Secret-like values are now extracted into encrypted credentials and
   redacted recursively; outbound webhooks sign with the integration's own secret.
6. **Inbound webhooks accepted disabled integrations and arbitrarily large bodies.** Both rejected.
7. **Malformed evidence chunk IDs crashed validation.** Invalid UUIDs now produce a validation error.
8. **Assigned approvers were not validated.** Must be an active member with `approval:decide`.
9. **Terminal resolutions could not be re-proposed** (idempotency key blocked a new attempt).
10. **Upload limits and OCR timeout were hardcoded/absent**; ZIP bombs were not guarded for
    DOCX/XLSX; document detail returned unbounded page text. All bounded/configured.
11. **N+1 queries** in case and exception lists; both now batch assignees/case references.
12. **OCR language configuration could fail** when `tha` data was absent; now falls back to installed
    languages and auto-detects the Windows Tesseract path.
13. **Docker worker/beat raced the API running `alembic upgrade head`**; migrations are now gated by
    `RUN_MIGRATIONS`.
14. **Vite dev server ignored `VITE_API_PROXY`** used by `docker-compose.dev.yml`; fixed.
15. **Accessibility:** pagination icon buttons lacked accessible names; `Field` labels were not
    associated with their controls. Both fixed.
16. **Unbounded/blocking PostgreSQL vector probe** replaced with capability caching (same as #1).
17. **Migration was not runnable without pgvector**; the extension and `embedding_vec` column are now
    optional.

## 5. Bugs discovered and fixed (severity order)

| Severity | Bug | Status |
| --- | --- | --- |
| Critical | PostgreSQL transaction poisoned by optional pgvector probe; investigations never completed | Fixed + regression coverage |
| High | Concurrent case-number allocation → HTTP 500 / lost work | Fixed (advisory lock) + PG concurrency test |
| High | Invoice `document_id` cross-tenant/type bypass | Fixed + tests |
| High | Integration secrets stored unencrypted when nested in `config` | Fixed + test |
| Medium | PostgreSQL JSON filters unusable | Fixed + PG tests |
| Medium | Investigation evidence FK violation on fabricated document IDs | Fixed + test |
| Medium | ZIP-bomb risk in DOCX/XLSX | Fixed + unit test |
| Medium | Oversized/disabled webhook acceptance | Fixed + tests |
| Medium | Unbounded document detail payload | Fixed + test |
| Low | OCR language crash / path detection | Fixed |
| Low | N+1 list queries | Fixed |
| Low | Missing accessible names/labels | Fixed |

## 6. Security findings

Verified by live requests and tests:

- **Tenant isolation:** cross-organization vendor, case, document reads → 404; cross-tenant document
  mutation → 404; invoice creation with a foreign document → 400; retrieval filters `org_id`.
- **RBAC:** viewer vendor creation → 403; approval decisions require `approval:decide`; self-approval
  → 403; execute-before-approval and self-approval are covered by tests.
- **File upload:** extension/MIME mismatch rejected, configurable size limit enforced, SHA dedupe,
  path traversal rejected, ZIP expansion guard.
- **Webhooks:** HMAC verified constant-time; wrong signature → 400; idempotency key dedupe; disabled
  integration → 400; payload > 1 MB → 400; outbound requests signed with per-integration secret.
- **Secrets:** integration credentials Fernet-encrypted; API returns key names only; config secrets
  removed and redacted; logs do not include passwords/tokens.
- **Rate limiting:** with `RATE_LIMIT_LOGIN=3/minute`, the 4th bad login returned 429 (live test).
- **CORS:** allowed origin echoed; `http://evil.example` preflight rejected (400, no allow-origin).
- **Headers:** `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  `Permissions-Policy`, request/correlation IDs observed.
- **AI containment:** no tools/SQL/shell; schema validation; citation validation against
  org-scoped chunks/pages; model cannot lower approval policy or execute actions. Accepting an AI
  suggestion creates a normal resolution proposal (`executed_at=null`, no execution rows) that still
  needs the ordinary approval/execute path.
- **Audit:** append-only API; no update/delete endpoints.

Residual security gaps are listed in §15 (malware scanning, SSO, audit WORM, no pen-test).

## 7. Database verification results

- PostgreSQL **18.6** (native service, isolated cluster on `127.0.0.1:55432`, Windows service
  `resolvepgtest`, database `resolve`; the pre-existing `postgresql-x64-18` service on port 5432 was
  never modified).
- `alembic upgrade head` → **pass**; `alembic check` → **no new upgrade operations**.
- `alembic downgrade base` then `upgrade head` → **pass** (reversible).
- SQLite `alembic upgrade head` → **pass**.
- Full backend suite on PostgreSQL: **134 passed** (post-Compose addendum).
- UUID, timezone-aware timestamps, `NUMERIC` money (values returned as `Decimal('1284.0000')`),
  JSON/JSONB, FK constraints, unique constraints, transactions and nested savepoints all exercised.
- Schema: 49 domain tables, 660 columns.
- Migration is idempotent with respect to the optional vector extension.

## 8. PostgreSQL and pgvector results

- Core PostgreSQL compatibility: **verified** (tests, migrations, live workflow, concurrency).
- pgvector **0.8.1** was compiled from official source with the installed MSVC toolchain against
  PostgreSQL 18.6 and installed natively.
- `CREATE EXTENSION vector` → 0.8.1; `document_chunks.embedding_vec vector(1024)`; JSON backfill
  **20/20**; HNSW cosine index `ix_document_chunks_embedding_vec`.
- `EXPLAIN (ANALYZE, BUFFERS)` with `enable_seqscan=off` shows **Index Scan using the HNSW index**;
  the API reports retrieval mode **`hybrid+pgvector`**.
- New document uploads synchronize JSON embeddings into `embedding_vec`; verified with a new
  two-chunk document and `hybrid+pgvector` search.
- Tenant isolation: a second organization returned zero knowledge hits and 404 for a foreign document.
- Migration `f7b2c9d4a1e3` makes the dimension follow `AI_EMBEDDING_DIM`, backfills vectors and
  rebuilds the index; fresh PostgreSQL and SQLite upgrades and downgrades pass, and `alembic check`
  reports no pending operations.
- The test suite sets `settings.DATABASE_URL` to the PostgreSQL URL when `RESOLVE_TEST_DATABASE_URL`
  is set, so dialect-specific code is really exercised.

## 9. OCR results

Installed **Tesseract 5.4.0.20240606** (UB Mannheim) and Thai traineddata (`eng`, `tha`, `osd`).

| Format | Result |
| --- | --- |
| PNG (generated invoice) | 142 chars, confidence 0.949, invoice number recognised |
| JPG (same content) | 142 chars, confidence 0.949 |
| Scanned PDF (image-only page) | 142 chars, confidence 0.95, `has_text_layer=false` |
| Text-layer PDF | embedded text extracted; short page also OCR'd by design |
| DOCX | `python-docx`, expected token found |
| XLSX | `openpyxl`, expected token found |
| CSV | `csv`, expected token found |

`apps/api/scripts/verify_ocr.py` reproduces this without external files. Automated tests cover real
PNG/scanned-PDF OCR when Tesseract is present and skip honestly when it is not. OCR language
selection now falls back to installed traineddata and logs `ocr_language_fallback`.

## 10. Real AI provider verification status

- **Real local AI is now configured and verified**: Ollama 0.40.16 with `qwen2.5:7b-instruct`
  (4.7 GB) and multilingual `bge-m3` embeddings (1024 dims) on the RTX 4070 SUPER.
- Live investigations through the API completed with `provider=ollama`, validated evidence,
  concrete root cause and suggested resolutions. Cold model load was ~44 s; warm calls 2–13 s.
- Direct checks: English JSON, Thai-only output, prompt-injection instruction inside a document was
  not followed, embeddings returned 1024 dimensions.
- Provider schemas now require evidence and recommendations; an evidence-repair call runs when a
  local model omits them, and an explicit limitation is stored if citations remain absent. Prompt
  version `investigation.v2`.
- The OpenAI-compatible provider is also exercised over **real HTTP** against a local fake server:
  chat JSON mode, schema payload, bearer auth, 429 retry, 500 retry exhaustion, non-retryable 400,
  invalid-JSON repair instructions, schema-validation exhaustion, embeddings, health, and registry
  credential gating. **8 tests pass** (`tests/test_ai_providers.py`).
- The deterministic stub remains for tests/demo and is labelled everywhere (`provider=stub`,
  `model=resolve-stub-1`, `deterministic_stub=true` in system info).
- Application behaviour with AI unavailable is verified (`ai_unavailable`, failed investigation,
  honest UI error).
- A 7B local model still has quality limits; all citations are validated and all actions remain
  human-approved. External provider quality/cost was not evaluated (no external credentials).

## 11. Frontend verification

- `tsc --noEmit`: pass.
- ESLint: **0 errors**, 4 pre-existing fast-refresh warnings.
- Vitest: **6/6**.
- Production build: pass (approx. 1.1 MB JS before gzip; manual vendor chunks).
- Playwright: **10/10** against the running stack:
  - all 14 navigation destinations (Command Center, Exceptions, Cases, Documents, Invoices, Vendors,
    Purchase Orders, Approvals, Integrations, Workflows, Evaluation, Analytics, Audit, Settings),
    asserting URLs and no “Something went wrong”;
  - zero console errors during the full navigation tour;
  - case-list pagination (next/previous page, real records);
  - viewer role sees read-only Settings (Save/inputs disabled);
  - forced API 500 shows the error state and “Try again” recovers;
  - login + live KPIs, exception evidence, AI investigation with validated evidence, document
    review, approval center, Thai locale + dark theme persistence.
- Loading/empty/error states exist and were exercised (skeleton, EmptyState, ErrorState).
- No page is a decorative mockup; each route calls the live API.

## 12. E2E results

Live API on PostgreSQL, seeded demo workspace (11 vendors, 20 POs, 103 invoices, 143 exceptions,
30 cases), plus the workflow under test:

```
login → vendor → PO → upload PDF → extract 10 fields → correct invoice number → review
→ create invoice (idempotent) → validate (REQUIRES_REVIEW) → 2 exceptions
→ case CASE-2026-00xx → assign investigator → real Ollama investigation with validated evidence
→ resolution proposed → approval queue → approve → execute (SMTP/Mailpit)
→ case RESOLUTION_IN_PROGRESS → 9 audit rows → 9 timeline entries → analytics live
```

Negative paths in the same run: viewer mutation 403, cross-tenant reads/mutations 404,
self-approval 403. Database values were queried directly after the run.

## 13. Docker verification

**Verified after the reboot (2026-11-19).** Docker Desktop 29.9.3 runs WSL2 3.0.1 with
`HyperVisorPresent=True`. `docker compose --env-file .env config` is valid, and the full stack starts
and reports healthy:

- web 8180 (all interfaces), API 8100, PostgreSQL 5433, Redis 6380, SeaweedFS 9100/9101, Mailpit
  8125/1126, n8n 5679, Prometheus 9190, Grafana 3101; all except web bind to `127.0.0.1`.
- 42 objects after the demo seed and 46 after verification uploads; new uploads process to `INDEXED`
  and download byte-for-byte.
- Backup/restore into a new database and bucket matched all 42 document hashes; the restored DB had
  11/11 vectors.
- Playwright 10/10 against the nginx bundle; n8n `/healthz` and monitoring health endpoints return 200.
- nginx now re-resolves the API service, so recreating the API does not leave 502s.
- MinIO was replaced by SeaweedFS 4.54 because the official images are retired. Native storage remains
  local; production should use managed S3. The worker/beat migration race and Vite dev proxy fixes are
  retained.

## 14. Performance findings

- Case list: **2 batched queries** for assignees and exception counts instead of 1–2 per row.
- Exception list: one batched case lookup instead of one per row.
- Document detail text is bounded (`DOCUMENT_DETAIL_MAX_CHARS`, default 60,000).
- Upload/decompression/OCR limits are configurable; OCR has a timeout.
- Pagination is enforced by API and UI; no unbounded list endpoint observed.
- pgvector HNSW index is used for similarity ordering (`Index Scan` verified); new vector rows are
  synchronized on indexing.
- Residual: `GET /resolutions` still builds approval/executions per row (bounded by page size);
  acceptable at current volume, noted for future batching.
- No benchmark claims are made beyond concurrency, query-shape and index-plan checks.

## 15. Remaining limitations (unverified / partial)

| Item | Status | Reason |
| --- | --- | --- |
| Docker image builds and Compose runtime | **Verified** | post-reboot addendum: full stack healthy, S3 + backup/restore + Playwright verified |
| pgvector extension, HNSW index | **Verified** | 0.8.1 native build, `vector(1024)`, backfill, Index Scan |
| Real local AI quality, latency, cost | **Partially verified** | Ollama Qwen2.5 7B verified end-to-end; 7B quality limits; external providers unverified |
| macOS client (Safari/Chrome) | **Partially verified** | no physical Mac; LAN path tested from Windows; macOS commands provided |
| Celery beat scheduled execution over time | Partially verified | worker + beat running; schedule observed, not run for hours |
| HTTPS on LAN | Not configured | HTTP development mode; use private CA/reverse proxy before real data |
| Malware scanning / AV | Not implemented | Documented deployment control (ClamAV etc.) |
| n8n / Prometheus / Grafana | Health verified | containers start and health endpoints return 200; workflow/dashboard content not exercised |
| MinIO | Replaced | images retired upstream; SeaweedFS S3 verified in Compose, managed S3 recommended for production |
| SSO/SAML/SCIM, audit WORM, field-level permissions | Not implemented | Out of scope |
| SQLite as production database | Rejected by configuration | Dev/test only |

## 16. Exact commands to start the application

**Verified native one-command start (Windows):**

```powershell
cd "C:\path\to\resolve"
.\scripts\start-resolve.ps1
.\scripts\status-resolve.ps1
.\scripts\health-check.ps1 -Deep
```

Then open `https://localhost:8180` (Windows) or `https://192.168.1.10:8180` (LAN). The native
rollback is `http://127.0.0.1:8090`. Stop with
`.\scripts\stop-resolve.ps1`.

Manual development start:

```powershell
# 1. Backend (from apps/api)
cd "C:\path\to\resolve\apps\api"
$env:DATABASE_URL = "postgresql+psycopg://resolve:resolve@127.0.0.1:5432/resolve"
..\..\.venv\Scripts\python.exe -m alembic upgrade head
..\..\.venv\Scripts\python.exe -m app.scripts.seed_demo        # demo only
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. Frontend (from apps/web)
cd "C:\path\to\resolve\apps\web"
npm ci
npm run dev        # http://localhost:5173 (proxies /api to :8000)

# 3. Optional worker + beat (Redis must be reachable)
cd "C:\path\to\resolve\apps\api"
$env:TASK_RUNNER = "celery"
$env:CELERY_BROKER_URL = "redis://127.0.0.1:6379/0"
..\..\.venv\Scripts\python.exe -m celery -A app.workers.celery_app.celery_app worker --pool=solo --loglevel=INFO
..\..\.venv\Scripts\python.exe -m celery -A app.workers.celery_app.celery_app beat --loglevel=INFO
```

SQLite quick start (development only): set `DATABASE_URL=sqlite:///./var/resolve.db` and
`AUTO_CREATE_SCHEMA=true`; `TASK_RUNNER=inline` removes the Redis requirement.

Demo login: `admin@example.com` / `the password in var/secrets/demo-credentials.txt` (other roles: manager, investigator, approver, viewer).

## 17. Exact test commands

```powershell
# Lint
cd "C:\path\to\resolve"
.\.venv\Scripts\python.exe -m ruff check apps/api

# Backend - SQLite (133 passed, 1 PostgreSQL-only skip)
cd apps\api
..\..\.venv\Scripts\python.exe -m pytest -q

# Backend - real PostgreSQL (134 passed)
$env:RESOLVE_TEST_DATABASE_URL = "postgresql+psycopg://resolve@127.0.0.1:55432/resolve"
..\..\.venv\Scripts\python.exe -m pytest -q

# Migrations
$env:DATABASE_URL = "postgresql+psycopg://resolve@127.0.0.1:55432/resolve"
..\..\.venv\Scripts\python.exe -m alembic upgrade head
..\..\.venv\Scripts\python.exe -m alembic check

# Document/OCR verification (requires Tesseract)
..\..\.venv\Scripts\python.exe scripts\verify_ocr.py

# Live workflow against a seeded PostgreSQL API
..\..\.venv\Scripts\python.exe scripts\verify_workflow_e2e.py --base-url http://127.0.0.1:8001

# Concurrency (duplicate uploads, invoice allocation)
..\..\.venv\Scripts\python.exe scripts\verify_concurrency.py --base-url http://127.0.0.1:8001

# Celery worker verification (worker + Redis running)
..\..\.venv\Scripts\python.exe scripts\verify_celery.py

# Frontend
cd ..\web
npm run typecheck
npm run lint
npm test
npm run build
npx playwright test
```

## 18. Production deployment requirements

- PostgreSQL 16+ **with pgvector** (`pgvector/pgvector:pg16` image), managed backups/PITR.
- Managed PostgreSQL with pgvector, managed S3-compatible storage (SeaweedFS or cloud), Redis, SMTP relay.
- Tesseract with `eng` and `tha` traineddata (the API image installs both).
- `SECRET_KEY`, database/S3/n8n passwords and AI keys from a secret manager.
- `ENV=production`, `DEBUG=false`, `DEMO_MODE=false`, `SEED_DEMO=false`, explicit `CORS_ORIGINS`,
  HTTPS termination with forwarded headers.
- Run migrations once before rolling API replicas; workers/beat use `RUN_MIGRATIONS=false`.
- Verify `/health/ready` (DB + storage) and monitor failed jobs, webhook failures, approval backlog.
- Malware scanning, SSO, audit WORM and retention policies are recommended additions, not included.
