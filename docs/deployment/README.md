# Deployment

## 1. Services

| Service | Port (Compose host) | Purpose |
| --- | --- | --- |
| `web` (nginx) | 8180 | Built SPA; proxies `/api` to the API |
| `api` | 8100 | FastAPI, migrations, optional seed |
| `worker` | — | Celery worker (documents, AI, evaluations, webhooks) |
| `beat` | — | Celery beat (approval expiry, outbox, notifications, integration health) |
| `postgres` | 5433 | PostgreSQL 16 + pgvector |
| `redis` | 6380 | Broker/result backend and optional rate-limit store |
| `seaweedfs` | 9100 / 9101 | S3-compatible object storage; master UI (loopback only) |
| `n8n` | 5679 | Optional automation (loopback only) |
| `mailpit` | 8125 / 1126 | Email inspection (SMTP on 1126 to the host) |
| `prometheus` / `grafana` | 9190 / 3101 | Optional monitoring profile (loopback only) |

Only `web` (8180) binds to all interfaces. Every other host port is bound to `127.0.0.1`, so the
stack can run next to the verified native services without exposing databases or object storage to
the LAN.

## 1a. Native Windows deployment (verified)

The current host runs the production build natively as Windows services:

| Component | Bind | Service |
| --- | --- | --- |
| PostgreSQL 18.6 + pgvector 0.8.1 | `127.0.0.1:55432` | `resolvepgtest` |
| Redis-compatible (Memurai) | `127.0.0.1:6379` | `Memurai` |
| FastAPI | `127.0.0.1:8000` | `RESOLVE-API` |
| Celery worker / beat | — | `RESOLVE-Worker`, `RESOLVE-Beat` |
| Ollama (Qwen2.5 7B + BGE-M3) | `0.0.0.0:11434` (LAN blocked) | `RESOLVE-Ollama` |
| Mailpit | `127.0.0.1:1025/8025` | `RESOLVE-Mailpit` |
| nginx SPA + `/api` proxy | `127.0.0.1:8090` | `RESOLVE-Web` |

```powershell
.\scripts\start-resolve.ps1
.\scripts\status-resolve.ps1
.\scripts\health-check.ps1 -Deep
.\scripts\stop-resolve.ps1
.\scripts\backup-resolve.ps1
```

The native deployment is a **localhost rollback**: only TCP 8180 (Docker web) is allowed inbound
(Private profile, `LocalSubnet`); native nginx listens on `127.0.0.1:8090`. See
[`ONE_RUN_SETUP_REPORT.md`](ONE_RUN_SETUP_REPORT.md), [`LAN_ACCESS_GUIDE.md`](LAN_ACCESS_GUIDE.md)
and [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md).

## 2. First deployment

```bash
cp .env.example .env
```

Edit at minimum:

- `SECRET_KEY` — long random string (production startup rejects the development default)
- `POSTGRES_PASSWORD`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `N8N_BASIC_AUTH_PASSWORD`,
  `N8N_WEBHOOK_SECRET`
- `ENV=production`, `DEBUG=false`, `DEMO_MODE=false`, `SEED_DEMO=false`
- `CORS_ORIGINS` and `FRONTEND_URL` to your real origins
- `AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL` (or Ollama settings) if AI is required
- SMTP settings (Mailpit by default; configure a real relay for production)
- TLS termination: put the stack behind a reverse proxy (Caddy, Traefik, nginx, load balancer) and
  forward `X-Forwarded-Proto`; the API runs with `--proxy-headers`. Cookies become `Secure`
  automatically when `ENV=production`.

Then:

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head     # also runs automatically at container start
docker compose exec api python -m app.scripts.seed_demo   # only for demo environments
```

Do not seed demo data in production. `reset_demo` refuses to run when `ENV=production`.

Development override (hot reload + Vite):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

## 3. Environment variables

The full list is in [`.env.example`](../.env.example). Groups:

| Group | Key variables |
| --- | --- |
| Core | `ENV`, `DEBUG`, `SECRET_KEY`, `FRONTEND_URL`, `CORS_ORIGINS`, `LOG_LEVEL`, `LOG_JSON` |
| Database | `DATABASE_URL`, `POSTGRES_*`, `DB_POOL_SIZE` |
| Jobs | `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `TASK_RUNNER` |
| Security | `ACCESS_TOKEN_TTL_MINUTES`, `REFRESH_TOKEN_TTL_DAYS`, `RATE_LIMIT_*`, `MAX_UPLOAD_MB`, `APPROVAL_EXPIRY_HOURS`, `ALLOW_SELF_APPROVAL` |
| Storage | `STORAGE_BACKEND`, `STORAGE_LOCAL_DIR`, `S3_*` |
| Documents | `OCR_ENABLED`, `OCR_PROVIDER`, `TESSERACT_CMD`, `OCR_LANGUAGE`, `PDF_RENDER_DPI` |
| AI | `AI_PROVIDER`, `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, `AI_TIMEOUT_SECONDS`, `AI_MAX_RETRIES`, `AI_*_COST_PER_1K`, `AI_EMBEDDING_*` |
| Retrieval | `CHUNK_SIZE`, `CHUNK_OVERLAP`, `RETRIEVAL_TOP_K`, `RETRIEVAL_MIN_SCORE`, weights |
| Email | `EMAIL_BACKEND`, `SMTP_*`, `EMAIL_FROM`, `EMAIL_SINK_DIR` |
| Automation | `N8N_BASE_URL`, `N8N_API_KEY`, `N8N_WEBHOOK_SECRET`, `WEBHOOK_*` |

`TASK_RUNNER=auto` uses Celery when a broker is configured; otherwise a bounded local thread pool
keeps the product functional in development. `inline` runs jobs synchronously (tests/seed).

## 4. Migrations

- Alembic revisions: `c30cec670d6b` (initial) and `f7b2c9d4a1e3` (pgvector dimension/backfill/HNSW).
- The API container entrypoint waits for PostgreSQL, then runs `alembic upgrade head`.
- Workers and beat set `RUN_MIGRATIONS=false` so only one process migrates at startup.
- The initial migration creates the `vector` extension and `embedding_vec` column **only if pgvector
  is available**; the second revision resizes it to `AI_EMBEDDING_DIM`, backfills JSON embeddings and
  builds the HNSW cosine index. Native pgvector 0.8.1 was compiled and verified on this host.
- CI runs migrations against a real pgvector-enabled PostgreSQL and `alembic check`.

- Generate new revisions with:
  ```bash
  cd apps/api
  alembic revision --autogenerate -m "describe change"
  alembic upgrade head
  ```

## 4a. Docker/WSL2 on this host

**Verified 2026-11-19 after the required reboot.** Docker Desktop 29.9.3, WSL2 3.0.1 and the WSL2
kernel are installed; `HyperVisorPresent=True`. The full stack starts, and `docker compose ps` shows
the API, web, PostgreSQL, Redis, SeaweedFS, worker, beat and Mailpit healthy; n8n and the optional
Prometheus/Grafana profile also report healthy.

- Only web `8180` is reachable from the LAN. API, PostgreSQL, Redis, S3, Mailpit, n8n, Prometheus and
  Grafana bind to `127.0.0.1`.
- MinIO's images were retired upstream (`minio/mc` no longer pulls). Compose uses **SeaweedFS 4.54**
  with an identity file generated from `S3_ACCESS_KEY`/`S3_SECRET_KEY`, so anonymous S3 access is
  rejected. The volume cap is 64 × 1 GB to allow new buckets after restarts.
- WSL2 is capped at 8 GB / 4 CPUs in `%USERPROFILE%\.wslconfig`. Unbounded WSL2 memory caused Docker
  engine restarts during image builds on this 32 GB host.
- The API uses path-style S3 addressing for custom endpoints and re-checks the bucket after a
  concurrent-create race. nginx re-resolves the `api` service so recreating the API does not cause
  502s.
- Production should still point `S3_ENDPOINT_URL` at managed S3/R2/B2 and run behind TLS; SeaweedFS is
  the verified local development store, not a production HA object store.

## 5. Backups and restore

PostgreSQL is the source of truth. Documents live in S3-compatible storage (SeaweedFS in Compose, or
the local volume when `STORAGE_BACKEND=local`).

Use the helper scripts; they dump the database through the container, mirror documents with
`app.scripts.s3_sync` (boto3, path style) and write a manifest with row counts and the dump SHA-256:

```powershell
# Windows
.\infrastructure\scripts\backup.ps1
.\infrastructure\scripts\restore.ps1 -BackupDir .\backups\compose-<stamp> -Database resolve_restore
```

```bash
# Linux/macOS
infrastructure/scripts/backup.sh
infrastructure/scripts/restore.sh backups/compose-<stamp> resolve_restore
```

Restore defaults to a **new** database and a new bucket (`<bucket>-restore`), so it can be verified
without touching live data. It prints restored row counts; compare them with the backup manifest. The
document restore uploads the backed-up tree with `s3_sync` and can be hash-checked against the source
directory. Verify a restore quarterly and document the outcome.

## 6. Monitoring

- `GET /health/ready` returns dependency status for the database, storage, Redis, AI configuration and
  the task runner. It returns HTTP 503 when the database or storage is unhealthy.
- Structured JSON logs are available with `LOG_JSON=true`; each request logs method, path, status,
  duration and request ID.
- `/api/v1/analytics/ai-usage` and `/jobs` expose AI usage and background job health.
- Optional Prometheus scrapes readiness; `infrastructure/monitoring` contains the config. Add
  exporters (postgres, redis) as needed.
- Alert on: failed Celery jobs, webhook failure rate, readiness failures, disk usage, approval backlog.

## 7. Scaling

- API is stateless: scale horizontally behind a load balancer; keep `X-Forwarded-*` headers.
- Celery workers scale independently; set concurrency by OCR/AI workload, not CPU alone.
- Use managed PostgreSQL with pgvector and managed Redis/S3 in production.
- Keep the API and worker images identical; only the command changes.
- Review `TASK_INLINE_MAX_CONCURRENCY` before disabling Celery.

## 8. Production checklist

- [ ] `ENV=production`, `DEBUG=false`, `DEMO_MODE=false`, `SEED_DEMO=false`
- [ ] Strong `SECRET_KEY`, database, S3 and n8n credentials from a secret manager
- [ ] HTTPS terminated and forwarded correctly; CORS allowlist contains only real origins
- [ ] PostgreSQL 16 with pgvector, managed backups and point-in-time recovery
- [ ] Object storage lifecycle/versioning enabled; malware scanning considered
- [ ] SMTP relay configured and SPF/DKIM aligned
- [ ] AI provider key restricted, budgets and cost alerts configured
- [ ] Migration job runs before new API replicas; workers/beat run with `RUN_MIGRATIONS=false`;
      rollback plan documented
- [ ] Monitoring, alerts and log retention configured
- [ ] Demo accounts removed (`reset_demo` never used; seed disabled)
