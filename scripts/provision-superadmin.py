"""Create or update a platform super administrator for acceptance/demo.

Runs a helper inside the API container so Argon2 hashing uses the application
code. The generated password is written to var/secrets/demo-credentials.txt and
never printed.
"""

from __future__ import annotations

import secrets
import subprocess
from pathlib import Path

EMAIL = "superadmin@example.com"
SECRET_FILE = Path("var/secrets/demo-credentials.txt")
HELPER = Path("var/create_superadmin_helper.py")

HELPER_CODE = '''
import os

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.identity import Membership, Organization, Role, User

email = os.environ["SUPERADMIN_EMAIL"]
password = os.environ["SUPERADMIN_PASSWORD"]

with SessionLocal() as db:
    org = db.scalar(select(Organization).where(Organization.slug == "northwind"))
    role = db.scalar(select(Role).where(Role.code == "super_admin"))
    if org is None or role is None:
        print("MISSING_ORG_OR_ROLE")
        raise SystemExit(1)
    legacy = db.scalar(select(User).where(User.email == "superadmin@resolve.local"))\n    if legacy is not None:\n        legacy.is_active = False\n    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            full_name="RESOLVE Super Admin",
            password_hash=hash_password(password),
            job_title="Platform Super Administrator",
            is_active=True,
            is_superadmin=True,
            must_change_password=False,
        )
        db.add(user)
        db.flush()
    else:
        user.password_hash = hash_password(password)
        user.is_active = True
        user.is_superadmin = True
    membership = db.scalar(
        select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id)
    )
    if membership is None:
        membership = Membership(org_id=org.id, user_id=user.id, role_id=role.id, is_active=True)
        db.add(membership)
    else:
        membership.role_id = role.id
        membership.is_active = True
    db.commit()
    print("SUPERADMIN_READY")
'''


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", "compose", *args], capture_output=True, text=True, check=False)


def main() -> int:
    existing = ""
    password = ""
    if SECRET_FILE.exists():
        for line in SECRET_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{EMAIL}="):
                existing = line.split("=", 1)[1].strip()
    password = existing or ("Aa1!" + secrets.token_urlsafe(24))

    HELPER.write_text(HELPER_CODE, encoding="utf-8")
    copied = docker("cp", str(HELPER), "api:/tmp/create_superadmin_helper.py")
    if copied.returncode != 0:
        print("copy failed", copied.stderr[:300])
        return 1
    result = docker(
        "exec", "-T",
        "-e", f"SUPERADMIN_EMAIL={EMAIL}",
        "-e", f"SUPERADMIN_PASSWORD={password}",
        "api", "python", "/tmp/create_superadmin_helper.py",
    )
    print(result.stdout.strip()[:200])
    if "SUPERADMIN_READY" not in result.stdout:
        print(result.stderr[-500:])
        return 1

    lines = SECRET_FILE.read_text(encoding="utf-8").splitlines() if SECRET_FILE.exists() else []
    lines = [line for line in lines if not line.startswith(f"{EMAIL}=")]
    lines.append(f"{EMAIL}={password}")
    SECRET_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("credentials stored for", EMAIL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
