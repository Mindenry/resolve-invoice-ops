# Known limitations

Status is current as of 2026-11-19, after the final hardening pass. Evidence for every VERIFIED item
is in `docs/FINAL_PRODUCTION_HARDENING_REPORT.md`.

## VERIFIED

- Docker Compose primary stack (18 services): API, worker, beat, web, PostgreSQL 16.16, pgvector
  0.8.7, Redis 7, SeaweedFS 4.54, Mailpit 1.34.0, n8n 2.48.6, Prometheus, Alertmanager, Grafana and
  six exporters.
- HTTPS on 8180 with a local mkcert CA (SANs include the LAN IP), TLS 1.2/1.3, HSTS, Secure/HttpOnly/
  SameSite=Lax cookies; Playwright 10/10 over HTTPS.
- Rotated demo credentials; the retired password is rejected; self-registration disabled in
  production; login UI contains no demo password.
- RBAC, tenant isolation, self-approval prevention, approval/execution separation and login rate
  limiting; 16/16 security checks.
- `vector(1024)`, JSON backfill, HNSW index and a real nearest-neighbour query.
- Container→Ollama access; real Qwen2.5 7B investigation with validated evidence.
- OCR in the container (Tesseract 5.4, eng/tha) verified on live documents.
- SeaweedFS S3 upload/download; backup/restore with SHA-256 checks.
- 28-step workflow over HTTPS (approval, SMTP, execution, audit, analytics).
- Backup `compose-20261119-205946` restored into an isolated DB and bucket (65 objects).
- n8n workflows A–E active, with HMAC, Redis-backed idempotency, duplicate suppression and Mailpit
  delivery; real outbox events delivered.
- Prometheus 13/13 targets up with 20 rules; Alertmanager → Mailpit verified; four Grafana dashboards.
- Backend: **136 passed + 1 skip** (PostgreSQL and SQLite); frontend typecheck/lint/Vitest/build.
- Git baseline: tag `v1.0.0`; working tree clean; secret scan clean.
- Only TCP 8180 exposed to the LAN; all internal services loopback or Docker-internal.

## PARTIALLY VERIFIED

- **macOS client:** no physical Mac was available. The LAN URL, firewall, login/refresh, upload,
  download, AI investigation and approval were exercised from Windows against
  `192.168.1.10:8180` over HTTPS. Safari/Keychain trust was not tested; the CA and commands are in
  `docs/HTTPS_LAN_SETUP.md`.
- **Celery beat:** schedules observed working, but not over a multi-hour window.
- **AI quality:** a 7B local model can produce imprecise root-cause wording. Citations are validated;
  invalid ones are stored/flagged. External provider quality and cost are unverified.
- **Backup scheduling:** the `RESOLVE-Daily-Backup` task runs daily at 02:30, has produced a verified
  backup through the scheduled path, and freshness is exported to Prometheus. Pruning is manual by
  design; copy backups off-host.
- **Docker Desktop:** the engine occasionally exits. A watchdog runs every minute and Compose has
  restart policies, but this is a workstation runtime, not a server runtime.
- **Rate limiting:** the Docker userland proxy rewrites client IPs to the gateway, so LAN clients
  share one bucket; limits still fire (429 observed). Storage is in-process memory.

## NOT VERIFIED / BLOCKED

- **Public domain / external DNS:** unavailable in this environment. HTTPS uses an IP + local CA.
- **External SMTP:** unavailable; Mailpit is a local sink and no mail leaves the machine.
- **Managed cloud storage (S3/R2/B2):** not tested with real cloud credentials.
- **High availability:** PostgreSQL, Redis and SeaweedFS are single-node; no replication/failover.
- **Malware scanning:** uploads are validated by type/size/ZIP guards but not virus-scanned. Add
  ClamAV or a gateway scanner for untrusted uploads.
- **SSO/SAML/SCIM, field-level permissions, audit WORM:** not implemented.
- **Independent penetration test:** not performed.

## Environment caveats

- Container images are pinned except where noted; re-check tags and prefer digest pinning before a
  long-lived production deployment.
- SeaweedFS uses a generated identity file; credentials must be backed up and rotated deliberately.
- The pre-existing PostgreSQL service on port 5432 still listens on 0.0.0.0, but Windows Firewall has
  no allow rule; it was not modified. Do not add a LAN rule.
- Demo accounts and synthetic data remain (`admin@example.com` etc.; password in
  `var/secrets/demo-credentials.txt`). Remove or re-key them for any non-demo use.
- Docker `.env`, backups and runtime data are Git-ignored; backups contain secrets/encryption keys and
  must be protected. Keep `N8N_ENCRYPTION_KEY` and `CREDENTIAL_ENCRYPTION_KEY` stable or encrypted
  values become unrecoverable.
- No existing native databases, uploads or backups were deleted or reset.

## Required before production use

See section 16 of `docs/FINAL_PRODUCTION_HARDENING_REPORT.md` for the complete pre-real-data
checklist. The short version: real domain/certificate, real SMTP, demo data removal, malware scanning,
managed/HA data services, server-grade Docker engine, scheduled off-host backups with restore drills,
UAT sign-off and an independent security review.
