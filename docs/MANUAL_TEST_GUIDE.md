# Manual test guide

A practical walkthrough for the running Docker deployment. It takes about 10 minutes for the quick
tour and 40–60 minutes for the full hands-on flow.

Use only synthetic data. Do not upload real invoices.

## 0. Before you start

```powershell
.\scripts\start-resolve.ps1
.\scripts\health-check.ps1 -Deep
```

- URL: `https://localhost:8180` (or the LAN address printed by the script)
- Credentials: `var/secrets/demo-credentials.txt` (open locally; never paste into chat)
- Test files: `var/testdata/INV-DEMO-1001.pdf`, `INV-DEMO-1001.png`, `corrupt-invoice.pdf`
- Generate them again if missing: `python scripts/make-test-files.py`

Accounts: `admin@`, `manager@`, `investigator@`, `approver@`, `viewer@example.com`, plus
`superadmin@example.com`. All use the password file above.

Accept a self-signed/local CA warning only if you trust `var/certs/rootCA.pem`; otherwise install the
CA first (`docs/HTTPS_LAN_SETUP.md`).

---

## 1. Quick tour (10 minutes, existing demo data)

- [ ] **Login** as `admin@example.com`. The Command Center should show non-zero exceptions, cases and
      approvals.
- [ ] **Exception Queue** → open any row. Check severity, rule, evidence and the linked invoice.
- [ ] **Cases** → open a HIGH priority case (for example `CASE-2026-0125`). Read the overview, SLA and
      linked records.
- [ ] **AI Investigation** tab → confirm summary, root cause, **validated evidence** and suggested
      resolutions. `Requires human review` may be present; that is intentional.
- [ ] **Approval Center** → you should see pending requests. As admin you cannot approve your own;
      log out and use `approver@example.com` to decide one.
- [ ] **Audit Logs** → filter by the case id. You should see the full sequence of actions.
- [ ] **Analytics** → trends, SLA posture, workload and AI usage should reflect real data.
- [ ] **Mailpit** at `http://127.0.0.1:8125` → check the approval/execution emails.

If everything above works, the read path, AI display, approvals and audit are healthy.

---

## 2. Full hands-on flow (40–60 minutes)

### 2.1 Create master data

- [ ] **Vendors** → create:
  - legal name: `Bangkok Office Supply Co., Ltd.`
  - vendor number: `V-DEMO-1001`
  - tax id: `TH0105551001`
  - currency: `THB` (or USD; keep it consistent with the invoice)
- [ ] **Purchase Orders** → create for that vendor:
  - PO number `PO-DEMO-1001`
  - issue date today, status `OPEN`
  - one item: qty `10`, unit price `420.00`, tax `7` (total around 4,494.00)

### 2.2 Upload and process a document

- [ ] **Documents** → **Upload document** → choose `var/testdata/INV-DEMO-1001.pdf`,
      type `INVOICE`.
- [ ] Wait for processing. Status should move through `QUEUED → PROCESSING → EXTRACTED` or
      `REQUIRES_REVIEW`. OCR takes a few seconds; a scanned image can take longer.
- [ ] Open the document. You should see extracted fields, confidence and the source page text.
- [ ] Correct one field (for example the invoice number or total), then **Review extraction → Approve**.

### 2.3 Invoice and exceptions

- [ ] On the document page, choose **Create invoice**. The invoice should link to the document.
- [ ] Open the invoice and press **Run validation**.
- [ ] Because the invoice has no matching PO or the totals differ, you should see exceptions such as
      `MISSING_PURCHASE_ORDER`, `MISSING_DOCUMENTS` or `AMOUNT_MISMATCH`.
- [ ] Return to the PO and confirm the invoice total comparison makes sense with the values you
      entered.

### 2.4 Case and investigation

- [ ] **Cases** → open the case created by the exception engine (newest at the top).
- [ ] **Assign** it to `investigator@example.com` (or yourself).
- [ ] Open the **AI Investigation** tab and press **Run investigation**. Expect 10–30 seconds with the
      local 7B model.
- [ ] Confirm the run completes with evidence. Every evidence row should show `validated`. If a
      citation is invalid it will be visibly flagged, not hidden.

### 2.5 Resolution and approval

- [ ] Accept a suggestion (**Accept as proposal**) or use the resolutions area to propose an action.
- [ ] Press **Request approval** and choose the approver.
- [ ] Log out. Log in as `approver@example.com`.
- [ ] **Approval Center** → approve the request (add a comment).
- [ ] Log back in as admin → open the case → **Execute** the resolution.
- [ ] Check **Mailpit** for the execution email and **Audit Logs** for the decision and execution.

### 2.6 Verify the evidence trail

- [ ] **Audit Logs** → filter by case id: expect creation, assignment, investigation, proposal,
      approval and execution entries.
- [ ] Case **Timeline** → expect the same sequence in human-readable form.
- [ ] **Analytics** → the resolution count / SLA figures should move.

---

## 3. Role and permission checks

- [ ] Login as `viewer@example.com`: pages load, but create/approve/execute actions are absent or
      rejected. Opening a settings page should be read-only.
- [ ] Login as `investigator@example.com`: can upload, triage and run investigations, but cannot
      approve a request.
- [ ] Login as `approver@example.com`: can approve, but cannot create vendors or POs.
- [ ] Login as `manager@example.com`: can create vendors/POs and assign cases.
- [ ] Login as `superadmin@example.com`: full access, including audit and settings.
- [ ] As admin, try to approve a request you created: it must be blocked (403 / UI hidden).

---

## 4. Negative tests (10 minutes)

- [ ] **Corrupt document:** upload `var/testdata/corrupt-invoice.pdf`. Status must become `FAILED`
      with an error, not stuck in processing.
- [ ] **Invalid file type:** rename any `.exe` to `.pdf` and upload. Expect a validation error (4xx).
- [ ] **Duplicate upload:** upload `INV-DEMO-1001.pdf` a second time. Expect
      `409 duplicate_document` and the existing document id.
- [ ] **Oversized file:** upload a file larger than 25 MB. Expect a 4xx rejection.
- [ ] **Low confidence:** upload `INV-DEMO-1001.png` (the scan-like version). It should end in
      `REQUIRES_REVIEW` if confidence is low, with fields still visible for correction.
- [ ] **Reprocess:** open a FAILED document and use Reprocess after replacing the file/source. The
      status should be re-evaluated.

Concurrency, expired approval, forged webhooks and cross-tenant access are covered by the automated
suite; they are hard to reproduce reliably by hand.

---

## 5. Automation and operations checks

- [ ] **n8n** `http://127.0.0.1:5679` → five RESOLVE workflows are active. During the flow above,
      check **Executions** for a new successful run.
- [ ] **Mailpit** `http://127.0.0.1:8125` → notifications from RESOLVE and n8n.
- [ ] **Grafana** `http://127.0.0.1:3101` → System Overview shows 13 targets, request rate and
      business panels. Business Operations shows your new case/invoice.
- [ ] **Prometheus** `http://127.0.0.1:9190/api/v1/targets` → all targets `up`.
- [ ] **Health** `https://localhost:8180/health/ready` → `ready` with database, storage and Redis ok.

---

## 6. Automated regression (optional)

```powershell
# Backend
cd apps/api
python -m pytest

# Frontend
cd apps/web
npm run typecheck
npm run lint
npm run test -- --run
npm run build

# Browser E2E (API password comes from the environment)
$env:RESOLVE_WEB_URL = "https://localhost:8180"
$env:RESOLVE_DEMO_PASSWORD = ((Get-Content ..\..\var\secrets\demo-credentials.txt |
  Where-Object { $_ -like "admin@example.com=*" }) -replace '^[^=]*=','')
npx playwright test

# Live acceptance and security suites
cd ../..
$env:RESOLVE_WEB_URL = "https://localhost:8180"
.\.venv\Scripts\python.exe scripts\final-acceptance.py
.\.venv\Scripts\python.exe scripts\verify-security.py
```

The acceptance suite creates a batch of synthetic records; that is expected.

---

## 7. What counts as a pass

- Every checklist item above behaves as described.
- No page crashes and no red console errors in the browser devtools.
- Exceptions are explainable (rule + values), not just "something went wrong".
- The approval cannot be bypassed by the requester.
- Audit entries exist for every state change you performed.
- Emails land in Mailpit; n8n shows a successful execution.
- After `.\scripts\restart-resolve.ps1`, the data you created is still there.

If something fails, note the case/invoice id, the page and the time, then check
`docker compose logs api web worker` before changing anything.
