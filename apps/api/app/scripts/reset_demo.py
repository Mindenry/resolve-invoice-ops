"""Reset the local database and demo storage, then optionally reseed.

Development/demo only. Refuses to run when ENV=production.

Usage (from apps/api):
    python -m app.scripts.reset_demo --yes
    python -m app.scripts.reset_demo --yes --seed
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from app.config.settings import settings
from app.db.base import Base
from app.db.session import engine, init_models
from app.services.storage import reset_storage_cache


def reset(*, purge_files: bool = True, seed_after: bool = False) -> None:
    if settings.ENV == "production":
        raise SystemExit("Refusing to reset a production database.")
    if settings.is_sqlite:
        database_file = Path(settings.DATABASE_URL.removeprefix("sqlite:///"))
        engine.dispose()
        if database_file.exists():
            database_file.unlink()
        for suffix in ("-wal", "-shm"):
            companion = Path(str(database_file) + suffix)
            companion.unlink(missing_ok=True)
    else:
        init_models()
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
    if purge_files and settings.STORAGE_BACKEND == "local":
        storage_dir = Path(settings.STORAGE_LOCAL_DIR)
        if storage_dir.exists():
            shutil.rmtree(storage_dir)
        storage_dir.mkdir(parents=True, exist_ok=True)
    mail_dir = Path(settings.EMAIL_SINK_DIR)
    if purge_files and mail_dir.exists():
        for item in mail_dir.glob("*.eml"):
            item.unlink(missing_ok=True)
    reset_storage_cache()
    init_models()
    print("Database reset complete.")
    if seed_after:
        from app.scripts.seed_demo import seed

        seed()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the RESOLVE local database and demo data.")
    parser.add_argument("--yes", action="store_true", help="Confirm the destructive reset")
    parser.add_argument("--keep-files", action="store_true", help="Keep stored document files")
    parser.add_argument("--seed", action="store_true", help="Reseed the demo workspace after reset")
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("Pass --yes to confirm the destructive reset.")
    reset(purge_files=not args.keep_files, seed_after=args.seed)


if __name__ == "__main__":
    main()
