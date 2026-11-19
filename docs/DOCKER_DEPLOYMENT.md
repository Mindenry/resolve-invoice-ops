# Docker deployment

This is the primary RESOLVE deployment on the Windows host. The native Windows services remain as a
localhost rollback.

## 1. Prerequisites

- Docker Desktop 4.99.0 with Docker Engine 29.9.3 and Compose v5.7.0
- WSL2 `docker-desktop` distribution, VirtualMachinePlatform enabled
- Ollama 0.40.16 with `qwen2.5:7b-instruct` and `bge-m3`
- 8 GB / 4 CPUs allocated to the Docker VM via `%USERPROFILE%\.wslconfig` (host 32 GB), 300+ GB free disk

Docker Desktop is started through Explorer and registered as a logon task so it survives the agent
shell. `com.docker.service` is also present but the per-user backend is what serves the Linux engine.

## 2. Services and host ports

| Service | Image | Host binding |
| --- | --- | --- |
| web (nginx SPA + `/api` proxy) | `resolve-web:local` | `0.0.0.0:8180` |
| api | `resolve-api:local` | `127.0.0.1:8100` |
| worker | `resolve-api:local` | internal |
| beat | `resolve-api:local` | internal |
| postgres | `pgvector/pgvector:pg16` | `127.0.0.1:5433` |
| redis | `redis:7-alpine` | `127.0.0.1:6380` |
| object storage (S3) | `chrislusf/seaweedfs:4.54` | `127.0.0.1:9100` S3, `127.0.0.1:9101` console |
| mailpit | `axllent/mailpit:v1.34.0` | `127.0.0.1:8125`, SMTP `1126` |
| n8n | `n8nio/n8n:2.48.6` | `127.0.0.1:5679` |
| prometheus | `prom/prometheus:latest` | `127.0.0.1:9190` |
| grafana | `grafana/grafana:latest` | `127.0.0.1:3101` |

Only 8180 is opened in Windows Firewall (Private, `LocalSubnet`). All other ports are loopback-only.

## 3. Storage

MinIO's official images are no longer distributed (archived upstream, pull access denied). The stack
uses **SeaweedFS 4.54** as the S3-compatible object store:

- single node: master, volume, filer and S3 gateway in one container
- credentials are required and generated from `S3_ACCESS_KEY` / `S3_SECRET_KEY` in `.env` into a
  temporary identity file (no anonymous S3)
- bucket `resolve-documents`, persisted in volume `resolve_seaweedfs_data`
- application config: `STORAGE_BACKEND=s3`, `S3_ENDPOINT_URL=http://seaweedfs:8333`,
  `S3_USE_SSL=false`
- the demo workspace was reseeded into the bucket (42 objects) and verification uploads were stored
  in S3; downloads and backup/restore were verified by SHA-256

`storage` in `/health/ready` reports `backend: s3` and bucket reachability.

## 4. AI path

- Host Ollama listens `0.0.0.0:11434`; Windows Firewall has no LAN allow rule for 11434.
- Containers use `AI_BASE_URL=http://host.docker.internal:11434`.
- Verified from inside the API container:
  `curl http://host.docker.internal:11434/api/version` → `0.40.16`.
- Models: Qwen2.5 7B Instruct (chat) and BGE-M3 (1024-dim embeddings); the vector column is
  `vector(1024)`.

## 5. Start / stop / restart

```powershell
cd "E:\Code\AI project"

# Primary (Docker) — starts Docker Desktop via Explorer if needed, up -d, waits for health
.\scripts\start-docker.ps1

# Through the top-level wrapper (auto → Docker, fallback native)
.\scripts\start-resolve.ps1

.\scripts\stop-docker.ps1        # compose stop; volumes preserved
.\scripts\stop-resolve.ps1       # stops Docker + native app services; data preserved
.\scripts\restart-docker.ps1
.\scripts\restart-resolve.ps1

.\scripts\status-docker.ps1
.\scripts\status-resolve.ps1
.\scripts\health-check.ps1 -Deep
```

Do **not** use `docker compose down -v`; it would delete data volumes.

## 6. Build and migrations

```powershell
docker compose --env-file .env build api web
docker compose --env-file .env --profile monitoring up -d
```

The API entrypoint waits for PostgreSQL, runs `alembic upgrade head`, and starts uvicorn. Worker and
beat set `RUN_MIGRATIONS=false` so only one process migrates.

Alembic revisions:

- `c30cec670d6b` initial schema (creates pgvector extension/column only when available)
- `f7b2c9d4a1e3` vector dimension (`AI_EMBEDDING_DIM`), JSON backfill, HNSW index

If the version table and schema ever disagree, repair only the vector revision:

```powershell
docker compose exec -T -e AI_EMBEDDING_DIM=1024 api alembic downgrade c30cec670d6b
docker compose exec -T -e AI_EMBEDDING_DIM=1024 api alembic upgrade head
docker compose restart api worker
```

## 7. Verification evidence

- `docker compose ps`: 11 services up; api/postgres/redis/seaweedfs/mailpit/web healthy.
- PostgreSQL 16.16; pgvector 0.8.7; `vector(1024)`; HNSW index; `EXPLAIN ANALYZE` shows
  `Index Scan using ix_document_chunks_embedding_vec`.
- Retrieval mode `hybrid+pgvector`; new embeddings synced.
- Full 27-step workflow completed, including real AI investigation and SMTP execution.
- Playwright 10/10 against `https://192.168.1.107:8180`.
- OCR in the API container: Tesseract eng+tha, live PNG confidence **0.955**, 7 fields extracted.
- 46 objects in `resolve-documents` after seed + verification uploads.
- Backup/restore: DB and 42 objects restored into separate targets; 42/42 SHA-256 hashes matched.
- Backend: 134 passed on PostgreSQL, 133 passed + 1 skip on SQLite; Ruff clean.
- n8n `/healthz` 200, Prometheus and Grafana health endpoints 200.

## 8. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `dockerDesktopLinuxEngine` 500 / pipe missing | Start Docker Desktop through Explorer, wait for engine; inspect Docker Desktop logs |
| Docker Desktop dies after shell exits | Use `scripts/start-docker.ps1`/logon task; it launches via Explorer, not as a child |
| `pull access denied` for MinIO | MinIO is retired; the stack uses SeaweedFS. Do not re-add MinIO |
| S3 `InternalError` for a new bucket | Restart `seaweedfs`; its single-node volume provisioning needs a healthy volume server |
| API unhealthy after engine restart | Ensure postgres/redis have `restart: unless-stopped`; run `docker compose up -d` |
| 429 on repeated logins | Demo rate limit; wait one minute or raise `RATE_LIMIT_LOGIN` for multi-user demos |
| API can’t reach AI | Check Ollama is running and `host.docker.internal:11434` from the API container |
| Web 502 | API not healthy; `docker compose logs api`; check DB/Redis |

## 9. Remaining Docker limitations

- Single-node SeaweedFS (no HA).
- `n8n`, `prometheus`, `grafana` images are still on `latest`; pin them before long-term production.
- n8n workflows/credentials are not configured.
- Grafana dashboards/alerts for RESOLVE are not provisioned.
- Docker Desktop is a workstation runtime, not a server-grade Linux engine.
