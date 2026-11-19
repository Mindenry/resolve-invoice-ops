# RESOLVE v1.0.0 — Release notes

**Status:** project closure release. Portfolio/demo ready and verified for controlled LAN evaluation.
**Not approved for real financial data** until the external items in `docs/KNOWN_LIMITATIONS.md` and
section 16 of `docs/FINAL_PRODUCTION_HARDENING_REPORT.md` are closed.
**Date:** 2026-11-19.
**Deployment:** Docker Compose (primary); native Windows services remain a loopback-only rollback.

## Highlights

- HTTPS on `https://localhost:8180` and `https://192.168.1.10:8180` with a trusted local mkcert CA,
  TLS 1.2/1.3, HSTS and secure cookies.
- Production authentication and authorization: rotated demo credentials, disabled self-registration,
  six roles, 47 permissions, tenant isolation, self-approval block, approval/execution separation and
  login rate limiting.
- Real workflow: vendor → PO → upload → OCR (Thai/English) → extraction → 10 exception rules → case →
  local Ollama investigation with validated citations → proposal → human approval → execution → audit
  → analytics.
- Five active n8n workflows with HMAC verification, Redis-backed idempotency and Mailpit delivery.
- Prometheus (13 targets), Alertmanager, and four Grafana dashboards; a controlled and a real alert
  both delivered.
- Verified backup and isolated restore, including `vector(1024)`, HNSW and object SHA-256.

## Fixed in this release

1. **Concurrent approval race** — two simultaneous approvals could both succeed. Decisions now use an
   atomic conditional update; only one can win (live result: one 200, one 409). Regression test added.
2. **Invoice detail crash** — the shared `Button` passed multiple children to Radix `Slot` when
   `asChild` was set. Fixed and re-verified with zero app console errors.

## Verification at this tag

| Gate | Result |
| --- | --- |
| Backend tests | 137 passed, 1 skipped |
| Frontend | typecheck OK, lint 0 errors, Vitest 6/6, build OK |
| Playwright over HTTPS | 10/10 |
| Full workflow | 28 steps |
| Acceptance (roles + 25 edge cases) | 26/26 |
| Security | 16/16 |
| n8n contract | 9/9 |
| Responsive/console | 0 overflow, 0 app console errors across 24 route/viewport checks |
| Restart persistence | data, workflows, dashboards, certificates and login verified |
| Backup/restore | counts, vectors, HNSW and SHA-256 verified |

## Upgrade from v1.0.0-rc.1

- Rebuild the API and web images (approval service and shared Button changed).
- No schema change and no data migration are required.
- The super administrator account is optional; provision it with
  `scripts/provision-superadmin.py` if you want the full six-role demo.

## Known limitations at this tag

No physical macOS/Safari test, no public domain/DNS, no external SMTP (Mailpit only), single-node data
services, Docker Desktop rather than a Linux engine, no malware scanning, no SSO, and shared rate-limit
buckets behind Docker's proxy. The demo workspace still contains synthetic data and must be removed
before real use. See `portfolio/KNOWN_LIMITATIONS.md`.

## Rollback

`git checkout v1.0.0` restores this source baseline. Data rollback uses the backup/restore procedure in
`docs/BACKUP_RESTORE_RUNBOOK.md`; the native deployment remains available on `127.0.0.1:8090`.
