"""Document and extraction schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from app.domain.enums import (
    DocumentStatus,
    DocumentType,
    ExtractionMethod,
    ExtractionRunStatus,
    ReviewStatus,
)
from app.schemas.common import ORMModel


class DocumentOut(ORMModel):
    id: uuid.UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    document_type: DocumentType
    status: DocumentStatus
    page_count: int
    char_count: int
    ocr_confidence: float | None = None
    requires_review: bool
    current_version: int
    vendor_id: uuid.UUID | None = None
    processing_error: str | None = None
    is_demo: bool
    created_at: datetime
    processed_at: datetime | None = None
    indexed_at: datetime | None = None
    has_extraction: bool = False
    chunk_count: int = 0


class PageOut(ORMModel):
    page_number: int
    text: str
    char_count: int
    has_text_layer: bool
    ocr_confidence: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class DocumentVersionOut(ORMModel):
    id: uuid.UUID
    version: int
    sha256: str
    size_bytes: int
    note: str | None = None
    created_at: datetime


class FieldOut(ORMModel):
    id: uuid.UUID
    field_name: str
    value: str | None = None
    effective_value: str | None = None
    normalized_value: str | None = None
    page_number: int | None = None
    source_text: str | None = None
    confidence: float
    method: ExtractionMethod
    review_status: ReviewStatus
    corrected_value: str | None = None
    bounding_box: dict[str, Any] | None = None
    notes: str | None = None


class ExtractionOut(ORMModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_version: int
    status: ExtractionRunStatus
    provider: str
    model: str | None = None
    prompt_version: str | None = None
    field_count: int
    avg_confidence: float | None = None
    requires_review: bool
    review_status: ReviewStatus
    review_note: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    fields: list[FieldOut] = Field(default_factory=list)


class DocumentDetail(DocumentOut):
    metadata: dict[str, Any] = Field(default_factory=dict)
    pages: list[PageOut] = Field(default_factory=list)
    versions: list[DocumentVersionOut] = Field(default_factory=list)
    extraction: ExtractionOut | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


class UploadResponse(ORMModel):
    document: DocumentOut
    job_id: uuid.UUID | None = None
    duplicate: bool = False


class FieldCorrection(ORMModel):
    value: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)


class ReviewAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ExtractionReviewRequest(ORMModel):
    action: ReviewAction
    note: str | None = Field(default=None, max_length=2000)
    approve_low_confidence_fields: bool = False


class ReprocessRequest(ORMModel):
    reason: str | None = Field(default=None, max_length=500)


class CreateInvoiceFromDocumentRequest(ORMModel):
    vendor_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    merge_with_existing: bool = False


class DocumentSearchHit(ORMModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    document_type: DocumentType
    page_start: int | None = None
    content: str
    score: float
    keyword_score: float = 0.0
    vector_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentSearchResponse(ORMModel):
    query: str
    hits: list[DocumentSearchHit]
    retrieval_mode: str
    notes: list[str] = Field(default_factory=list)
