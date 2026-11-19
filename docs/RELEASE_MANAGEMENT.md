# Release management

## 1. Versioning

RESOLVE follows semantic versioning with pre-release suffixes:

```
MAJOR.MINOR.PATCH[-rc.N]
```

* `MAJOR` — incompatible API or data-model change requiring a migration plan.
* `MINOR` — backwards-compatible capability.
* `PATCH` — fixes only.
* `-rc.N` — candidate that has passed the gates below but is not approved for unrestricted production.

`VERSION` holds the current version. `CHANGELOG.md` holds the history; `RELEASE_NOTES.md` holds the
notes for the current tag.

Current baseline: **1.0.0-rc.1** (tag `v1.0.0-rc.1`).

## 2. Repository layout and identity

* Branch: `master` (single-branch pre-release line).
* The repository-local Git identity is `RESOLVE Project <resolve@localhost>`. It is a technical
  identity for this workstation and does not impersonate a person. Global Git config is untouched.
* No remote is configured. Pushing requires explicit owner approval.

## 3. What is never committed

Ignored and verified before every commit:

* `.env` and any `.env.backup-*`
* `var/` (certs, secrets, metrics, logs, local storage)
* `backups/`
* `*.pem`, `*.key`
* `*.db`, `*.sqlite3`, `*.log`
* Python/Node caches, `dist/`, `node_modules/`, `.venv/`

The public CA certificate (`var/certs/rootCA.pem`) is also ignored; distribute it out-of-band. Only
`rootCA.pem` is safe to share — never `server-key.pem` or the mkcert CA private key.

## 4. Commit and tag procedure

```powershell
# 1. Secret scan (see section 5)
# 2. Review exactly what will be committed
git status --short
git add -A
git diff --cached --stat
git diff --cached            # read it; no secrets, no dumps, no large binaries

# 3. Commit
git commit -m "chore: establish RESOLVE verified deployment baseline"

# 4. Tag the candidate
git tag -a v1.0.0-rc.1 -m "RESOLVE v1.0.0-rc.1 - verified hardening baseline"
git tag --list
git show --stat v1.0.0-rc.1
```

Rules:

* Never rewrite or delete history on a shared branch.
* Never `git add -f` an ignored path.
* Never commit a real credential even if it is "only for testing".
* Tag only after the release gates pass (section 6).

## 5. Secret scanning

Run before every commit:

```powershell
# Files Git would actually add (respects .gitignore)
git ls-files --others --exclude-standard
git grep -n -I -E "minioadmin|resolve-minio-secret|BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}" --cached -- .
```

Also confirm that the sensitive paths are ignored:

```powershell
git check-ignore -v .env var/certs/server-key.pem backups
```

If a secret was ever committed: rotate it first, then plan history cleanup; never only delete the
file in a new commit and assume the value is safe.

## 6. Release gates

A candidate is taggable only when all of these hold on the target machine:

| Gate | Command / evidence |
| --- | --- |
| Compose stack healthy | `docker compose ps` (all services up/healthy) |
| Backend tests | `cd apps/api; ..\..\.venv\Scripts\python.exe -m pytest` → 136 passed, 1 skipped |
| Frontend quality | `npm run typecheck`, `npm run lint` (0 errors), `npm run test -- --run` (6/6), `npm run build` |
| HTTPS E2E | Playwright 10/10 with `RESOLVE_WEB_URL=https://192.168.1.107:8180` |
| Full workflow | `apps/api/scripts/verify_workflow_e2e.py --base-url https://192.168.1.107:8180` → 28 steps |
| Security | `scripts/verify-security.py` → 16/16 |
| Automation | `scripts/verify-n8n-workflows.py` 9/9, plus the outbox and document-failure E2E scripts |
| Monitoring | 13/13 targets up, 20 rules loaded, controlled alert delivered |
| Backup | fresh `backups/compose-*` with manifest |
| Restore | isolated DB + bucket, counts, vectors, HNSW and SHA-256 verified |
| Restart | `docker compose restart` then data/workflows/dashboards/login still work |

## 7. Environment configuration guide

1. `Copy-Item .env.example .env`
2. Generate secrets (never reuse the sample values):

```powershell
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"
python -c "import secrets; print('S3_SECRET_KEY=' + secrets.token_urlsafe(32))"
python -c "import secrets; print('N8N_ENCRYPTION_KEY=' + secrets.token_urlsafe(24))"
python -c "import secrets; print('N8N_WEBHOOK_SECRET=' + secrets.token_urlsafe(40))"
python -c "import secrets; print('GRAFANA_PASSWORD=Aa1!' + secrets.token_urlsafe(24))"
```

3. Set `S3_ACCESS_KEY`, `DATABASE_URL` (matching `POSTGRES_PASSWORD`), `FRONTEND_URL`,
   `CORS_ORIGINS`, and the AI endpoints (`AI_PROVIDER=ollama`, `AI_BASE_URL`,
   `AI_EMBEDDING_*`).
4. Issue the TLS certificate and place it in `var/certs/` (see `docs/HTTPS_LAN_SETUP.md`).
5. Start: `docker compose --env-file .env --profile monitoring up -d --build`.
6. Provision n8n (owner, SMTP credential, workflows, integrations) with the scripts under
   `scripts/`.
7. Create the read-only automation account with `scripts/provision-automation-user.py`.

Compose fails fast if `POSTGRES_PASSWORD`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `N8N_ENCRYPTION_KEY`,
`N8N_WEBHOOK_SECRET`, `RESOLVE_AUTOMATION_*` or `GRAFANA_PASSWORD` are missing.

## 8. Rollback

| Scenario | Action |
| --- | --- |
| Bad application release | `git checkout <previous-tag>` and rebuild the affected images |
| Bad configuration | restore the previous `.env` from `var/env-backups/` and recreate the service |
| Data corruption | restore the newest verified backup into a new database, verify, then switch `DATABASE_URL` |
| Docker unusable | start the native Windows services (`scripts/start-native.ps1`); they bind loopback only |

Rollback never deletes Docker volumes. `docker compose down -v` is forbidden by policy.

## 9. Post-release tasks

* Renew the mkcert certificate before 2029-02-19 (alert fires 30 days before expiry).
* Rotate the demo credentials or delete the demo workspace before real data is loaded.
* Keep `N8N_ENCRYPTION_KEY` stable; changing it makes imported credentials undecryptable.
* Re-run the release gates after any dependency or base-image bump.
