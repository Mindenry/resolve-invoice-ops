# Demo script (5–10 minutes)

## Before the interview

1. Start the stack: `.\scripts\start-resolve.ps1` and `.\scripts\health-check.ps1 -Deep`.
2. Open Chrome at `https://192.168.1.107:8180` and confirm the certificate is valid.
3. Have credentials ready out-of-band (never in slides): admin, approver, viewer, from
   `var/secrets/demo-credentials.txt`.
4. Open a second tab at `http://127.0.0.1:3101` (Grafana) and a third at `http://127.0.0.1:5679`
   (n8n) if you plan to show operations.
5. Optional: Mailpit at `http://127.0.0.1:8125` to show the execution email.

If the demo data has been reset, the workflow still works: create a vendor/PO/invoice live (steps 3–5
take about two minutes with the seeded vendor).

## Timeline

### 0:00 — Frame the problem (45 s)

> "Invoice exceptions are not a detection problem, they are an investigation and proof problem. A
> duplicate or a VAT error is easy to flag. The expensive part is gathering evidence, deciding who may
> approve, and proving later that the decision was legitimate. RESOLVE models that whole path."

Show the Command Center (`/`). Point at the KPIs: total exceptions, open cases, critical, pending
approvals, average resolution time, AI usage. Everything is live SQL — no mock charts.

### 0:45 — Document intake and OCR (60 s)

Go to **Documents** → open a processed invoice (e.g. `s3-check.pdf` or the E2E invoice document).

- Show the page image/text, the extracted fields with per-field confidence, and the source quote.
- Say: "Parsing is deterministic first; the LLM is only a fallback when required fields are missing,
  and it must quote the page. Low confidence or arithmetic issues set `REQUIRES_REVIEW`."

### 1:45 — Exception detection (60 s)

Go to **Exception Queue**.

- Filter by severity or type; open one.
- Show the rule code, evidence, invoice link and the case it belongs to.
- Say: "Ten versioned rules. Money is `Decimal` and `NUMERIC(18,4)`, tested to the cent. The queue is
  explainable: every exception names the rule, the values and the tolerance."

### 2:45 — Case workspace and AI investigation (2 min)

Open **Cases** → the case `E2E price variance J81AR6` (or any HIGH priority case).

- Overview: SLA, assignee, exceptions, linked invoice/PO.
- Click **AI Investigation**.
- Walk through: summary, root cause, **three validated evidence items** (invoice, contract chunk,
  prior case), hypotheses, limitations, required actions, suggested resolutions.
- Say: "This is `qwen2.5:7b-instruct` running locally through Ollama. Every citation is validated
  against a real organization-scoped row; fabricated ids are rejected. The model does not have tools
  and cannot approve or execute."

If you want to run it live: click **Run investigation** and wait ~10–15 s. Fallback: the stored run is
already there.

### 4:45 — Resolution and human approval (90 s)

- Click **Accept as proposal** on a suggestion (or open **Resolutions**).
- Show the proposal, risk level and that approval is required.
- Switch to the **Approver** account (or the Approval Center with approver credentials).
- Show that the requester cannot approve their own request (403) — this is a policy, not a UI trick.
- Approve as the approver, then execute.
- Open **Mailpit** and show the confirmation email produced by the execution.
- Say: "Approval and execution are separate permissions. Execution is idempotent; a retry cannot send
  twice. A concurrency test proved only one decision can win — I found and fixed that race."

### 6:15 — Audit and analytics (45 s)

- **Audit Logs**: filter the case; show actor, action, before/after, request id.
- **Analytics**: trends, SLA posture, workload, AI usage.
- Say: "The audit trail is append-only and is the artefact an auditor actually asks for."

### 7:00 — Operations (optional, 1–2 min)

- Grafana → **System Overview** and **Business Operations**: 13 targets, real metrics.
- n8n → workflows A–E: show one execution and explain HMAC + idempotency.
- Mention the backup task, the restore verification and the 20 alert rules.

### 8:00 — Close (30 s)

> "The goal was a system that is correct where money is involved, honest where AI is involved, and
> operable in reality. Everything you saw ran on this machine: HTTPS, Docker, local AI, OCR,
> monitoring, backup and restore. Known gaps are documented — for example, no physical Mac test and no
> external SMTP — rather than hidden."

## Strong lines to use

- "The AI cannot approve money. That is an architectural decision, not a prompt."
- "A citation that does not resolve to a real row is not evidence; it is a bug."
- "The concurrency test found a double-approval race. I fixed it with an atomic claim and added a
  regression test."
- "I would rather show you a documented limitation than a demo that lies."

## Fallbacks

| Problem | Fallback |
| --- | --- |
| Ollama slow/unavailable | use the stored completed investigation and say so |
| Docker not running | start with the script; native rollback is on 8090 |
| Certificate warning | check the CA trust; never click through in a demo |
| Mailpit empty | show the execution result JSON and the audit row |
| No pending approval | create a resolution live as admin, approve as approver |

## Do not do

- Do not show `.env`, `var/secrets`, browser devtools with tokens, or server logs containing headers.
- Do not claim macOS/Safari was tested.
- Do not claim real SMTP or public DNS.
- Do not claim HA or a production host.
