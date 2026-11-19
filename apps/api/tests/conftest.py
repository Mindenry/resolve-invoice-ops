"""Test fixtures: isolated in-memory SQLite, seeded RBAC and organization users."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

os.environ.update(
    ENV="test",
    DATABASE_URL="sqlite://",
    AI_PROVIDER="stub",
    AI_EMBEDDING_PROVIDER="stub",
    AI_EMBEDDING_DIM="64",
    TASK_RUNNER="inline",
    RATE_LIMIT_ENABLED="false",
    DEMO_MODE="true",
    SECRET_KEY="test-secret-key-0123456789abcdef0123456789",
    PASSWORD_MIN_LENGTH="10",
    EMAIL_BACKEND="sink",
    AUTO_CREATE_SCHEMA="false",
)
# When running against PostgreSQL, settings.is_sqlite must be false as well so
# dialect-specific code paths (pgvector, JSONB, etc.) are exercised by tests.
POSTGRES_TEST_URL = os.environ.get("RESOLVE_TEST_DATABASE_URL", "").strip()
if POSTGRES_TEST_URL:
    os.environ["DATABASE_URL"] = POSTGRES_TEST_URL

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.db.session as session_module  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.domain.enums import RoleCode  # noqa: E402
from app.main import app  # noqa: E402
from app.models.identity import Membership, Organization, Role, User  # noqa: E402
from app.modules.auth.service import ensure_rbac  # noqa: E402
from app.modules.exceptions.rules import ensure_default_rules  # noqa: E402


@dataclass
class OrgFixture:
    org: Organization
    users: dict[RoleCode, User]
    headers: dict[RoleCode, dict[str, str]]


def _postgres_fixture_engine() -> tuple[Engine, Engine, str]:
    """Create an isolated PostgreSQL schema and an engine scoped to it.

    Each test gets its own schema, so tests are independent and never touch existing data.
    The outer engine is only used to create/drop the schema.
    """
    schema = f"resolve_test_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        POSTGRES_TEST_URL,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_pre_ping=True,
    )
    return engine, admin_engine, schema


@pytest.fixture()
def db() -> Iterator[Session]:
    if POSTGRES_TEST_URL:
        engine, admin_engine, schema = _postgres_fixture_engine()
        Base.metadata.create_all(bind=engine)
        TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        session_module.engine = engine
        session_module.SessionLocal = TestingSession
        with TestingSession() as session:
            ensure_rbac(session)
            session.commit()
            yield session
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
        return

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    # Route background tasks and fixtures through the same in-memory database.
    session_module.engine = engine
    session_module.SessionLocal = TestingSession
    with TestingSession() as session:
        ensure_rbac(session)
        session.commit()
        yield session
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def org(db: Session) -> OrgFixture:
    organization = Organization(
        name="Test Organization",
        slug="test-org",
        default_currency="USD",
        settings={
            "require_purchase_order": True,
            "po_exempt_vendor_ids": [],
            "approval_policy": {"approval_required_risk": "HIGH", "allow_self_approval": False},
        },
    )
    db.add(organization)
    db.flush()
    users: dict[RoleCode, User] = {}
    headers: dict[RoleCode, dict[str, str]] = {}
    for role_code in RoleCode:
        if role_code == RoleCode.SUPER_ADMIN:
            continue
        role = db.query(Role).filter(Role.code == role_code.value).one()
        email = f"{role_code.value}@example.com"
        user = User(
            email=email,
            full_name=role_code.value.replace("_", " ").title(),
            password_hash=hash_password("TestPassword123!"),
            job_title=role.name,
        )
        db.add(user)
        db.flush()
        db.add(Membership(org_id=organization.id, user_id=user.id, role_id=role.id))
        token, _ = create_access_token(
            user_id=user.id, organization_id=organization.id, role=role.code
        )
        users[role_code] = user
        headers[role_code] = {
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": str(organization.id),
        }
    ensure_default_rules(db, organization.id, created_by_id=users[RoleCode.ORG_ADMIN].id)
    db.commit()
    return OrgFixture(org=organization, users=users, headers=headers)


@pytest.fixture()
def second_org(db: Session) -> OrgFixture:
    organization = Organization(name="Other Organization", slug="other-org", default_currency="EUR")
    db.add(organization)
    db.flush()
    role = db.query(Role).filter(Role.code == RoleCode.ORG_ADMIN.value).one()
    user = User(
        email="other-admin@example.com",
        full_name="Other Admin",
        password_hash=hash_password("TestPassword123!"),
    )
    db.add(user)
    db.flush()
    db.add(Membership(org_id=organization.id, user_id=user.id, role_id=role.id))
    token, _ = create_access_token(user_id=user.id, organization_id=organization.id, role=role.code)
    ensure_default_rules(db, organization.id, created_by_id=user.id)
    db.commit()
    return OrgFixture(
        org=organization,
        users={RoleCode.ORG_ADMIN: user},
        headers={
            RoleCode.ORG_ADMIN: {
                "Authorization": f"Bearer {token}",
                "X-Organization-Id": str(organization.id),
            }
        },
    )


@pytest.fixture()
def sample_ids() -> dict[str, uuid.UUID]:
    return {}
