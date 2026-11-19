"""Canonical domain enumerations shared by ORM models, schemas and services."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class BaseStrEnum(StrEnum):
    """StrEnum with a stable lowercase-ish value used directly in the database."""

    @classmethod
    def values(cls) -> list[str]:
        return [member.value for member in cls]


def enum_type(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Portable enum column: VARCHAR + CHECK constraint, stores enum values."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=48,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


class RoleCode(BaseStrEnum):
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    OPERATIONS_MANAGER = "ops_manager"
    INVESTIGATOR = "investigator"
    APPROVER = "approver"
    VIEWER = "viewer"


class Locale(BaseStrEnum):
    EN = "en"
    TH = "th"


class DocumentStatus(BaseStrEnum):
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    EXTRACTED = "EXTRACTED"
    VALIDATING = "VALIDATING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


class DocumentType(BaseStrEnum):
    INVOICE = "INVOICE"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    CONTRACT = "CONTRACT"
    POLICY = "POLICY"
    SOP = "SOP"
    CASE_ATTACHMENT = "CASE_ATTACHMENT"
    OTHER = "OTHER"


class ExtractionRunStatus(BaseStrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


class ExtractionMethod(BaseStrEnum):
    TEXT = "TEXT"
    OCR = "OCR"
    RULE = "RULE"
    LLM = "LLM"
    MANUAL = "MANUAL"
    DERIVED = "DERIVED"


class ReviewStatus(BaseStrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CORRECTED = "CORRECTED"


class VendorStatus(BaseStrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"


class PurchaseOrderStatus(BaseStrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class InvoiceStatus(BaseStrEnum):
    DRAFT = "DRAFT"
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    VALIDATED = "VALIDATED"
    MATCHED = "MATCHED"
    APPROVED = "APPROVED"
    READY_FOR_EXPORT = "READY_FOR_EXPORT"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ValidationStatus(BaseStrEnum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"


class ExceptionType(BaseStrEnum):
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    VENDOR_MISMATCH = "VENDOR_MISMATCH"
    MISSING_PURCHASE_ORDER = "MISSING_PURCHASE_ORDER"
    MISSING_DOCUMENTS = "MISSING_DOCUMENTS"
    TAX_DISCREPANCY = "TAX_DISCREPANCY"
    INVALID_INVOICE_DATE = "INVALID_INVOICE_DATE"
    DUPLICATE_VENDOR = "DUPLICATE_VENDOR"
    EXTRACTION_ANOMALY = "EXTRACTION_ANOMALY"
    INTEGRATION_FAILURE = "INTEGRATION_FAILURE"


class ExceptionStatus(BaseStrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    LINKED = "LINKED"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class Severity(BaseStrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Priority(BaseStrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class CaseStatus(BaseStrEnum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    AWAITING_INFORMATION = "AWAITING_INFORMATION"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RESOLUTION_IN_PROGRESS = "RESOLUTION_IN_PROGRESS"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CommentVisibility(BaseStrEnum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class InvestigationStatus(BaseStrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RiskLevel(BaseStrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ResolutionStatus(BaseStrEnum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ActionType(BaseStrEnum):
    REQUEST_VENDOR_CONFIRMATION = "REQUEST_VENDOR_CONFIRMATION"
    REQUEST_MISSING_DOCUMENTS = "REQUEST_MISSING_DOCUMENTS"
    CREATE_APPROVAL_REQUEST = "CREATE_APPROVAL_REQUEST"
    UPDATE_CASE_PRIORITY = "UPDATE_CASE_PRIORITY"
    ASSIGN_CASE = "ASSIGN_CASE"
    RETRY_INTEGRATION = "RETRY_INTEGRATION"
    RETRY_BACKGROUND_JOB = "RETRY_BACKGROUND_JOB"
    CREATE_EMAIL_DRAFT = "CREATE_EMAIL_DRAFT"
    NOTIFY_TEAM = "NOTIFY_TEAM"
    MARK_DUPLICATE = "MARK_DUPLICATE"
    ESCALATE_CASE = "ESCALATE_CASE"


class ApprovalStatus(BaseStrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class IntegrationKind(BaseStrEnum):
    REST = "REST"
    WEBHOOK = "WEBHOOK"
    CSV = "CSV"
    EXCEL = "EXCEL"
    N8N = "N8N"
    MINIO = "MINIO"
    EMAIL = "EMAIL"


class IntegrationStatus(BaseStrEnum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    UNTESTED = "UNTESTED"
    DISABLED = "DISABLED"


class WorkflowStatus(BaseStrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"


class Direction(BaseStrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class WebhookStatus(BaseStrEnum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    SENT = "SENT"
    RETRYING = "RETRYING"


class NotificationChannel(BaseStrEnum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    WEBHOOK = "WEBHOOK"


class NotificationStatus(BaseStrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    READ = "READ"


class NotificationType(BaseStrEnum):
    CASE_CREATED = "CASE_CREATED"
    CASE_ASSIGNED = "CASE_ASSIGNED"
    CASE_ESCALATED = "CASE_ESCALATED"
    CASE_RESOLVED = "CASE_RESOLVED"
    HIGH_PRIORITY_CASE = "HIGH_PRIORITY_CASE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_COMPLETED = "APPROVAL_COMPLETED"
    INTEGRATION_FAILED = "INTEGRATION_FAILED"
    DOCUMENT_PROCESSED = "DOCUMENT_PROCESSED"


class JobStatus(BaseStrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EntityType(BaseStrEnum):
    INVOICE = "INVOICE"
    VENDOR = "VENDOR"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    DOCUMENT = "DOCUMENT"
    CASE = "CASE"
    INTEGRATION = "INTEGRATION"
    ORGANIZATION = "ORGANIZATION"


class InvestigationSourceType(BaseStrEnum):
    INVOICE = "INVOICE"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    VENDOR = "VENDOR"
    DOCUMENT = "DOCUMENT"
    EXCEPTION = "EXCEPTION"
    CASE = "CASE"
    CHUNK = "CHUNK"
    HISTORY = "HISTORY"
    RULE = "RULE"
    NOTE = "NOTE"


class EmailBackend(BaseStrEnum):
    SINK = "sink"
    SMTP = "smtp"


class EventType(BaseStrEnum):
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_PROCESSED = "document.processed"
    DOCUMENT_FAILED = "document.failed"
    EXCEPTION_DETECTED = "exception.detected"
    CASE_CREATED = "case.created"
    CASE_ASSIGNED = "case.assigned"
    CASE_PRIORITY_CHANGED = "case.priority_changed"
    CASE_ESCALATED = "case.escalated"
    CASE_RESOLVED = "case.resolved"
    INVESTIGATION_COMPLETED = "investigation.completed"
    RESOLUTION_PROPOSED = "resolution.proposed"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"
    RESOLUTION_EXECUTED = "resolution.executed"
    INTEGRATION_FAILED = "integration.failed"
    CASE_COMMENTED = "case.commented"
    INVOICE_VALIDATED = "invoice.validated"
    VENDOR_MERGED = "vendor.merged"
