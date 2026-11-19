# Security policy

RESOLVE handles financial operations data, so security defects are treated as high priority.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Contact the maintainers privately with:

- affected version/commit and component;
- reproduction steps and a minimal proof of concept;
- impact assessment (tenant data, approvals, file upload, secrets);
- any suggested remediation.

Never include real credentials, customer documents or personal data in a report.

## Supported versions

The current release is `v1.0.0` (release candidate for controlled evaluation). Security fixes are
applied to the current `main` line; there are no maintained backport branches yet.

## Implemented controls (summary)

| Area | Control |
| --- | --- |
| Passwords | Argon2id, minimum length/complexity, lockout, generic errors, password-reset replay protection |
| Sessions | Signed short-lived access JWT; rotating refresh tokens hashed at rest; family revocation on reuse; session listing/revocation |
| Tenancy | `org_id` on every tenant table; membership checked per request; cross-tenant resources return 404; cross-tenant links rejected |
| RBAC | Six roles, 47 permissions; backend dependency checks; role-rank and last-admin protection; self-approval blocked |
| Uploads | Extension + magic-byte validation, configurable size limit, SHA-256 dedupe, storage-key traversal rejection, DOCX/XLSX ZIP-expansion guard, authenticated downloads |
| Webhooks | HMAC-SHA256 over the raw body, constant-time comparison, idempotency keys, disabled-integration and 1 MB payload rejection, per-integration signing secrets |
| Secrets | Environment-only configuration; Fernet-encrypted integration credentials; recursive redaction; secrets excluded from logs and API responses |
| AI | No tools/SQL/shell; untrusted data delimiting; strict schema; org-scoped retrieval; citation validation; deterministic approval policy; failures fail closed |
| API | Security headers, no-store on API responses, explicit CORS allowlist, rate limiting (stricter on login), generic 500 envelopes, request IDs |
| Audit | Append-only API with actor, request ID and before/after snapshots |

Detailed threat model and residual risks: [`docs/security/README.md`](docs/security/README.md).

## Verified in the latest pass

Live checks confirmed: cross-tenant reads/mutations return 404, viewer mutations 403, self-approval
403, login rate limiting returns 429 on the configured limit, CORS rejects unknown origins, security
headers are present, webhook signatures/limits are enforced, and integration secrets are encrypted
and absent from config responses. The primary Docker LAN deployment exposes only nginx on TCP 8180
(Private profile, LocalSubnet); the native rollback is localhost-only on 8090 and all data services
are loopback-only. Backup folders containing configuration/encryption keys are ACL-restricted. See
[`docs/FINAL_VERIFICATION_REPORT.md`](docs/FINAL_VERIFICATION_REPORT.md) §6 and
[`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md).

## Residual risks and deployment responsibilities

- Uploaded files are not malware-scanned; deploy ClamAV or equivalent for high-risk environments.
- SSO/SAML/SCIM, field-level permissions and database-level audit WORM storage are not implemented.
- Synthetic demo accounts and data remain. They use rotated strong passwords stored outside Git and
  must be removed or re-keyed before real financial data; never expose the demo workspace to the
  internet.
- PostgreSQL with pgvector and encrypted object storage are required for production; SQLite is
  blocked by production configuration validation.
- Perform an independent penetration test before handling real financial data.
