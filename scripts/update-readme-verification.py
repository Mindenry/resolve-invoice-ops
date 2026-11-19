"""Refresh the README verification-status section with the current evidence."""

from pathlib import Path

path = Path("README.md")
text = path.read_text(encoding="utf-8")

start_marker = "## Verification status"
end_marker = "## One-run Windows deployment"
start = text.index(start_marker)
end = text.index(end_marker)

new_section = """## Verification status

Verified on this machine against the Docker Compose deployment (see
[`docs/FINAL_PRODUCTION_HARDENING_REPORT.md`](docs/FINAL_PRODUCTION_HARDENING_REPORT.md)):

- **HTTPS** on `https://localhost:8180` and `https://192.168.1.107:8180` with a local mkcert CA
  (the IP is a SAN), TLS 1.2/1.3, HSTS, Secure/HttpOnly/SameSite=Lax cookies and a loopback-only HTTP
  redirect. **Playwright 10/10 over HTTPS.**
- **Security:** demo passwords rotated (the retired password returns 401), self-registration
  disabled, RBAC and tenant isolation enforced, self-approval blocked, login rate limiting active.
  `scripts/verify-security.py` passes **16/16**.
- **Backend:** **136 passed + 1 skipped** on PostgreSQL and SQLite (`cd apps/api; pytest`).
- **Frontend:** typecheck, lint (0 errors), Vitest 6/6, production build.
- **Full workflow:** **28 steps** over HTTPS: vendor, PO, upload, OCR, extraction, exceptions, case,
  real Ollama investigation with validated citations, proposal, approval, execution, audit and
  analytics.
- **n8n:** five active workflows (A-E) with HMAC verification, Redis-backed idempotency, duplicate
  suppression, retry visibility and Mailpit delivery; real outbox events (`case.created`,
  `case.escalated`, `document.failed`) delivered with HTTP 200.
- **Observability:** Prometheus **13/13 targets up** with 20 alert rules, Alertmanager to Mailpit
  (controlled and real database-down alerts delivered), four Grafana dashboards provisioned from Git.
- **Data:** PostgreSQL 16.16 + pgvector 0.8.7, `vector(1024)`, HNSW index and a real
  nearest-neighbour query; SeaweedFS S3 with authenticated path-style access.
- **Backup/restore:** `backups/compose-20261119-205946` (65 objects) restored into an isolated
  database and bucket; counts, vectors, HNSW, retrieval and an object SHA-256 matched.
- **Restart persistence:** after `docker compose restart`, all services return, data is intact,
  n8n workflows stay active, Grafana dashboards and certificates still work, and login succeeds.

**Not verified here:** a physical macOS client (trust steps documented, Safari untested), external
DNS/domain, external SMTP (Mailpit only), managed cloud S3, and a hardened Linux Docker Engine
(Docker Desktop is used with a watchdog task). See `docs/KNOWN_LIMITATIONS.md`.

"""

path.write_text(text[:start] + new_section + text[end:], encoding="utf-8")
print("README verification section refreshed")
