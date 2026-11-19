# Deployment overview

## 1. Current deployment

| Item | Value |
| --- | --- |
| Host | Windows 10 LTSC 19045, Docker Desktop 4.99.0 / Engine 29.9.3 / Compose 5.7.0 |
| WSL2 VM | 8 GB RAM, 4 CPUs |
| Project | `C:\path\to\resolve`, Compose project `resolve` |
| Primary URL | `https://192.168.1.10:8180` (LAN), `https://localhost:8180` (host) |
| Certificate | mkcert local CA, SANs `resolve.local`, `192.168.1.10`, `localhost`, `127.0.0.1`, valid to 2029-02-19 |
| LAN exposure | TCP 8180 only, Private profile, `LocalSubnet` |
| Rollback | Native Windows services on `127.0.0.1:8090` |
| Release | tag `v1.0.0` (see `docs/FINAL_PROJECT_CLOSURE_REPORT.md`) |

## 2. Services (18 containers)

| Service | Image | Exposure |
| --- | --- | --- |
| web (nginx) | nginx 1.27 + React build | `8180:443`, HTTP `127.0.0.1:8081:80` |
| api | FastAPI/uvicorn | `127.0.0.1:8100:8000` |
| worker / beat | Celery | internal |
| postgres | pgvector/pg16 | `127.0.0.1:5433` |
| redis | redis:7-alpine | `127.0.0.1:6380` |
| seaweedfs | chrislusf/seaweedfs 4.54 | `127.0.0.1:9100/9101` |
| n8n | n8nio/n8n 2.48.6 | `127.0.0.1:5679` |
| mailpit | axllent/mailpit 1.34 | `127.0.0.1:8125/1126` |
| prometheus | prom/prometheus 3.1.0 | `127.0.0.1:9190` |
| alertmanager | prom/alertmanager 0.28 | `127.0.0.1:9193` |
| grafana | grafana 13.3.1 | `127.0.0.1:3101` |
| exporters | postgres, redis, nginx, celery, node, blackbox | Docker network only |

Ollama runs on the host at `:11434` and is reached with `host.docker.internal`.

## 3. First start

```powershell
cd "C:\path\to\resolve"
Copy-Item .env.example .env          # fill every blank secret
mkcert -install
mkcert -cert-file var\certs\server.pem -key-file var\certs\server-key.pem `
  resolve.local 192.168.1.10 localhost 127.0.0.1
Copy-Item (Join-Path (mkcert -CAROOT).Trim() "rootCA.pem") var\certs\rootCA.pem
docker compose --env-file .env --profile monitoring up -d --build
.\scripts\health-check.ps1 -Deep
```

Then provision automation once:

```powershell
.\.venv\Scripts\python.exe scripts\provision-n8n-owner.py
.\.venv\Scripts\python.exe scripts\provision-n8n-credential.py
.\.venv\Scripts\python.exe scripts\generate-n8n-workflows.py
# import the JSON files with `docker compose exec n8n n8n import:workflow ...`
.\.venv\Scripts\python.exe scripts\activate-n8n-workflows.py
.\.venv\Scripts\python.exe scripts\provision-n8n-integrations.py
.\.venv\Scripts\python.exe scripts\provision-automation-user.py
```

## 4. Operations commands

```powershell
.\scripts\start-resolve.ps1        # Docker first, health wait, URLs
.\scripts\stop-resolve.ps1         # preserves all volumes/data
.\scripts\restart-resolve.ps1
.\scripts\status-resolve.ps1
.\scripts\health-check.ps1 -Deep
.\scripts\backup-resolve.ps1
.\scripts\restore-resolve.ps1 -BackupDir .\backups\compose-<stamp>
```

Scheduled tasks:

- `RESOLVE-Docker-Watchdog` — every minute, restarts Docker Desktop if the engine is down and starts
  missing Compose services (sentinel `var/docker-watchdog.disabled` for intentional stops).
- `RESOLVE-Daily-Backup` — daily 02:30, runs the verified backup and writes a Prometheus timestamp.

## 5. HTTPS and trust

- Only nginx terminates TLS.
- HSTS one year; TLS 1.2/1.3; HTTP/2.
- Windows trusts the mkcert CA after `mkcert -install`.
- macOS: copy `var/certs/rootCA.pem` and run
  `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain rootCA.pem`.
- Windows `curl` needs `--ssl-no-revoke` because mkcert has no CRL/OCSP endpoint; browsers validate
  normally.

## 6. Monitoring

| Endpoint | Purpose |
| --- | --- |
| `https://<host>:8180/health` | liveness |
| `/health/ready` | DB, Redis, storage and AI readiness |
| `127.0.0.1:9190` | Prometheus |
| `127.0.0.1:3101` | Grafana (4 dashboards) |
| `127.0.0.1:9193` | Alertmanager |
| `127.0.0.1:8125` | Mailpit (alerts and test mail) |

Alerts: API/DB/Redis/storage/worker down, outbox stalled, queue backlog, 5xx, latency, approval
backlog, document failures, Ollama/n8n/nginx down, memory, disk, stale backup, certificate expiry.

## 7. Backup and restore

- Backup: `pg_dump -Fc`, S3 mirror, `manifest.json` with counts and SHA-256, `database.toc.txt`.
- Restore default: new database `resolve_restore_<timestamp>` + new bucket; live data untouched.
- Verified: counts, `vector(1024)`, HNSW, nearest-neighbour query, object SHA-256, login and workflow.
- Backups contain sensitive data: keep them off-host and access-controlled.

## 8. Recovery playbook

| Symptom | Action |
| --- | --- |
| Docker engine down | watchdog restarts it; otherwise `start-docker.ps1` |
| API unhealthy | `docker compose ps`, logs, DB/Redis health, recreate `api` |
| nginx 502 after API recreate | nginx re-resolves Docker DNS; check `web` logs |
| S3 bucket error | restart `seaweedfs`, check volume health |
| Wrong config | restore `.env` from `var/env-backups/`, recreate the service |
| Data incident | restore the latest verified backup into a new database, verify, then switch |
| Full rollback | native services via `start-native.ps1` (loopback only) |

Never run `docker compose down -v`. Never reset the database to "fix" a problem.

## 9. What is intentionally not here

Kubernetes, a public domain, external SMTP, a Linux production engine, HA data services and malware
scanning are not part of this deployment. Each has a documented integration point and a reason in
[KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).
