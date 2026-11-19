# Technical decisions

| # | Decision | Rationale | Consequence |
| --- | --- | --- | --- |
| 1 | Modular monolith, one deployable API | Transactional consistency across documents, invoices, rules, cases and approvals; small team; clear extraction path | Modules must keep boundaries; no cross-module ORM traversal without a service |
| 2 | Deterministic calculations and rules; LLM only for language reasoning | Financial correctness, explainability, policy enforcement | AI output is structured, validated and never authoritative |
| 3 | PostgreSQL + pgvector in production, SQLite for tests/dev | Real vector search and JSONB in production; portable CI without external services | Vector fast path is PostgreSQL-only and documented; exact cosine fallback |
| 4 | Access token in memory + refresh token in httpOnly cookie | Limits XSS impact, avoids local storage tokens, prevents CSRF on mutations | SPA must refresh on load; cookie path is scoped to `/api/v1/auth` |
| 5 | Transactional outbox for integrations | Events must not be lost or published before commit | Events can be skipped/retried; consumers must be idempotent |
| 6 | Celery in Compose, local executor fallback | Full stack in production; product remains runnable without infrastructure | Job status is persisted regardless of runner; inline mode for tests |
| 7 | Case grouping is automatic but reviewable | Operators expect a single workspace per incident | Rule engine dedupes by fingerprint; humans can merge/split |
| 8 | Approval policy is deterministic and separate from AI | AI must never lower risk or bypass approval | Risk is raised to the action default; external/financial actions always require approval |
| 9 | Generated OpenAPI types, small hand-written UI projection | Type safety without coupling build pipelines | `packages/shared-types` is generated; CI checks the UI projection |
| 10 | No Docker/LLM/OCR in the authoring environment | Constraints of the environment | Limitations are recorded rather than simulated; CI validates infrastructure |

See `docs/decisions/` for short ADRs.

## 1. Why not microservices?

The core value is an auditable transaction: detect → link → investigate → approve → execute → audit.
Splitting this across services at this stage would add distributed transactions, duplicated
authorization and operational overhead without a demonstrated scaling need. Domain modules are
separated by package, schema and service boundaries so extraction remains feasible.

## 2. Why not let the AI choose actions?

The action registry is an allowlist with typed parameters. The policy engine assigns risk, requires
approval and enforces permissions. The model may suggest an action type, but a human proposal,
validation and (where required) approval are still required. This keeps prompt injection from turning
into financial impact.

## 3. Why confidence is labelled heuristic

LLM self-reported confidence is not calibrated. The UI says “heuristic confidence” and explains the
basis. Calibration against a labelled dataset is a roadmap item; the evaluation lab measures accuracy
rather than trusting self-reported scores.

## 4. Why invoices are not unique by (vendor, number)

The duplicate-invoice rule must be able to persist a second invoice and investigate it. A database
uniqueness constraint would reject the very condition the product exists to manage. Duplicate
detection is a rule with evidence, and rejection requires an approved resolution.

## 5. Why an outbox instead of direct webhook calls at write time?

Webhooks must not run inside the business transaction (slow, retryable, external). Writing an event
row in the same transaction guarantees the event reflects a committed change. Publishing later with
idempotency keys is safe under retries.

## 6. Why refresh rotation with family revocation?

If a refresh token leaks, rotation gives the attacker and the legitimate user divergent tokens.
Detecting reuse and revoking the family forces re-authentication. This is implemented and tested,
including family revocation after the rotated token is used.
