# Security

## 1. Threat model

| Asset | Threat | Control |
| --- | --- | --- |
| Credentials | stuffing, brute force | Argon2id, generic error messages, 5-attempt lockout, per-IP/user rate limits, short access tokens |
| Refresh tokens | XSS theft, replay | httpOnly `SameSite=Lax` cookie, hashed at rest, rotation, family revocation on reuse, Secure in production |
| Tenant data | cross-organization access | organization resolved per request, membership checks, every query filters `org_id`, cross-org tests |
| Privileges | role escalation | backend permission checks, rank checks on role changes, superadmin separate, last-admin protection, self-approval block |
| Documents | malicious files, traversal, XSS | extension + magic-byte allowlist, configurable `MAX_UPLOAD_MB` limit, ZIP-expansion guard for DOCX/XLSX, storage-key sanitisation, `nosniff`, `X-Frame-Options: DENY`, download requires auth |
| AI | prompt injection, fabricated citations | untrusted-data delimiting, no tools, strict schema, deterministic citation validation, bounded retries, org-scoped context |
| Actions | unauthorised financial changes | allowlisted actions, typed parameters, policy engine, approval, permission recheck at execution, idempotency, audit |
| Webhooks | forgery, replay | HMAC-SHA256 signature validation, constant-time compare, idempotency keys |
| Secrets | leakage | env-only configuration, encrypted integration credentials, redacted config responses, no secrets in logs |
| Audit | tampering | append-only API (no update/delete endpoints), before/after snapshots |

## 2. Authentication and sessions

- Passwords are hashed with Argon2id (`time_cost=2`, 19 MiB, parallelism 1) and rehashed on login when
  parameters change.
- Password policy: ≥10 characters, upper/lower/digit, common-password rejection.
- Access JWT: HS256, issuer/audience validated, `exp`/`iat`/`nbf` required, `type=access` enforced.
- Refresh tokens: 48-byte random values prefixed `rt_`, stored as SHA-256, rotated on every use,
  grouped into families. Presenting a revoked token revokes the family and is audited.
- Password change/reset revokes all refresh tokens.
- Login failures are audited with a nullable organization (auth events may occur before tenancy is
  known).
- Sessions can be listed and revoked by the owner.

## 3. Authorization

- Six roles and 47 permissions, seeded idempotently from code into the database.
- Permission checks are dependencies on the backend; the frontend only hides controls.
- Organization membership is verified on every request. A superadmin may target any organization via
  the header, but this is explicit and audited.
- Role changes cannot exceed the actor's rank; the superadmin role cannot be granted.
- The last active organization admin cannot be deactivated or demoted.
- The last-admin rule and self-deactivation are covered by tests.

## 4. Data isolation

Every tenant table has `org_id`. Service functions always receive `org_id` from the authenticated
principal, and resource lookups include it. Foreign resources return 404 rather than confirming
existence. Retrieval only searches documents in the caller's organization with permitted statuses.
Tests exercise cross-organization headers and foreign resource IDs.

## 5. File security

- Allowed extensions/magic bytes; mismatch rejected.
- Configurable maximum upload size (`MAX_UPLOAD_MB`) enforced for upload and version upload.
- DOCX/XLSX archives are rejected above `MAX_DECOMPRESSED_MB` or 20,000 entries (ZIP bomb guard).
- Files stored under `org_id/hash-prefix/hash.ext`; `..` traversal rejected.
- Checksum dedupe prevents accidental duplicate storage within an organization.
- Preview uses an authenticated blob fetch, not a public URL.
- OCR runs in the worker with a configurable timeout; failures are persisted, not hidden.
- Uploaded text is always treated as untrusted data in prompts.

## 6. AI security

- No arbitrary SQL, shell, Python, tool calls or URL fetching is exposed to the model.
- System instructions explicitly forbid following instructions found in documents and forbid
  revealing the prompt.
- Output must satisfy a Pydantic schema. Invalid JSON is repaired with bounded attempts; after the
  budget it fails closed with `ai_invalid_output`.
- Evidence is validated against real records/pages/chunks. Invalid evidence is persisted with an
  error and excluded from support; if nothing validates, the root cause is withheld.
- Context is limited to the requesting organization, authorized statuses and the specific case.
- The model cannot lower risk or approval requirements: policy is deterministic and applied after
  the model returns.
- AI failures are visible to users (`ai_unavailable`, `ai_invalid_output`, `context_error`) and never
  replaced with canned answers. The stub provider is for tests only, always labelled.

## 7. Webhooks and automation

- Inbound requests require a valid `X-Resolve-Signature` HMAC over the raw body.
- Disabled integrations are rejected; payloads over 1 MB are rejected before parsing.
- Idempotency keys are unique per organization; duplicates return the stored event.
- Outbound events are signed with the integration's own `signing_secret` when configured, otherwise
  the deployment secret; the receiver can verify with `packages/integration-sdk`.
- Integration URLs must be absolute HTTP(S); invalid URLs are rejected at write time.
- Delivery failures mark the integration degraded and are visible to operators.
- No workflow is reported as successful unless the HTTP call succeeded.

## 8. Secrets and configuration

- `.env` is git-ignored; `.env.example` contains placeholders only.
- Production startup validates: non-default secret, no wildcard CORS, PostgreSQL, debug disabled.
- Integration credentials are encrypted with Fernet, keyed by a SHA-256 derivation of
  `CREDENTIAL_ENCRYPTION_KEY` or `SECRET_KEY`; only key names are returned to clients.
- Logs exclude passwords, tokens, API keys and document contents.
- Health endpoints expose dependency status, never credentials.

## 9. Browser and API hardening

- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  `Permissions-Policy`, COOP; HSTS in production.
- No caching of `/api/v1` responses (`Cache-Control: no-store`).
- CORS is an explicit allowlist with credentials; wildcard is rejected in production.
- Bearer tokens for mutations avoid CSRF; the refresh cookie is Lax and path-scoped.
- Rate limiting via slowapi; stricter limits on auth endpoints.
- Generic 500 responses; details and stack traces stay in server logs.

## 10. Verification evidence

The controls above were exercised in the latest pass: cross-tenant reads/mutations → 404, viewer
mutations → 403, self-approval → 403, 4th login at a 3/minute limit → 429, disallowed CORS origin
→ rejected preflight, security headers observed, webhook signature/disabled/size checks tested,
per-integration signing verified, and encrypted credentials absent from responses. Full results:
[`docs/FINAL_VERIFICATION_REPORT.md`](../FINAL_VERIFICATION_REPORT.md) §6.

## 11. Residual risks / next steps

- SSO/SAML and SCIM are not implemented; enterprise deployments should add an identity provider.
- Audit retention/immutability at the database level (WORM storage or hash chaining) is a roadmap item.
- Per-field/entity permissions (e.g. vendor bank details) are not implemented.
- Malware scanning of uploaded files is not implemented; deploy ClamAV or an equivalent in front of
  object storage for high-risk environments.
- The seeded demo password is public by design; demo deployments must not be exposed to the internet.

## 12. Current deployment posture (2026-11-19)

- Only TCP **8180** (Docker nginx) is allowed inbound, Private profile, `RemoteAddress=LocalSubnet`.
  The native rollback nginx binds `127.0.0.1:8090` and its old LAN rule is disabled.
- PostgreSQL (5432/55432), Redis (6379), API (8000), Ollama (11434), Mailpit (1025/8025), SeaweedFS
  S3 (9100/9101) and n8n (5678/5679) are loopback-only and have no inbound allow rule.
- The LAN deployment is HTTP (`ENV=development`) for evaluation; refresh cookies are not `Secure`.
  Put it behind HTTPS and switch to `ENV=production` before real data.
- Backups contain `.env`/encryption keys; the backup folder ACL is restricted to
  Administrators/SYSTEM. Store an encrypted copy off-host.
- Docker Compose is verified after reboot. Only web 8180 binds to all interfaces; API 8100,
  PostgreSQL 5433, Redis 6380, SeaweedFS 9100/9101, Mailpit 8125/1126, n8n 5679 and monitoring
  9190/3101 bind to `127.0.0.1`. Do not publish them without new scoped firewall rules. The SeaweedFS
  gateway requires generated credentials; anonymous S3 access is rejected.
