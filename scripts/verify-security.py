"""Live security acceptance checks against the running HTTPS deployment.

No secret is printed. Results are the source of truth for the hardening report.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx

LAN = "https://192.168.1.107:8180"
API = f"{LAN}/api/v1"
VERIFY = "var/certs/rootCA.pem"


def secrets() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in Path("var/secrets/demo-credentials.txt").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("RESOLVE"):
            email, password = line.split("=", 1)
            data[email.strip()] = password.strip()
    return data


def login(client: httpx.Client, email: str, password: str) -> httpx.Response:
    return client.post(
        f"{API}/auth/login",
        json={"email": email, "password": password, "organization_slug": "northwind"},
    )


def main() -> int:
    creds = secrets()
    client = httpx.Client(verify=VERIFY, timeout=30)
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(("PASS " if ok else "FAIL ") + name + (f" ({detail})" if detail else ""))

    # 1. Rotated demo password; the retired password must be rejected.
    legacy = os.environ.get("RESOLVE_LEGACY_PASSWORD", "")
    if legacy:
        old = login(client, "admin@example.com", legacy)
        check("retired demo password rejected", old.status_code == 401, str(old.status_code))
    else:
        print("SKIP retired demo password check (set RESOLVE_LEGACY_PASSWORD to the retired value)")
    good = login(client, "admin@example.com", creds["admin@example.com"])
    check("rotated admin password works", good.status_code == 200, str(good.status_code))
    admin_headers = {
        "Authorization": f"Bearer {good.json()['access_token']}",
        "X-Organization-Id": good.json()["organization"]["id"],
    }

    # 2. Viewer cannot mutate.
    viewer = login(client, "viewer@example.com", creds["viewer@example.com"])
    viewer_headers = {
        "Authorization": f"Bearer {viewer.json()['access_token']}",
        "X-Organization-Id": viewer.json()["organization"]["id"],
    }
    write = client.post(
        f"{API}/vendors",
        headers=viewer_headers,
        json={"name": f"Security test {uuid.uuid4().hex[:6]}", "code": uuid.uuid4().hex[:8]},
    )
    check("viewer write rejected", write.status_code == 403, str(write.status_code))

    # 3. Unauthenticated mutation rejected.
    anon = client.post(f"{API}/vendors", json={"name": "anon", "code": "anon"})
    check("unauthenticated mutation rejected", anon.status_code == 401, str(anon.status_code))

    # 4. Forged organization header rejected.
    forged = dict(viewer_headers)
    forged["X-Organization-Id"] = str(uuid.uuid4())
    case_page = client.get(f"{API}/cases", headers=forged)
    check(
        "forged organization header rejected",
        case_page.status_code in {403, 404},
        str(case_page.status_code),
    )

    # 5. Login rate limiting (20/minute); use a non-existent account to avoid lockout.
    statuses = []
    for _ in range(25):
        statuses.append(login(client, "nobody@example.com", "wrong-password").status_code)
    first_429 = statuses.index(429) + 1 if 429 in statuses else None
    check("login rate limit fires", 429 in statuses, f"first_429={first_429}")

    # 6. Cookie flags + headers on HTTPS.
    cookie = good.headers.get("set-cookie", "").lower()
    check(
        "refresh cookie secure/httponly/samesite",
        "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie,
    )
    head = client.get(f"{API}/auth/me", headers=admin_headers)
    hsts = head.headers.get("strict-transport-security", "")
    check("HSTS present", "max-age=31536000" in hsts, hsts[:40])
    check(
        "security headers present",
        "nosniff" in (head.headers.get("x-content-type-options") or "")
        and "DENY" in (head.headers.get("x-frame-options") or ""),
        f"{head.headers.get('x-content-type-options')} / {head.headers.get('x-frame-options')}",
    )
    check("api cache-control no-store", head.headers.get("cache-control") == "no-store")

    # 7. Internal surfaces are not reachable through the LAN web port.
    metrics = client.get(f"{LAN}/metrics")
    check(
        "metrics not proxied to LAN",
        "resolve_http_requests_total" not in metrics.text
        and "text/html" in (metrics.headers.get("content-type") or ""),
        f"{metrics.status_code} {metrics.headers.get('content-type')}",
    )
    for name, port in [("n8n", 5679), ("grafana", 3101), ("prometheus", 9190), ("api", 8100)]:
        try:
            httpx.get(f"http://192.168.1.107:{port}/", timeout=4)
            reachable = True
        except httpx.HTTPError:
            reachable = False
        check(f"{name} not reachable on LAN", not reachable)

    # 8. Error envelope does not leak internals.
    missing = client.get(f"{API}/cases/{uuid.uuid4()}", headers=admin_headers)
    body = missing.text
    check(
        "error response hides internals",
        "Traceback" not in body and "postgresql://" not in body and "password" not in body.lower(),
        str(missing.status_code),
    )

    failures = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failures)}/{len(results)} security checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
