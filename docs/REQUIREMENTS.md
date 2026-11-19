# Requirements traceability

This matrix maps the product requirements to the implementation and the evidence that it works.
Legend: **✅ implemented and tested**, **⚙️ implemented, environment-dependent**, **📋 documented
limitation**.

## A. Authentication & organization

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| Login / logout / refresh rotation | `modules/auth/service.py`, httpOnly refresh cookie | `tests/test_auth.py` rotation, reuse detection, logout |
| Password hashing | Argon2id (`core/security.py`) | auth tests, login failures |
| Password reset | hashed single-use tokens, 30 min expiry, session revocation | `test_password_reset_flow` |
| Session management | token families, list/revoke endpoints | auth tests |
| Roles & permissions | 6 roles, 47 permissions seeded from `core/permissions.py` | `test_role_matrix_reflects_permissions` |
| Backend enforcement | `dependencies/auth.py`, `require_permission` | viewer/investigator 403 tests |
| Organization isolation | every repository query filters `org_id`; membership checks | `test_cross_organization_header_is_rejected`, foreign resource 404 |
| Last-admin protection | membership service guard | `test_last_admin_cannot_be_deactivated` |

## B. Command center

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| 11 KPIs | `modules/analytics/service.py` | `test_command_center_uses_real_data` |
| Time range / filters | `days`, exception type, priority | API + UI controls |
| Trends & distributions | daily buckets computed from rows | dashboard screenshot |
| Real data only | SQL aggregates, no constants | analytics test |
| Empty states | reusable `EmptyState` | UI review |

## C. Document management

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| PDF/DOCX/XLSX/CSV/TXT/PNG/JPG | `processing.py` | document tests, demo documents |
| Validation, MIME/magic, size, secure names | `validate_upload` | unsupported file / MIME mismatch tests |
| Storage abstraction | local + S3-compatible (`services/storage.py`; SeaweedFS in Compose) | Compose S3 + upload/download/backup/restore + `test_s3_storage.py` |
| SHA-256 duplicate detection | unique `(org_id, sha256)` + 409 | `test_duplicate_upload_rejected` |
| Versioning | `document_versions` + versions endpoint | `test_document_versioning` |
| Real asynchronous processing | Celery or local executor, persisted job status | job rows, dashboard pipeline |
| OCR with honest failure | Tesseract provider; `ocr_unavailable` | `test_unsupported_image_without_ocr_fails_honestly` |
| Processing states | UPLOADED→QUEUED→PROCESSING→EXTRACTED→INDEXED / FAILED / REQUIRES_REVIEW | UI stepper + DB |

## D. Document intelligence & review

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| Invoice fields | deterministic parser + optional LLM | upload/extract test asserts fields, page, source, confidence |
| Evidence per field | page number, source text, bbox (OCR) | field rows |
| Confidence heuristics | method-aware score, OCR attenuation | low-confidence review warning |
| Human review | edit, approve, reject, reprocess | review tests |
| Audit of corrections | `document.field_corrected` audit | audit page |
| No calibrated-probability claims | UI labels “heuristic” | prompts + UI |

## E. Vendors

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| CRUD, risk flags, terms | vendors module | vendor tests + UI |
| Deterministic duplicates | tax ID, normalized name, fuzzy ≥ threshold | `test_duplicate_vendor_detection` |
| AI suggestions never auto-merge | merge is explicit and permission-gated | UI merge warning + audit |
| Merge authorisation | `vendor:merge`, audited | merge endpoint + audit |

## F. Purchase orders

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| CRUD + line items + totals | Decimal recomputation | PO tests/data |
| Lifecycle statuses | validated transitions | PO service + UI |
| Expiry handling | `refresh_expired` | seeded expired PO |
| Invoice matching data | candidate scoring by vendor/currency/date/amount | invoice detail candidates |

## G. Invoices

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| CRUD, associations, statuses | invoices module | creation from document test |
| Deterministic validation | totals, lines, dates, vendor, PO, duplicates | validation checks in UI + tests |
| Matching | explicit or auto-match within tolerance | match endpoints |
| Invalid transition prevention | transition map | invoice transition tests (implicit in validation tests) |
| No money movement | approval/export only | architecture docs |

## H. Exception engine

| Rule | Implementation | Test |
| --- | --- | --- |
| Duplicate invoice | normalized number + vendor + amount + date window + document hash | exact, same-number-different-amount, idempotency |
| Amount mismatch | Decimal absolute/percentage tolerance, partial invoices | beyond + within tolerance |
| Vendor mismatch | tax ID, linked vendor, PO vendor, extracted name | vendor mismatch test |
| Missing PO | policy and vendor exemptions; value threshold | policy on/off test |
| Missing documents | configurable requirements incl. contract threshold | seeded cases |
| Tax discrepancy | arithmetic + implied rate allow-list + line tax | tax test |
| Invalid date | future, old, due-before-invoice, PO/contract expiry | future date test |
| Duplicate vendor | deterministic tax/normalized name | duplicate vendor test |
| Extraction anomaly | failed doc, low OCR, missing/conflicting fields | failed document test |
| Integration failure | repeated webhook/workflow/job failures | integration rule test |
| Dedupe | unique `(org, fingerprint)`, counters, reopen | idempotency test |
| Versioned configuration | rule + version tables; update creates version | `test_rule_update_creates_new_version` |

## I. Cases

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| Case number, SLA, priority | sequence per org/year, SLA by priority | case creation test |
| Validated state machine | `ALLOWED_TRANSITIONS` | invalid transition/resolution summary tests |
| Assignment history | `case_assignments` | assign test |
| Comments & timeline | comments + activities | comment test |
| Escalation / merge | audited, activity logged | escalation + merge test |
| Search/filter/pagination/bulk assign | list service + bulk endpoint | filters test |

## J. AI investigation

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| Structured pipeline | context builder → prompt → schema validation → evidence validation → persistence | investigation E2E tests |
| Only authorised data | all context queries filter org; retrieval filters document status | cross-org tests; retrieval service |
| Evidence schema + validation | document/page/chunk/exception/PO/vendor checks | hallucinated evidence tests |
| Guardrails | bounded retries, timeouts, JSON repair, prompt-injection rules, no tools | retry test, prompts |
| Usage accounting | tokens, latency, model, prompt version, cost | investigation record |
| Failure handling | QUEUED→RUNNING→COMPLETED/FAILED with reason | AI unavailable test |
| Explicit insufficiency | root cause withheld if no evidence validates | hallucination test |

## K. Resolutions & approvals

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| Action registry | 11 allow-listed actions with typed parameters | action catalog test |
| Policy engine | risk/threshold/external/financial rules | resolution tests |
| Approval lifecycle | PENDING/APPROVED/REJECTED/EXPIRED/CANCELLED | approve/reject tests |
| Self-approval block | requester cannot decide unless policy allows | `test_self_approval_is_denied` |
| Idempotent execution | unique idempotency key + COMPLETED short-circuit | execution test asserts one attempt |
| Failure persistence | `resolution_executions` attempt records | executor failure path |
| Audit | proposed/requested/decided/executed/failed | audit test |

## L. Automation & notifications

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| Integration registry | REST/webhook/n8n/CSV/Excel/S3/email | integration tests + UI |
| Encrypted credentials | Fernet, never returned | credential encryption test |
| Connection tests | real HTTP/health checks | UI + open integration test coverage |
| Signed webhooks | HMAC-SHA256, idempotency, async processing | valid/invalid signature tests |
| Delivery failure visibility | webhook rows + integration degradation | `test_webhook_delivery_failure_is_persisted` |
| Workflow honesty | failed execution when n8n absent | `test_workflow_without_n8n_fails_honestly` |
| Notifications | in-app, preferences, email sink/SMTP | notifications UI + tests |
| Background jobs | persisted status, retries, manual retry | job list + retry endpoint |

## M. Audit, security, quality

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| Immutable audit | no write/update endpoints; append-only rows | `test_audit_trail_and_export` (405) |
| Structured logs & request IDs | structlog + middleware | middleware code |
| Health checks | `/health`, `/health/live`, `/health/ready` | deployment docs |
| Rate limiting | slowapi, stricter auth limits | settings + main |
| File/permission security | auth on download, org checks | download auth test |
| Secrets | env-only, masked config, encrypted credentials | `.env.example`, settings validation |
| CI | backend, frontend, infrastructure workflows | `.github/workflows` |
