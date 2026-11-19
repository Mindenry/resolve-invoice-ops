"""Prepare a second, isolated tenant fixture for cross-tenant tests.

Rotates the password of one E2E tenant user, deactivates the other stale E2E
test users, and prints the credentials to stdout so the caller can store them in
.env (the caller must not echo them).
"""

from __future__ import annotations

import secrets

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.identity import Membership, Organization, User
from sqlalchemy import select

FIXTURE_SLUG = "e2e-other-cilg8f"


def main() -> int:
    password = "Aa1!" + secrets.token_urlsafe(20)
    with SessionLocal() as db:
        fixture_org = db.scalar(select(Organization).where(Organization.slug == FIXTURE_SLUG))
        if fixture_org is None:
            print("FIXTURE_MISSING")
            return 1
        memberships = list(
            db.scalars(
                select(Membership).where(
                    Membership.org_id == fixture_org.id
                )
            )
        )
        if not memberships:
            print("FIXTURE_NO_USER")
            return 1

        fixture_user = db.get(User, memberships[0].user_id)
        fixture_user.password_hash = hash_password(password)
        fixture_user.is_active = True
        memberships[0].is_active = True

        stale = db.scalars(
            select(User).where(
                User.email.like("other-%@example.com"),
                User.email != fixture_user.email,
            )
        ).all()
        for user in stale:
            user.is_active = False

        db.commit()
        print(f"FIXTURE_EMAIL={fixture_user.email}")
        print(f"FIXTURE_PASSWORD={password}")
        print(f"FIXTURE_ORG={fixture_org.id}")
        print(f"FIXTURE_ORG_SLUG={fixture_org.slug}")
        print(f"DEACTIVATED={len(stale)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
