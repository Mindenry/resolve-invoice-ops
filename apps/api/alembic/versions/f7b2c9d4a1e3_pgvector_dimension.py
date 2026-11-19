"""pgvector dimension, JSON backfill and HNSW index

Revision ID: f7b2c9d4a1e3
Revises: c30cec670d6b
Create Date: 2026-11-19

The initial revision creates ``embedding_vec`` only when pgvector is available.
This revision makes the vector dimension follow ``AI_EMBEDDING_DIM``, backfills
it from the portable JSON embeddings, and (re)builds the HNSW cosine index.
It is a no-op on SQLite or when pgvector is not installed.
"""

from __future__ import annotations

import os

from alembic import op

revision = "f7b2c9d4a1e3"
down_revision = "c30cec670d6b"
branch_labels = None
depends_on = None

INDEX = "ix_document_chunks_embedding_vec"


def _dimension() -> int:
    try:
        value = int(os.environ.get("AI_EMBEDDING_DIM", "384"))
    except ValueError:
        value = 384
    return max(1, min(value, 16000))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    try:
        with bind.begin_nested():
            bind.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception:  # noqa: BLE001 - optional extension
        return

    dimension = _dimension()
    exists = bind.exec_driver_sql(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'document_chunks' "
        "AND column_name = 'embedding_vec'"
    ).scalar()
    if exists:
        current = bind.exec_driver_sql(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding_vec'"
        ).scalar()
        if current != f"vector({dimension})":
            op.execute(f"DROP INDEX IF EXISTS {INDEX}")
            op.execute("ALTER TABLE document_chunks DROP COLUMN embedding_vec")
            exists = False

    if not exists:
        op.execute(f"ALTER TABLE document_chunks ADD COLUMN embedding_vec vector({dimension})")

    op.execute(
        "UPDATE document_chunks SET embedding_vec = (embedding::text)::vector "
        "WHERE embedding IS NOT NULL AND embedding_vec IS NULL "
        f"AND json_array_length(embedding) = {dimension}"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {INDEX} ON document_chunks "
        "USING hnsw (embedding_vec vector_cosine_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding_vec")
