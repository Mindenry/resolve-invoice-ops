# Production readiness

This document separates verified capability from the remaining production requirements.

## 1. Readiness matrix

| Area | State | Evidence |
| --- | --- | --- |
| Docker primary deployment | **READY (candidate)** | 18 services up; core services healthy |
| Native rollback | **READY (localhost)** | services running; UI `127.0.0.1:8090` |
| HTTPS (Windows/LAN) | **READY** | mkcert chain, HSTS, secure cookies, Playwright 10/10 |
| macOS HTTPS trust | **BLOCKED** | no Mac; CA + commands documented |
| PostgreSQL 16.16 | **READY** | migrations, backup/restore verified |
| pgvector 0.8.7 | **READY** | `vector(1024)`, HNSW index, nearest-neighbour query |
| Redis / Celery worker + beat | **READY** | real jobs, outbox fan-out every minute |
| Local AI | **READY (7B quality)** | Ollama Qwen2.5 7B + BGE-M3, validated citations |
| OCR | **READY** | Tesseract 5.4 eng/tha in container |
| Object storage | **READY (single node)** | SeaweedFS S3; upload/download/backup verified |
| Frontend | **READY** | production nginx bundle; Playwright 10/10 over HTTPS |
| Authentication | **READY** | rotated credentials, refresh rotation, logout, rate limit |
| Authorization | **READY** | RBAC, tenant isolation, self-approval block, separation |
| n8n automation | **READY (single instance)** | five active workflows, HMAC, idempotency, Mailpit |
| Monitoring | **READY** | 13/13 targets, 20 rules, 4 dashboards, alert delivery |
| Backup/restore | **READY** | fresh backup + isolated restore with SHA/vector checks |
| Restart persistence | **READY** | data, workflows, dashboards, certs, login survive restart |
| Release management | **READY** | tag `v1.0.0`, clean tree, secret scan clean |
| Real SMTP | **BLOCKED** | no external relay; Mailpit only |
| Public DNS/domain | **BLOCKED** | no domain; IP + local CA |
| Malware scanning | **NOT IMPLEMENTED** | add gateway/ClamAV for untrusted files |
| SSO/SCIM/audit WORM | **NOT IMPLEMENTED** | roadmap |
| HA data services | **NOT IMPLEMENTED** | single-node PG/Redis/SeaweedFS |
| Penetration test | **NOT DONE** | schedule before production |

## 2. Required before real financial data

1. Delete or fully re-key the demo workspace and accounts; keep only named users.
2. Replace Mailpit with a real SMTP relay over TLS (SPF/DKIM/DMARC).
3. Obtain a real domain + internal DNS and a managed certificate instead of the local CA.
4. Move to a Linux Docker Engine or managed container host with automated patching.
5. Managed PostgreSQL (PITR), managed Redis and HA object storage.
6. Install and verify the daily backup task, off-host copy and periodic restore drills.
7. Confirm document/audit retention and legal requirements.
8. Add malware scanning for untrusted uploads.
9. Review rate-limit topology (real client IPs, shared limiter storage).
10. UAT sign-off and an independent security review/pen test.

## 3. Current security posture

Verified: one LAN port (8180) on the Private profile with `LocalSubnet`; internal services loopback
or Docker-internal; retired demo password rejected; production mode with no debug; tenant isolation
404; RBAC 403; self-approval 403; approval/execute separation; login rate limiting; CORS allow-list;
single-valued security headers; encrypted integration credentials; webhook HMAC; upload size/type/ZIP
guards; audit rows; AI cannot execute actions; n8n cannot approve or execute.

Not production-safe yet: demo credentials/data, no malware scan, no SSO, single-node data services,
Docker Desktop workstation runtime, Mailpit instead of real mail.

## 4. Operations and recovery

Use `scripts/start-resolve.ps1`, `stop-resolve.ps1`, `restart-resolve.ps1`, `status-resolve.ps1`,
`health-check.ps1 -Deep`, `backup-resolve.ps1`, `restore-resolve.ps1`. See
`OPERATIONS_RUNBOOK.md`, `BACKUP_RESTORE_RUNBOOK.md`, `DOCKER_DEPLOYMENT.md`,
`OBSERVABILITY_RUNBOOK.md`, `N8N_RESOLVE_AUTOMATION.md`, `RELEASE_MANAGEMENT.md`,
`KNOWN_LIMITATIONS.md`.

## 5. Go/no-go

- **Go:** controlled LAN evaluation and UAT with synthetic data over HTTPS, with native rollback
  available and the watchdog enabled.
- **No-go:** real financial production until the section 2 items and the independent review are
  complete.
