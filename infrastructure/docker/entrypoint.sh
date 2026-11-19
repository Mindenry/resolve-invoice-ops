#!/bin/sh
set -eu

echo "Waiting for the database..."
python - <<'PY'
import time
import sys
from sqlalchemy import create_engine, text
from app.config.settings import settings

for attempt in range(60):
    try:
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("Database is ready.")
        break
    except Exception as exc:  # noqa: BLE001
        print(f"  attempt {attempt + 1}/60: {exc}")
        time.sleep(2)
else:
    print("Database did not become ready.", file=sys.stderr)
    raise SystemExit(1)
PY

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "Applying migrations..."
  alembic upgrade head
else
  echo "Skipping migrations (RUN_MIGRATIONS=false)."
fi

if [ "${SEED_DEMO:-false}" = "true" ]; then
  echo "Seeding the demo workspace if it is empty..."
  python - <<'PY'
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.identity import Organization
from app.scripts.seed_demo import seed

with SessionLocal() as db:
    exists = db.scalar(select(Organization).where(Organization.slug == "northwind"))
if exists:
    print("Demo organization already present; skipping seed.")
else:
    seed()
PY
fi

exec "$@"