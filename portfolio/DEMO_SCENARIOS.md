# Demo scenarios

Three scenarios, each with setup, expected observations and the engineering point it demonstrates.

---

## Scenario A — "The invoice that does not match the PO"

**Setup:** a vendor, an open PO for USD 1,000, and an invoice for USD 1,284 linked to that PO.

**Walkthrough**

1. Open the invoice detail. It shows subtotal 1,200, tax 84, total 1,284, plus a warning that the PO
   total differs.
2. Open the Exception Queue and find `AMOUNT_MISMATCH` with the tolerance and the delta.
3. Open the case and its AI investigation: the summary, the contract chunk and a prior similar case
   are cited as validated evidence.
4. Accept a proposal, request approval, switch to the approver, approve, execute.
5. Show the audit rows and the confirmation email.

**Expected observations**

- The exception is explainable: rule, values, tolerance, percentage difference.
- The AI recommendation follows the evidence; it does not invent a payment instruction.
- Execution requires a non-requester approval and is idempotent.

**Engineering point:** deterministic detection → grounded explanation → human decision → auditable
action.

---

## Scenario B — "Duplicate, but a different vendor"

**Setup:** invoice `INV-100` from vendor A, then the same number from vendor B, same amount.

**Walkthrough**

1. Create both invoices and validate each.
2. Vendor A's second invoice raises `DUPLICATE_INVOICE` with an exact match.
3. Vendor B's invoice with the same number does **not** raise a duplicate; it raises its own missing
   PO/document exceptions.

**Expected observations**

- Duplicate detection is vendor-aware; the same number from another vendor is a different liability.
- The dedupe fingerprint and the evidence list make the decision reviewable.

**Engineering point:** business identity matters more than string equality.

---

## Scenario C — "The race in the approval path"

**Setup:** a pending approval for a high-risk resolution.

**Walkthrough**

1. Explain that two approvers (or a double-click) could submit at the same time.
2. Show the regression test and the live acceptance result: one request returns 200, the other 409.
3. Show the audit log: exactly one `approval.decided` row.

**Expected observations**

- The decision is an atomic claim (`UPDATE ... WHERE status='PENDING'`), not a read-check-write.
- The loser writes no decision, no execution and no audit event.

**Engineering point:** correctness under concurrency, found by an adversarial test rather than
assumed.

---

## Scenario D (optional) — "The document that cannot be read"

**Setup:** a corrupt PDF or a low-quality scan.

**Walkthrough**

1. Upload the corrupt file: the document enters `FAILED` with a redacted error.
2. The failure event flows through the outbox to n8n, which emails the document owner.
3. Upload a low-quality scan: OCR confidence 0.52 marks the extraction `REQUIRES_REVIEW`.
4. Use Reprocess after fixing the source file; the status is re-evaluated.

**Expected observations**

- Failures are first-class, visible and retryable; they are not swallowed.
- The system never pretends a low-confidence extraction is reliable.

**Engineering point:** graceful degradation and honest confidence.

---

## Talking points that apply to every scenario

- **Where is the money calculated?** In Python with `Decimal`, persisted as `NUMERIC(18,4)`, never by
  the model.
- **What stops the AI from acting?** No tools, no write credentials, and proposals are separate
  records that require human approval.
- **What happens if n8n is down?** The outbox retries, the delivery is recorded as failed, and a
  Prometheus alert fires. Financial state is unaffected.
- **What happens if the API restarts?** nginx re-resolves the container, sessions continue with
  refresh rotation, and queued work resumes from Redis.
- **How do you know the backup works?** It is restored into a new database and bucket and verified by
  counts, vector dimension, HNSW and SHA-256.
