# Known limitations

Statuses are honest and current as of 2026-11-19 post-reboot verification.

## VERIFIED

- Docker Compose primary stack with API, worker, beat, web, PostgreSQL 16.16, pgvector 0.8.7,
  Redis 7, SeaweedFS S3 4.54, Mailpit 1.34.0, n8n 2.48.6, Prometheus and Grafana.
- `vector(1024)`, JSON backfill, HNSW index and a real `Index Scan`.
- Container→Ollama access; real Qwen2.5 7B investigation with validated evidence.
- OCR in the container (Tesseract 5.4, eng/tha), confidence 0.955 on a live PNG; 7 fields extracted.
- S3 upload/download and Compose backup/restore with SHA-256 checks (42/42 hashes matched).
- Full 27-step workflow through nginx (approval, SMTP, execution, audit, analytics).
- Docker backup/restore into separate DB/bucket including vectors.
- Playwright 10/10 against the Docker LAN URL.
- Backend: **134 passed on PostgreSQL, 133 passed + 1 skip on SQLite**; Ruff clean.
- Only TCP 8180 exposed to the LAN; all internal services loopback-only.

## PARTIALLY VERIFIED

- **macOS client:** no physical Mac was available. The LAN URL, firewall, login/refresh, upload,
  document download, AI investigation and approval were exercised from Windows against
  `192.168.1.107:8180`. Safari was not tested. Use `docs/LAN_ACCESS_GUIDE.md`.
- **n8n:** service is healthy (`/healthz` 200), but no RESOLVE workflows/credentials were imported or
  executed. Templates exist under `infrastructure/n8n/workflows`.
- **Monitoring:** Prometheus/Grafana are running and healthy, but RESOLVE-specific dashboards, alerts
  and exporters (Postgres/Redis) are not provisioned.
- **Celery beat:** running and schedules observed; not run over a long multi-hour window.
- **AI quality:** a 7B local model can produce imprecise root-cause wording. Citations are validated;
  invalid ones are stored/flagged. External provider quality/cost is unverified.

## NOT VERIFIED / BLOCKED

- **HTTPS on the LAN:** not configured. Current deployment is HTTP `ENV=development`; refresh cookies
  are not `Secure`. Do not use real financial data over HTTP. A private CA/mkcert and nginx TLS are
  required before production.
- **Docker Desktop as a server runtime:** it is a workstation runtime and per-user. Logon tasks start
  it through Explorer. A production server should use Docker Engine on Linux or a managed container
  platform.
- **High availability:** PostgreSQL, Redis and SeaweedFS are single-node; no replication/failover.
- **Malware scanning:** uploaded files are validated by type/size/ZIP guards but not virus-scanned.
  Add ClamAV or a gateway scanner for untrusted uploads.
- **SSO/SAML/SCIM, field-level permissions, audit WORM:** not implemented.
- **Git release:** repository has no commits and no configured Git identity. No commit/tag was
  created. Working tree is intact; configure identity and review ignored files before committing.

## Environment caveats

- Docker images `prom/prometheus:latest` and `grafana/grafana:latest` remain on `latest`. Pin digests/
  versions before long-term production.
- SeaweedFS uses a generated identity file; credentials must be backed up and rotated deliberately.
- The pre-existing PostgreSQL service on port 5432 still listens on 0.0.0.0, but Windows Firewall has
  no allow rule; it was not modified. Do not add a LAN rule.
- Demo accounts (`admin@example.com` etc., `the password in var/secrets/demo-credentials.txt`) and synthetic data remain. Remove/change them
  for any non-demo use.
- Docker `.env`, backups and runtime data are git-ignored; backups contain secrets/encryption keys and
  must be protected.
- No changes were made to existing native databases, uploads or backups.

## Required before production use

1. HTTPS with a trusted/private CA; `ENV=production`, `DEBUG=false`, `DEMO_MODE=false`.
2. Replace demo users/data; strong secrets in a secret manager; rotate keys with a plan.
3. Managed PostgreSQL with PITR, managed S3-compatible storage, managed Redis or HA.
4. Malware scanning, centralized logs/metrics/alerts, retention/RTBF procedures.
5. Pin all images and run on a server-grade Docker engine.
6. Independent security review/pen test.
