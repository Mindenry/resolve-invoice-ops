# API documentation

Base path: `/api/v1`. Interactive OpenAPI: `/docs` (Swagger UI) and `/redoc`. The canonical
machine-readable document is `/openapi.json`; `packages/shared-types` generates TypeScript from it.

## Authentication

- `POST /auth/login` returns an access token (JSON) and sets an httpOnly refresh cookie scoped to
  `/api/v1/auth`.
- Send `Authorization: Bearer <access_token>` on every request.
- Send `X-Organization-Id: <uuid>` to select the active organization. The access token also carries
  an organization claim; the header takes precedence but must match an active membership (or the
  user must be a platform superadmin).
- `POST /auth/refresh` rotates the refresh token (cookie or `{ "refresh_token": "…" }`). Reuse of a
  rotated token revokes the whole token family.
- `POST /auth/logout` revokes the current refresh token and clears the cookie.

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"the password in var/secrets/demo-credentials.txt"}'
```

Access tokens are intentionally short-lived (30 minutes by default). The SPA keeps the access token
in memory and recovers a session through the refresh cookie on reload. Mutating requests use the
bearer token, not the cookie, so they are not CSRF-able; the refresh cookie is `SameSite=Lax`,
`HttpOnly` and `Secure` in production.

## Error envelope

```json
{
  "error": {
    "code": "missing_permission",
    "message": "You do not have permission to perform this action.",
    "details": {"required": ["vendor:create"], "missing": ["vendor:create"]},
    "request_id": "5ef34c…"
  }
}
```

| Status | Typical codes |
| --- | --- |
| 400 | `invalid_case_transition`, `invalid_action_parameters`, `weak_password`, `approval_required` |
| 401 | `invalid_credentials`, `token_expired`, `refresh_token_reuse`, `missing_token` |
| 403 | `missing_permission`, `cross_organization_access_denied`, `self_approval_denied` |
| 404 | `case_not_found`, `document_not_found`, `investigation_not_found` |
| 409 | `duplicate_document`, `approval_not_pending`, `already_member` |
| 422 | schema validation, `unsupported_file_type`, `mime_mismatch`, `file_too_large` |
| 429 | `rate_limited` with `Retry-After` |
| 503 | `ai_unavailable` (no provider configured or provider failed) |

Validation errors include `details: [{loc, message, type}]`.

## Pagination, filtering, sorting

List endpoints accept `page` (1-based), `page_size` (≤200) and often `sort` / `order`. Responses:

```json
{
  "items": [],
  "meta": {"page": 1, "page_size": 25, "total": 0, "pages": 0, "has_next": false}
}
```

Repeat query parameters for multi-value filters, e.g.
`/exceptions?exception_type=AMOUNT_MISMATCH&status=OPEN&severity=HIGH`.

## Endpoint groups

### Authentication and account

| Method | Path | Permission |
| --- | --- | --- |
| POST | `/auth/login`, `/auth/register`, `/auth/refresh`, `/auth/logout` | public/session |
| POST | `/auth/password-reset`, `/auth/password-reset/confirm` | public |
| POST | `/auth/change-password` | authenticated |
| GET | `/auth/me`, `/auth/organizations`, `/auth/sessions` | authenticated |
| DELETE | `/auth/sessions/{id}` | authenticated |

### Users and organizations

| Method | Path | Permission |
| --- | --- | --- |
| GET/PATCH | `/users/me` | authenticated |
| GET | `/users` | `user:read` |
| POST / PATCH / DELETE | `/users`, `/users/{membership_id}` | `user:manage` |
| GET/PATCH | `/organizations/current` | `org:read` / `org:update` |
| GET/PUT | `/organizations/settings` | `org:read` / `org:update` |
| GET | `/organizations/roles`, `/organizations/permissions`, `/organizations/roles/matrix`, `/organizations/members/assignable` | `role:read` / `user:read` |
| GET | `/organizations/ai-configuration` | `ai:configure` |
| GET | `/system/info` | public metadata (no secrets) |

### Vendors, purchase orders, invoices

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/vendors`, `/vendors/duplicates`, `/vendors/{id}` | `vendor:read` |
| POST / PATCH / DELETE | `/vendors`, `/vendors/{id}` | `vendor:create` / `vendor:update` / `vendor:delete` |
| POST | `/vendors/{id}/merge` | `vendor:merge` |
| GET | `/purchase-orders`, `/purchase-orders/{id}`, `/purchase-orders/summary` | `po:read` |
| POST / PATCH / DELETE | `/purchase-orders`, `/purchase-orders/{id}` | `po:create` / `po:update` |
| POST | `/purchase-orders/{id}/transition` | `po:update` |
| GET | `/invoices`, `/invoices/{id}` | `invoice:read` |
| POST / PATCH | `/invoices`, `/invoices/{id}` | `invoice:create` / `invoice:update` |
| POST | `/invoices/{id}/validate`, `/invoices/{id}/match` | `invoice:update` |
| POST | `/invoices/{id}/approve`, `/invoices/{id}/transition` to approved states | `invoice:approve` |
| DELETE | `/invoices/{id}` | `invoice:update` (cancels, soft deletes) |

Example invoice creation:

```bash
curl -X POST http://localhost:8000/api/v1/invoices \
  -H "Authorization: Bearer $TOKEN" -H "X-Organization-Id: $ORG" \
  -H 'Content-Type: application/json' \
  -d '{
    "invoice_number": "INV-2041",
    "vendor_id": "…",
    "invoice_date": "2026-02-10",
    "currency": "USD",
    "subtotal": "1000.00",
    "tax": "70.00",
    "total": "1070.00",
    "items": [{"description":"Widgets","quantity":"10","unit_price":"100.00","tax_rate":"7"}]
  }'
```

The response includes validation notes and any auto-detected exceptions/case links.

### Documents and knowledge

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/documents`, `/documents/{id}`, `/documents/{id}/extraction`, `/documents/{id}/chunks`, `/documents/search/knowledge`, `/documents/capabilities` | `document:read` |
| POST | `/documents` (multipart), `/documents/{id}/versions` | `document:upload` |
| PATCH | `/documents/{id}/fields/{field_id}` | `document:review` |
| POST | `/documents/{id}/review`, `/documents/{id}/reprocess`, `/documents/{id}/create-invoice` | `document:review` |
| GET | `/documents/{id}/download` | `document:read` (audited) |
| DELETE | `/documents/{id}` | `document:delete` |

Upload limits: 25 MB, extension + magic-byte validation, duplicate SHA-256 rejection with the existing
document id in `details`.

### Exceptions and cases

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/exceptions`, `/exceptions/{id}`, `/exceptions/summary`, `/exceptions/rules`, `/exceptions/rules/{code}` | `exception:read` |
| POST | `/exceptions/scan` | `exception:triage` |
| POST | `/exceptions/{id}/status`, `/exceptions/{id}/attach` | `exception:triage` |
| PATCH | `/exceptions/rules/{code}` | `org:update` |
| GET | `/cases`, `/cases/{id}`, `/cases/{id}/timeline` | `case:read` |
| POST | `/cases` | `case:create` |
| PATCH | `/cases/{id}` | `case:update` |
| POST | `/cases/{id}/assign`, `/cases/bulk/assign`, `/cases/{id}/escalate` | `case:assign` |
| POST | `/cases/{id}/transition`, `/cases/{id}/resolve`, `/cases/{id}/merge` | `case:close` / `case:merge` |
| POST | `/cases/{id}/comments` | `case:comment` |

Case transitions are validated (`OPEN → INVESTIGATING → …`); resolving requires a resolution summary
and resolves linked exceptions. Merging moves exceptions, comments and links into the target case.

### Investigation, resolutions and approvals

| Method | Path | Permission |
| --- | --- | --- |
| POST | `/cases/{id}/investigations` | `investigation:run` |
| GET | `/cases/{id}/investigations`, `/investigations/{id}`, `/investigations/ai-status` | `investigation:read` |
| POST | `/investigations/{id}/suggestions/{index}/accept` | `resolution:propose` |
| GET | `/resolutions`, `/resolutions/{id}`, `/cases/{id}/resolutions`, `/resolutions/actions` | `resolution:read` |
| POST | `/cases/{id}/resolutions`, `/resolutions/{id}/cancel` | `resolution:propose` |
| POST | `/resolutions/{id}/execute`, `/resolutions/{id}/retry` | `resolution:execute` |
| GET | `/approvals`, `/approvals/{id}`, `/approvals/stats` | `approval:read` |
| POST | `/approvals/{id}/approve`, `/approvals/{id}/reject` | `approval:decide` |
| POST | `/approvals/cases/{case_id}/request` | `resolution:propose` |

Investigations are queued and processed asynchronously. Poll the case investigation list; the record
moves `QUEUED → RUNNING → COMPLETED|FAILED`. Evidence items include `is_validated` and
`validation_error`.

### Automation, notifications, analytics, evaluation, audit

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/integrations`, `/integrations/events`, `/integrations/{id}` | `integration:read` |
| POST/PATCH/DELETE | `/integrations`, `/integrations/{id}` | `integration:manage` |
| POST | `/integrations/{id}/test` | `integration:manage` |
| PUT | `/integrations/{id}/credentials` | `integration:manage` |
| POST | `/webhooks/{integration_id}` | HMAC signature (public route) |
| GET | `/workflows/templates`, `/workflows/executions`, `/jobs` | `workflow:run` / `workflow:read` |
| POST | `/workflows/{key}/trigger`, `/workflows/executions/{id}/retry`, `/jobs/{id}/retry` | `workflow:run` |
| GET | `/notifications`, `/notifications/unread-count`, `/notifications/preferences` | authenticated |
| POST/PUT | `/notifications/{id}/read`, `/notifications/read-all`, `/notifications/preferences` | authenticated |
| GET | `/analytics/overview`, `/analytics/resolution-time`, `/analytics/ai-usage` | `analytics:read` |
| GET | `/evaluation/datasets`, `/evaluation/runs`, `/evaluation/compare` | `evaluation:read` |
| POST | `/evaluation/datasets`, `/evaluation/runs` | `evaluation:run` |
| GET | `/audit`, `/audit/actions`, `/audit/{id}`, `/audit/export` | `audit:read` |
| GET | `/saved-filters` | authenticated |

Inbound webhook example:

```bash
BODY='{"event_type":"integration.ping","id":"evt-1"}'
SIG=$(printf %s "$BODY" | openssl dgst -sha256 -hmac "$N8N_WEBHOOK_SECRET" -hex | awk '{print $2}')
curl -X POST "http://localhost:8000/api/v1/webhooks/$INTEGRATION_ID" \
  -H "X-Resolve-Signature: $SIG" -H 'Content-Type: application/json' -d "$BODY"
```

## Rate limits

Authenticated requests are keyed by user; anonymous requests by IP. Default 600/minute; login,
registration and password-reset are 10/minute; inbound webhooks 120/minute. Limits use slowapi and
can be backed by Redis with `RATE_LIMIT_STORAGE_URI`.

## Versioning policy

The URL prefix is the contract version. Additive fields are non-breaking; removals or semantic
changes require `/api/v2`. Deprecations are documented in the OpenAPI description before removal.
