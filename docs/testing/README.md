# Testing

## 1. Commands

```bash
# Backend
cd apps/api
pytest -q                      # full suite (SQLite in-memory, stub AI, inline tasks)
pytest tests/test_rules.py -q  # focused
ruff check .

# Backend against real PostgreSQL (isolated database)
$env:RESOLVE_TEST_DATABASE_URL = "postgresql+psycopg://resolve@127.0.0.1:55432/resolve"
pytest -q

# Frontend
cd apps/web
npm test                       # Vitest + Testing Library helpers
npm run typecheck
npm run lint
npm run build

# End-to-end (API on :8000, Vite on :5173, Chrome installed)
cd apps/web
npx playwright test
```

## 2. Test architecture

- Each backend test gets a fresh database. With `RESOLVE_TEST_DATABASE_URL` set, each test receives
  its own PostgreSQL schema and `settings.DATABASE_URL` points at PostgreSQL, so dialect-specific
  code (JSONB, savepoints, advisory locks, pgvector fallback) is really exercised. Without it, an
  in-memory SQLite `StaticPool` database is used.
- `get_db` is overridden to the test session. `app.db.session.SessionLocal` is patched as well, so
  deferred work and the inline task runner use the same database.
- Tasks run inline (`ENV=test`, `TASK_RUNNER=inline`), making async flows deterministic.
- The AI layer uses the explicit `stub` provider; provider failures and fabricated citations are
  tested with small fake providers, and the OpenAI-compatible transport is tested against a local
  fake HTTP server.
- HTTP tests exercise real routers, dependencies, status codes and error envelopes.
- PostgreSQL tests commit real rows so concurrency (case numbers) and transaction recovery are
  exercised, not simulated.

## 3. Coverage map

| Area | Tests | What is asserted |
| --- | --- | --- |
| Money | `test_money.py` | parsing, commercial rounding, Decimal tax, tolerance semantics |
| Text | `test_text.py` | legal-name normalisation (incl. Thai), invoice numbers, tax IDs, currencies, chunk overlap |
| Auth | `test_auth.py` | login, bad password, refresh rotation and reuse revocation, logout, reset flow + replay, weak password, provider gate, password change, multi-org selection |
| RBAC/tenancy | `test_rbac.py` | viewer/investigator denials, cross-org header rejection, foreign resource 404, role matrix, last-admin protection, role escalation |
| Rules | `test_rules.py` | duplicate exact/same-number-different-amount, idempotent dedupe, amount tolerance, missing PO policy, tax, future date, vendor mismatch, duplicate vendor, extraction anomaly, integration failure, case grouping, disabled rules, new rule version |
| Cases | `test_cases.py` | numbering, SLA, detail, invalid transitions, resolution summary requirement, exception resolution, assignment and comments, escalation/merge, filters/pagination, **PostgreSQL concurrent number allocation** |
| Documents | `test_documents.py` | real PDF parse/extract, duplicate upload, unsupported/MIME mismatch, correction + approve, reject reason, authenticated audited download, invoice creation from document, versioning, knowledge search, honest OCR failure, **real OCR (PNG/scanned PDF)**, DOCX/XLSX/CSV, upload limit, ZIP-bomb guard, bounded detail text, invoice-document type/tenant validation |
| AI providers | `test_ai_providers.py` | local fake OpenAI server: chat JSON, bearer auth, schema payload, 429/500 retries, non-retryable 400, invalid-JSON repair, schema exhaustion, embeddings, health, credential gating |
| Vendors | `test_vendors.py` | risk-flag JSON filter, tenant isolation |
| Investigation | `test_investigation.py` | end-to-end validated evidence, hallucinated document rejection and withheld root cause, AI unavailable, JSON retry, permission, evidence ID requirements, out-of-context citations, AI status |
| Resolutions/approvals | `test_resolutions_approvals.py` | approval required for external actions, approve + execute, execution idempotency, self-approval denial, rejection reason, execute-before-approval, low-risk auto-validation, invalid params, viewer denial, catalogue metadata, idempotency key |
| Integrations | `test_integrations.py` | credential encryption/redaction, signature rejection/acceptance, n8n absence is a failure, delivery failure persisted, skipped outbox without targets, permissions |
| Analytics/evaluation/audit | `test_analytics_evaluation.py` | KPIs from real rows, AI usage, dataset + real run metrics + stub label, provider failure leaves metrics empty, audit append-only and export |
| S3 storage/sync | `test_s3_storage.py` | path-style vs virtual-host addressing, concurrent bucket-create race, bucket failure, sync prefix/delete, download path-traversal rejection |
| Frontend unit | `format.test.ts`, `ui.test.tsx` | money/percent/confidence formatting, humanisation, class merging, UI primitives |
| E2E | `e2e/smoke.spec.ts`, `e2e/routes.spec.ts` | login, live dashboard, exception evidence, AI investigation with validated evidence, document review, approval center, Thai locale + dark theme, all 14 nav routes with no console errors, pagination, viewer read-only settings, API error + retry |

## 4. Latest verification (this environment)

| Check | Result |
| --- | --- |
| `ruff check apps/api` | pass |
| `pytest -q` (SQLite) | 133 passed, 1 PostgreSQL-only skip |
| `pytest -q` (`RESOLVE_TEST_DATABASE_URL`, PostgreSQL 18.6) | 134 passed |
| `alembic upgrade head` + `alembic check` (PostgreSQL) | pass, no pending operations |
| `alembic downgrade base` → `upgrade head` | pass |
| `scripts/verify_workflow_e2e.py` | 27 steps verified, DB inspected; also run through nginx/LAN with real Ollama AI and SMTP |
| `scripts/verify_concurrency.py` | 5/5 invoice requests 201; 1 upload / 4 conflicts; duplicate flagged |
| `scripts/verify_celery.py` | maintenance + investigation jobs SUCCEEDED in a real worker |
| `scripts/verify_ocr.py` | PNG, JPG, scanned PDF, text PDF, DOCX, XLSX, CSV pass |
| Live OCR upload (LAN) | `REQUIRES_REVIEW`, confidence 0.93, total `1284.00` extracted |
| `scripts/start-resolve.ps1` / `stop-resolve.ps1` | stop→start verified, data retained |
| `scripts/health-check.ps1 -Deep` | services + DB + Redis + AI generation pass |
| `scripts/backup-resolve.ps1` / `restore-resolve.ps1` | isolated restore including vectors verified |
| `npm run typecheck` / `npm run build` | pass |
| `npm run lint` | 0 errors, 4 fast-refresh warnings |
| `npm test` | 6 passed |
| `npx playwright test` | 10 passed via native LAN `http://192.168.1.107:8090` |
| `npx playwright test` (`RESOLVE_WEB_URL=https://127.0.0.1:8180`) | 10 passed against the Compose/nginx stack, including a real Ollama investigation |
| Docker Compose | all core services healthy; n8n and Prometheus/Grafana health endpoints 200 |
| Compose S3 | seed wrote 42 objects; new upload reached `INDEXED`; download byte-identical |
| Compose backup/restore | DB restored to a new database; 42/42 document SHA-256 hashes matched |
| Screenshot capture | 19 screenshots, no console errors |

A physical Mac was not available; the LAN path was tested from Windows. See
[`docs/ONE_RUN_SETUP_REPORT.md`](../ONE_RUN_SETUP_REPORT.md) and
[`docs/FINAL_VERIFICATION_REPORT.md`](../FINAL_VERIFICATION_REPORT.md).

## 5. What is not covered by automated tests

- **PostgreSQL/pgvector runtime path**: migrations are validated in CI, but ANN retrieval and
  `embedding_vec` are not exercised without a PostgreSQL service. Exact cosine on SQLite is tested.
- **Real OCR**: Tesseract is absent in the authoring environment, so only the honest failure path is
  executed. Run `pytest` with Tesseract installed to exercise image OCR.
- **Real LLM quality**: evaluations with the stub measure the harness. Use a configured provider and
  the labelled dataset to obtain meaningful metrics; results are stored per run.
- **Docker runtime**: the core Compose stack, S3 path, backup/restore and n8n/monitoring health were
  verified on this host after reboot. Long-running multi-host/HA container behavior and container
  upgrades are not covered. `test_s3_storage.py` covers the S3 client and sync helper with a fake
  client; it does not require Docker.
- **Email SMTP**: the sink backend is tested; Mailpit/SMTP is configuration-tested only.
- **Malware scanning and SSO**: not implemented (see security residual risks).

## 6. Adding tests

- Use the `org` fixture for an organization with all roles and precomputed headers.
- Build business data with `tests/factories.py` (services, not raw inserts) so invariants hold.
- Use `client` for HTTP contracts and services directly for rule/pipeline edge cases.
- For AI edge cases, use a small provider object implementing `complete()` and monkeypatch
  `build_llm_provider` in the module under test.
- Add a regression test for every bug fix; never remove or skip a failing test to make CI green.
