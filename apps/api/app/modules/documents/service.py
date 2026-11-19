"""Document upload, asynchronous processing, extraction review and knowledge indexing."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai.client import record_usage, run_coroutine_safely
from app.ai.registry import build_embedding_provider
from app.config.settings import settings
from app.core.errors import BadRequestError, ConflictError, NotFoundError, UnprocessableError
from app.core.logging import get_logger
from app.core.money import parse_amount
from app.core.pagination import Pagination
from app.core.security import utcnow
from app.core.text import chunk_text, normalize_currency, normalize_name, normalize_tax_id, similarity
from app.domain.enums import (
    DocumentStatus,
    DocumentType,
    EventType,
    ExtractionMethod,
    ExtractionRunStatus,
    InvoiceStatus,
    NotificationType,
    ReviewStatus,
)
from app.models.documents import (
    Document,
    DocumentChunk,
    DocumentExtraction,
    DocumentPage,
    DocumentVersion,
    ExtractedField,
)
from app.models.finance import Invoice, PurchaseOrder, Vendor
from app.modules.documents import ai_extract
from app.modules.documents.parsing import (
    FieldCandidate,
    average_confidence,
    extract_invoice_fields,
    missing_required,
)
from app.modules.documents.processing import (
    ParsedDocument,
    ocr_status,
    parse_document,
)
from app.modules.documents.schemas import (
    DocumentDetail,
    DocumentOut,
    DocumentVersionOut,
    ExtractionOut,
    FieldOut,
    PageOut,
)
from app.services.audit import record_audit
from app.services.deferred import queue_task_after_commit
from app.services.events import emit_event
from app.services.notifications import notify
from app.services.storage import compute_sha256, get_storage, storage_key

logger = get_logger(__name__)

ALLOWED_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

MAGIC = {
    ".pdf": b"%PDF",
    ".png": b"\x89PNG",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".docx": b"PK\x03\x04",
    ".xlsx": b"PK\x03\x04",
}


def _sanitize_filename(filename: str) -> str:
    name = Path(filename or "document").name
    name = "".join(ch for ch in name if ch.isprintable() and ch not in {'"', "'", "\\", "/"})
    name = name.strip(". ") or "document"
    if len(name) > 200:
        stem = Path(name).stem[:150]
        name = f"{stem}{Path(name).suffix}"
    return name


def validate_upload(filename: str, content_type: str | None, data: bytes) -> tuple[str, str]:
    """Returns (safe filename, canonical mime type). Raises a typed 4xx on failure."""
    safe_name = _sanitize_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_TYPES:
        raise UnprocessableError(
            f"Unsupported file type '{suffix or 'none'}'. Allowed: {', '.join(sorted(ALLOWED_TYPES))}.",
            code="unsupported_file_type",
        )
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if not data:
        raise UnprocessableError("The uploaded file is empty.", code="empty_file")
    if len(data) > max_bytes:
        raise UnprocessableError(
            f"File exceeds the {settings.MAX_UPLOAD_MB} MB upload limit.", code="file_too_large"
        )
    magic = MAGIC.get(suffix)
    if magic and not data.startswith(magic):
        raise UnprocessableError(
            "File content does not match its extension.", code="mime_mismatch"
        )
    canonical = ALLOWED_TYPES[suffix]
    if content_type and content_type not in {canonical, "application/octet-stream"}:
        # Browsers occasionally send a generic type; the extension + magic check above is authoritative.
        logger.info("upload_mime_mismatch", provided=content_type, expected=canonical)
    return safe_name, canonical


def get_document(db: Session, *, org_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.org_id == org_id, Document.deleted_at.is_(None)
        )
    )
    if document is None:
        raise NotFoundError("Document not found.", code="document_not_found")
    return document


def latest_extraction(db: Session, document_id: uuid.UUID) -> DocumentExtraction | None:
    return db.scalar(
        select(DocumentExtraction)
        .where(DocumentExtraction.document_id == document_id)
        .order_by(DocumentExtraction.created_at.desc())
        .limit(1)
    )


def _chunk_count(db: Session, document_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document_id)
    ) or 0


def _doc_out(db: Session, document: Document, extraction: DocumentExtraction | None = None) -> DocumentOut:
    extraction = extraction or latest_extraction(db, document.id)
    return DocumentOut(
        id=document.id,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        document_type=document.document_type,
        status=document.status,
        page_count=document.page_count,
        char_count=document.char_count,
        ocr_confidence=document.ocr_confidence,
        requires_review=document.requires_review,
        current_version=document.current_version,
        vendor_id=document.vendor_id,
        processing_error=document.processing_error,
        is_demo=document.is_demo,
        created_at=document.created_at,
        processed_at=document.processed_at,
        indexed_at=document.indexed_at,
        has_extraction=extraction is not None,
        chunk_count=_chunk_count(db, document.id),
    )


def _field_out(field: ExtractedField) -> FieldOut:
    return FieldOut(
        id=field.id,
        field_name=field.field_name,
        value=field.value,
        effective_value=field.effective_value,
        normalized_value=field.normalized_value,
        page_number=field.page_number,
        source_text=field.source_text,
        confidence=field.confidence,
        method=field.method,
        review_status=field.review_status,
        corrected_value=field.corrected_value,
        bounding_box=field.bounding_box,
        notes=field.notes,
    )


def _extraction_out(db: Session, extraction: DocumentExtraction) -> ExtractionOut:
    fields = db.scalars(
        select(ExtractedField)
        .where(ExtractedField.extraction_id == extraction.id)
        .order_by(ExtractedField.field_name)
    ).all()
    return ExtractionOut(
        id=extraction.id,
        document_id=extraction.document_id,
        document_version=extraction.document_version,
        status=extraction.status,
        provider=extraction.provider,
        model=extraction.model,
        prompt_version=extraction.prompt_version,
        field_count=extraction.field_count,
        avg_confidence=extraction.avg_confidence,
        requires_review=extraction.requires_review,
        review_status=extraction.review_status,
        review_note=extraction.review_note,
        error=extraction.error,
        started_at=extraction.started_at,
        finished_at=extraction.finished_at,
        created_at=extraction.created_at,
        fields=[_field_out(field) for field in fields],
    )


def detail(db: Session, document: Document, *, include_text: bool = True) -> DocumentDetail:
    extraction = latest_extraction(db, document.id)
    pages = db.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_number)
    ).all()
    versions = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version.desc())
    ).all()
    available, reason = ocr_status()
    base = _doc_out(db, document, extraction)

    # Bound the response body: a single very large or badly OCR'd document must
    # not be able to produce an unbounded JSON payload.
    remaining = max(settings.DOCUMENT_DETAIL_MAX_CHARS, 0)
    capped_pages: list[PageOut] = []
    for page in pages:
        if not include_text:
            budget, text = 1500, page.text or ""
        else:
            budget, text = remaining, page.text or ""
        clipped = text[:budget]
        remaining -= len(clipped)
        capped_pages.append(
            PageOut(
                page_number=page.page_number,
                text=clipped,
                char_count=page.char_count,
                has_text_layer=page.has_text_layer,
                ocr_confidence=page.ocr_confidence,
                extra=page.extra or {},
            )
        )

    return DocumentDetail(
        **base.model_dump(),
        metadata=document.metadata_ or {},
        pages=capped_pages,
        versions=[DocumentVersionOut.model_validate(version) for version in versions],
        extraction=_extraction_out(db, extraction) if extraction else None,
        capabilities={"ocr_available": available, "ocr_detail": reason},
    )


def list_documents(
    db: Session,
    *,
    org_id: uuid.UUID,
    pagination: Pagination,
    search: str | None = None,
    status: list[DocumentStatus] | None = None,
    document_type: DocumentType | None = None,
    vendor_id: uuid.UUID | None = None,
    requires_review: bool | None = None,
) -> tuple[list[DocumentOut], int]:
    stmt = select(Document).where(Document.org_id == org_id, Document.deleted_at.is_(None))
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(or_(func.lower(Document.original_filename).like(pattern)))
    if status:
        stmt = stmt.where(Document.status.in_(status))
    if document_type:
        stmt = stmt.where(Document.document_type == document_type)
    if vendor_id:
        stmt = stmt.where(Document.vendor_id == vendor_id)
    if requires_review is not None:
        stmt = stmt.where(Document.requires_review.is_(requires_review))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sort_column = {
        "created_at": Document.created_at,
        "original_filename": Document.original_filename,
        "status": Document.status,
        "size_bytes": Document.size_bytes,
    }.get(pagination.sort or "created_at", Document.created_at)
    ordering = sort_column.asc() if pagination.order == "asc" else sort_column.desc()
    rows = db.scalars(stmt.order_by(ordering).offset(pagination.offset).limit(pagination.page_size)).all()
    return [_doc_out(db, document) for document in rows], total


def upload_document(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    filename: str,
    content_type: str | None,
    data: bytes,
    document_type: DocumentType = DocumentType.INVOICE,
    vendor_id: uuid.UUID | None = None,
    is_demo: bool = False,
) -> tuple[Document, bool]:
    safe_name, mime_type = validate_upload(filename, content_type, data)
    sha256 = compute_sha256(data)
    existing = db.scalar(
        select(Document).where(Document.org_id == org_id, Document.sha256 == sha256)
    )
    if existing is not None:
        raise ConflictError(
            "This file has already been uploaded to the organization.",
            code="duplicate_document",
            details={"document_id": str(existing.id), "filename": existing.original_filename},
        )
    if vendor_id is not None:
        vendor = db.scalar(
            select(Vendor).where(Vendor.id == vendor_id, Vendor.org_id == org_id, Vendor.deleted_at.is_(None))
        )
        if vendor is None:
            raise BadRequestError("Vendor not found in this organization.", code="vendor_not_found")

    key = storage_key(str(org_id), sha256, safe_name)
    storage = get_storage()
    storage.save(key, data)

    document = Document(
        org_id=org_id,
        uploaded_by_id=actor_id,
        vendor_id=vendor_id,
        original_filename=safe_name,
        storage_filename=safe_name,
        mime_type=mime_type,
        size_bytes=len(data),
        sha256=sha256,
        storage_key=key,
        storage_backend=storage.name,
        document_type=document_type,
        status=DocumentStatus.QUEUED,
        current_version=1,
        is_demo=is_demo,
        metadata_={"upload": {"content_type": content_type, "storage": storage.name}},
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentVersion(
            document_id=document.id,
            version=1,
            storage_key=key,
            sha256=sha256,
            size_bytes=len(data),
            note="Initial upload",
            created_by_id=actor_id,
        )
    )
    record_audit(
        db,
        org_id=org_id,
        action="document.uploaded",
        entity_type="document",
        entity_id=document.id,
        summary=f"Document {safe_name} uploaded",
        actor_id=actor_id,
        after={"filename": safe_name, "size": len(data), "document_type": document_type.value},
    )
    emit_event(
        db,
        org_id=org_id,
        event_type=EventType.DOCUMENT_UPLOADED,
        entity_type="DOCUMENT",
        entity_id=document.id,
        payload={"filename": safe_name, "document_type": document_type.value},
    )
    queue_task_after_commit(
        db, "process_document", {"document_id": str(document.id)}, org_id
    )
    return document, False


# ---------------------------------------------------------------------------- processing


def _bbox_for(page: DocumentPage, value: str) -> dict[str, Any] | None:
    boxes = (page.extra or {}).get("ocr_boxes") or []
    if not boxes or not value:
        return None
    token = value.split()[0].strip().lower()
    for box in boxes:
        if str(box.get("text", "")).lower().startswith(token[:12]):
            return {
                "left": box.get("left"),
                "top": box.get("top"),
                "width": box.get("width"),
                "height": box.get("height"),
            }
    return None


def _store_pages(db: Session, document: Document, parsed: ParsedDocument) -> dict[int, DocumentPage]:
    for existing in db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all():
        db.delete(existing)
    db.flush()
    pages: dict[int, DocumentPage] = {}
    for result in parsed.pages:
        page = DocumentPage(
            document_id=document.id,
            page_number=result.page_number,
            text=result.text,
            char_count=len(result.text),
            has_text_layer=result.has_text_layer,
            ocr_confidence=result.ocr_confidence,
            width=result.width,
            height=result.height,
            extra=result.extra,
        )
        db.add(page)
        pages[result.page_number] = page
    db.flush()
    return pages


def _ai_fallback(
    db: Session,
    *,
    org_id: uuid.UUID,
    document: Document,
    pages: list[tuple[int, str]],
    existing: list[FieldCandidate],
    actor_id: uuid.UUID | None,
) -> tuple[list[FieldCandidate], dict[str, Any]]:
    from app.ai.registry import build_llm_provider

    provider = build_llm_provider()
    if provider is None or not settings.AI_EXTRACTION_ENABLED:
        return [], {"status": "skipped", "reason": "llm_not_configured"}
    existing_values = {candidate.field_name: candidate.value for candidate in existing}
    try:
        extraction = run_coroutine_safely(
            ai_extract.extract_with_llm(pages=pages, provider=provider, existing=existing_values)
        )
    except Exception as exc:  # noqa: BLE001 - AI failure must not destroy deterministic extraction
        logger.warning("ai_extraction_failed", document_id=str(document.id), error=str(exc))
        record_usage(
            db,
            org_id=org_id,
            user_id=actor_id,
            purpose="invoice_extraction",
            provider=settings.AI_PROVIDER,
            model=settings.AI_MODEL,
            prompt_version=ai_extract.prompt_version(),
            status="FAILED",
            error=str(exc)[:400],
        )
        return [], {"status": "failed", "reason": str(exc)[:300]}
    candidates: list[FieldCandidate] = []
    for item in extraction.fields:
        if item.field_name in existing_values:
            continue
        candidates.append(
            FieldCandidate(
                field_name=item.field_name,
                value=item.value,
                page_number=item.page_number or 1,
                source_text=item.source_text or item.value,
                confidence=float(item.confidence),
                method="LLM",
            )
        )
    record_usage(
        db,
        org_id=org_id,
        user_id=actor_id,
        purpose="invoice_extraction",
        provider=extraction.provider,
        model=extraction.model,
        prompt_version=ai_extract.prompt_version(),
        input_tokens=extraction.input_tokens,
        output_tokens=extraction.output_tokens,
        latency_ms=extraction.latency_ms,
    )
    return candidates, {
        "status": "completed",
        "provider": extraction.provider,
        "model": extraction.model,
        "rejected": extraction.rejected,
        "prompt_version": ai_extract.prompt_version(),
        "input_tokens": extraction.input_tokens,
        "output_tokens": extraction.output_tokens,
        "latency_ms": extraction.latency_ms,
    }


def extract_and_store(
    db: Session,
    *,
    document: Document,
    parsed: ParsedDocument,
    actor_id: uuid.UUID | None,
) -> DocumentExtraction | None:
    pages = _store_pages(db, document, parsed)
    page_map = {page.page_number: page for page in pages.values()}
    document.page_count = len(parsed.pages)
    document.char_count = parsed.char_count
    document.ocr_confidence = parsed.ocr_confidence
    document.metadata_ = {
        **(document.metadata_ or {}),
        "parser": parsed.parser,
        "parser_metadata": parsed.metadata,
    }
    if document.document_type != DocumentType.INVOICE:
        # Contracts, policies and SOPs are indexed for retrieval but are not parsed as invoices.
        document.status = DocumentStatus.EXTRACTED
        document.processed_at = utcnow()
        document.processing_error = None
        document.requires_review = False
        db.flush()
        record_audit(
            db,
            org_id=document.org_id,
            action="document.indexed_source",
            entity_type="document",
            entity_id=document.id,
            summary=f"Source document prepared for retrieval: {document.original_filename}",
            actor_id=actor_id,
            after={"pages": len(parsed.pages), "document_type": document.document_type.value},
        )
        return None

    document.status = DocumentStatus.VALIDATING
    db.flush()

    extraction = DocumentExtraction(
        org_id=document.org_id,
        document_id=document.id,
        document_version=document.current_version,
        status=ExtractionRunStatus.RUNNING,
        provider="deterministic",
        prompt_version=None,
        started_at=utcnow(),
    )
    db.add(extraction)
    db.flush()

    text_pages = [(page.page_number, page.text) for page in parsed.pages]
    candidates = extract_invoice_fields(text_pages, ocr_confidence=parsed.ocr_confidence)
    ai_meta: dict[str, Any] = {"status": "skipped", "reason": "not_required"}
    if document.document_type == DocumentType.INVOICE and missing_required(candidates):
        ai_candidates, ai_meta = _ai_fallback(
            db,
            org_id=document.org_id,
            document=document,
            pages=text_pages,
            existing=candidates,
            actor_id=actor_id,
        )
        candidates.extend(ai_candidates)

    for candidate in candidates:
        normalized: str | None = None
        if candidate.field_name in {"subtotal", "tax", "total"}:
            amount = parse_amount(candidate.value)
            normalized = str(amount) if amount is not None else None
        elif candidate.field_name == "currency":
            normalized = normalize_currency(candidate.value, default="")
        elif candidate.field_name == "invoice_date" or candidate.field_name == "due_date":
            normalized = candidate.value
        db.add(
            ExtractedField(
                org_id=document.org_id,
                extraction_id=extraction.id,
                document_id=document.id,
                field_name=candidate.field_name,
                value=candidate.value,
                normalized_value=normalized,
                page_number=candidate.page_number,
                source_text=candidate.source_text,
                confidence=round(float(candidate.confidence), 3),
                method=ExtractionMethod(candidate.method),
                bounding_box=_bbox_for(page_map.get(candidate.page_number), candidate.source_text or "")
                if candidate.page_number in page_map
                else None,
                notes=None,
            )
        )

    missing = missing_required(candidates) if document.document_type == DocumentType.INVOICE else []
    values = {candidate.field_name: candidate.value for candidate in candidates}
    arithmetic_notes = ai_extract.validate_extracted_arithmetic(values)
    avg_confidence = average_confidence(candidates)
    low_confidence = bool(parsed.ocr_confidence is not None and parsed.ocr_confidence < 0.6)
    requires_review = bool(
        missing
        or arithmetic_notes
        or (candidates and avg_confidence < 0.6)
        or low_confidence
        or parsed.metadata.get("truncated")
    )
    extraction.status = ExtractionRunStatus.REQUIRES_REVIEW if requires_review else ExtractionRunStatus.COMPLETED
    extraction.field_count = len(candidates)
    extraction.avg_confidence = avg_confidence
    extraction.requires_review = requires_review
    extraction.finished_at = utcnow()
    extraction.raw_output = {
        "deterministic_fields": len([c for c in candidates if c.method != "LLM"]),
        "llm": ai_meta,
        "missing_required": missing,
        "arithmetic_notes": arithmetic_notes,
        "parser": parsed.parser,
        "ocr_confidence": parsed.ocr_confidence,
    }
    if ai_meta.get("status") == "completed":
        extraction.provider = ai_meta.get("provider", settings.AI_PROVIDER)
        extraction.model = ai_meta.get("model")
        extraction.prompt_version = ai_meta.get("prompt_version")
        extraction.input_tokens = int(ai_meta.get("input_tokens") or 0)
        extraction.output_tokens = int(ai_meta.get("output_tokens") or 0)

    document.requires_review = requires_review
    document.status = DocumentStatus.REQUIRES_REVIEW if requires_review else DocumentStatus.EXTRACTED
    document.processed_at = utcnow()
    document.processing_error = None
    document.metadata_ = {
        **(document.metadata_ or {}),
        "extraction": {
            "missing_required": missing,
            "arithmetic_notes": arithmetic_notes,
            "ocr_confidence": parsed.ocr_confidence,
        },
    }
    db.flush()
    record_audit(
        db,
        org_id=document.org_id,
        action="document.extracted",
        entity_type="document",
        entity_id=document.id,
        summary=f"Extraction completed for {document.original_filename}",
        actor_id=actor_id,
        after={
            "fields": len(candidates),
            "avg_confidence": avg_confidence,
            "requires_review": requires_review,
            "provider": extraction.provider,
        },
    )
    return extraction


def index_document(db: Session, *, document: Document) -> dict[str, Any]:
    pages = db.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_number)
    ).all()
    for existing in db.scalars(
        select(DocumentChunk).where(DocumentChunk.document_id == document.id)
    ).all():
        db.delete(existing)
    db.flush()

    created: list[DocumentChunk] = []
    index = 0
    for page in pages:
        for piece in chunk_text(
            page.text, size=settings.CHUNK_SIZE, overlap=settings.CHUNK_OVERLAP
        ):
            chunk = DocumentChunk(
                org_id=document.org_id,
                document_id=document.id,
                chunk_index=index,
                content=piece,
                page_start=page.page_number,
                page_end=page.page_number,
                token_estimate=max(1, len(piece) // 4),
                metadata_={
                    "document_type": document.document_type.value,
                    "filename": document.original_filename,
                    "page": page.page_number,
                },
            )
            db.add(chunk)
            created.append(chunk)
            index += 1
    db.flush()
    if not created:
        return {"chunks": 0, "status": "empty"}

    provider = build_embedding_provider()
    if provider is None:
        document.metadata_ = {
            **(document.metadata_ or {}),
            "indexing": {"status": "keyword_only", "reason": "embedding_provider_not_configured"},
        }
        db.flush()
        return {"chunks": len(created), "status": "keyword_only"}

    try:
        vectors: list[list[float]] = []
        for start in range(0, len(created), 32):
            batch = created[start : start + 32]
            result = run_coroutine_safely(provider.embed([chunk.content for chunk in batch]))
            vectors.extend(result.vectors)
            record_usage(
                db,
                org_id=document.org_id,
                user_id=None,
                purpose="document_indexing",
                provider=result.provider,
                model=result.model,
                prompt_version=None,
                input_tokens=result.input_tokens,
                output_tokens=0,
                latency_ms=result.latency_ms,
            )
        for chunk, vector in zip(created, vectors, strict=False):
            chunk.embedding = vector
            chunk.embedding_model = provider.model
            chunk.embedding_dim = len(vector)
        db.flush()
        from app.modules.knowledge.service import sync_embedding_vectors

        sync_embedding_vectors(db, created)
        document.indexed_at = utcnow()
        if document.status == DocumentStatus.EXTRACTED:
            document.status = DocumentStatus.INDEXED
        document.metadata_ = {
            **(document.metadata_ or {}),
            "indexing": {"status": "indexed", "model": provider.model, "chunks": len(created)},
        }
        db.flush()
        return {"chunks": len(created), "status": "indexed"}
    except Exception as exc:  # noqa: BLE001 - indexing must degrade gracefully
        logger.warning("document_indexing_failed", document_id=str(document.id), error=str(exc))
        document.metadata_ = {
            **(document.metadata_ or {}),
            "indexing": {"status": "failed", "reason": str(exc)[:300], "chunks": len(created)},
        }
        db.flush()
        return {"chunks": len(created), "status": "failed", "reason": str(exc)[:200]}


def process_document_job(document_id: uuid.UUID, org_id: uuid.UUID) -> dict[str, Any]:
    """Background entry point: parse, extract, index using short transactions.

    The status transition is claimed atomically so a duplicated queue delivery cannot
    process the same document twice and collide on page/chunk rows.
    """
    from sqlalchemy import update

    from app.db.session import session_scope

    with session_scope() as db:
        document = db.get(Document, document_id)
        if document is None or document.org_id != org_id:
            return {"status": "skipped", "reason": "document_not_found"}
        if document.status in {DocumentStatus.INDEXED, DocumentStatus.EXTRACTED} and document.processed_at:
            return {"status": "skipped", "reason": "already_processed"}
        claim = db.execute(
            update(Document)
            .where(
                Document.id == document_id,
                Document.org_id == org_id,
                Document.status.in_(
                    [DocumentStatus.QUEUED, DocumentStatus.UPLOADED, DocumentStatus.FAILED, DocumentStatus.REQUIRES_REVIEW]
                ),
            )
            .values(status=DocumentStatus.PROCESSING, processing_error=None)
        )
        if claim.rowcount == 0:
            return {"status": "skipped", "reason": "claimed_elsewhere"}
        db.refresh(document)
        storage_key_value = document.storage_key
        mime_type = document.mime_type
        filename = document.original_filename

    try:
        data = get_storage().read(storage_key_value)
        parsed = parse_document(data, mime_type=mime_type, filename=filename)
    except Exception as exc:  # noqa: BLE001 - persist the failure for the UI
        with session_scope() as db:
            document = db.get(Document, document_id)
            if document is not None:
                document.status = DocumentStatus.FAILED
                document.processing_error = f"{type(exc).__name__}: {exc}"[:2000]
                document.requires_review = True
                document.metadata_ = {
                    **(document.metadata_ or {}),
                    "processing_error": {"code": getattr(exc, "code", "processing_error"), "message": str(exc)[:500]},
                }
                record_audit(
                    db,
                    org_id=org_id,
                    action="document.processing_failed",
                    entity_type="document",
                    entity_id=document.id,
                    summary=f"Processing failed for {document.original_filename}",
                    after={"error": str(exc)[:300]},
                )
                emit_event(
                    db,
                    org_id=org_id,
                    event_type=EventType.DOCUMENT_FAILED,
                    entity_type="DOCUMENT",
                    entity_id=document.id,
                    payload={
                        "filename": document.original_filename,
                        "status": document.status.value,
                        "error_code": getattr(exc, "code", "processing_error"),
                        "error": str(exc)[:500],
                        "attempts": len((document.metadata_ or {}).get("processing_attempts", [])),
                    },
                )
                notify(
                    db,
                    org_id=org_id,
                    user_id=document.uploaded_by_id,
                    type=NotificationType.DOCUMENT_PROCESSED,
                    title=f"Processing failed: {document.original_filename}",
                    body=str(exc)[:400],
                    entity_type="DOCUMENT",
                    entity_id=document.id,
                )
        raise

    with session_scope() as db:
        document = db.get(Document, document_id)
        if document is None:
            return {"status": "skipped", "reason": "document_deleted"}
        extraction = extract_and_store(db, document=document, parsed=parsed, actor_id=None)
        index_result = index_document(db, document=document)
        field_count = extraction.field_count if extraction else 0
        emit_event(
            db,
            org_id=org_id,
            event_type=EventType.DOCUMENT_PROCESSED,
            entity_type="DOCUMENT",
            entity_id=document.id,
            payload={
                "status": document.status.value,
                "fields": field_count,
                "requires_review": document.requires_review,
                "indexing": index_result,
            },
        )
        notify(
            db,
            org_id=org_id,
            user_id=document.uploaded_by_id,
            type=NotificationType.DOCUMENT_PROCESSED,
            title=(
                f"Review required: {document.original_filename}"
                if document.requires_review
                else f"Processed: {document.original_filename}"
            ),
            body=(
                f"{field_count} fields extracted ({extraction.avg_confidence or 0:.2f} average confidence)."
                if extraction
                else "Document indexed for retrieval. No invoice fields were extracted for this document type."
            ),
            entity_type="DOCUMENT",
            entity_id=document.id,
        )
        return {
            "status": document.status.value,
            "extraction_id": str(extraction.id) if extraction else None,
            "fields": field_count,
            "indexing": index_result,
        }


# ------------------------------------------------------------------------------- review


def correct_field(
    db: Session,
    *,
    document: Document,
    field_id: uuid.UUID,
    value: str | None,
    notes: str | None,
    actor_id: uuid.UUID | None,
) -> ExtractedField:
    field = db.scalar(
        select(ExtractedField).where(
            ExtractedField.id == field_id,
            ExtractedField.document_id == document.id,
            ExtractedField.org_id == document.org_id,
        )
    )
    if field is None:
        raise NotFoundError("Extracted field not found.", code="field_not_found")
    before = {"value": field.effective_value, "review_status": field.review_status.value}
    field.corrected_value = value
    field.corrected_by_id = actor_id
    field.corrected_at = utcnow()
    field.review_status = ReviewStatus.CORRECTED
    if notes is not None:
        field.notes = notes
    record_audit(
        db,
        org_id=document.org_id,
        action="document.field_corrected",
        entity_type="document",
        entity_id=document.id,
        summary=f"Field '{field.field_name}' corrected",
        actor_id=actor_id,
        before=before,
        after={"value": value, "notes": notes},
    )
    return field


def review_extraction(
    db: Session,
    *,
    document: Document,
    action: str,
    note: str | None,
    approve_low_confidence_fields: bool,
    actor_id: uuid.UUID | None,
) -> DocumentExtraction:
    extraction = latest_extraction(db, document.id)
    if extraction is None:
        raise BadRequestError("This document has no extraction to review.", code="no_extraction")
    if extraction.review_status == ReviewStatus.APPROVED and action == "APPROVE":
        return extraction
    fields = db.scalars(
        select(ExtractedField).where(ExtractedField.extraction_id == extraction.id)
    ).all()
    if action == "APPROVE":
        low = [field for field in fields if field.confidence < 0.6 and field.review_status == ReviewStatus.PENDING]
        if low and not approve_low_confidence_fields:
            raise BadRequestError(
                "Some fields have low confidence. Confirm them explicitly before approving.",
                code="low_confidence_fields",
                details={
                    "fields": [
                        {"id": str(field.id), "field_name": field.field_name, "confidence": field.confidence}
                        for field in low
                    ]
                },
            )
        for field in fields:
            if field.review_status in {ReviewStatus.PENDING, ReviewStatus.CORRECTED}:
                field.review_status = ReviewStatus.APPROVED
        extraction.review_status = ReviewStatus.APPROVED
        extraction.requires_review = False
        extraction.review_note = note
        document.requires_review = False
        document.status = DocumentStatus.INDEXED if document.indexed_at else DocumentStatus.EXTRACTED
        summary = "Extraction approved"
    elif action == "REJECT":
        if not note:
            raise BadRequestError("A rejection note is required.", code="note_required")
        for field in fields:
            if field.review_status == ReviewStatus.PENDING:
                field.review_status = ReviewStatus.REJECTED
        extraction.review_status = ReviewStatus.REJECTED
        extraction.review_note = note
        extraction.requires_review = True
        document.requires_review = True
        document.status = DocumentStatus.REQUIRES_REVIEW
        summary = "Extraction rejected"
    else:
        raise BadRequestError("Unsupported review action.", code="invalid_review_action")
    extraction.reviewed_by_id = actor_id
    extraction.reviewed_at = utcnow()
    record_audit(
        db,
        org_id=document.org_id,
        action="document.extraction_reviewed",
        entity_type="document",
        entity_id=document.id,
        summary=summary,
        actor_id=actor_id,
        after={"action": action, "note": note, "status": document.status.value},
    )
    notify(
        db,
        org_id=document.org_id,
        user_id=document.uploaded_by_id,
        type=NotificationType.DOCUMENT_PROCESSED,
        title=f"{summary}: {document.original_filename}",
        body=(note or "")[:400],
        entity_type="DOCUMENT",
        entity_id=document.id,
    )
    return extraction


def reprocess_document(
    db: Session, *, document: Document, actor_id: uuid.UUID | None, reason: str | None = None
) -> None:
    if document.status == DocumentStatus.PROCESSING:
        raise ConflictError("The document is already being processed.", code="already_processing")
    document.status = DocumentStatus.QUEUED
    document.processing_error = None
    document.requires_review = False
    record_audit(
        db,
        org_id=document.org_id,
        action="document.reprocessing_requested",
        entity_type="document",
        entity_id=document.id,
        summary=f"Reprocessing requested for {document.original_filename}",
        actor_id=actor_id,
        context={"reason": reason},
    )
    queue_task_after_commit(
        db, "process_document", {"document_id": str(document.id)}, document.org_id
    )


def add_version(
    db: Session,
    *,
    document: Document,
    actor_id: uuid.UUID | None,
    filename: str,
    content_type: str | None,
    data: bytes,
    note: str | None = None,
) -> DocumentVersion:
    safe_name, mime_type = validate_upload(filename, content_type, data)
    sha256 = compute_sha256(data)
    if sha256 == document.sha256:
        raise ConflictError(
            "The new version is identical to the current file.", code="duplicate_version"
        )
    duplicate_version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id, DocumentVersion.sha256 == sha256
        )
    )
    if duplicate_version is not None:
        raise ConflictError(
            "This file was already uploaded as a previous version.", code="duplicate_version"
        )
    other_document = db.scalar(
        select(Document).where(
            Document.org_id == document.org_id,
            Document.sha256 == sha256,
            Document.id != document.id,
            Document.deleted_at.is_(None),
        )
    )
    if other_document is not None:
        raise ConflictError(
            "This file belongs to another document in the organization.",
            code="duplicate_document",
            details={"document_id": str(other_document.id)},
        )

    key = storage_key(str(document.org_id), sha256, safe_name)
    get_storage().save(key, data)
    new_version = document.current_version + 1
    version = DocumentVersion(
        document_id=document.id,
        version=new_version,
        storage_key=key,
        sha256=sha256,
        size_bytes=len(data),
        note=note,
        created_by_id=actor_id,
    )
    db.add(version)
    document.current_version = new_version
    document.storage_key = key
    document.sha256 = sha256
    document.size_bytes = len(data)
    document.mime_type = mime_type
    document.storage_backend = get_storage().name
    document.status = DocumentStatus.QUEUED
    document.processing_error = None
    document.requires_review = False
    document.processed_at = None
    document.indexed_at = None
    for page in db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all():
        db.delete(page)
    for chunk in db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all():
        db.delete(chunk)
    record_audit(
        db,
        org_id=document.org_id,
        action="document.version_added",
        entity_type="document",
        entity_id=document.id,
        summary=f"Document version {new_version} uploaded",
        actor_id=actor_id,
        after={"version": new_version, "sha256": sha256, "note": note},
    )
    queue_task_after_commit(
        db, "process_document", {"document_id": str(document.id)}, document.org_id
    )
    return version


# ------------------------------------------------------------------- invoice creation


def _resolve_vendor_from_fields(
    db: Session, *, org_id: uuid.UUID, fields: dict[str, str]
) -> Vendor | None:
    tax_id = normalize_tax_id(fields.get("vendor_tax_id"))
    if tax_id:
        vendor = db.scalar(
            select(Vendor).where(
                Vendor.org_id == org_id, Vendor.tax_id == tax_id, Vendor.deleted_at.is_(None)
            )
        )
        if vendor is not None:
            return vendor
    name = fields.get("vendor_name")
    if name:
        normalized = normalize_name(name)
        candidates = db.scalars(
            select(Vendor).where(Vendor.org_id == org_id, Vendor.deleted_at.is_(None))
        ).all()
        for vendor in candidates:
            if vendor.normalized_name == normalized:
                return vendor
        best = max(candidates, key=lambda v: similarity(v.normalized_name, normalized), default=None)
        if best is not None and similarity(best.normalized_name, normalized) >= 0.92:
            return best
    return None


def create_invoice_from_document(
    db: Session,
    *,
    document: Document,
    actor_id: uuid.UUID | None,
    vendor_id: uuid.UUID | None = None,
    purchase_order_id: uuid.UUID | None = None,
) -> Invoice:
    from app.modules.documents.parsing import parse_date
    from app.modules.exceptions.service import detect_for_invoice
    from app.modules.invoices.schemas import InvoiceCreate
    from app.modules.invoices.service import create_invoice, validate_invoice

    existing = db.scalar(
        select(Invoice).where(
            Invoice.org_id == document.org_id,
            Invoice.document_id == document.id,
            Invoice.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing

    extraction = latest_extraction(db, document.id)
    if extraction is None:
        raise BadRequestError("The document has not been extracted yet.", code="no_extraction")
    if extraction.review_status == ReviewStatus.REJECTED:
        raise BadRequestError("The extraction was rejected and cannot be converted.", code="extraction_rejected")
    fields_rows = db.scalars(
        select(ExtractedField).where(ExtractedField.extraction_id == extraction.id)
    ).all()
    fields = {row.field_name: (row.effective_value or "") for row in fields_rows if row.effective_value}

    invoice_number = fields.get("invoice_number")
    if not invoice_number:
        raise UnprocessableError(
            "Invoice number is missing from the extraction.", code="missing_invoice_number"
        )
    invoice_date = parse_date(fields.get("invoice_date", ""))
    if invoice_date is None:
        raise UnprocessableError("Invoice date is missing or invalid.", code="missing_invoice_date")
    total = parse_amount(fields.get("total"))
    if total is None:
        raise UnprocessableError("Invoice total is missing or invalid.", code="missing_total")
    subtotal = parse_amount(fields.get("subtotal")) or total
    tax = parse_amount(fields.get("tax")) or (total - subtotal)
    if tax < 0:
        tax = Decimal("0")
    due_date = parse_date(fields.get("due_date", "")) if fields.get("due_date") else None
    currency = normalize_currency(fields.get("currency"), default="USD")

    vendor = None
    if vendor_id:
        vendor = db.scalar(
            select(Vendor).where(
                Vendor.id == vendor_id,
                Vendor.org_id == document.org_id,
                Vendor.deleted_at.is_(None),
            )
        )
        if vendor is None:
            raise BadRequestError(
                "Vendor not found in this organization.", code="vendor_not_found"
            )
    if vendor is None:
        vendor = _resolve_vendor_from_fields(db, org_id=document.org_id, fields=fields)

    po = None
    if purchase_order_id:
        po = db.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.id == purchase_order_id,
                PurchaseOrder.org_id == document.org_id,
                PurchaseOrder.deleted_at.is_(None),
            )
        )
        if po is None:
            raise BadRequestError(
                "Purchase order not found in this organization.", code="purchase_order_not_found"
            )
    if po is None and fields.get("purchase_order_number"):
        target = fields["purchase_order_number"].strip().upper()
        for candidate in db.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.org_id == document.org_id, PurchaseOrder.deleted_at.is_(None)
            )
        ):
            if candidate.po_number.strip().upper() == target:
                po = candidate
                break

    payload = InvoiceCreate(
        invoice_number=invoice_number,
        vendor_id=vendor.id if vendor else None,
        purchase_order_id=po.id if po else None,
        document_id=document.id,
        invoice_date=invoice_date,
        due_date=due_date,
        currency=currency,
        subtotal=subtotal,
        tax=tax,
        total=total,
        source="DOCUMENT",
        vendor_name_raw=fields.get("vendor_name"),
        notes=f"Created from extraction {extraction.id}",
    )
    invoice = create_invoice(
        db,
        org_id=document.org_id,
        actor_id=actor_id,
        payload=payload,
        status=InvoiceStatus.RECEIVED,
        is_demo=document.is_demo,
    )
    invoice.extraction_id = extraction.id
    if vendor is not None and document.vendor_id is None:
        document.vendor_id = vendor.id
    validate_invoice(db, invoice=invoice, actor_id=actor_id)
    detect_for_invoice(db, org_id=document.org_id, invoice=invoice, actor_id=actor_id)
    record_audit(
        db,
        org_id=document.org_id,
        action="invoice.created_from_document",
        entity_type="invoice",
        entity_id=invoice.id,
        summary=f"Invoice {invoice.invoice_number} created from document {document.original_filename}",
        actor_id=actor_id,
    )
    return invoice
