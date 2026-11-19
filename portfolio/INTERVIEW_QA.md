# Interview Q&A

Answers are based on what this system actually does. Where something is not implemented, the answer
says so.

---

**1. What problem does RESOLVE solve, in one sentence?**
It turns a failed invoice control into a complete, evidence-backed, human-approved and auditable
resolution, instead of stopping at "exception created".

**2. Walk me through the architecture.**
React SPA → nginx (TLS, single LAN port) → FastAPI modular monolith → PostgreSQL with pgvector, Redis
and S3-compatible storage, with Celery worker/beat for OCR, AI and execution. n8n consumes signed
domain events; Prometheus/Alertmanager/Grafana observe everything. The backend is a monolith on
purpose: money and approvals need one transaction boundary.

**3. Why a monolith instead of microservices?**
One team, one deployment, and strong transactional guarantees for invoices, approvals and audit. A
distributed design would add failure modes (partial approvals, duplicate execution, event ordering)
without a scaling need. The service boundaries inside the monolith are explicit, so extraction later
is possible.

**4. Why PostgreSQL and pgvector instead of a separate vector database?**
Tenancy, joins, backups and transactions stay in one system. At this scale HNSW inside PostgreSQL is
fast, and vector rows participate in the same backup/restore and audit story. A dedicated vector store
would add an operational dependency without a measured need.

**5. How does multi-tenancy work?**
`org_id` is on every business table and every query takes it from the authenticated principal, never
from the request body. Unique constraints are tenant-scoped. A foreign id returns 404, not 403, so ids
do not leak. Cross-tenant reads and mutations are part of the acceptance suite.

**6. How do permissions work?**
47 permissions grouped by domain, six roles composed from them, and service-layer checks via
dependency injection. Role rank prevents granting above your own level. The UI hides actions it cannot
perform, but the server is the authority.

**7. Explain the approval model.**
A high-risk resolution creates an approval request with a requester, an assigned approver, a risk
level and a 48-hour expiry. The requester cannot decide it. `approval:decide` and
`resolution:execute` are separate permissions. Execution requires an approved request and is
idempotent.

**8. What was the hardest bug you found?**
Two concurrent approvals both succeeded. The old code read `PENDING`, mutated the ORM object and
inserted a decision, so two transactions could pass the check. I replaced it with an atomic
conditional update (`UPDATE ... WHERE status='PENDING'`) and required `rowcount = 1`; the loser gets
409 and writes nothing. I added `test_second_decision_is_a_conflict` and verified live with two
parallel requests. It is the kind of bug that only appears under real concurrency.

**9. How do you keep the AI honest?**
Three layers: the prompt sees only organization-scoped records; the output must match a strict JSON
schema; every citation is resolved back to a real document/page/chunk/case row and invalid ones are
flagged. The model has no tools and no write access, and money is recomputed in code. If evidence is
insufficient the run is marked for human review.

**10. Why not let the LLM compute totals or decide approval?**
Because a model can be confidently wrong or manipulated by document text. Financial math and policy
need deterministic, reproducible behaviour with a legal trail. The LLM explains and recommends;
people decide.

**11. How does retrieval work?**
Documents are chunked (~900 chars, 120 overlap), embedded with `bge-m3` at 1024 dimensions, and stored
in pgvector with an HNSW index. Search is hybrid: keyword weight 0.45 + cosine 0.55, filtered by
organization and permission, plus similar resolved cases. `top_k` is bounded and the prompt includes
only the selected chunks.

**12. What happens when the AI provider is down?**
The investigation fails with a clear error and the case remains usable. Deterministic retrieval and
all non-AI features keep working. In this deployment Ollama runs locally, so there is no external
outage, but the provider abstraction supports OpenAI-compatible endpoints.

**13. How do you handle document failures and retries?**
Uploads validate size, MIME, magic bytes, ZIP guards and SHA-256. Parsing failures set the document to
`FAILED` with a redacted error and emit `document.failed`. Reprocess can be triggered after the source
is fixed. Low OCR confidence or missing fields set `REQUIRES_REVIEW` instead of pretending success.

**14. How is money stored and calculated?**
`NUMERIC(18,4)` in PostgreSQL and `Decimal` in Python, never floats. Line totals are computed
server-side; validation recomputes subtotal + tax, line sums and the implied VAT rate with cent-level
tolerance. The acceptance suite checks exact values through the API and direct SQL.

**15. How do you guarantee no duplicate execution?**
Resolution execution has an idempotency key and an execution record per attempt; a repeated call
returns the existing result. Invoice creation per document is idempotent. Webhooks deduplicate by
key. n8n claims an event id in Redis (`SET NX EX`) before acting.

**16. How does the n8n integration work?**
RESOLVE writes domain events to an outbox in the same transaction as the business change. A beat task
publishes them every minute with an HMAC-SHA256 signature over the raw body and an idempotency key.
n8n verifies the signature, claims the id, and routes to email or escalation. Failures are recorded in
`webhook_events` and `workflow_executions`. n8n cannot approve or execute.

**17. How do you observe the system?**
`/metrics` exposes HTTP counters/histograms and real business gauges (cases, exceptions, approvals,
documents, vectors, outbox age). Prometheus scrapes 13 targets, 20 alert rules feed Alertmanager →
Mailpit, and four Grafana dashboards are provisioned from Git. Backup freshness is exported through
the node-exporter textfile collector.

**18. How do you test it?**
137 backend tests, 6 frontend unit tests, 10 Playwright E2E over HTTPS, a 28-step live workflow, a
26-case financial/security acceptance suite, 16 security checks and 9 n8n contract checks. Tests are
run against PostgreSQL and SQLite; the live suite uses real OCR and real local models. A bug found by
the suite is fixed and regression-tested.

**19. What are the biggest limitations?**
No physical macOS/Safari test, no public domain/DNS, no external SMTP (Mailpit only), single-node data
services, Docker Desktop rather than a Linux production engine, no malware scanning, no SSO, and rate
limiting shares a bucket behind Docker's proxy. Each has a documented mitigation or integration point.

**20. What would you do next with more time?**
In order: replace demo data/accounts, real SMTP and certificate, malware scanning, move to a Linux
engine with managed PostgreSQL/Redis/object storage, add a CI pipeline that runs the full suite on
every change, implement SSO/SCIM, and commission an external penetration test. Then measure
resolution time and false-positive rates with real users before adding features.

---

## Bonus: questions that test depth

**How would you scale the API?**
The API is stateless apart from rate-limit memory; move the limiter to Redis, run multiple uvicorn
workers/containers behind nginx, and keep the database as the coordination point. Celery already
scales independently. Vector search scales with HNSW parameters and read replicas.

**How would you make the outbox exactly-once?**
You cannot guarantee exactly-once delivery over HTTP; you guarantee at-least-once delivery plus
idempotent consumers. That is what the event id + claim store provides. The business effect is
idempotent, which is what actually matters.

**Why is the refresh token in a cookie and the access token in memory?**
The access token is short-lived and attached by the SPA; the refresh token is long-lived and must not
be readable by JavaScript. `HttpOnly` + `Secure` + `SameSite=Lax` limits theft and CSRF exposure,
and rotation with reuse detection limits replay.

**What happens if Redis is down?**
Celery workers cannot consume, the outbox cannot publish, and the idempotency claim endpoint returns
503 so n8n fails closed instead of double-processing. The API can still serve reads and deterministic
validation; Prometheus raises `ResolveRedisDown`.

**How do you prevent a malicious document from prompt-injecting the model?**
Document text is delimited as data, the system prompt forbids following embedded instructions, the
output schema is enforced, and citations must resolve to stored rows. The model has no tools and no
ability to act, so the worst case is a bad explanation that a human must review.

**How do you handle a migration that goes wrong?**
Migrations run on start and the app refuses to auto-create schema in production. The project already
hit a stamped-but-missing-column drift; it was repaired with a controlled downgrade/re-upgrade while
preserving data. Backups are taken before schema changes and restores are verified in isolation.
