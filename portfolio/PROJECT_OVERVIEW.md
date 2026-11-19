# Project overview

## 1. Problem statement

Accounts-payable teams receive invoices as PDFs, scans and spreadsheets from hundreds of vendors.
Before an invoice can be paid it must be matched against a purchase order, tax rules, vendor master
data and supporting documents. Failures are not rare edge cases; they are the normal workload:

- the same invoice arrives twice, from two channels;
- the amount or currency does not match the PO;
- VAT is calculated at the wrong rate;
- the vendor on the invoice is not the vendor on the PO;
- a required contract or delivery note is missing;
- OCR misreads a date or a total.

The detection step is comparatively easy. The expensive part is the **investigation**: gathering the
contract, the PO, previous invoices and similar cases, deciding what happened, deciding who may
approve the fix, proving the decision later, and making sure the same invoice is not paid twice.

Most tools stop at "exception created". RESOLVE models the whole path from detection to a signed-off,
audited resolution.

## 2. Users and jobs to be done

| Role | Job |
| --- | --- |
| Organization Admin | Configure the workspace, users, integrations and AI, and answer auditors |
| Operations Manager (Finance Manager) | Own the queue, assign work, escalate, watch SLA and analytics |
| Investigator (Finance Operator) | Triage, correct extracted fields, run investigations, propose resolutions |
| Approver | Decide high-risk resolutions; never the requester |
| Viewer | Read-only access for audit, finance control or leadership |
| Super Admin | Platform-level administration, separate from tenant administration |
| Automation account | Read-only machine identity used by n8n for summaries and health checks |

## 3. Business requirements

1. **Detect** financial exceptions deterministically, with decimal precision and explainable rules.
2. **Extract** structured fields from real documents (PDF, DOCX, XLSX, CSV, images) with OCR.
3. **Investigate** with AI that can only use evidence from the organization's own records.
4. **Recommend** a resolution, but never execute it.
5. **Require** a human approval that the requester cannot give themselves.
6. **Execute** idempotently and record every action in an immutable audit trail.
7. **Isolate** tenants and enforce role permissions at the service layer.
8. **Automate** notifications and escalations without letting automation approve money.
9. **Operate** with HTTPS, monitoring, alerts, backup and restore.
10. **Demonstrate** honestly: every claim must be reproducible on the running system.

## 4. What was built

A full-stack platform with a FastAPI backend (50 tables, 47 permissions, 10 exception rules), a React
frontend with 20+ routes, a Celery worker/beat pipeline, PostgreSQL + pgvector, S3-compatible object
storage, Tesseract OCR, local Ollama models, five n8n workflows, and a Prometheus/Grafana stack.

The differentiating design choices:

- **Deterministic core, probabilistic periphery.** Money math, state transitions, permissions and
  policy are ordinary Python. The LLM explains and recommends; it never computes a payable amount or
  changes a state.
- **Evidence or nothing.** Every AI citation is re-checked against a real document/page/chunk/case in
  the same organization. Invalid citations are flagged and the investigation can end in
  `NEEDS_REVIEW` instead of inventing confidence.
- **Approval as a first-class object.** A resolution requiring approval is created together with an
  approval request; execution is blocked until an authorized, non-requester decision exists.
- **Idempotency everywhere it matters.** Invoice creation per document, resolution execution,
  webhook delivery and AI-consumer claims all have stable keys.
- **Operable by default.** Health endpoints, Prometheus metrics, 20 alert rules, four dashboards,
  verified backups and a scheduled restore-tested procedure.

## 5. Verified outcome (not aspirational)

| Claim | Evidence |
| --- | --- |
| Full workflow works end to end over HTTPS | 28-step script: vendor → PO → upload → OCR → extraction → exceptions → case → Ollama investigation → proposal → approval → execution → audit → analytics |
| Financial controls work | 26-case acceptance suite covering duplicates, tolerance, VAT, date, currency, partial invoices, concurrency and more |
| AI is grounded | Investigation with 3–4 validated evidence items, `qwen2.5:7b-instruct`, `bge-m3` embeddings, HNSW retrieval |
| Security holds | 16/16 live checks plus cross-tenant, self-approval and registration checks |
| Automation is real | Five active n8n workflows, HMAC, duplicate suppression, Mailpit delivery |
| Operations are real | 13/13 Prometheus targets, 20 rules, alert delivered, backup restored with SHA-256 match |
| Quality is measured | 137 backend tests, 10 Playwright E2E, 6 Vitest, 26 acceptance cases |

A real defect was found by this process and fixed: two concurrent approvals could both succeed. The
decision is now an atomic compare-and-set, and the case is part of the regression suite
(`test_second_decision_is_a_conflict`).

## 6. Scope boundaries

**In scope:** invoice exceptions, document intelligence, AI investigation, case management,
resolution/approval, audit, analytics, integrations, AI evaluation.

**Deliberately out of scope:** general ledger, payment execution to banks, procurement authoring,
HR, payroll, and any feature that would require real money movement. RESOLVE stops at a recorded,
approved resolution and a notification/action that is safe and auditable.

## 7. Deployment in one line

Docker Compose on a Windows workstation, HTTPS on port 8180 with a local CA, all internal services
loopback-only, native Windows services kept as a localhost rollback. See
[DEPLOYMENT_OVERVIEW.md](DEPLOYMENT_OVERVIEW.md).

## 8. Why this project is portfolio-worthy

It is not a CRUD demo. It demonstrates:

- system design under real constraints (tenancy, approvals, idempotency, AI safety);
- data modelling with money, versions, audit and vectors;
- production operations (TLS, monitoring, alerts, backup/restore, runbooks);
- testing discipline that found and fixed a concurrency bug;
- honest engineering communication, including what does **not** work yet.

The limitations are documented in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) — including the ones
that only external resources (a Mac, a domain, a real SMTP relay) could close.
