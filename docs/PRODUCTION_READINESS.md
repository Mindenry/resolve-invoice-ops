# Production readiness

This document separates verified evaluation capability from production requirements.

## 1. Readiness matrix

| Area | State | Evidence |
| --- | --- | --- |
| Docker primary deployment | **READY (evaluation)** | 11 containers up; API/web/DB/Redis/S3/Mailpit healthy |
| Native rollback | **READY (localhost)** | services running; UI `127.0.0.1:8090` |
| PostgreSQL 16.16 | **READY** | migrations, backup/restore verified |
| pgvector 0.8.7 | **READY** | `vector(1024)`, JSON backfill, HNSW index, `Index Scan` |
| Redis / Celery worker + beat | **READY** | real jobs and investigations executed |
| Local AI | **READY (7B quality)** | Ollama + Qwen2.5 7B + BGE-M3; validated citations |
| OCR | **READY** | Tesseract 5.4 eng/tha in container; live confidence 0.955, 7 fields |
| Object storage | **READY (single node)** | SeaweedFS S3; upload/download/migration verified |
| Frontend | **READY** | production nginx bundle; Playwright 10/10 via LAN |
| LAN access | **READY (HTTP)** | single port 8180, Private/LocalSubnet firewall |
| HTTPS | **NOT READY** | HTTP dev mode; private CA/TLS required |
| n8n | **PARTIAL** | healthy service; no workflows/credentials configured |
| Monitoring | **PARTIAL** | Prometheus/Grafana healthy; no RESOLVE dashboards/alerts |
| Backup/restore | **READY** | Docker DB + 42 objects restored into isolated targets |
| Malware scanning | **NOT IMPLEMENTED** | add gateway/ClamAV for untrusted files |
| SSO/SCIM/audit WORM | **NOT IMPLEMENTED** | roadmap |

## 2. Required before real financial data

1. HTTPS on the LAN (private CA or trusted reverse proxy); `ENV=production`, `DEBUG=false`,
   `DEMO_MODE=false`, `Secure` cookies.
2. Remove/change demo users and data; strong unique secrets in a secret manager.
3. Managed PostgreSQL with PITR/encryption, managed S3-compatible storage, managed Redis or HA.
4. Malware scanning, centralized logs/metrics/alerts, retention/RTBF procedures.
5. Pin all container images (Prometheus/Grafana are still `latest`) and run on a server-grade Docker
   engine, not Docker Desktop.
6. Independent security review/pen test.
7. Physical macOS Safari/Chrome acceptance test.

## 3. Current security posture

Verified: one LAN port (8180); internal services loopback; tenant isolation 404; RBAC 403;
self-approval 403; approval/execute separation; rate limiting; CORS allowlist; security headers;
encrypted integration credentials; webhook signatures; upload size/type/ZIP guards; audit rows;
AI cannot execute actions.

Not production-safe yet: HTTP, demo credentials/data, no malware scan, no SSO, single-node
PostgreSQL/Redis/SeaweedFS, Docker Desktop workstation runtime.

## 4. Operations and recovery

Use `scripts/start-resolve.ps1`, `stop-resolve.ps1`, `restart-resolve.ps1`, `status-resolve.ps1`,
`health-check.ps1 -Deep`, `backup-resolve.ps1`, `restore-resolve.ps1`. See
`OPERATIONS_RUNBOOK.md`, `BACKUP_RESTORE_RUNBOOK.md`, `DOCKER_DEPLOYMENT.md`, `KNOWN_LIMITATIONS.md`.

## 5. Go/no-go

- **Go:** controlled LAN evaluation with synthetic data over HTTP, with native rollback available.
- **No-go:** real financial production until HTTPS, identity/secrets, malware scanning, managed
  data services, monitoring and an independent security review are complete.
