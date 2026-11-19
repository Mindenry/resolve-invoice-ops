# Security design

## 1. Threat model in one page

| Asset | Threat | Control |
| --- | --- | --- |
| Invoices, vendor and financial data | cross-tenant read/write | organization-scoped queries, header validation, 404 on foreign ids |
| Money actions | unauthorized approval/execution | RBAC, separation of duties, self-approval block, atomic decision |
| Credentials | theft or leakage | Argon2, hashed refresh tokens, secret file ACL, no secrets in Git/logs |
| Documents | malicious/oversized uploads | size, MIME + magic, ZIP guards, SHA-256 dedupe, OCR timeouts |
| AI | prompt injection / fabricated evidence | org-scoped context, strict schema, citation validation, no tools |
| Automation | forged events / replay | HMAC-SHA256, idempotency keys, Redis claim store, read-only account |
| Management plane | LAN exposure | loopback bindings, single HTTPS port, firewall `LocalSubnet` |
| Sessions | fixation/replay | rotating refresh tokens with reuse detection, logout revocation |

## 2. Authentication

- Email + password. Argon2id via `argon2-cffi`.
- Access token: JWT HS256, 30 minutes, issuer/audience checked.
- Refresh token: 14 days, opaque, stored hashed; rotated on every refresh.
- Reuse of an old refresh token revokes the token family and signs the session out.
- Cookies: `Secure`, `HttpOnly`, `SameSite=Lax`, path-scoped to the API.
- Login rate limit 20/min per client address; account lockout support exists in the service layer.
- Password change invalidates other sessions. Reset tokens are hashed, single-use and expiring.

## 3. Authorization

- 47 permissions grouped by domain (cases, documents, invoices, approvals, automation, admin).
- Six roles compose permissions; role rank prevents an admin from granting above their own level.
- Every service takes `org_id` from the authenticated principal, never from the request body.
- Object-level checks use `(id, org_id)` predicates; a foreign id is a 404, not a 403 leak.
- Approval rules: the requester cannot decide; the assigned approver (or a super admin) must; the
  decision requires `approval:decide`; execution requires `resolution:execute`.
- The n8n automation account is `viewer` only.

## 4. Approval integrity (the concurrency fix)

A real defect was found during the final acceptance run: two simultaneous approvals could both
succeed. The fix is an atomic claim in the same transaction:

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

Only one transaction can change the row from `PENDING`; the loser receives 409 and writes no decision,
no audit row and no execution. Covered by `test_second_decision_is_a_conflict` and by live concurrent
requests (one 200, one 409).

## 5. Money and state integrity

- `Decimal` + PostgreSQL `NUMERIC(18,4)`; rounding at a single boundary.
- Validation recomputes subtotal + tax, line sums and implied VAT rate.
- Resolution execution is idempotent; attempts are recorded and retries cannot duplicate the effect.
- State transitions are validated in one service function, not scattered across routers.
- Domain events are written in the same transaction as the change (outbox), so integrations cannot
  cause a partial financial state.

## 6. Secrets

| Secret | Storage | Protection |
| --- | --- | --- |
| JWT key | `.env` | Git-ignored, ACL-restricted, production startup validation |
| Credential encryption key | `.env` | encrypted integration credentials in DB |
| Demo passwords | `var/secrets/demo-credentials.txt` | Git-ignored, ACL to Administrators/SYSTEM |
| TLS private key | `var/certs/server-key.pem` | Git-ignored, ACL, never in backups without protection |
| n8n encryption key / owner | `.env` | stable across restarts |
| S3 credentials | `.env` | no insecure Compose defaults |
| Integration signing secrets | DB (encrypted) | redacted from API responses and logs |

Rules enforced by review and tests: no secret in Git, logs, prompts, browser responses or reports.
The retired demo password appears nowhere in the repository and is rejected by the live API.

## 7. Transport and network

- TLS 1.2/1.3 with a local mkcert CA; SANs include the LAN IP; HSTS one year.
- One LAN port (8180). Everything else is loopback or Docker-internal.
- nginx overwrites `X-Forwarded-For` and uvicorn trusts only private ranges.
- Security headers are single-valued (nginx hides upstream duplicates).
- HTTP is a loopback-only 301 redirect.
- No port forwarding, no public exposure, no VPN requirement for local use.

## 8. Input and output safety

- Pydantic schemas reject unknown/invalid fields at the boundary.
- Upload validation: size, MIME, magic bytes, ZIP bomb guards, per-document OCR timeouts.
- SQL is parameterized through SQLAlchemy; no string-built queries with user input.
- HTML is rendered by React (escaped by default); no `dangerouslySetInnerHTML` in feature pages.
- Error envelopes return a code, a generic message and a request id — never stack traces, SQL, DSNs or
  secrets. Verified with a live 404.
- AI prompts treat document text as data, delimited and instruction-hardened; output is schema-checked.

## 9. Auditability

- Append-only `audit_logs` with actor, request id, before/after snapshots and entity references.
- Case timeline and approval decisions are separate, queryable records.
- Every AI run stores prompt version, provider/model, token usage, latency and evidence validation.
- Every webhook delivery stores status code, error and idempotency key.
- Audit and analytics are queryable by admins; export is available.

## 10. Verified security results

| Check | Result |
| --- | --- |
| Retired demo password | 401 |
| Rotated password | 200 |
| Viewer write | 403 |
| Unauthenticated mutation | 401 |
| Forged organization header | 403 |
| Login rate limit | 429 after threshold |
| Refresh cookie flags | Secure + HttpOnly + SameSite=Lax |
| HSTS / nosniff / DENY / no-store | present |
| `/metrics` via LAN web port | SPA HTML only, no metrics |
| n8n / Grafana / Prometheus / API on LAN | refused |
| Cross-tenant case read | 404 |
| Self-approval | 403 |
| Concurrent approval | one 200, one 409 |
| Expired approval | 409 |
| Invalid HMAC | 400 |
| Malformed/corrupt/oversized upload | 422 / FAILED / 422 |

## 11. Residual risks

- Rate limiting is per published port behind Docker's userland proxy; LAN clients share a bucket.
- Demo data and accounts still exist; they must be removed before real data.
- No malware scanning yet.
- Local CA must be installed per client; no public domain.
- Single-node data services and Docker Desktop are not a hardened production host.

These are documented rather than hidden in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).
