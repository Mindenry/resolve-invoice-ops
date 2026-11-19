# LAN + HTTPS access guide (Windows host → macOS client)

The primary deployment is Docker Compose with **HTTPS on one LAN port, 8180**. Nginx serves the SPA
and proxies `/api` and `/health` to the loopback API. HTTP exists only as a localhost redirect on
`127.0.0.1:8081`.

## 1. Actual URLs

| From | URL |
| --- | --- |
| Windows | **https://localhost:8180** |
| macOS / LAN | **https://192.168.1.107:8180** |
| Optional name | **https://resolve.local:8180** (only if you add a hosts/DNS entry for 192.168.1.107) |
| LAN health | **https://192.168.1.107:8180/health** |
| HTTP redirect (host only) | `http://127.0.0.1:8081/` → `https://…:8180` |
| API (host only) | `http://127.0.0.1:8100` |

Certificate SANs: `resolve.local`, `localhost`, `192.168.1.107`, `127.0.0.1`.
Certificate issuer: local **mkcert** CA, valid until **2029-02-19**.
Root CA file: `E:\Code\AI project\var\certs\rootCA.pem` (public certificate only).

## 2. Exposure

- **Allowed inbound:** TCP **8180** (HTTPS), Private profile, `RemoteAddress=LocalSubnet`
  (`RESOLVE Docker Web (TCP 8180)`).
- **Not exposed:** PostgreSQL 5433/5432, Redis 6380, API 8100, SeaweedFS 9100/9101, n8n 5679,
  Mailpit 8125/1126, Prometheus 9190, Grafana 3101, Ollama 11434.
- Native rollback nginx binds `127.0.0.1:8090`; its old LAN firewall rule is disabled.
- No port forwarding or public Internet exposure was configured.

## 3. Install and trust the CA on macOS

Copy **`var/certs/rootCA.pem`** from the Windows host to the Mac using AirDrop, a USB drive, a shared
folder, or `scp` if an SSH server is available (the host does not run SSH by default).

Then on the Mac:

```bash
# Inspect first
openssl x509 -in ~/Downloads/rootCA.pem -noout -subject -issuer -dates

# Trust for the whole machine (requires admin password)
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain ~/Downloads/rootCA.pem

# Verify the server chain and hostname
curl --cacert ~/Downloads/rootCA.pem -I https://192.168.1.107:8180/
security verify-cert -c ~/Downloads/rootCA.pem
```

Safari/Chrome use the macOS Keychain trust; after trusting the root CA the certificate warning
should disappear. If your organization requires a per-user trust instead of system-wide, import the
same certificate into **Keychain Access → System/Login → Certificates → Always Trust**.

For `resolve.local`, add this to `/etc/hosts` on the Mac:

```
192.168.1.107 resolve.local
```

**No physical Mac was available during this run. The commands above are provided; Safari/Keychain
trust is NOT TESTED on a real Mac.**

## 4. Verify from macOS Terminal

```bash
nc -vz 192.168.1.107 8180
curl --cacert ~/Downloads/rootCA.pem -s https://192.168.1.107:8180/health

# Login using the rotated password from the secure file
read -r RESOLVE_PASSWORD < /dev/tty   # paste the admin password, it is not echoed as a command
curl --cacert ~/Downloads/rootCA.pem -s -c cookies.txt \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"admin@example.com\",\"password\":\"$RESOLVE_PASSWORD\",\"organization_slug\":\"northwind\"}" \
  https://192.168.1.107:8180/api/v1/auth/login | python3 -m json.tool | head -20

curl --cacert ~/Downloads/rootCA.pem -s -b cookies.txt -c cookies.txt \
  -H 'Content-Type: application/json' -d '{}' \
  https://192.168.1.107:8180/api/v1/auth/refresh | python3 -m json.tool | head -10
```

Then open `https://192.168.1.107:8180` in Chrome and Safari:

1. Confirm the certificate is valid and the URL is HTTPS.
2. Login with a demo account using the password in `var/secrets/demo-credentials.txt`.
3. Command Center live metrics; upload a document; open a case; run an AI investigation.
4. Approve a pending request; check Mailpit on Windows (`http://127.0.0.1:8125`).
5. Reload the browser; the Secure/HttpOnly refresh cookie restores the session.

## 5. HTTPS acceptance results (Windows)

- Valid chain with `curl --ssl-no-revoke --cacert var/certs/rootCA.pem` → **200**.
- Windows system trust store (mkcert root installed) → **200**.
- HTTP `127.0.0.1:8081` → **301** to HTTPS.
- Playwright **10/10** against `https://192.168.1.107:8180` with certificate verification enabled.
- Refresh cookie: `Secure`, `HttpOnly`, `SameSite=Lax`.
- HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` present.
- Windows curl/Schannel may require `--ssl-no-revoke` because mkcert has no CRL/OCSP endpoint; this is
  a client revocation-check limitation, not a certificate-name/chain failure.

## 6. Renewal and rotation

Certificate expires **2029-02-19**. To renew:

```powershell
cd "E:\Code\AI project"
mkcert -cert-file var\certs\server.pem -key-file var\certs\server-key.pem `
  resolve.local 192.168.1.107 localhost 127.0.0.1
Copy-Item (Join-Path (mkcert -CAROOT).Trim() "rootCA.pem") var\certs\rootCA.pem -Force
docker compose --env-file .env up -d --force-recreate --no-deps web
```

Do not commit `server-key.pem` or the mkcert CA private key. The public `rootCA.pem` may be shared
with clients. If the root CA is rotated, remove the old CA from Windows/macOS trust stores and repeat
the Mac trust step.

## 7. Troubleshooting

| Symptom | Check |
| --- | --- |
| Certificate warning | Root CA not trusted; SAN/URL mismatch; using HTTP port |
| `curl` revocation error on Windows | Use `--ssl-no-revoke`, or verify in Chrome/Invoke-WebRequest |
| Mac cannot connect | Private profile; 8180 rule; `nc -vz`; host firewall |
| Page loads, API 502 | `docker compose ps api`; `https://127.0.0.1:8180/health` |
| Cookie not stored | Must use HTTPS; check `Secure` cookie and same-origin `/api` |
| AI stays QUEUED | worker/Redis/Ollama; container→host endpoint |
| HTTP 8081 not redirecting | It is bound to `127.0.0.1` only by design |

Do not expose 8180 to the public Internet. Use a VPN for remote access, and keep HTTPS + production
mode enabled.
