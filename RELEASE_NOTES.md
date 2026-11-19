# RESOLVE v1.0.0-rc.1 — Release notes

**Status:** release candidate for pre-production / controlled evaluation.
**Baseline date:** 2026-11-19.
**Deployment:** Docker Compose (primary) with loopback-only native Windows services as rollback.

This is a candidate, not a general-availability release. It must not receive real financial data
until the remaining items in `docs/KNOWN_LIMITATIONS.md` and the "before real data" checklist in
`docs/FINAL_PRODUCTION_HARDENING_REPORT.md` are closed.

## What works (verified on this machine)

* HTTPS on `https://localhost:8180` and `https://192.168.1.107:8180` with a trusted local mkcert
  chain, TLS 1.2/1.3, HSTS and Secure/HttpOnly/SameSite=Lax refresh cookies.
* Production authentication: rotated demo passwords, disabled self-registration, RBAC, tenant
  isolation, self-approval prevention, approval/execution separation and rate limiting.
* Full operational workflow over HTTPS through real Ollama (`qwen2.5:7b-instruct` + `bge-m3`),
  Tesseract OCR (Thai + English), pgvector retrieval, approvals, execution, audit and analytics.
* n8n workflows A–E with HMAC validation, Redis-backed idempotency, retries and Mailpit delivery.
* Prometheus, Alertmanager and Grafana with live metrics, 20 alert rules and four dashboards.
* Backup to `backups/compose-20261119-205946` and restore into an isolated database and bucket,
  including 16 pgvector rows at dimension 1024 and an HNSW index.
* Restart persistence for data, workflows, dashboards, certificates and credentials.

## Upgrade / install

1. Copy `.env.example` to `.env` and fill every blank secret (see `docs/RELEASE_MANAGEMENT.md`).
2. Issue the TLS certificate with mkcert (see `docs/HTTPS_LAN_SETUP.md`).
3. `docker compose --env-file .env --profile monitoring up -d --build`
4. Provision n8n owner, credential and workflows with the scripts in
   `docs/N8N_RESOLVE_AUTOMATION.md`.
5. Trust `var/certs/rootCA.pem` on each client (macOS steps included).

## Upgrade from 0.3.0

* Rotate all demo passwords; the old seeded password is no longer valid.
* The API image now requires `prometheus-client` (already in `apps/api/pyproject.toml`).
* n8n now requires `N8N_ENCRYPTION_KEY`, `N8N_OWNER_*`, `N8N_WEBHOOK_SECRET` and
  `RESOLVE_AUTOMATION_*` in `.env`; Compose fails fast if they are missing.
* S3 credentials and the PostgreSQL password no longer have default values in Compose.

## Known limitations at this tag

No physical macOS/Safari test, no external DNS/domain, no external SMTP (Mailpit only), Docker
Desktop rather than a Linux engine, single-node SeaweedFS (not HA), and rate limiting shares one
bucket per published Docker port because the Docker userland proxy rewrites client IPs.

## Rollback

`git checkout v1.0.0-rc.1` restores the exact source baseline. Data rollback uses the backup and
restore procedure in `docs/BACKUP_RESTORE_RUNBOOK.md`; the native Windows deployment remains a
localhost-only fallback.
