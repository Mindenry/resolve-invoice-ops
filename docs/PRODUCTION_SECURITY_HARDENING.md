# Production security hardening

Scope: the Docker Compose deployment on this Windows workstation. Native services remain a
loopback-only rollback path.

## 1. Runtime configuration

| Setting | Value | Notes |
| --- | --- | --- |
| `ENV` | `production` | enables production validation and HSTS |
| `DEBUG` | `false` | startup validation rejects `true` in production |
| `DEMO_MODE` | `false` | demo affordances disabled |
| `AUTO_CREATE_SCHEMA` | ignored in production | schema is created only by `alembic upgrade head` |
| `SECRET_KEY` | 64 chars, random | replaces every development default |
| `CREDENTIAL_ENCRYPTION_KEY` | 64 chars, random | encrypts integration credentials |
| `CORS_ORIGINS` | four HTTPS origins | no wildcard |
| `FRONTEND_URL` | `https://192.168.1.10:8180` | used in links and emails |
| Refresh cookie | `Secure`, `HttpOnly`, `SameSite=Lax` | issued only over HTTPS |
| Access token | JWT HS256, 30 min | rotating refresh tokens, 14 days |
| Password hashing | Argon2 | via `argon2-cffi` |
| Rate limits | 600/min default, 20/min login | slowapi fixed window |
| Upload limit | 25 MB API, 30 MB nginx | MIME and size validated server-side |

Production startup validation (`Settings.validate_runtime`) refuses to boot when `SECRET_KEY` is a
development value, CORS contains `*`, the database is SQLite, or `DEBUG` is true.

## 2. Credential rotation

The seeded accounts were rotated to one strong random password:

| Account | Role |
| --- | --- |
| `admin@example.com` | Organization Admin |
| `manager@example.com` | Operations Manager |
| `investigator@example.com` | Investigator |
| `approver@example.com` | Approver |
| `viewer@example.com` | Viewer |
| `automation@example.com` | Viewer (read-only, n8n service account) |

* Storage: `var/secrets/demo-credentials.txt`, Git-ignored, ACL restricted to Administrators and
  SYSTEM (`icacls /inheritance:r`).
* The previously published password returns **401**; the rotated password returns **200**.
* The login page no longer prints or autofills a demo password, and the i18n strings that held it were
  removed.
* Self-service registration returns **403 `registration_disabled`** in production.
* Two stale E2E tenant users from earlier test runs were deactivated; one isolated tenant remains as a
  controlled fixture for cross-tenant tests.

### Rotation procedure

```powershell
# As the signed-in user, via the UI (Profile → Change password) or:
.\.venv\Scripts\python.exe - <<'PY'
# change-password flow: login, then POST /api/v1/auth/change-password
PY
```

Changing a password signs out other sessions. Store new values in the secret file, never in Git,
chat, tickets or the browser console. If a password is exposed, rotate first and investigate second.

## 3. Authorization model

Permissions are explicit in `apps/api/app/core/permissions.py`:

* **Viewer** — read-only (`case:read`, `document:read`, `analytics:read`, …).
* **Investigator** — viewer + upload/triage/investigate/propose.
* **Approver** — viewer + `approval:decide`, `resolution:execute`, `invoice:approve`.
* **Operations Manager** — investigator + approver + assignment/creation/automation management.
* **Organization Admin** — all permissions within the organization.
* **Super Admin** — platform-wide, never granted to demo accounts.

Cross-cutting controls:

* **Tenant isolation** — every query is scoped by `org_id`; forged or mismatched
  `X-Organization-Id` returns 403/404, verified live.
* **Self-approval** — `ALLOW_SELF_APPROVAL=false`; a requester cannot approve their own proposal
  (verified 403).
* **Approval/execution separation** — execution requires an approved request; n8n cannot approve or
  execute.
* **Automation account** — `viewer` only, so an automation bug cannot mutate financial state.

## 4. Secrets management

| Secret | Location | Protection |
| --- | --- | --- |
| Application/JWT keys | `.env` | Git-ignored; ACL on the repository folder |
| Demo passwords | `var/secrets/demo-credentials.txt` | Git-ignored; ACL restricted |
| TLS key | `var/certs/server-key.pem` | Git-ignored; ACL restricted |
| CA private key | mkcert CAROOT (user profile) | outside the repo |
| n8n encryption key / owner | `.env` | Git-ignored |
| S3 credentials | `.env` | Git-ignored; no Compose defaults |
| Integration signing secrets | DB, encrypted with `CREDENTIAL_ENCRYPTION_KEY` | never returned by the API (redacted) |
| Grafana admin | `.env` | Git-ignored |

Rules enforced in code and review:

* Secrets are never returned to the browser or included in AI prompts.
* Logs redact secret-like keys (`SENSITIVE_KEYS` in the integrations service).
* Error envelopes contain a code, a generic message and a request id — never stack traces, SQL or
  connection strings (verified).
* n8n receives only the webhook secret and the read-only automation credentials.

## 5. Network exposure

Allowed inbound: **TCP 8180 only**, Private profile, `RemoteAddress=LocalSubnet`, rule
`RESOLVE Docker Web (TCP 8180)`.

Bound to loopback and not reachable from the LAN (verified):

| Service | Host binding |
| --- | --- |
| API | `127.0.0.1:8100` |
| PostgreSQL | `127.0.0.1:5433` |
| Redis | `127.0.0.1:6380` |
| SeaweedFS S3 / UI | `127.0.0.1:9100` / `9101` |
| Mailpit UI / SMTP | `127.0.0.1:8125` / `1126` |
| n8n | `127.0.0.1:5679` |
| Prometheus / Alertmanager / Grafana | `127.0.0.1:9190` / `9193` / `3101` |
| Exporters | Docker network only |
| Ollama | host process on 11434, not published by Compose |

No port forwarding or public exposure was configured. Use a VPN for remote access.

## 6. Transport security

* TLS 1.2/1.3, local mkcert chain, SANs `resolve.local`, `192.168.1.10`, `localhost`, `127.0.0.1`.
* HSTS `max-age=31536000; includeSubDomains`.
* HTTP on 8081 redirects to HTTPS and is loopback-only.
* `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`,
  `Cross-Origin-Opener-Policy`; API responses are `Cache-Control: no-store`.
* nginx hides upstream duplicates so each header is single-valued.

## 7. Verified security acceptance (16/16)

Run: `$env:RESOLVE_LEGACY_PASSWORD="<retired>"; .\.venv\Scripts\python.exe scripts\verify-security.py`

| Check | Result |
| --- | --- |
| Retired demo password rejected | 401 |
| Rotated admin password works | 200 |
| Viewer write rejected | 403 |
| Unauthenticated mutation rejected | 401 |
| Forged organization header rejected | 403 |
| Login rate limit fires | 429 (first at request 18–21 depending on window) |
| Refresh cookie Secure/HttpOnly/SameSite=Lax | pass |
| HSTS present | `max-age=31536000; includeSubDomains` |
| Security headers single-valued | `nosniff` / `DENY` |
| API `Cache-Control: no-store` | pass |
| `/metrics` not served through the LAN web port | SPA HTML only, no Prometheus series |
| n8n / Grafana / Prometheus / API not reachable on LAN | connection refused |
| Error envelope hides internals | no traceback, no DSN, no password |

Additional checks from the end-to-end suite: cross-tenant reads and mutations return 404,
self-approval returns 403, self-service registration returns 403.

## 8. Residual risks and mitigations

| Risk | Mitigation / status |
| --- | --- |
| Rate-limit bucket shared per published port (Docker userland proxy rewrites client IP to the gateway) | limits still fire; keep credentials strong; put a Linux engine or reverse proxy with real client IPs before wider exposure |
| Rate limits stored in process memory | single API process; move to Redis storage before scaling out |
| Demo workspace still exists with synthetic data | delete or re-key before real financial data; documented in the readiness checklist |
| Mailpit, not real SMTP | no outbound mail; configure a real relay with TLS before production mail |
| Local CA must be installed on each client | documented; no public CA because no domain/DNS is available |
| Docker Desktop, not a hardened Linux engine | watchdog task installed; migrate to a Linux Docker Engine for production |
| Single-node SeaweedFS | no replication/HA; back up before risky changes |
