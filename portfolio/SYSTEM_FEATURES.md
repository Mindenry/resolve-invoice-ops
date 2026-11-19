# System features

Feature status is based on the running deployment and the executed test suite. "Verified" means a
real test exercised it; "implemented" means the code path exists and is covered by tests but was not
part of the final live walkthrough.

## 1. Identity, roles and tenancy

- Email/password login with Argon2 hashing, JWT access tokens (30 min) and rotating refresh tokens in
  `Secure; HttpOnly; SameSite=Lax` cookies.
- Six roles (super admin, org admin, operations manager, investigator, approver, viewer) and 47
  permissions. Role changes are ranked to prevent privilege escalation.
- Organization-scoped queries in every service; forged or mismatched organization headers are
  rejected (403/404).
- Self-service registration disabled in production; invitations are admin-controlled.
- Password change signs out other sessions; reset tokens are single-use and hashed.
- Login rate limiting (20/min per client address) and a 600/min default API limit.
- **Verified:** role matrix, viewer write denial, investigator approval denial, cross-tenant 404,
  forged-header 403, self-approval 403.

## 2. Vendor and purchase-order management

- Vendor master with legal name, tax id, currency, payment terms, status and risk flags.
- Duplicate-vendor detection by tax id / normalized name.
- Purchase orders with line items, quantities, unit prices, tax rates, derived totals and statuses
  (draft → open → partially received → completed/cancelled/expired).
- Server-side totals; clients cannot dictate a line total.
- **Verified:** vendor/PO creation in the 28-step workflow and acceptance setup.

## 3. Document intelligence

- Upload validation: size limit (25 MB), MIME and magic-byte checks, ZIP guards, SHA-256 duplicate
  detection (409 `duplicate_document` with the existing id).
- Parsing for PDF (PyMuPDF), DOCX, XLSX, CSV and plain text; images via OCR.
- Tesseract OCR with Thai + English, page rendering at 200 DPI, per-page confidence.
- Deterministic invoice field extraction (number, dates, vendor, PO, subtotal, tax, total, tax id,
  currency, line items) with confidence and page anchors.
- Optional LLM fallback only when required fields are missing; the model must quote the source text.
- Arithmetic validation of extracted values; low confidence or missing fields set `REQUIRES_REVIEW`.
- Human correction of individual fields, extraction approval/rejection, document versioning and
  reprocessing.
- Chunking + embeddings into pgvector for knowledge search.
- **Verified:** Thai/English OCR, low-confidence image (0.52 → `REQUIRES_REVIEW`), corrupt PDF → FAILED,
  invalid format 422, 26 MB upload 422, duplicate 409, reprocess 200.

## 4. Exception engine

Ten versioned rules, each with a code, severity, configuration and historical versions:

| Rule | Detects |
| --- | --- |
| DUP_INVOICE_001 | duplicate invoice number (exact/fuzzy, same vendor, amount/currency aware) |
| AMOUNT_MISMATCH_001 | invoice total vs PO total beyond absolute/percent tolerance; partial invoices |
| VENDOR_MISMATCH_001 | invoice vendor vs PO vendor, blocked vendors, extracted-name mismatch |
| MISSING_PO_001 | invoice without a PO when policy requires one |
| MISSING_DOCS_001 | missing invoice/contract/PO documents by requirement and threshold |
| TAX_DISCREPANCY_001 | subtotal + tax ≠ total; implied VAT rate outside allowed rates; line-tax mismatch |
| INVALID_DATE_001 | future or implausibly old invoice dates |
| DUP_VENDOR_001 | vendors sharing tax id or normalized name |
| EXTRACTION_ANOMALY_001 | implausible extracted values/confidence |
| INTEGRATION_FAILURE_001 | repeated inbound/outbound integration failures |

Each exception stores a stable dedupe fingerprint, severity, evidence and a link to the invoice/entity.
Exceptions can be triaged, ignored or attached to cases.

**Verified:** duplicate, different-vendor same-number, amount mismatch, VAT error, vendor mismatch,
missing PO, missing documents, future date, currency mismatch, partial invoice, multi-line invoice.

## 5. Case management

- Case numbers, titles, descriptions, priority/severity, tags, SLA hours and due dates.
- Automatic grouping of invoice exceptions into a case; manual creation and merge.
- Assignment history, transitions with validation, escalation, resolve/close/reopen.
- Comments (internal/external), activity timeline and full case audit.
- SLA posture: breached, due within 24h, average resolution time.
- **Verified:** create, assign, escalate, resolve, timeline (9 entries), audit (9 rows).

## 6. AI investigation

- Queued investigation with status polling (`QUEUED → RUNNING → COMPLETED/NEEDS_REVIEW/FAILED`).
- Hybrid retrieval: keyword + cosine similarity over chunk embeddings, plus similar resolved cases.
- Strict JSON output: summary, root cause, hypotheses, missing information, limitations, required
  actions, suggested resolutions and citations.
- Every citation validated against a real organization-scoped document/page/chunk/case.
- Token/cost/latency and prompt version persisted.
- Human review flag when confidence or evidence is insufficient.
- **Verified:** `qwen2.5:7b-instruct`, 3/4 validated evidence items, 3,056 tokens, 12.4 s latency,
  suggestions produced and accepted as proposals.

## 7. Resolutions and approvals

- Allow-listed action registry with typed parameters and risk levels.
- Deterministic policy decides whether approval is required.
- Approval object: requester, assigned approver, risk, expiry (48h), decision and note.
- Self-approval blocked; approval and execution are separate permissions.
- Execution is idempotent (execution rows + idempotency key), records success/failure and can retry.
- **Verified:** proposal → approval queue → decision → execution (Mailpit) → audit; concurrent
  approval yields exactly one success; expired approval 409; self-approval 403; viewer execute 403.

## 8. Notifications, automation and integrations

- In-app notifications with preferences; email via Mailpit/SMTP; notification delivery worker.
- Integration registry: REST, webhook, n8n, CSV/Excel, S3, email; encrypted credentials; connection
  tests; signed inbound webhooks with idempotency; outbound event fan-out with retries.
- Five n8n workflows: new exception/case, critical escalation, daily summary, document failure,
  health monitor. HMAC + Redis claim store prevents duplicate processing.
- Automation account is read-only; n8n cannot approve or execute.
- **Verified:** 9/9 n8n contract checks, real outbox deliveries (case.created, case.escalated,
  document.failed), duplicate suppression, invalid HMAC rejection, scheduled runs.

## 9. Analytics and audit

- Command center KPIs: total/open/critical/high-priority cases, pending approvals, resolved today,
  AI-assisted resolutions, average resolution hours.
- Trends (exceptions/cases/resolutions), distributions, SLA, workload, AI usage/cost, processing
  pipeline — all from SQL, no mock data.
- Append-only audit log with actor, request id, before/after snapshots, filters and CSV export.
- **Verified:** dashboard metrics and analytics endpoint; audit rows asserted directly in PostgreSQL.

## 10. AI evaluation

- Datasets, real runs, per-sample results, accuracy/precision/recall/F1, root-cause, evidence,
  citation, recommendation and groundedness metrics.
- Deterministic stub provider clearly labelled for tests.
- Implemented and unit-tested; not part of the final live demo.

## 11. Operations

- Health (`/health`, `/health/live`, `/health/ready`), Prometheus `/metrics`, structured logs with
  request/correlation ids.
- Four Grafana dashboards, 20 alert rules, Alertmanager → Mailpit.
- Docker-first start/stop/restart/status/health scripts, watchdog task, daily backup task and a
  verified restore procedure.
