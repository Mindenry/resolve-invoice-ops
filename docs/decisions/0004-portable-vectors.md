# ADR 0004 — Portable data types and vector search

- **Status:** accepted
- **Date:** 2026-02-14

## Context

Production needs PostgreSQL + pgvector. CI and local evaluation must work without external services.
The model layer must not fork by dialect.

## Decision

Use SQLAlchemy portable types (`Uuid`, `JSON`, `Numeric`, `DateTime`) everywhere. Store embeddings as
JSON arrays in `document_chunks.embedding`. On PostgreSQL, the initial migration creates a pgvector
`embedding_vec vector(384)` side column and an HNSW cosine index; retrieval uses `<=>` when available
and falls back to exact cosine. Alembic excludes the side column from autogenerate comparisons.

## Consequences

- Tests run on SQLite with identical application code.
- ANN performance requires PostgreSQL; the JSON column remains the schema of record.
- Changing embedding dimension requires a migration and re-indexing.
