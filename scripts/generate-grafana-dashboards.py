"""Generate the four provisioned RESOLVE Grafana dashboards."""

import json
from pathlib import Path

D = Path("infrastructure/monitoring/grafana/dashboards")
D.mkdir(parents=True, exist_ok=True)
DS = {"type": "prometheus", "uid": "prometheus"}


def stat(i, title, expr, x, y, w=6, h=5, unit="short"):
    return {
        "id": i,
        "type": "stat",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"refId": "A", "expr": expr, "legendFormat": title}],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "red", "value": None},
                        {"color": "green", "value": 1},
                    ],
                },
            },
            "overrides": [],
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
    }


def ts(i, title, expr, x, y, w=12, h=7, unit="short"):
    return {
        "id": i,
        "type": "timeseries",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"refId": "A", "expr": expr, "legendFormat": title}],
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
    }


def dash(uid, title, panels):
    return {
        "uid": uid,
        "title": title,
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "panels": panels,
    }


overview = [
    stat(1, "API up", 'up{job="resolve-api"}', 0, 0),
    stat(2, "DB up", "resolve_db_up", 6, 0),
    stat(3, "Redis up", "resolve_redis_up", 12, 0),
    stat(4, "Storage up", "resolve_storage_up", 18, 0),
    ts(5, "Request rate", "sum(rate(resolve_http_requests_total[5m]))", 0, 5, unit="reqps"),
    ts(
        6,
        "5xx error rate",
        'sum(rate(resolve_http_requests_total{status=~"5.."}[5m])) / clamp_min(sum(rate(resolve_http_requests_total[5m])), 0.001)',
        12,
        5,
        unit="percentunit",
    ),
    ts(
        7,
        "API p95 latency",
        "histogram_quantile(0.95, sum(rate(resolve_http_request_duration_seconds_bucket[5m])) by (le))",
        0,
        12,
        unit="s",
    ),
    ts(
        8,
        "Requests by route",
        "sum by (route) (rate(resolve_http_requests_total[5m]))",
        12,
        12,
        unit="reqps",
    ),
]

database = [
    stat(1, "PostgreSQL up", 'pg_up{job="postgres"}', 0, 0),
    stat(2, "Postgres connections", 'pg_stat_activity_count{job="postgres"}', 6, 0),
    stat(3, "Redis memory", 'redis_memory_used_bytes{job="redis"}', 12, 0, unit="bytes"),
    stat(4, "Redis clients", 'redis_connected_clients{job="redis"}', 18, 0),
    ts(5, "Database size", 'pg_database_size_bytes{job="postgres"}', 0, 5, unit="bytes"),
    ts(
        6,
        "Redis ops/sec",
        'sum(rate(redis_commands_processed_total{job="redis"}[5m]))',
        12,
        5,
        unit="ops",
    ),
    stat(7, "Chunks", "resolve_chunks_total", 0, 12),
    stat(8, "Vector rows", "resolve_chunk_vectors_total", 6, 12),
    stat(9, "Configured vector dimension", "resolve_vector_dimension", 12, 12),
    ts(
        10,
        "Cache hit ratio",
        'pg_stat_database_blks_hit{job="postgres"} / clamp_min(pg_stat_database_blks_hit{job="postgres"} + pg_stat_database_blks_read{job="postgres"}, 1)',
        18,
        12,
        unit="percentunit",
    ),
]

ai = [
    stat(1, "AI configured", "resolve_ai_configured", 0, 0),
    stat(
        2,
        "Ollama probe",
        'probe_success{job="blackbox", instance="http://host.docker.internal:11434/api/version"}',
        6,
        0,
    ),
    stat(3, "n8n probe", 'probe_success{job="blackbox", instance="http://n8n:5678/healthz"}', 12, 0),
    stat(4, "Documents", "resolve_documents_total", 18, 0),
    ts(
        5,
        "Investigation request rate",
        'sum(rate(resolve_http_requests_total{route=~".*investigations.*"}[5m]))',
        0,
        5,
        unit="reqps",
    ),
    ts(
        6,
        "Processing latency proxy",
        "histogram_quantile(0.95, sum(rate(resolve_http_request_duration_seconds_bucket[5m])) by (le))",
        12,
        5,
        unit="s",
    ),
    stat(7, "Chunks embedded", "resolve_chunk_vectors_total", 0, 12),
    stat(8, "Chunks total", "resolve_chunks_total", 6, 12),
    ts(
        9,
        "Document endpoint rate",
        'sum(rate(resolve_http_requests_total{route=~"/api/v1/documents.*"}[5m]))',
        12,
        12,
        unit="reqps",
    ),
]

business = [
    stat(1, "Total cases", "resolve_cases_total", 0, 0),
    stat(2, "Open cases", "resolve_cases_open", 6, 0),
    stat(3, "Critical cases", "resolve_cases_critical", 12, 0),
    stat(4, "Overdue cases", "resolve_cases_overdue", 18, 0),
    stat(5, "Open exceptions", "resolve_exceptions_open", 0, 5),
    stat(6, "Invoices", "resolve_invoices_total", 6, 5),
    stat(7, "Pending approvals", "resolve_approvals_pending", 12, 5),
    stat(8, "Resolved/closed cases", "resolve_cases_resolved", 18, 5),
    ts(9, "Cases", "resolve_cases_total", 0, 10),
    ts(10, "Approvals pending", "resolve_approvals_pending", 12, 10),
]

files = {
    "resolve-overview.json": dash("resolve-overview", "RESOLVE — System Overview", overview),
    "resolve-database-storage.json": dash(
        "resolve-database-storage", "RESOLVE — Database & Storage", database
    ),
    "resolve-ai-documents.json": dash(
        "resolve-ai-documents", "RESOLVE — AI & Document Processing", ai
    ),
    "resolve-business.json": dash("resolve-business", "RESOLVE — Business Operations", business),
}

for name, payload in files.items():
    (D / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("wrote", D / name)
