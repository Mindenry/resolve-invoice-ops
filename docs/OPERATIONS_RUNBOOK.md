# Operations runbook

## 1. Deployment modes

| Mode | Status | Entry point | Data |
| --- | --- | --- | --- |
| Docker Compose | **Primary / LAN** | `https://192.168.1.107:8180` | Docker volumes: `resolve_postgres_data`, `resolve_seaweedfs_data`, `resolve_n8n_data`, `resolve_grafana_data` |
| Native Windows | **Rollback / localhost** | `http://127.0.0.1:8090` | `resolve_live` on isolated PostgreSQL 55432 + local storage |

The two deployments use separate databases and storage. Do not point both at the same database or
bucket. Native data is preserved by design; Docker was initialized with its own synthetic data.

## 2. Start, stop, restart

```powershell
cd "E:\Code\AI project"

.\scripts\start-resolve.ps1        # auto: Docker first, native fallback
.\scripts\start-resolve.ps1 -Mode docker
.\scripts\start-resolve.ps1 -Mode native

.\scripts\stop-resolve.ps1         # stop both app layers, preserve volumes
.\scripts\stop-resolve.ps1 -DockerOnly
.\scripts\stop-resolve.ps1 -NativeOnly
.\scripts\stop-resolve.ps1 -StopDockerDesktop

.\scripts\restart-resolve.ps1
.\scripts\restart-resolve.ps1 -Mode docker
.\scripts\restart-resolve.ps1 -Mode native
.\scripts\restart-docker.ps1
```

`start-docker.ps1` starts Docker Desktop through Explorer if needed, runs
`docker compose --profile monitoring up -d`, and waits for API/web health. It never builds unless
images are missing.

## 3. Status and health

```powershell
.\scripts\status-resolve.ps1
.\scripts\status-docker.ps1
.\scripts\health-check.ps1
.\scripts\health-check.ps1 -Deep
.\scripts\health-check.ps1 -Native -Deep
```

Health checks cover engine, required containers, API readiness (DB/storage/Redis/AI), web, container→
Ollama, pgvector extension/vectors/HNSW index, n8n, Mailpit, firewall and LAN listener. `-Deep` calls
Ollama for a real generation.

## 4. Endpoints

| Purpose | Primary Docker |
| --- | --- |
| UI | `https://localhost:8180` / `https://192.168.1.107:8180` |
| Health | `/health` through 8180 |
| API | `127.0.0.1:8100` |
| Mailpit | `127.0.0.1:8125` |
| n8n | `127.0.0.1:5679` |
| Grafana | `127.0.0.1:3101` |
| Prometheus | `127.0.0.1:9190` |
| S3 API / console | `127.0.0.1:9100` / `127.0.0.1:9101` |
| PostgreSQL | `127.0.0.1:5433` |
| Redis | `127.0.0.1:6380` |

Only 8180 is allowed inbound by Windows Firewall (Private, LocalSubnet). Do not add rules for
database, Redis, S3 console, n8n or monitoring ports.

## 5. Logs

```powershell
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f beat
docker compose logs -f web
docker compose logs -f postgres
docker compose logs -f seaweedfs

# native rollback
Get-Content var\logs\RESOLVE-API.err.log -Tail 50
Get-Content var\logs\RESOLVE-Worker.err.log -Tail 50
```

Docker Desktop diagnostics: `%LOCALAPPDATA%\Docker\log\host` and `...\vm`.
Post-reboot Docker automation log: `var\logs\post-reboot-docker.log`.

## 6. Scheduled tasks / autostart

- `RESOLVE-Docker-Desktop` — launches Docker Desktop through Explorer at logon.
- `RESOLVE-PostReboot-Docker` — 1 minute after logon, waits for the engine and starts Compose;
  writes the post-reboot log.
- Native Windows services (`resolvepgtest`, `Memurai`, `RESOLVE-*`) start automatically.
- Docker containers use `restart: unless-stopped`.

## 7. Common recovery

| Problem | Action |
| --- | --- |
| Docker pipe missing / HTTP 500 | Start Docker Desktop, wait for engine; run `scripts/start-docker.ps1` |
| Docker Desktop exits when shell closes | Launch through `start-docker.ps1`/logon task, not a child process |
| API unhealthy | `docker compose ps`; check postgres/redis health and `docker compose logs api` |
| Worker not processing | `docker compose ps worker`; logs; Redis health; restart worker |
| S3 InternalError for new bucket | Restart `seaweedfs`; check volume server health |
| Disk full | Remove old backups/build cache carefully; never delete volumes without a verified backup |
| AI 429/timeout | Check Ollama, model loaded, timeout 180 s; retry |
| Repeated login 429 | Rate limit; wait or raise `RATE_LIMIT_LOGIN` for demo |
| Native rollback needed | `start-resolve.ps1 -Mode native`; native UI is `127.0.0.1:8090` |

## 8. Safe maintenance rules

- Never run `docker compose down -v` on data-bearing volumes.
- Take a backup before schema or key changes.
- Use `alembic upgrade head`; do not edit production tables by hand.
- Do not rotate secrets without a rotation/migration plan.
- Keep at least one working deployment untouched until the other passes verification.
- Demo credentials/data are not production identity or data.

## 9. Access and security

- LAN URL: `https://192.168.1.107:8180` (valid mkcert certificate; TLS 1.2/1.3, HSTS).
- Firewall: `RESOLVE Docker Web (TCP 8180)`, Private, LocalSubnet. The old 8090 LAN rule is disabled.
- Management UIs are loopback only: n8n `127.0.0.1:5679`, Grafana `127.0.0.1:3101`, Prometheus
  `127.0.0.1:9190`, Alertmanager `127.0.0.1:9193`, Mailpit `127.0.0.1:8125`.
- For real data: replace the local CA with a managed certificate, remove demo data/accounts, and
  finish the items in `docs/KNOWN_LIMITATIONS.md`.

## 10. Monitoring and automation

```powershell
# Stack health, targets and alerts
curl.exe --ssl-no-revoke https://192.168.1.107:8180/health
curl.exe http://127.0.0.1:9190/api/v1/targets
curl.exe http://127.0.0.1:9190/api/v1/alerts

# n8n executions are visible in the loopback UI; workflows A-E are documented in
# docs/N8N_RESOLVE_AUTOMATION.md
```

- Alerts go to Mailpit (`ops@resolve.local`); see `docs/OBSERVABILITY_RUNBOOK.md`.
- Backup freshness is exported as `resolve_backup_last_success_timestamp_seconds`; if it is older
  than 26 hours the `ResolveBackupStale` alert fires.
- The Docker watchdog task `RESOLVE-Docker-Watchdog` runs every minute. Create
  `var/docker-watchdog.disabled` before an intentional stop so it does not restart Docker.
