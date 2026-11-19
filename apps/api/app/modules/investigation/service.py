"""AI investigation pipeline with evidence grounding and deterministic validation."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.base import ChatMessage
from app.ai.client import (
    calculate_cost,
    record_usage,
    run_coroutine_safely,
    structured_completion,
)
from app.ai.prompts import INVESTIGATION_INSTRUCTIONS, INVESTIGATION_PROMPT_VERSION, INVESTIGATION_SYSTEM
from app.ai.registry import build_llm_provider
from app.config.settings import settings
from app.core.errors import AIOutputError, AIUnavailableError, BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.core.security import utcnow
from app.domain.enums import (
    ActionType,
    EventType,
    InvestigationSourceType,
    InvestigationStatus,
    NotificationType,
)
from app.models.ai import Investigation, InvestigationEvidence
from app.models.cases import Case, CaseComment, CaseLink, ExceptionRecord
from app.models.documents import Document, DocumentChunk, DocumentExtraction, DocumentPage, ExtractedField
from app.models.finance import Invoice, PurchaseOrder, PurchaseOrderItem, Vendor
from app.modules.cases.service import log_activity
from app.modules.documents.schemas import DocumentSearchResponse
from app.modules.investigation.schemas import (
    EvidenceOut,
    InvestigationModelOutput,
    InvestigationOut,
)
from app.modules.knowledge.service import hybrid_search, similar_cases
from app.services.audit import record_audit
from app.services.events import emit_event
from app.services.notifications import notify

logger = get_logger(__name__)

MAX_CONTEXT_CHARS = 45_000


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _case_exceptions(db: Session, case: Case) -> list[ExceptionRecord]:
    return list(
        db.scalars(
            select(ExceptionRecord)
            .where(ExceptionRecord.case_id == case.id)
            .order_by(ExceptionRecord.severity.desc())
        )
    )


def _linked_ids(db: Session, case: Case, entity_type: str) -> list[uuid.UUID]:
    return [
        link.entity_id
        for link in db.scalars(
            select(CaseLink).where(
                CaseLink.case_id == case.id, CaseLink.entity_type == entity_type
            )
        )
    ]


def build_context(
    db: Session,
    *,
    org_id: uuid.UUID,
    case: Case,
    top_k: int = 6,
    include_similar_cases: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Load only organization-scoped records and build citation candidates."""
    exceptions = _case_exceptions(db, case)
    invoice_ids = set(_linked_ids(db, case, "INVOICE"))
    vendor_ids = set(_linked_ids(db, case, "VENDOR"))
    po_ids = set(_linked_ids(db, case, "PURCHASE_ORDER"))
    document_ids = set(_linked_ids(db, case, "DOCUMENT"))

    for record in exceptions:
        if record.entity_type == "INVOICE":
            invoice_ids.add(record.entity_id)
        elif record.entity_type == "VENDOR":
            vendor_ids.add(record.entity_id)

    invoices = list(
        db.scalars(
            select(Invoice).where(
                Invoice.id.in_(invoice_ids), Invoice.org_id == org_id, Invoice.deleted_at.is_(None)
            )
        )
    ) if invoice_ids else []
    for invoice in invoices:
        if invoice.vendor_id:
            vendor_ids.add(invoice.vendor_id)
        if invoice.purchase_order_id:
            po_ids.add(invoice.purchase_order_id)
        if invoice.document_id:
            document_ids.add(invoice.document_id)

    vendors = list(
        db.scalars(
            select(Vendor).where(
                Vendor.id.in_(vendor_ids), Vendor.org_id == org_id, Vendor.deleted_at.is_(None)
            )
        )
    ) if vendor_ids else []
    purchase_orders = list(
        db.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.id.in_(po_ids),
                PurchaseOrder.org_id == org_id,
                PurchaseOrder.deleted_at.is_(None),
            )
        )
    ) if po_ids else []

    contracts = db.scalars(
        select(Document).where(
            Document.org_id == org_id,
            Document.document_type.in_(["CONTRACT", "POLICY", "SOP"]),
            Document.deleted_at.is_(None),
            Document.status.in_(["INDEXED", "EXTRACTED"]),
        )
    ).all()
    contract_docs = list(contracts)[:40]

    evidence_candidates: list[dict[str, Any]] = []
    invoice_payloads: list[dict[str, Any]] = []
    for invoice in invoices:
        vendor = next((v for v in vendors if v.id == invoice.vendor_id), None)
        po = next((p for p in purchase_orders if p.id == invoice.purchase_order_id), None)
        invoice_payloads.append(
            {
                "id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
                "status": invoice.status.value,
                "validation_status": invoice.validation_status.value,
                "invoice_date": invoice.invoice_date.isoformat(),
                "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                "currency": invoice.currency,
                "subtotal": str(invoice.subtotal),
                "tax": str(invoice.tax),
                "total": str(invoice.total),
                "vendor_id": str(invoice.vendor_id) if invoice.vendor_id else None,
                "vendor_name": vendor.legal_name if vendor else invoice.vendor_name_raw,
                "purchase_order_id": str(invoice.purchase_order_id) if invoice.purchase_order_id else None,
                "purchase_order_number": po.po_number if po else None,
                "document_id": str(invoice.document_id) if invoice.document_id else None,
                "validation_notes": invoice.validation_notes or [],
            }
        )
        evidence_candidates.append(
            {
                "source_type": "INVOICE",
                "source_id": str(invoice.id),
                "document_id": str(invoice.document_id) if invoice.document_id else None,
                "page_number": None,
                "field_name": "total",
                "quote": f"Invoice {invoice.invoice_number} total {invoice.currency} {invoice.total}",
                "relationship": "Invoice under investigation",
            }
        )
        if invoice.document_id:
            extraction = db.scalar(
                select(DocumentExtraction)
                .where(DocumentExtraction.document_id == invoice.document_id)
                .order_by(DocumentExtraction.created_at.desc())
                .limit(1)
            )
            if extraction is not None:
                for field in db.scalars(
                    select(ExtractedField).where(ExtractedField.extraction_id == extraction.id)
                ).all():
                    quote = field.corrected_value or field.value or ""
                    if not quote:
                        continue
                    evidence_candidates.append(
                        {
                            "source_type": "DOCUMENT",
                            "source_id": str(invoice.document_id),
                            "document_id": str(invoice.document_id),
                            "page_number": field.page_number,
                            "field_name": field.field_name,
                            "quote": (field.source_text or quote)[:600],
                            "relationship": f"Extracted field '{field.field_name}' "
                            f"(method {field.method.value}, confidence {field.confidence:.2f})",
                        }
                    )

    po_payloads: list[dict[str, Any]] = []
    for po in purchase_orders:
        items = db.scalars(
            select(PurchaseOrderItem)
            .where(PurchaseOrderItem.purchase_order_id == po.id)
            .order_by(PurchaseOrderItem.line_number)
        ).all()
        vendor = next((v for v in vendors if v.id == po.vendor_id), None)
        po_payloads.append(
            {
                "id": str(po.id),
                "po_number": po.po_number,
                "status": po.status.value,
                "vendor_id": str(po.vendor_id),
                "vendor_name": vendor.legal_name if vendor else None,
                "currency": po.currency,
                "issue_date": po.issue_date.isoformat(),
                "expiration_date": po.expiration_date.isoformat() if po.expiration_date else None,
                "subtotal": str(po.subtotal),
                "tax": str(po.tax),
                "total": str(po.total),
                "items": [
                    {
                        "line": item.line_number,
                        "description": item.description,
                        "quantity": str(item.quantity),
                        "unit_price": str(item.unit_price),
                        "line_total": str(item.line_total),
                        "tax_rate": str(item.tax_rate),
                    }
                    for item in items
                ],
            }
        )
        evidence_candidates.append(
            {
                "source_type": "PURCHASE_ORDER",
                "source_id": str(po.id),
                "document_id": None,
                "page_number": None,
                "field_name": "total",
                "quote": f"Purchase order {po.po_number} total {po.currency} {po.total} "
                f"({po.status.value})",
                "relationship": "Purchase order linked to the case",
            }
        )

    vendor_payloads = [
        {
            "id": str(vendor.id),
            "vendor_number": vendor.vendor_number,
            "legal_name": vendor.legal_name,
            "tax_id": vendor.tax_id,
            "status": vendor.status.value,
            "currency": vendor.currency,
            "payment_terms_days": vendor.payment_terms_days,
            "risk_flags": vendor.risk_flags,
            "address": " ".join(
                filter(None, [vendor.address_line1, vendor.city, vendor.country])
            ),
        }
        for vendor in vendors
    ]
    for vendor in vendors:
        evidence_candidates.append(
            {
                "source_type": "VENDOR",
                "source_id": str(vendor.id),
                "document_id": None,
                "page_number": None,
                "field_name": "legal_name",
                "quote": f"Vendor {vendor.legal_name} (tax id {vendor.tax_id or 'not recorded'}, "
                f"status {vendor.status.value})",
                "relationship": "Vendor master record",
            }
        )

    exception_payloads = [
        {
            "id": str(record.id),
            "exception_type": record.exception_type.value,
            "severity": record.severity.value,
            "status": record.status.value,
            "rule_code": record.rule_code,
            "rule_version": record.rule_version,
            "title": record.title,
            "description": record.description,
            "evidence": record.evidence,
            "detection_count": record.detection_count,
        }
        for record in exceptions
    ]
    for record in exceptions:
        evidence_candidates.append(
            {
                "source_type": "EXCEPTION",
                "source_id": str(record.id),
                "document_id": None,
                "page_number": None,
                "field_name": None,
                "quote": f"{record.title}: {record.description}"[:600],
                "relationship": f"Detected by rule {record.rule_code} v{record.rule_version}",
            }
        )

    comments = db.scalars(
        select(CaseComment)
        .where(CaseComment.case_id == case.id, CaseComment.deleted_at.is_(None))
        .order_by(CaseComment.created_at.desc())
        .limit(10)
    ).all()
    for comment in comments:
        evidence_candidates.append(
            {
                "source_type": "NOTE",
                "source_id": str(comment.id),
                "document_id": None,
                "page_number": None,
                "field_name": None,
                "quote": comment.body[:600],
                "relationship": f"Case comment ({comment.visibility.value.lower()})",
            }
        )

    # Retrieval is organization scoped and limited to authorised document statuses.
    query = " ".join(
        [
            case.title,
            " ".join(record.exception_type.value.replace("_", " ") for record in exceptions),
            " ".join(v.legal_name for v in vendors),
            "contract payment terms",
        ]
    )[:400]
    retrieval: DocumentSearchResponse | None = None
    try:
        retrieval = hybrid_search(
            db,
            org_id=org_id,
            query=query,
            top_k=top_k,
            document_types=["CONTRACT", "POLICY", "SOP"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("investigation_retrieval_failed", error=str(exc))
    retrieved_chunks: list[dict[str, Any]] = []
    if retrieval is not None:
        for hit in retrieval.hits:
            retrieved_chunks.append(
                {
                    "chunk_id": str(hit.chunk_id),
                    "document_id": str(hit.document_id),
                    "document_title": hit.document_title,
                    "page": hit.page_start,
                    "content": hit.content[:1200],
                    "score": hit.score,
                }
            )
            evidence_candidates.append(
                {
                    "source_type": "CHUNK",
                    "source_id": str(hit.chunk_id),
                    "document_id": str(hit.document_id),
                    "page_number": hit.page_start,
                    "field_name": None,
                    "quote": hit.content[:600],
                    "relationship": f"Retrieved knowledge (score {hit.score:.2f})",
                }
            )

    history = similar_cases(
        db, org_id=org_id, title=case.title, description=case.description, limit=5
    ) if include_similar_cases else []
    for item in history:
        evidence_candidates.append(
            {
                "source_type": "HISTORY",
                "source_id": item["case_id"],
                "document_id": None,
                "page_number": None,
                "field_name": None,
                "quote": f"{item['case_number']}: {item['title']} — {item['resolution_summary']}"[:600],
                "relationship": f"Similar resolved case (score {item['score']})",
            }
        )

    context = {
        "task": "investigation",
        "case": {
            "case_number": case.case_number,
            "title": case.title,
            "description": case.description,
            "status": case.status.value,
            "priority": case.priority.value,
            "severity": case.severity.value,
            "tags": case.tags,
            "created_at": _iso(case.created_at),
            "due_at": _iso(case.due_at),
        },
        "exceptions": exception_payloads,
        "invoices": invoice_payloads,
        "purchase_orders": po_payloads,
        "vendors": vendor_payloads,
        "retrieved_knowledge": retrieved_chunks,
        "similar_cases": history,
        "allowed_actions": [action.value for action in ActionType],
    }

    allowed = {
        "exception_ids": {str(record.id) for record in exceptions},
        "invoice_ids": {str(invoice.id) for invoice in invoices},
        "po_ids": {str(po.id) for po in purchase_orders},
        "vendor_ids": {str(vendor.id) for vendor in vendors},
        "document_ids": {str(document.id) for document in contract_docs} | {str(d) for d in document_ids},
        "chunk_ids": {chunk["chunk_id"] for chunk in retrieved_chunks},
        "history_ids": {item["case_id"] for item in history},
        "note_ids": {str(comment.id) for comment in comments},
        "case_id": str(case.id),
        "retrieval_mode": retrieval.retrieval_mode if retrieval else "unavailable",
        "retrieval_notes": retrieval.notes if retrieval else ["Retrieval unavailable"],
    }
    summary = {
        "exceptions": len(exception_payloads),
        "invoices": len(invoices),
        "purchase_orders": len(purchase_orders),
        "vendors": len(vendors),
        "retrieved_chunks": len(retrieved_chunks),
        "similar_cases": len(history),
        "retrieval_mode": allowed["retrieval_mode"],
    }
    return context, evidence_candidates, {"allowed": allowed, "summary": summary}


def _validate_evidence(
    db: Session,
    *,
    org_id: uuid.UUID,
    allowed: dict[str, Any],
    item: Any,
) -> tuple[bool, str | None]:
    source_type = item.source_type
    source_id = item.source_id
    if source_type in {
        InvestigationSourceType.EXCEPTION,
        InvestigationSourceType.INVOICE,
        InvestigationSourceType.PURCHASE_ORDER,
        InvestigationSourceType.VENDOR,
        InvestigationSourceType.CHUNK,
        InvestigationSourceType.HISTORY,
        InvestigationSourceType.NOTE,
    } and not source_id:
        return False, "source_id is required for this evidence type"
    if source_type == InvestigationSourceType.INVOICE and source_id not in allowed["invoice_ids"]:
        return False, "Invoice is not part of this investigation context"
    if source_type == InvestigationSourceType.PURCHASE_ORDER and source_id not in allowed["po_ids"]:
        return False, "Purchase order is not part of this investigation context"
    if source_type == InvestigationSourceType.VENDOR and source_id not in allowed["vendor_ids"]:
        return False, "Vendor is not part of this investigation context"
    if source_type == InvestigationSourceType.EXCEPTION and source_id not in allowed["exception_ids"]:
        return False, "Exception is not linked to this case"
    if source_type == InvestigationSourceType.HISTORY and source_id not in allowed["history_ids"]:
        return False, "Historical case was not provided in the context"
    if source_type == InvestigationSourceType.NOTE and source_id not in allowed["note_ids"]:
        return False, "Note is not part of this case"
    if source_type in {InvestigationSourceType.DOCUMENT, InvestigationSourceType.CHUNK}:
        document_id = str(item.document_id) if item.document_id else None
        if not document_id:
            return False, "document_id is required for document evidence"
        if document_id not in allowed["document_ids"]:
            return False, "Document is not accessible in this organization or context"
        document = db.scalar(
            select(Document).where(
                Document.id == uuid.UUID(document_id),
                Document.org_id == org_id,
                Document.deleted_at.is_(None),
            )
        )
        if document is None:
            return False, "Document does not exist in this organization"
        if item.page_number is not None and document.page_count and item.page_number > document.page_count:
            return False, f"Page {item.page_number} exceeds the document's {document.page_count} pages"
        if source_type == InvestigationSourceType.CHUNK:
            try:
                chunk_id = uuid.UUID(source_id or "")
            except (ValueError, AttributeError, TypeError):
                return False, "Chunk id is not a valid UUID"
            chunk = db.scalar(
                select(DocumentChunk).where(
                    DocumentChunk.id == chunk_id,
                    DocumentChunk.org_id == org_id,
                    DocumentChunk.document_id == document.id,
                )
            )
            if chunk is None:
                return False, "Chunk does not exist in this organization"
            if " ".join(item.quote.split()).lower() not in " ".join(chunk.content.split()).lower():
                return False, "Quote is not present in the cited chunk"
        else:
            page_number = item.page_number or 1
            page = db.scalar(
                select(DocumentPage).where(
                    DocumentPage.document_id == document.id, DocumentPage.page_number == page_number
                )
            )
            if page is None:
                return False, "Cited page does not exist"
            if " ".join(item.quote.split()).lower() not in " ".join(page.text.split()).lower():
                extraction = db.scalar(
                    select(DocumentExtraction)
                    .where(DocumentExtraction.document_id == document.id)
                    .order_by(DocumentExtraction.created_at.desc())
                    .limit(1)
                )
                field_match = None
                if extraction is not None:
                    field_match = db.scalar(
                        select(ExtractedField).where(
                            ExtractedField.extraction_id == extraction.id,
                            ExtractedField.page_number == page_number,
                            ExtractedField.source_text.is_not(None),
                        )
                    )
                if field_match is None or " ".join(item.quote.split()).lower() not in " ".join(
                    (field_match.source_text or "").split()
                ).lower():
                    return False, "Quote was not found on the cited page"
    return True, None


def _evidence_rows(
    db: Session,
    *,
    org_id: uuid.UUID,
    investigation_id: uuid.UUID,
    items: list[Any],
    contradicting: bool,
    results: list[tuple[bool, str | None]],
) -> list[InvestigationEvidence]:
    rows: list[InvestigationEvidence] = []
    document_cache: dict[uuid.UUID, bool] = {}
    for index, item in enumerate(items):
        valid, error = results[index]
        document_id = item.document_id
        if document_id is not None and str(document_id) not in {
            str(doc_id) for doc_id in document_cache
        }:
            exists = db.scalar(
                select(Document.id).where(
                    Document.id == document_id,
                    Document.org_id == org_id,
                    Document.deleted_at.is_(None),
                )
            )
            document_cache[document_id] = exists is not None
        if document_id is not None and not document_cache.get(document_id, False):
            # Preserve the fabricated ID for transparency without violating the FK.
            if error:
                error = f"{error} (attempted document_id={document_id})"
            else:
                error = f"Document {document_id} is not accessible"
            document_id = None
        rows.append(
            InvestigationEvidence(
                investigation_id=investigation_id,
                source_type=item.source_type,
                source_id=item.source_id,
                document_id=document_id,
                page_number=item.page_number,
                field_name=item.field_name,
                quote=item.quote,
                relationship=item.relationship,
                is_contradicting=contradicting,
                is_validated=valid,
                validation_error=error,
            )
        )
    return rows


def _strict_investigation_schema() -> dict[str, Any]:
    """Provider-facing schema that forces the fields weaker local models omit.

    Pydantic defaults are convenient for validation, but they make the generated
    JSON schema omit ``required`` entries; Ollama then allows the model to drop
    evidence entirely. The model is still validated against the permissive
    Pydantic model, so unexpected omissions fail visibly later.
    """
    schema = InvestigationModelOutput.model_json_schema()
    properties = schema.setdefault("properties", {})
    schema["required"] = list(properties.keys())
    properties.setdefault("evidence", {})["minItems"] = 1
    properties.setdefault("suggested_resolutions", {})["minItems"] = 1
    definitions = schema.setdefault("$defs", {})
    evidence = definitions.setdefault("EvidenceItem", {})
    evidence["required"] = ["source_type", "source_id", "document_id", "quote"]
    evidence["properties"]["source_id"] = {"type": "string", "maxLength": 64}
    resolution = definitions.setdefault("SuggestedResolutionItem", {})
    resolution["required"] = ["action_type", "description", "risk_level"]
    return schema


def _build_prompt(context: dict[str, Any], allowed: dict[str, Any], evidence_candidates: list[dict[str, Any]]) -> list[ChatMessage]:
    allowed_actions = ", ".join(context.get("allowed_actions") or [])
    instructions = INVESTIGATION_INSTRUCTIONS.replace("{allowed_actions}", allowed_actions)
    payload = {
        **context,
        "evidence_candidates": evidence_candidates,
        "investigation_id_hints": {
            "source_ids": {
                "exceptions": sorted(allowed["exception_ids"]),
                "invoices": sorted(allowed["invoice_ids"]),
                "purchase_orders": sorted(allowed["po_ids"]),
                "vendors": sorted(allowed["vendor_ids"]),
                "documents": sorted(allowed["document_ids"]),
                "chunks": sorted(allowed["chunk_ids"]),
                "history": sorted(allowed["history_ids"]),
            }
        },
        "retrieval_notes": allowed["retrieval_notes"],
    }
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    if len(serialized) > MAX_CONTEXT_CHARS:
        serialized = serialized[:MAX_CONTEXT_CHARS] + "\n... context truncated ..."
    user = (
        f"{instructions}\n\n"
        "Evidence candidates below are the only sources you may cite. Use their exact ids, pages and quotes.\n"
        f"<context_json>\n{serialized}\n</context_json>"
    )
    return [
        ChatMessage(role="system", content=INVESTIGATION_SYSTEM),
        ChatMessage(role="user", content=user),
    ]


def execute_investigation(db: Session, investigation: Investigation) -> Investigation:
    case = db.get(Case, investigation.case_id)
    if case is None or case.org_id != investigation.org_id:
        investigation.status = InvestigationStatus.FAILED
        investigation.error = "Case not found"
        investigation.error_code = "case_not_found"
        investigation.completed_at = utcnow()
        return investigation

    provider = build_llm_provider()
    if provider is None:
        investigation.status = InvestigationStatus.FAILED
        investigation.error = (
            "No LLM provider is configured. Set AI_PROVIDER and the matching credentials to run investigations."
        )
        investigation.error_code = "ai_unavailable"
        investigation.completed_at = utcnow()
        investigation.requires_human_review = True
        record_audit(
            db,
            org_id=case.org_id,
            action="investigation.failed",
            entity_type="case",
            entity_id=case.id,
            summary="Investigation failed: AI provider unavailable",
            actor_id=investigation.created_by_id,
        )
        return investigation

    investigation.status = InvestigationStatus.RUNNING
    investigation.started_at = investigation.started_at or utcnow()
    investigation.provider = settings.AI_PROVIDER
    investigation.model = settings.AI_MODEL
    investigation.prompt_version = INVESTIGATION_PROMPT_VERSION
    db.flush()

    try:
        context, evidence_candidates, wrapper = build_context(
            db,
            org_id=case.org_id,
            case=case,
            top_k=settings.RETRIEVAL_TOP_K,
            include_similar_cases=True,
        )
        allowed = wrapper["allowed"]
        investigation.context_summary = wrapper["summary"]
        messages = _build_prompt(context, allowed, evidence_candidates)
    except Exception as exc:  # noqa: BLE001 - context failures must be visible, never silent
        logger.exception("investigation_context_failed", investigation_id=str(investigation.id))
        # A failed SQL statement aborts the PostgreSQL transaction; recover before
        # persisting the failure state, otherwise the job itself can never commit.
        investigation_id = investigation.id
        db.rollback()
        investigation = db.get(Investigation, investigation_id)
        if investigation is None:
            raise
        investigation.status = InvestigationStatus.FAILED
        investigation.error = f"Investigation context could not be assembled: {exc}"[:2000]
        investigation.error_code = "context_error"
        investigation.completed_at = utcnow()
        investigation.requires_human_review = True
        return investigation

    try:
        parsed, result, attempts = run_coroutine_safely(
            structured_completion(
                provider=provider,
                messages=messages,
                schema=InvestigationModelOutput,
                schema_json=_strict_investigation_schema(),
            )
        )
    except (AIUnavailableError, AIOutputError) as exc:
        investigation.status = InvestigationStatus.FAILED
        investigation.error = str(exc)[:2000]
        investigation.error_code = getattr(exc, "code", "ai_failure")
        investigation.completed_at = utcnow()
        investigation.requires_human_review = True
        record_usage(
            db,
            org_id=case.org_id,
            user_id=investigation.created_by_id,
            purpose="case_investigation",
            provider=settings.AI_PROVIDER,
            model=settings.AI_MODEL,
            prompt_version=INVESTIGATION_PROMPT_VERSION,
            status="FAILED",
            error=str(exc)[:400],
        )
        record_audit(
            db,
            org_id=case.org_id,
            action="investigation.failed",
            entity_type="case",
            entity_id=case.id,
            summary=f"Investigation failed: {exc}",
            actor_id=investigation.created_by_id,
        )
        return investigation
    except ValidationError as exc:
        investigation.status = InvestigationStatus.FAILED
        investigation.error = f"Provider output failed schema validation: {exc}"[:2000]
        investigation.error_code = "ai_invalid_output"
        investigation.completed_at = utcnow()
        return investigation

    if evidence_candidates and (not parsed.evidence or not parsed.suggested_resolutions):
        # Local and smaller models sometimes omit optional arrays. Ask once more with a
        # strict schema; keep the original answer if the repair also fails, so the
        # investigation fails visibly rather than inventing evidence.
        repair_messages = [
            *messages,
            ChatMessage(role="assistant", content=result.content[:6000]),
            ChatMessage(
                role="user",
                content=(
                    "Your response omitted mandatory grounding. Rewrite the complete JSON object. "
                    "Include at least two evidence items copied exactly from evidence_candidates "
                    "(source_type, source_id, quote) and at least one allowed suggested resolution. "
                    "Do not invent ids or quotes."
                ),
            ),
        ]
        try:
            repaired, repaired_result, repair_attempts = run_coroutine_safely(
                structured_completion(
                    provider=provider,
                    messages=repair_messages,
                    schema=InvestigationModelOutput,
                    schema_json=_strict_investigation_schema(),
                    max_attempts=2,
                )
            )
            parsed = repaired
            result = repaired_result
            attempts += repair_attempts
        except (AIUnavailableError, AIOutputError, ValidationError) as exc:
            logger.warning(
                "investigation_evidence_repair_failed",
                investigation_id=str(investigation.id),
                error=str(exc)[:300],
            )

    if evidence_candidates and not parsed.evidence:
        parsed.requires_human_review = True
        if len(parsed.limitations) < 10:
            parsed.limitations = [
                *parsed.limitations,
                "The AI provider did not cite verifiable evidence; findings require manual verification.",
            ]

    evidence_results = [
        _validate_evidence(db, org_id=case.org_id, allowed=allowed, item=item)
        for item in parsed.evidence
    ]
    contradicting_results = [
        _validate_evidence(db, org_id=case.org_id, allowed=allowed, item=item)
        for item in parsed.contradicting_evidence
    ]
    valid_evidence = sum(1 for valid, _ in evidence_results if valid)
    invalid_evidence = len(evidence_results) - valid_evidence
    limitations = list(parsed.limitations)
    if invalid_evidence:
        limitations.append(
            f"{invalid_evidence} cited evidence item(s) failed validation and must not be trusted."
        )
    root_cause = parsed.root_cause
    if root_cause and valid_evidence == 0 and parsed.evidence:
        root_cause = None
        limitations.append(
            "The proposed root cause was withheld because none of its evidence references validated."
        )

    investigation.status = InvestigationStatus.COMPLETED
    investigation.summary = parsed.summary
    investigation.root_cause = root_cause
    investigation.root_cause_hypotheses = [item.model_dump(mode="json") for item in parsed.root_cause_hypotheses]
    investigation.raw_output = {
        "exception_types": [item.value for item in parsed.exception_types],
        "model_output": parsed.model_dump(mode="json"),
        "attempts": attempts,
        "evidence_candidates": len(evidence_candidates),
    }
    investigation.risk_level = parsed.risk_assessment.level
    investigation.confidence = parsed.confidence
    investigation.confidence_basis = parsed.confidence_basis
    investigation.requires_human_review = parsed.requires_human_review or invalid_evidence > 0 or valid_evidence == 0
    investigation.missing_information = parsed.missing_information
    investigation.limitations = limitations
    investigation.required_actions = parsed.required_actions
    investigation.suggested_resolutions = [item.model_dump(mode="json") for item in parsed.suggested_resolutions]
    investigation.input_tokens = result.input_tokens
    investigation.output_tokens = result.output_tokens
    investigation.cost_usd = calculate_cost(result.input_tokens, result.output_tokens)
    investigation.latency_ms = result.latency_ms
    investigation.completed_at = utcnow()
    investigation.error = None
    investigation.error_code = None
    db.flush()

    for row in _evidence_rows(
        db,
        org_id=case.org_id,
        investigation_id=investigation.id,
        items=parsed.evidence,
        contradicting=False,
        results=evidence_results,
    ):
        db.add(row)
    for row in _evidence_rows(
        db,
        org_id=case.org_id,
        investigation_id=investigation.id,
        items=parsed.contradicting_evidence,
        contradicting=True,
        results=contradicting_results,
    ):
        db.add(row)
    db.flush()

    record_usage(
        db,
        org_id=case.org_id,
        user_id=investigation.created_by_id,
        purpose="case_investigation",
        provider=result.provider,
        model=result.model,
        prompt_version=INVESTIGATION_PROMPT_VERSION,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_ms=result.latency_ms,
    )
    record_audit(
        db,
        org_id=case.org_id,
        action="investigation.completed",
        entity_type="case",
        entity_id=case.id,
        summary=f"AI investigation completed ({result.provider}/{result.model})",
        actor_id=investigation.created_by_id,
        after={
            "confidence": parsed.confidence,
            "risk": parsed.risk_assessment.level.value,
            "valid_evidence": valid_evidence,
            "invalid_evidence": invalid_evidence,
            "tokens": result.input_tokens + result.output_tokens,
        },
    )
    log_activity(
        db,
        case=case,
        actor_id=investigation.created_by_id,
        activity_type="AI_INVESTIGATION_COMPLETED",
        summary=f"AI investigation completed with {valid_evidence} validated evidence item(s)",
        payload={"investigation_id": str(investigation.id), "confidence": parsed.confidence},
    )
    emit_event(
        db,
        org_id=case.org_id,
        event_type=EventType.INVESTIGATION_COMPLETED,
        entity_type="CASE",
        entity_id=case.id,
        payload={"investigation_id": str(investigation.id), "risk": parsed.risk_assessment.level.value},
    )
    if case.assigned_user_id:
        notify(
            db,
            org_id=case.org_id,
            user_id=case.assigned_user_id,
            type=NotificationType.CASE_CREATED,
            title=f"AI investigation ready for {case.case_number}",
            body=(parsed.summary or "")[:400],
            entity_type="CASE",
            entity_id=case.id,
        )
    return investigation


def run_investigation_job(investigation_id: uuid.UUID, org_id: uuid.UUID) -> dict[str, Any]:
    from app.db.session import session_scope

    with session_scope() as db:
        investigation = db.get(Investigation, investigation_id)
        if investigation is None or investigation.org_id != org_id:
            return {"status": "skipped", "reason": "investigation_not_found"}
        if investigation.status == InvestigationStatus.COMPLETED:
            return {"status": "skipped", "reason": "already_completed"}
        result = execute_investigation(db, investigation)
        return {"status": result.status.value, "investigation_id": str(result.id), "error": result.error}


def create_investigation(
    db: Session,
    *,
    case: Case,
    actor_id: uuid.UUID | None,
) -> Investigation:
    existing = db.scalar(
        select(Investigation)
        .where(
            Investigation.case_id == case.id,
            Investigation.status.in_([InvestigationStatus.QUEUED, InvestigationStatus.RUNNING]),
        )
        .limit(1)
    )
    if existing is not None:
        raise BadRequestError(
            "An investigation is already running for this case.", code="investigation_in_progress"
        )
    investigation = Investigation(
        org_id=case.org_id,
        case_id=case.id,
        status=InvestigationStatus.QUEUED,
        provider=settings.AI_PROVIDER,
        model=settings.AI_MODEL,
        prompt_version=INVESTIGATION_PROMPT_VERSION,
        created_by_id=actor_id,
    )
    db.add(investigation)
    db.flush()
    from app.services.deferred import queue_task_after_commit

    if build_llm_provider() is None:
        investigation.status = InvestigationStatus.FAILED
        investigation.error = "No AI provider is configured."
        investigation.error_code = "ai_unavailable"
        investigation.completed_at = utcnow()
        investigation.requires_human_review = True
    else:
        queue_task_after_commit(
            db, "run_investigation", {"investigation_id": str(investigation.id)}, case.org_id
        )
    record_audit(
        db,
        org_id=case.org_id,
        action="investigation.requested",
        entity_type="case",
        entity_id=case.id,
        summary=f"AI investigation requested for {case.case_number}",
        actor_id=actor_id,
    )
    return investigation


def _evidence_out(row: InvestigationEvidence) -> EvidenceOut:
    return EvidenceOut(
        id=row.id,
        source_type=row.source_type,
        source_id=row.source_id,
        document_id=row.document_id,
        page_number=row.page_number,
        field_name=row.field_name,
        quote=row.quote,
        relationship=row.relationship,
        is_contradicting=row.is_contradicting,
        is_validated=row.is_validated,
        validation_error=row.validation_error,
    )


def investigation_out(db: Session, investigation: Investigation) -> InvestigationOut:
    evidence = db.scalars(
        select(InvestigationEvidence).where(
            InvestigationEvidence.investigation_id == investigation.id
        )
    ).all()
    return InvestigationOut(
        id=investigation.id,
        case_id=investigation.case_id,
        status=investigation.status,
        provider=investigation.provider,
        model=investigation.model,
        prompt_version=investigation.prompt_version,
        summary=investigation.summary,
        root_cause=investigation.root_cause,
        root_cause_hypotheses=investigation.root_cause_hypotheses or [],
        risk_level=investigation.risk_level,
        confidence=investigation.confidence,
        confidence_basis=investigation.confidence_basis,
        requires_human_review=investigation.requires_human_review,
        missing_information=investigation.missing_information or [],
        limitations=investigation.limitations or [],
        required_actions=investigation.required_actions or [],
        suggested_resolutions=investigation.suggested_resolutions or [],
        input_tokens=investigation.input_tokens,
        output_tokens=investigation.output_tokens,
        cost_usd=float(investigation.cost_usd) if investigation.cost_usd is not None else None,
        latency_ms=investigation.latency_ms,
        error=investigation.error,
        error_code=investigation.error_code,
        created_at=investigation.created_at,
        completed_at=investigation.completed_at,
        evidence_count=len(evidence),
        invalid_evidence_count=sum(1 for item in evidence if not item.is_validated),
        evidence=[_evidence_out(item) for item in evidence],
    )


def get_investigation(db: Session, *, org_id: uuid.UUID, investigation_id: uuid.UUID) -> Investigation:
    investigation = db.scalar(
        select(Investigation).where(
            Investigation.id == investigation_id, Investigation.org_id == org_id
        )
    )
    if investigation is None:
        raise NotFoundError("Investigation not found.", code="investigation_not_found")
    return investigation


def list_for_case(db: Session, *, case: Case) -> list[Investigation]:
    return list(
        db.scalars(
            select(Investigation)
            .where(Investigation.case_id == case.id)
            .order_by(Investigation.created_at.desc())
            .limit(20)
        )
    )


def accept_suggestion(
    db: Session,
    *,
    investigation: Investigation,
    suggestion_index: int,
    actor_id: uuid.UUID,
    case_id: uuid.UUID | None,
) -> Any:
    from app.modules.resolutions.service import create_resolution

    suggestions = investigation.suggested_resolutions or []
    if suggestion_index >= len(suggestions):
        raise BadRequestError("Suggestion index is out of range.", code="invalid_suggestion")
    suggestion = suggestions[suggestion_index]
    case = db.get(Case, case_id or investigation.case_id)
    if case is None or case.org_id != investigation.org_id:
        raise NotFoundError("Case not found.", code="case_not_found")
    evidence = [
        {
            "source_type": row.source_type.value,
            "source_id": row.source_id,
            "document_id": str(row.document_id) if row.document_id else None,
            "page_number": row.page_number,
            "quote": row.quote,
        }
        for row in db.scalars(
            select(InvestigationEvidence).where(
                InvestigationEvidence.investigation_id == investigation.id,
                InvestigationEvidence.is_validated.is_(True),
                InvestigationEvidence.is_contradicting.is_(False),
            )
        ).all()
    ]
    parameters: dict[str, Any] = {"case_id": str(case.id)}
    invoices = db.scalars(
        select(Invoice).where(
            Invoice.id.in_(
                select(ExceptionRecord.entity_id).where(
                    ExceptionRecord.case_id == case.id, ExceptionRecord.entity_type == "INVOICE"
                )
            )
        )
    ).all()
    if invoices:
        parameters["invoice_id"] = str(invoices[0].id)
        if invoices[0].vendor_id:
            parameters["vendor_id"] = str(invoices[0].vendor_id)
    if investigation.missing_information:
        parameters["requested_items"] = investigation.missing_information[:10]
    return create_resolution(
        db,
        case=case,
        actor_id=actor_id,
        action_type=suggestion.get("action_type"),
        description=suggestion.get("description", ""),
        parameters=parameters,
        evidence=evidence,
        risk_level=suggestion.get("risk_level", "MEDIUM"),
        ai_model=investigation.model,
        prompt_version=investigation.prompt_version,
        investigation_id=investigation.id,
    )

