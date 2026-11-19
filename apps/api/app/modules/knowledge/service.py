"""Knowledge retrieval: keyword, vector and hybrid search with permission boundaries.

Vectors are stored as portable JSON arrays. When PostgreSQL + pgvector is available the
`document_chunks.embedding_vec` column and HNSW index created by the migration are used
for approximate nearest-neighbour search; otherwise exact cosine similarity is computed in
Python over the permission-filtered candidate set.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.ai.client import record_usage, run_coroutine_safely
from app.ai.registry import build_embedding_provider
from app.config.settings import settings
from app.core.logging import get_logger
from app.domain.enums import DocumentStatus, DocumentType
from app.models.cases import Case
from app.models.documents import Document, DocumentChunk
from app.modules.documents.schemas import DocumentSearchHit, DocumentSearchResponse

logger = get_logger(__name__)

ALLOWED_STATUSES = (
    DocumentStatus.INDEXED,
    DocumentStatus.EXTRACTED,
)

_pgvector_state: bool | None = None


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[0-9a-zก-๙]{2,}", value.lower()))


def keyword_score(query_tokens: set[str], content: str) -> float:
    if not query_tokens:
        return 0.0
    content_tokens = _tokens(content)
    if not content_tokens:
        return 0.0
    overlap = query_tokens & content_tokens
    if not overlap:
        return 0.0
    # Coverage of the query terms, dampened by content length so short precise chunks win.
    coverage = len(overlap) / len(query_tokens)
    density = len(overlap) / math.sqrt(len(content_tokens))
    return min(1.0, coverage * 0.8 + min(density, 0.2))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _candidate_chunks(
    db: Session, *, org_id: uuid.UUID, document_types: list[DocumentType] | None, limit: int = 1000
) -> list[tuple[DocumentChunk, Document]]:
    stmt = (
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.org_id == org_id,
            Document.deleted_at.is_(None),
            Document.status.in_(ALLOWED_STATUSES),
        )
        .limit(limit)
    )
    if document_types:
        stmt = stmt.where(Document.document_type.in_(document_types))
    return [(chunk, document) for chunk, document in db.execute(stmt).all()]


def _pgvector_ready(db: Session) -> bool:
    """Detect the optional pgvector column without poisoning the transaction.

    PostgreSQL aborts the whole transaction after a failed statement, so the
    probe runs inside a SAVEPOINT. The result is cached for the process.
    """
    global _pgvector_state
    if _pgvector_state is not None:
        return _pgvector_state
    if settings.is_sqlite:
        _pgvector_state = False
        return False
    try:
        with db.begin_nested():
            found = db.scalar(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'document_chunks' AND column_name = 'embedding_vec'"
                )
            )
        _pgvector_state = bool(found)
    except Exception as exc:  # noqa: BLE001 - optional extension
        _pgvector_state = False
        logger.info("pgvector_unavailable", error=str(exc)[:200])
    return _pgvector_state


def _pgvector_search(
    db: Session,
    *,
    org_id: uuid.UUID,
    query_vector: list[float],
    document_types: list[DocumentType] | None,
    limit: int,
) -> list[tuple[uuid.UUID, float]] | None:
    """Use pgvector when the database supports it. Returns None to fall back."""
    if settings.is_sqlite or not _pgvector_ready(db):
        return None
    try:
        vector_literal = "[" + ",".join(f"{value:.8f}" for value in query_vector) + "]"
        sql = text(
            """
            SELECT c.id, 1 - (c.embedding_vec <=> CAST(:vector AS vector)) AS score
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.org_id = :org_id
              AND d.deleted_at IS NULL
              AND d.status IN ('INDEXED', 'EXTRACTED')
              AND c.embedding_vec IS NOT NULL
            ORDER BY c.embedding_vec <=> CAST(:vector AS vector)
            LIMIT :limit
            """
        )
        with db.begin_nested():
            rows = db.execute(
                sql, {"vector": vector_literal, "org_id": org_id, "limit": limit}
            ).all()
        return [(row[0], float(row[1])) for row in rows]
    except Exception as exc:  # noqa: BLE001 - pgvector may be partially installed
        logger.info("pgvector_search_unavailable", error=str(exc)[:200])
        return None


def sync_embedding_vectors(db: Session, chunks: list[DocumentChunk]) -> None:
    """Mirror portable JSON embeddings into the optional pgvector column.

    New chunks would otherwise be invisible to the ANN path (the ORM model does
    not map the migration-only ``embedding_vec`` column).
    """
    if settings.is_sqlite or not _pgvector_ready(db):
        return
    params = [
        {"vector": json.dumps(chunk.embedding), "chunk_id": chunk.id}
        for chunk in chunks
        if chunk.embedding and chunk.id
    ]
    if not params:
        return
    try:
        with db.begin_nested():
            db.execute(
                text(
                    "UPDATE document_chunks SET embedding_vec = CAST(:vector AS vector) "
                    "WHERE id = :chunk_id"
                ),
                params,
            )
    except Exception as exc:  # noqa: BLE001 - keyword fallback remains available
        logger.warning("pgvector_sync_failed", error=str(exc)[:200])


def hybrid_search(
    db: Session,
    *,
    org_id: uuid.UUID,
    query: str,
    top_k: int = 6,
    document_types: list[DocumentType] | None = None,
    min_score: float | None = None,
) -> DocumentSearchResponse:
    query = query.strip()
    query_tokens = _tokens(query)
    notes: list[str] = []
    candidates = _candidate_chunks(db, org_id=org_id, document_types=document_types)
    vector_scores: dict[uuid.UUID, float] = {}
    mode = "keyword"

    provider = build_embedding_provider()
    if provider is not None and candidates:
        try:
            embedded = [chunk for chunk, _ in candidates if chunk.embedding]
            if embedded:
                result = run_coroutine_safely(provider.embed([query]))
                if result.vectors:
                    query_vector = result.vectors[0]
                    record_usage(
                        db,
                        org_id=org_id,
                        user_id=None,
                        purpose="knowledge_query",
                        provider=result.provider,
                        model=result.model,
                        input_tokens=result.input_tokens,
                        latency_ms=result.latency_ms,
                    )
                    pg_hits = _pgvector_search(
                        db,
                        org_id=org_id,
                        query_vector=query_vector,
                        document_types=document_types,
                        limit=max(top_k * 8, 50),
                    )
                    if pg_hits is not None:
                        vector_scores = dict(pg_hits)
                        mode = "hybrid+pgvector"
                    else:
                        for chunk, _ in candidates:
                            if chunk.embedding:
                                vector_scores[chunk.id] = max(
                                    0.0, cosine(query_vector, chunk.embedding)
                                )
                        mode = "hybrid"
            else:
                notes.append("No chunks have embeddings yet; keyword search was used.")
        except Exception as exc:  # noqa: BLE001 - retrieval must never fail the request
            logger.warning("query_embedding_failed", error=str(exc))
            notes.append("Embedding provider failed; results are keyword-only.")
    else:
        notes.append("Embedding provider is not configured; results are keyword-only.")

    threshold = settings.RETRIEVAL_MIN_SCORE if min_score is None else min_score
    scored: list[tuple[float, float, float, DocumentChunk, Document]] = []
    for chunk, document in candidates:
        keyword = keyword_score(query_tokens, chunk.content)
        vector = vector_scores.get(chunk.id, 0.0)
        combined = keyword if not vector_scores else settings.KEYWORD_WEIGHT * keyword + settings.VECTOR_WEIGHT * vector
        if combined < threshold:
            continue
        scored.append((combined, keyword, vector, chunk, document))
    scored.sort(key=lambda item: item[0], reverse=True)

    hits = [
        DocumentSearchHit(
            chunk_id=chunk.id,
            document_id=document.id,
            document_title=document.original_filename,
            document_type=document.document_type,
            page_start=chunk.page_start,
            content=chunk.content[:1500],
            score=round(combined, 4),
            keyword_score=round(keyword, 4),
            vector_score=round(vector, 4),
            metadata={
                "document_status": document.status.value,
                "vendor_id": str(document.vendor_id) if document.vendor_id else None,
                "chunk_index": chunk.chunk_index,
            },
        )
        for combined, keyword, vector, chunk, document in scored[:top_k]
    ]
    return DocumentSearchResponse(query=query, hits=hits, retrieval_mode=mode, notes=notes)


def similar_cases(
    db: Session, *, org_id: uuid.UUID, title: str, description: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Deterministic historical case retrieval by token overlap on resolution text."""
    query_tokens = _tokens(f"{title} {description}")
    if not query_tokens:
        return []
    cases = db.scalars(
        select(Case)
        .where(Case.org_id == org_id, Case.status.in_(["RESOLVED", "CLOSED"]))
        .order_by(Case.resolved_at.desc())
        .limit(200)
    ).all()
    scored: list[tuple[float, Case]] = []
    for case in cases:
        tokens = _tokens(f"{case.title} {case.description} {case.resolution_summary or ''}")
        if not tokens:
            continue
        overlap = len(query_tokens & tokens) / len(query_tokens)
        if overlap > 0:
            scored.append((overlap, case))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "case_id": str(case.id),
            "case_number": case.case_number,
            "title": case.title,
            "resolution_summary": (case.resolution_summary or "")[:600],
            "resolved_at": case.resolved_at.isoformat() if case.resolved_at else None,
            "score": round(score, 3),
        }
        for score, case in scored[:limit]
    ]


def validate_citation(
    db: Session, *, org_id: uuid.UUID, document_id: uuid.UUID | None, page_number: int | None
) -> tuple[bool, str | None]:
    if document_id is None:
        return False, "Document id is required for document evidence"
    document = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.org_id == org_id, Document.deleted_at.is_(None)
        )
    )
    if document is None:
        return False, "Referenced document does not exist in this organization"
    if page_number is not None:
        if page_number < 1 or (document.page_count and page_number > document.page_count):
            return False, f"Page {page_number} does not exist (document has {document.page_count} pages)"
        exists = db.scalar(
            select(DocumentChunk.id)
            .where(
                DocumentChunk.document_id == document.id,
                or_(DocumentChunk.page_start == page_number, DocumentChunk.page_end == page_number),
            )
            .limit(1)
        )
        if exists is None and document.page_count == 0:
            return False, "Document has no extracted pages"
    return True, None
