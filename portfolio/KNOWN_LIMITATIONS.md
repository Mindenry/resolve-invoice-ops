# Known limitations

This file exists because a portfolio that claims everything works is not credible. Status is current
as of the closure run; evidence is in `docs/FINAL_PROJECT_CLOSURE_REPORT.md`.

## Verified working

- Docker Compose deployment with 18 services; HTTPS on a local CA; loopback-only management plane.
- Login/refresh/logout, RBAC (6 roles, 47 permissions), tenant isolation, self-approval block,
  approval/execution separation, login rate limiting.
- Vendor, PO, invoice, validation, 10 exception rules, case management, document upload/OCR/extraction,
  AI investigation with validated evidence, resolutions, approvals, execution, audit, analytics.
- n8n workflows A–E with HMAC and Redis idempotency; Prometheus/Grafana/Alertmanager; backup and
  isolated restore; restart persistence.
- 137 backend tests, 10 Playwright E2E, 26 acceptance cases, 16 security checks, 28-step workflow.

## Partially verified

| Item | What is missing |
| --- | --- |
| macOS/Safari | no Mac available; CA and commands provided, trust not executed |
| Backup scheduling | task installed and executed once; long-term unattended history not observed |
| Celery beat | schedules observed working, not over a multi-hour window |
| AI quality | 7B local model; citations validated, but wording can be imprecise; no external-model benchmark |
| Rate limiting | limits fire, but Docker's userland proxy collapses client IPs to one bucket; storage is in-process |
| Docker engine | watchdog mitigates idle exits; Docker Desktop is a workstation runtime |

## Blocked by external resources

- Public domain and DNS (HTTPS uses an IP + local CA).
- External SMTP (Mailpit is a local sink; no mail leaves the machine).
- Off-host backup storage.
- A server-grade Linux host / managed data services.
- Malware scanning service.
- Independent penetration test.
- Business user acceptance testing.

Each has a documented integration point and a setup path in `docs/` and
`portfolio/DEPLOYMENT_OVERVIEW.md`.

## Deliberately not implemented

- SSO/SAML/SCIM and field-level permissions.
- Audit WORM / external notarisation.
- General ledger, payment rails or bank integrations.
- HA/replication for PostgreSQL, Redis or object storage.
- Multi-region or multi-cluster operation.

## Security caveats

- Demo accounts and synthetic data still exist. Remove or re-key them before real financial data.
- No antivirus scanning on uploads (type/size/ZIP guards only).
- The local CA must be installed on every client.
- Backups contain sensitive data; protect them and keep encryption keys with the restore plan.

## What "production ready" would require here

1. Remove the demo workspace and accounts; named users only.
2. Real SMTP over TLS and a managed certificate with a real domain.
3. Malware scanning and upload quarantine.
4. Linux Docker Engine (or managed containers) and managed PostgreSQL/Redis/S3 with HA and PITR.
5. Off-host, encrypted, scheduled backups with quarterly restore drills.
6. Real client-IP handling for rate limits and centralized limiter storage.
7. SSO/SCIM, retention policy and audit export/notarisation as required.
8. UAT with finance users and an independent security review.

## Honest positioning

This is a **release candidate for controlled evaluation**, not a system approved for real money. It is
strong evidence of engineering ability across backend, frontend, data, AI safety, operations and
testing — and it is explicit about the line between "verified here" and "requires production
infrastructure".
