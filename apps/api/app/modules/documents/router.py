"""Document management, extraction review and retrieval endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.core.errors import UnprocessableError
from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.domain.enums import DocumentStatus, DocumentType
from app.models.documents import DocumentChunk
from app.modules.documents import service
from app.modules.documents.processing import system_capabilities
from app.modules.documents.schemas import (
    CreateInvoiceFromDocumentRequest,
    DocumentDetail,
    DocumentOut,
    DocumentSearchResponse,
    ExtractionOut,
    ExtractionReviewRequest,
    FieldCorrection,
    FieldOut,
    ReprocessRequest,
    UploadResponse,
)
from app.schemas.common import APIMessage

router = APIRouter(prefix="/documents", tags=["Documents"])

DocReader = Annotated[Principal, Depends(require_permission("document:read"))]
DocUploader = Annotated[Principal, Depends(require_permission("document:upload"))]
DocReviewer = Annotated[Principal, Depends(require_permission("document:review"))]


@router.get("", response_model=Page[DocumentOut], summary="List documents")
def list_documents(
    principal: DocReader,
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    search: str | None = Query(None, max_length=160),
    status: list[DocumentStatus] | None = Query(None),
    document_type: DocumentType | None = Query(None),
    vendor_id: uuid.UUID | None = Query(None),
    requires_review: bool | None = Query(None),
) -> Page[DocumentOut]:
    items, total = service.list_documents(
        db,
        org_id=principal.org_id,
        pagination=pagination,
        search=search,
        status=status,
        document_type=document_type,
        vendor_id=vendor_id,
        requires_review=requires_review,
    )
    return Page.build(items, total, pagination)


@router.post("", response_model=UploadResponse, status_code=201, summary="Upload a document")
async def upload_document(
    principal: DocUploader,
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File(description="PDF, DOCX, XLSX, CSV, TXT, PNG or JPEG")],
    document_type: Annotated[DocumentType, Form()] = DocumentType.INVOICE,
    vendor_id: Annotated[uuid.UUID | None, Form()] = None,
) -> UploadResponse:
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UnprocessableError("File exceeds the upload limit.", code="file_too_large")
    document, _ = service.upload_document(
        db,
        org_id=principal.org_id,
        actor_id=principal.user_id,
        filename=file.filename or "document",
        content_type=file.content_type,
        data=data,
        document_type=document_type,
        vendor_id=vendor_id,
    )
    db.commit()
    return UploadResponse(document=service._doc_out(db, document))


@router.get("/capabilities", summary="Document processing capabilities")
def capabilities(principal: DocReader) -> dict[str, object]:
    return {
        **system_capabilities(),
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "supported_types": [".pdf", ".docx", ".xlsx", ".csv", ".txt", ".png", ".jpg", ".jpeg"],
    }


@router.get("/{document_id}", response_model=DocumentDetail, summary="Document detail with extraction")
def get_document(
    document_id: uuid.UUID, principal: DocReader, db: Annotated[Session, Depends(get_db)]
) -> DocumentDetail:
    document = service.get_document(db, org_id=principal.org_id, document_id=document_id)
    return service.detail(db, document)


@router.get("/{document_id}/download", summary="Download a document")
def download_document(
    document_id: uuid.UUID, principal: DocReader, db: Annotated[Session, Depends(get_db)]
) -> Response:
    from app.services.audit import record_download

    document = service.get_document(db, org_id=principal.org_id, document_id=document_id)
    data = service.get_storage().read(document.storage_key)
    record_download(db, principal=principal, document=document)
    db.commit()
    return Response(
        content=data,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.original_filename}"',
            "Content-Length": str(len(data)),
        },
    )


@router.get("/{document_id}/extraction", response_model=ExtractionOut, summary="Latest extraction")
def get_extraction(
    document_id: uuid.UUID, principal: DocReader, db: Annotated[Session, Depends(get_db)]
) -> ExtractionOut:
    document = service.get_document(db, org_id=principal.org_id, document_id=document_id)
    extraction = service.latest_extraction(db, document.id)
    if extraction is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("No extraction exists for this document.", code="no_extraction")
    return service._extraction_out(db, extraction)


@router.patch("/{document_id}/fields/{field_id}", response_model=FieldOut, summary="Correct an extracted field")
def correct_field(
    document_id: uuid.UUID,
    field_id: uuid.UUID,
    payload: FieldCorrection,
    principal: DocReviewer,
    db: Annotated[Session, Depends(get_db)],
) -> FieldOut:
    document = service.get_document(db, org_id=principal.org_id, document_id=document_id)
    field = service.correct_field(
        db,
        document=document,
        field_id=field_id,
        value=payload.value,
        notes=payload.notes,
        actor_id=principal.user_id,
    )
    db.commit()
    return service._field_out(field)


@router.post("/{document_id}/review", response_model=ExtractionOut, summary="Approve or reject an extraction")
def review_extraction(
    document_id: uuid.UUID,
    payload: ExtractionReviewRequest,
    principal: DocReviewer,
    db: Annotated[Session, Depends(get_db)],
) -> ExtractionOut:
    document = service.get_document(db, org_id=principal.org_id, document_id=document_id)
    extraction = service.review_extraction(
        db,
        document=document,
        action=payload.action.value,
        note=payload.note,
        approve_low_confidence_fields=payload.approve_low_confidence_fields,
        actor_id=principal.user_id,
    )
    db.commit()
    return service._extraction_out(db, extraction)


@router.post("/{document_id}/reprocess", response_model=APIMessage, summary="Reprocess a document")
def reprocess_document(
    document_id: uuid.UUID,
    payload: ReprocessRequest,
    principal: DocReviewer,
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    document = service.get_document(db, org_id=principal.org_id, document_id=document_id)
    service.reprocess_document(db, document=document, actor_id=principal.user_id, reason=payload.reason)
    db.commit()
    return APIMessage(message="Document queued for reprocessing.")


@router.post("/{document_id}/create-invoice", summary="Create an invoice from the reviewed extraction")
def create_invoice(
    document_id: uuid.UUID,
    payload: CreateInvoiceFromDocumentRequest,
    principal: DocReviewer,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    document = service.get_document(db, org_id=principal.org_id, document_id=document_id)
    invoice = service.create_invoice_from_document(
        db,
        document=document,
        actor_id=principal.user_id,
        vendor_id=payload.vendor_id,
        purchase_order_id=payload.purchase_order_id,
    )
    db.commit()
    return {"invoice_id": str(invoice.id), "invoice_number": invoice.invoice_number}


@router.get("/{document_id}/chunks", summary="Knowledge chunks for a document")
def list_chunks(
    document_id: uuid.UUID, principal: DocReader, db: Annotated[Session, Depends(get_db)]
) -> list[dict[str, object]]:
    document = service.get_document(db, org_id=principal.org_id, document_id=document_id)
    chunks = db.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
    ).all()
    return [
        {
            "id": str(chunk.id),
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "page": chunk.page_start,
            "embedded": chunk.embedding is not None,
            "embedding_model": chunk.embedding_model,
            "token_estimate": chunk.token_estimate,
        }
        for chunk in chunks
    ]


@router.post("/{document_id}/versions", status_code=201, summary="Upload a new document version")
async def upload_version(
    document_id: uuid.UUID,
    principal: DocUploader,
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    note: Annotated[str | None, Form()] = None,
) -> dict[str, object]:
    from app.modules.documents.schemas import DocumentVersionOut

    document = service.get_document(db, org_id=principal.org_id, document_id=document_id)
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UnprocessableError("File exceeds the upload limit.", code="file_too_large")
    version = service.add_version(
        db,
        document=document,
        actor_id=principal.user_id,
        filename=file.filename or document.original_filename,
        content_type=file.content_type,
        data=data,
        note=note,
    )
    db.commit()
    return DocumentVersionOut.model_validate(version).model_dump(mode="json")


@router.delete("/{document_id}", response_model=APIMessage, summary="Delete a document")
def delete_document(
    document_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_permission("document:delete"))],
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    from app.core.security import utcnow
    from app.services.audit import record_audit

    document = service.get_document(db, org_id=principal.org_id, document_id=document_id)
    document.deleted_at = utcnow()
    record_audit(
        db,
        org_id=principal.org_id,
        action="document.deleted",
        entity_type="document",
        entity_id=document.id,
        summary=f"Document {document.original_filename} deleted",
        actor=principal.user,
    )
    db.commit()
    return APIMessage(message="Document deleted.")


@router.get("/search/knowledge", response_model=DocumentSearchResponse, summary="Hybrid knowledge search")
def knowledge_search(
    principal: DocReader,
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(min_length=2, max_length=300),
    top_k: int = Query(6, ge=1, le=20),
    document_types: list[DocumentType] | None = Query(None),
) -> DocumentSearchResponse:
    from app.modules.knowledge.service import hybrid_search

    return hybrid_search(
        db,
        org_id=principal.org_id,
        query=q,
        top_k=top_k,
        document_types=document_types,
    )
