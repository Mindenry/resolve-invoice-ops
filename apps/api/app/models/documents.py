"""Document storage, versioning, extraction and knowledge chunk models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import (
    DocumentStatus,
    DocumentType,
    ExtractionMethod,
    ExtractionRunStatus,
    ReviewStatus,
    enum_type,
)


class Document(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, OrgScopedMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("org_id", "sha256", name="uq_documents_org_sha256"),
        Index("ix_documents_org_status", "org_id", "status"),
        Index("ix_documents_org_type", "org_id", "document_type"),
    )

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(20), default="local", nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(
        enum_type(DocumentType, "document_type"), default=DocumentType.OTHER, nullable=False
    )
    status: Mapped[DocumentStatus] = mapped_column(
        enum_type(DocumentStatus, "document_status"), default=DocumentStatus.UPLOADED, nullable=False
    )
    processing_error: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    version_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_document_version"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentPage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_document_page_number"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_text_layer: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)


class DocumentExtraction(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "document_extractions"
    __table_args__ = (Index("ix_extractions_org_document", "org_id", "document_id"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[ExtractionRunStatus] = mapped_column(
        enum_type(ExtractionRunStatus, "extraction_run_status"),
        default=ExtractionRunStatus.QUEUED,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(40), default="deterministic", nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    raw_output: Mapped[dict[str, Any] | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    field_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_confidence: Mapped[float | None] = mapped_column(Float)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, "review_status"), default=ReviewStatus.PENDING, nullable=False
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float | None] = mapped_column(Float)


class ExtractedField(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "document_fields"
    __table_args__ = (Index("ix_fields_extraction_name", "extraction_id", "field_name"),)

    extraction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    value: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    source_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    method: Mapped[ExtractionMethod] = mapped_column(
        enum_type(ExtractionMethod, "extraction_method"), default=ExtractionMethod.RULE, nullable=False
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, "field_review_status"), default=ReviewStatus.PENDING, nullable=False
    )
    corrected_value: Mapped[str | None] = mapped_column(Text)
    corrected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bounding_box: Mapped[dict[str, Any] | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def effective_value(self) -> str | None:
        return self.corrected_value if self.corrected_value is not None else self.value


class DocumentChunk(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
        Index("ix_chunks_org_document", "org_id", "document_id"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column()
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    embedding_dim: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
