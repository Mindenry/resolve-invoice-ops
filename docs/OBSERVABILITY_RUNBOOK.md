# Observability runbook

Prometheus, Alertmanager and Grafana run in the `monitoring` Compose profile. Every exporter is on
the Docker network only; only the three user-facing UIs are published, and only on loopback.

## 1. Endpoints

| Service | Host URL | Exposure |
| --- | --- | --- |
| Prometheus | <http://127.0.0.1:9190> | loopback |
| Alertmanager | <http://127.0.0.1:9193> | loopback |
| Grafana | <http://127.0.0.1:3101> | loopback (`admin` + `GRAFANA_PASSWORD` in `.env`) |
| Mailpit (alert inbox) | <http://127.0.0.1:8125> | loopback |
| postgres-exporter | `postgres-exporter:9187` | Docker only |
| redis-exporter | `redis-exporter:9121` | Docker only |
| nginx-exporter | `nginx-exporter:9113` | Docker only |
| celery-exporter | `celery-exporter:9808` | Docker only |
| node-exporter | `node-exporter:9100` | Docker only |
| blackbox-exporter | `blackbox-exporter:9115` | Docker only |

Start: `docker compose --env-file .env --profile monitoring up -d`

Grafana is provisioned from Git: datasource `prometheus` (uid `prometheus`) and four dashboards in
the `RESOLVE` folder. Anonymous access and sign-up are disabled.

## 2. Scrape targets

`infrastructure/monitoring/prometheus.yml`:

| Job | Target | Notes |
| --- | --- | --- |
| resolve-api | `api:8000/metrics` | HTTP counters/histograms + business gauges |
| prometheus | `localhost:9090` | self-monitoring |
| postgres | `postgres-exporter:9187` | exporter needs `POSTGRES_PASSWORD` |
| redis | `redis-exporter:9121` | |
| nginx | `nginx-exporter:9113` → `web:8080/nginx_status` | stub_status is internal-only |
| celery | `celery-exporter:9808` | worker count and queue length from the broker |
| alertmanager | `alertmanager:9093` | |
| node | `node-exporter:9100` | Docker VM CPU/RAM/disk |
| blackbox | Ollama, n8n, SeaweedFS, nginx_status | HTTP probes |
| blackbox-cert | `https://web:443/` | TLS expiry only (hostname check skipped by design) |

Verified: 13/13 targets `up`.

## 3. Application metrics

`GET /metrics` on the API (loopback only) exposes:

**HTTP**: `resolve_http_requests_total{method,route,status}`,
`resolve_http_request_duration_seconds_bucket{method,route}`.

**Dependency health**: `resolve_db_up`, `resolve_redis_up`, `resolve_storage_up`,
`resolve_ai_configured`.

**Business state (real DB queries at scrape time)**: `resolve_cases_total`, `resolve_cases_open`,
`resolve_cases_resolved`, `resolve_cases_critical` (URGENT priority), `resolve_cases_overdue`,
`resolve_exceptions_open`, `resolve_invoices_total`, `resolve_documents_total`,
`resolve_documents_failed`, `resolve_chunks_total`, `resolve_chunk_vectors_total`,
`resolve_approvals_pending`, `resolve_jobs_failed`, `resolve_outbox_pending`,
`resolve_outbox_oldest_seconds`, `resolve_vector_dimension`.

Scraping adds one small read-only session and a handful of indexed counts; failures in business
queries no longer mark the database down (only a failed connection does).

Host metrics come from `node-exporter`; the backup script writes
`var/metrics/resolve_backup.prom`, collected through the node-exporter textfile collector as
`resolve_backup_last_success_timestamp_seconds`.

## 4. Dashboards

| UID | Title | Highlights |
| --- | --- | --- |
| `resolve-overview` | RESOLVE — System Overview | API/DB/Redis/storage up, request rate, 5xx ratio, p95 latency, per-route rate |
| `resolve-database-storage` | RESOLVE — Database & Storage | pg up/connections/size/cache hit, Redis memory/clients/ops, chunk and vector counts, vector dimension |
| `resolve-ai-documents` | RESOLVE — AI & Document Processing | AI configured, Ollama/n8n probes, documents, chunk embeddings, document endpoint rate, latency proxy |
| `resolve-business` | RESOLVE — Business Operations | total/open/critical/overdue cases, open exceptions, invoices, pending approvals, resolved cases |

All panels query Prometheus; there are no synthetic series.

## 5. Alerts (20 rules, `infrastructure/monitoring/alerts.yml`)

Critical: API down, Postgres exporter down, DB unreachable, Redis unreachable, storage unavailable,
worker down, nginx unavailable.

Warning: outbox stalled (beat/worker), Celery queue backlog, 5xx rate > 5 %, p95 > 2 s, approval
backlog > 20, document failures > 5, Ollama unreachable, n8n unreachable, host memory > 90 %, disk
free < 15 %, no backup in 26 h, TLS certificate expiring within 30 days.

Delivery: Alertmanager → Mailpit SMTP (`mailpit:1025`) → `ops@resolve.local`. Group wait 5 s, repeat
1 h, resolved notifications enabled. No external address is used.

### Controlled alert test (executed)

1. A temporary rule `ResolveControlledAlertTest` (`expr: vector(1)`) was appended to `alerts.yml`.
2. `POST http://127.0.0.1:9190/-/reload`.
3. Alertmanager showed `ResolveControlledAlertTest / active`.
4. Mailpit received `[RESOLVE ALERT] ResolveControlledAlertTest` at `ops@resolve.local`.
5. The rule was removed and Prometheus reloaded; the alert resolved.

A real alert (`ResolveDatabaseDown`) also fired during development when a metrics bug set
`resolve_db_up=0`; it delivered to Mailpit and resolved after the fix — evidence that the delivery
path works for real conditions, not only synthetic ones.

## 6. Runbook

```powershell
# Status
curl http://127.0.0.1:9190/-/ready
curl http://127.0.0.1:9190/api/v1/targets
curl http://127.0.0.1:9190/api/v1/rules
curl http://127.0.0.1:9190/api/v1/alerts
curl http://127.0.0.1:9193/api/v2/alerts

# Reload after editing rules (config is mounted read-only)
curl -X POST http://127.0.0.1:9190/-/reload

# Logs
docker compose logs prometheus alertmanager grafana --tail 100
```

### Common issues

| Symptom | Check |
| --- | --- |
| Target DOWN | `docker compose ps`, exporter logs, credentials (`postgres-exporter` uses the DB password) |
| No alert mail | `docker compose ps mailpit`; Alertmanager logs; Mailpit UI `127.0.0.1:8125` |
| Dashboard empty | datasource health in Grafana, target up, time range |
| `resolve_db_up=0` but API healthy | API logs for `metrics_db_unreachable`; check DB_URL |
| Backup alert never resolves | run `scripts/backup-resolve.ps1`; confirm `var/metrics/resolve_backup.prom` updated |
| Certificate alert | renew mkcert cert, recreate `web` |

Grafana password rotation: update `GRAFANA_PASSWORD` in `.env` and
`docker compose up -d --force-recreate grafana`. The value is never logged.

## 7. Retention and backup

Prometheus keeps 15 days in volume `prometheus_data`; Alertmanager silences/state in
`alertmanager_data`; Grafana state in `grafana_data`. Dashboards and datasources are provisioned from
Git, so they survive volume loss by re-provisioning. Metrics history is intentionally not backed up.
