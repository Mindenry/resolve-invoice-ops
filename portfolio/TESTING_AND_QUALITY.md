# Testing and quality

## 1. Philosophy

Three rules shaped the test strategy:

1. **Test the money and the state machine directly.** Financial behaviour is deterministic and must be
   proven with real database assertions, not mocks.
2. **Test the workflow through the same door a user uses.** The end-to-end suite runs over HTTPS
   through nginx with a real browser-compatible client, real OCR and a real local model.
3. **Do not hide failures.** A failing case is recorded with its actual result; defects are fixed and
   the suite is rerun.

## 2. Test pyramid

| Layer | Count | Tool | What it covers |
| --- | --- | --- | --- |
| Backend unit/integration | **137 passed, 1 skipped** | pytest | auth, RBAC, tenant scoping, invoices, rules, documents, AI schema, approvals, execution idempotency, S3, analytics, metrics, claims |
| Frontend unit | **6 passed** | Vitest + Testing Library | formatters, UI primitives |
| Static checks | typecheck + lint | tsc, ESLint | type safety and style (0 errors) |
| Browser E2E | **10 passed** | Playwright | login, routes, pagination, permissions, error/retry, exceptions, case investigation, document review, approvals, Thai locale + dark theme |
| Acceptance | **26 passed** | custom Python runner | roles, financial edge cases, uploads, webhooks, approvals, tenancy, retries |
| Security | **16 passed** | custom runner | credentials, cookies, headers, rate limit, exposure, error leakage |
| Live workflow | **28 steps** | `verify_workflow_e2e.py` | vendor → PO → upload → OCR → extraction → exceptions → case → AI → proposal → approval → execution → audit → analytics |
| n8n contract | **9 passed** | custom runner | signed events, duplicates, invalid HMAC, Mailpit, real outbox |
| Responsive/console | 24 route/viewport checks | Playwright | 0 horizontal overflow, 0 app console errors |

The skipped backend test is PostgreSQL-specific and is exercised by the live database checks.

## 3. Financial edge-case matrix (live)

Full evidence with invoice/approval ids is in `docs/FINAL_ACCEPTANCE_RESULTS.md`.

| ID | Case | Expected | Result |
| --- | --- | --- | --- |
| F01 | Duplicate invoice (same vendor/number/amount) | DUPLICATE_INVOICE | PASS |
| F02 | Same number, different vendor | no duplicate | PASS |
| F03 | Amount differs from PO | AMOUNT_MISMATCH | PASS |
| F04 | VAT 12% implied vs 10% line | TAX_DISCREPANCY + line_tax_mismatch | PASS |
| F05 | Vendor differs from PO | VENDOR_MISMATCH | PASS |
| F06 | Missing PO | MISSING_PURCHASE_ORDER | PASS |
| F07 | Missing documents | MISSING_DOCUMENTS | PASS |
| F08 | Future invoice date | INVALID_INVOICE_DATE + failed check | PASS |
| F09 | Invalid tax information / vendor identity | VENDOR_MISMATCH blocks | PASS |
| F10 | Currency mismatch | po_currency_mismatch FAIL | PASS |
| F11 | Partial invoice (10% shortfall) | AMOUNT_MISMATCH MEDIUM, partial flag | PASS |
| F12 | Multiple lines, exact decimals | no arithmetic failure | PASS |
| F13 | Duplicate document upload | 409 duplicate_document + existing id | PASS |
| F14 | Low OCR confidence image | REQUIRES_REVIEW (0.52) | PASS |
| F15 | Invalid file format | 422 | PASS |
| F16 | Corrupted PDF | status FAILED with error | PASS |
| F17 | 26 MB upload | 422 | PASS |
| F18 | Duplicate inbound webhook | same event id, no duplicate | PASS |
| F19 | Invalid webhook HMAC | 400 | PASS |
| F20 | Concurrent approval | one 200, one 409 | PASS |
| F21 | Expired approval | 409 | PASS |
| F22 | Self-approval | 403 | PASS |
| F23 | Viewer executes resolution | 403 | PASS |
| F24 | Cross-tenant case read | 404 | PASS |
| F25 | Retry after processing failure | reprocess 200, status re-evaluated | PASS |
| R01 | Role matrix (6 roles + automation) | all boundaries enforced | PASS |

Decimal precision is checked through the API and direct SQL (`NUMERIC(18,4)`), e.g. invoice total
`1284.0000` and line sums.

## 4. The defect this process found

During the first acceptance run, two approvals submitted concurrently returned **200 and 200**.
The decision path mutated the ORM object and inserted a decision row without proving that the request
was still `PENDING`. Under READ COMMITTED both transactions could pass the check.

Fix: an atomic conditional update in `approvals/service.py`:

```python
claim = db.execute(
    update(ApprovalRequest)
    .where(ApprovalRequest.id == approval.id, ApprovalRequest.status == PENDING)
    .values(status=new_status, decided_at=now, decided_by_id=actor.id)
)
if claim.rowcount != 1:
    db.rollback()
    raise ConflictError("This approval request was already decided.")
```

Verification after the fix:

- live concurrent requests: `[409, 200]`;
- new regression test `test_second_decision_is_a_conflict` (409, one audit row);
- full backend suite: **137 passed, 1 skipped**;
- the 28-step workflow still passes end to end.

This is the most important quality story in the project: the test suite was adversarial enough to
find a real double-decision bug in the most safety-critical path.

## 5. End-to-end workflow (28 steps)

Run against `https://192.168.1.10:8180`:

1. login as org admin; 2. profile; 3. create vendor; 4. create PO; 5. upload document; 6. OCR/parse;
7. extract 10 fields; 8. correct a field; 9. approve extraction; 10. create invoice; 11. idempotent
invoice creation; 12. validate invoice; 13. generate exceptions; 14. read exceptions with invoice
linkage; 15. create case; 16. assign investigator; 17. run Ollama investigation; 18. validate
evidence; 19. generate suggestions; 20. propose resolution; 21. approval appears in approver queue;
22. approve; 23. execute; 24. audit trail; 25. case timeline; 26. analytics; 27. viewer write denial;
28. registration disabled / cross-tenant / self-approval denial and direct SQL assertions.

## 6. Browser and UX quality

- Playwright 10/10 against the production bundle over HTTPS, including a failing-API error state with
  retry, role-based read-only settings, Thai locale and dark theme persistence.
- Responsive checks at 1440×900, 834×1112 and 390×844 for eight routes: **0 horizontal overflow**.
- Console/page errors: **0** in the app after fixing a `Slot` children bug that broke the invoice
  detail page (found by the portfolio capture run). The fix is in the shared Button component and was
  re-verified by screenshots and the E2E suite.
- n8n and Grafana are captured from their real UIs; console messages there are external and recorded
  separately in `portfolio/qa/UX_REPORT.md`.

## 7. Security testing

16 live checks plus the workflow's negative tests. See `SECURITY_DESIGN.md` for the table. Notable
results: retired password 401, forged org header 403, login 429 after the limit, metrics not exposed
on the LAN port, management UIs refused on the LAN, error envelope leaks nothing.

## 8. Operations testing

- 13/13 Prometheus targets up; 20 rules loaded; controlled alert delivered to Mailpit; a real
  database-down alert also delivered and resolved.
- Backup produced and restored into an isolated database and bucket with count, vector, HNSW and
  SHA-256 verification.
- `docker compose restart` followed by data, workflow, dashboard, certificate and login verification.
- Daily backup task executed once through the scheduled path with exit code 0.

## 9. Reproduce

```powershell
cd apps/api; ..\..\.venv\Scripts\python.exe -m pytest
cd apps/web; npm run typecheck; npm run lint; npm run test -- --run; npm run build
cd apps/web; npx playwright test          # with RESOLVE_WEB_URL and RESOLVE_DEMO_PASSWORD

# Live suites (HTTPS, certificate trusted)
.\.venv\Scripts\python.exe scripts\final-acceptance.py
.\.venv\Scripts\python.exe scripts\verify-security.py
.\.venv\Scripts\python.exe scripts\verify-n8n-workflows.py
.\.venv\Scripts\python.exe apps\api\scripts\verify_workflow_e2e.py --base-url https://192.168.1.10:8180
```

Evidence files: `docs/FINAL_ACCEPTANCE_RESULTS.md`, `portfolio/qa/UX_REPORT.md`,
`docs/FINAL_PRODUCTION_HARDENING_REPORT.md`.
