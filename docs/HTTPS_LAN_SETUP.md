# HTTPS and LAN setup

RESOLVE terminates TLS in nginx and publishes exactly one LAN port. All other services are loopback
or Docker-internal. This guide reproduces the configuration that is running now.

## 1. Topology

```
Windows/macOS browser
        │  https://<host>:8180   (only allowed inbound port)
        ▼
   resolve-web (nginx 1.27)
        │  /api, /health, /docs  → http://api:8000   (Docker network)
        ▼
   FastAPI + Celery + PostgreSQL + Redis + SeaweedFS + n8n + monitoring
```

* Host ports: web `8180 → 443`, HTTP `127.0.0.1:8081 → 80` (redirect only).
* Certificate: local **mkcert** CA; SANs `resolve.local`, `192.168.1.10`, `localhost`, `127.0.0.1`;
  valid until **2029-02-19**.
* HSTS `max-age=31536000; includeSubDomains`; TLS 1.2/1.3; HTTP/2 enabled.

## 2. Create the CA and certificate (one time)

```powershell
winget install --id FiloSottile.mkcert --exact
mkcert -install                       # trusts the CA for the current Windows user
mkcert -CAROOT                        # prints the CA directory

New-Item -ItemType Directory -Force var\certs | Out-Null
mkcert -cert-file var\certs\server.pem -key-file var\certs\server-key.pem `
  resolve.local 192.168.1.10 localhost 127.0.0.1
Copy-Item (Join-Path (mkcert -CAROOT).Trim() "rootCA.pem") var\certs\rootCA.pem -Force

icacls "var\certs" /inheritance:r /grant:r "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F"
```

`var/` is Git-ignored, so the private key never reaches source control. Keep `server-key.pem` and the
mkcert CA private key out of backups that are not protected.

> The examples use `192.168.1.10` as a LAN address. Replace it with your host's address in the
> certificate SANs, `FRONTEND_URL`, `CORS_ORIGINS` and the URLs below.

## 3. nginx and Compose

`infrastructure/docker/nginx.conf`:

* `listen 443 ssl; http2 on;`
* `ssl_protocols TLSv1.2 TLSv1.3;`
* the certificate paths `/etc/nginx/certs/server.pem` and `server-key.pem`
* proxies `/api`, `/health`, `/docs`, `/openapi.json` with `X-Forwarded-Proto https`
* security headers at server level, with `proxy_hide_header` preventing duplicates from the API
* a localhost-only HTTP server returning `301 https://$host:8180$request_uri`
* an internal `:8080/nginx_status` server for the exporter (Docker networks only)

`docker-compose.yml` publishes `8180:443` and `127.0.0.1:8081:80` and mounts `./var/certs` read-only.

Apply:

```powershell
docker compose --env-file .env build web
docker compose --env-file .env up -d --force-recreate --no-deps web
```

## 4. Windows trust and verification

`mkcert -install` already added the CA to the Windows trust store. Verify:

```powershell
# Windows curl uses Schannel; mkcert has no CRL/OCSP, so --ssl-no-revoke is required
curl.exe --ssl-no-revoke -I https://192.168.1.10:8180/
curl.exe --ssl-no-revoke https://192.168.1.10:8180/health

# Certificate contents
& "C:\Program Files\Git\usr\bin\openssl.exe" x509 -in var\certs\server.pem `
  -noout -subject -issuer -dates -ext subjectAltName

# HTTP redirect (loopback only)
curl.exe -I http://127.0.0.1:8081/
```

Expected: HTTP 200, issuer = mkcert local CA, SANs as above, `301` from 8081, HSTS present, refresh
cookie `Secure; HttpOnly; SameSite=Lax`.

## 5. macOS trust

Copy `var/certs/rootCA.pem` to the Mac (AirDrop/USB/scp), then:

```bash
openssl x509 -in ~/Downloads/rootCA.pem -noout -subject -issuer -dates
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain ~/Downloads/rootCA.pem
security verify-cert -c ~/Downloads/rootCA.pem
curl --cacert ~/Downloads/rootCA.pem -I https://192.168.1.10:8180/
```

Optional DNS name: add `192.168.1.10 resolve.local` to `/etc/hosts`, then browse
`https://resolve.local:8180`.

**No physical Mac was available during this hardening run. The commands are provided; Safari and
Keychain trust are NOT TESTED.**

## 6. Firewall

```powershell
# Only this rule is enabled for the LAN
Get-NetFirewallRule -DisplayName "RESOLVE Docker Web (TCP 8180)" |
  Format-Table DisplayName, Enabled, Profile, Direction, Action
Get-NetFirewallRule -DisplayName "RESOLVE Docker Web (TCP 8180)" |
  Get-NetFirewallAddressFilter | Format-List RemoteAddress

# Confirm nothing else listens on the LAN
Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalAddress -notin @("127.0.0.1","::1") } |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

Required rule: TCP 8180 inbound, `Private` profile, `RemoteAddress=LocalSubnet`. Old LAN rules for
8090 and other services must stay disabled. No port forwarding is configured.

## 7. Renewal

```powershell
mkcert -cert-file var\certs\server.pem -key-file var\certs\server-key.pem `
  resolve.local 192.168.1.10 localhost 127.0.0.1
Copy-Item (Join-Path (mkcert -CAROOT).Trim() "rootCA.pem") var\certs\rootCA.pem -Force
docker compose --env-file .env up -d --force-recreate --no-deps web
```

If the CA itself is replaced, remove the old CA from every client trust store and repeat the macOS
step. The `ResolveCertificateExpiringSoon` alert fires 30 days before expiry.

## 8. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Certificate warning | CA not trusted on that client, wrong host (HTTP port), or SAN mismatch |
| Windows curl revocation error | mkcert has no CRL/OCSP: use `--ssl-no-revoke` or a browser |
| Mac cannot connect | Check the 8180 rule, Private profile, `nc -vz 192.168.1.10 8180` |
| Page loads, API 502 | `docker compose ps api`; `https://127.0.0.1:8180/health` |
| Cookie not stored | Must use HTTPS and same-origin `/api`; check `Secure` attribute |
| `resolve.local` fails | Add the hosts/DNS entry; SAN covers the name but DNS must resolve |
| Rate limit hit during testing | 20 logins/minute per gateway IP; wait for the window |

Do not expose 8180 to the Internet. Use a VPN for remote access and keep production mode enabled.
