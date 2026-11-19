"""Exception detection orchestration, deduplication and case grouping."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.core.pagination import Pagination
from app.core.security import utcnow
from app.domain.enums import (
    CaseStatus,
    EventType,
    ExceptionStatus,
    ExceptionType,
    InvoiceStatus,
    NotificationType,
    Severity,
    ValidationStatus,
)
from app.models.cases import Case, CaseLink, ExceptionRecord, ExceptionRule, ExceptionRuleVersion
from app.models.documents import Document
from app.models.finance import Invoice, PurchaseOrder, Vendor
from app.modules.cases.service import PRIORITY_FROM_SEVERITY, create_case, link_entity, log_activity
from app.modules.exceptions import rules as rule_engine
from app.modules.exceptions.rules import Finding, RuleContext, RuleDefinition
from app.modules.exceptions.schemas import (
    DetectionResult,
    ExceptionDetail,
    ExceptionOut,
    ExceptionSummary,
    ExceptionSummaryRow,
    RuleDetail,
    RuleOut,
    RuleUpdate,
    RuleVersionOut,
)
from app.services.audit import record_audit
from app.services.events import emit_event
from app.services.notifications import notify, user_ids_with_permission

logger = get_logger(__name__)

ACTIVE_CASE_STATUSES = [
    CaseStatus.OPEN,
    CaseStatus.INVESTIGATING,
    CaseStatus.AWAITING_INFORMATION,
    CaseStatus.AWAITING_APPROVAL,
    CaseStatus.RESOLUTION_IN_PROGRESS,
    CaseStatus.REOPENED,
]


# ------------------------------------------------------------------------------- rules


def _rules_for(db: Session, org_id: uuid.UUID, entity_type: str) -> list[tuple[ExceptionRule, RuleDefinition, dict[str, Any], int]]:
    rule_engine.ensure_default_rules(db, org_id)
    db.flush()
    rules = db.scalars(
        select(ExceptionRule).where(ExceptionRule.org_id == org_id, ExceptionRule.is_enabled.is_(True))
    ).all()
    selected = []
    for rule in rules:
        if entity_type not in (rule.applies_to or []):
            continue
        definition = rule_engine.RULE_LIBRARY.get(rule.code)
        if definition is None:
            logger.warning("rule_without_implementation", code=rule.code)
            continue
        config, version = rule_engine.active_config(db, rule)
        selected.append((rule, definition, config, version))
    return selected


def list_rules(db: Session, *, org_id: uuid.UUID) -> list[RuleOut]:
    rule_engine.ensure_default_rules(db, org_id)
    db.flush()
    rows = db.scalars(select(ExceptionRule).where(ExceptionRule.org_id == org_id).order_by(ExceptionRule.code)).all()
    result: list[RuleOut] = []
    for rule in rows:
        config, version = rule_engine.active_config(db, rule)
        definition = rule_engine.RULE_LIBRARY.get(rule.code)
        result.append(
            RuleOut(
                id=rule.id,
                code=rule.code,
                name=rule.name,
                description=rule.description,
                exception_type=rule.exception_type,
                severity=rule.severity,
                applies_to=list(rule.applies_to or []),
                is_enabled=rule.is_enabled,
                is_system=rule.is_system,
                active_version=version,
                config=config,
                conditions=definition.conditions if definition else {},
                test_cases=[dict(case) for case in (definition.test_cases if definition else ())],
                updated_at=rule.updated_at,
            )
        )
    return result


def get_rule(db: Session, *, org_id: uuid.UUID, code: str) -> RuleDetail:
    rule_engine.ensure_default_rules(db, org_id)
    db.flush()
    rule = db.scalar(select(ExceptionRule).where(ExceptionRule.org_id == org_id, ExceptionRule.code == code))
    if rule is None:
        raise NotFoundError("Exception rule not found.", code="rule_not_found")
    config, version = rule_engine.active_config(db, rule)
    definition = rule_engine.RULE_LIBRARY.get(rule.code)
    versions = db.scalars(
        select(ExceptionRuleVersion)
        .where(ExceptionRuleVersion.rule_id == rule.id)
        .order_by(ExceptionRuleVersion.version.desc())
    ).all()
    return RuleDetail(
        id=rule.id,
        code=rule.code,
        name=rule.name,
        description=rule.description,
        exception_type=rule.exception_type,
        severity=rule.severity,
        applies_to=list(rule.applies_to or []),
        is_enabled=rule.is_enabled,
        is_system=rule.is_system,
        active_version=version,
        config=config,
        conditions=definition.conditions if definition else {},
        test_cases=[dict(case) for case in (definition.test_cases if definition else ())],
        updated_at=rule.updated_at,
        versions=[
            RuleVersionOut(
                id=item.id,
                version=item.version,
                config=item.config,
                conditions=item.conditions,
                thresholds=item.thresholds,
                test_cases=item.test_cases,
                is_active=item.is_active,
                change_note=item.change_note,
                created_at=item.created_at,
            )
            for item in versions
        ],
    )


def update_rule(
    db: Session, *, org_id: uuid.UUID, code: str, actor_id: uuid.UUID | None, payload: RuleUpdate
) -> RuleDetail:
    rule_engine.ensure_default_rules(db, org_id)
    db.flush()
    rule = db.scalar(select(ExceptionRule).where(ExceptionRule.org_id == org_id, ExceptionRule.code == code))
    if rule is None:
        raise NotFoundError("Exception rule not found.", code="rule_not_found")
    current_config, current_version = rule_engine.active_config(db, rule)
    current_rule_version = db.scalar(
        select(ExceptionRuleVersion)
        .where(ExceptionRuleVersion.rule_id == rule.id, ExceptionRuleVersion.is_active.is_(True))
        .order_by(ExceptionRuleVersion.version.desc())
        .limit(1)
    )
    new_config = payload.config if payload.config is not None else current_config
    if not isinstance(new_config, dict):
        raise BadRequestError("Rule config must be an object.", code="invalid_rule_config")
    if payload.severity is not None:
        rule.severity = payload.severity
    if payload.is_enabled is not None:
        rule.is_enabled = payload.is_enabled
    rule.updated_by_id = actor_id

    changed = (
        payload.config is not None
        or payload.conditions is not None
        or payload.thresholds is not None
        or payload.test_cases is not None
    )
    if changed:
        for version in db.scalars(
            select(ExceptionRuleVersion).where(
                ExceptionRuleVersion.rule_id == rule.id, ExceptionRuleVersion.is_active.is_(True)
            )
        ):
            version.is_active = False
        db.add(
            ExceptionRuleVersion(
                rule_id=rule.id,
                version=current_version + 1,
                config=new_config,
                conditions=(payload.conditions if payload.conditions is not None else (current_rule_version.conditions if current_rule_version else {})),
                thresholds=(payload.thresholds if payload.thresholds is not None else (current_rule_version.thresholds if current_rule_version else {})),
                test_cases=(payload.test_cases if payload.test_cases is not None else (current_rule_version.test_cases if current_rule_version else [])),
                is_active=True,
                change_note=payload.change_note or "Rule configuration updated",
                created_by_id=actor_id,
            )
        )
    record_audit(
        db,
        org_id=org_id,
        action="exception_rule.updated",
        entity_type="exception_rule",
        entity_id=rule.id,
        summary=f"Rule {rule.code} updated",
        actor_id=actor_id,
        before={"config": current_config, "version": current_version},
        after={"config": new_config, "enabled": rule.is_enabled},
    )
    db.flush()
    return get_rule(db, org_id=org_id, code=code)


# --------------------------------------------------------------------------- detection


_UNSET = object()


def _exception_out(db: Session, record: ExceptionRecord, *, case: Any = _UNSET) -> ExceptionOut:
    if case is _UNSET:
        case = db.get(Case, record.case_id) if record.case_id else None
    return ExceptionOut(
        id=record.id,
        exception_type=record.exception_type,
        severity=record.severity,
        status=record.status,
        title=record.title,
        description=record.description,
        rule_code=record.rule_code,
        rule_version=record.rule_version,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        case_id=record.case_id,
        case_number=case.case_number if case else None,
        case_status=case.status if case else None,
        detection_count=record.detection_count,
        first_detected_at=record.first_detected_at,
        last_detected_at=record.last_detected_at,
        evidence=record.evidence or {},
        is_demo=record.is_demo,
    )


def _persist_findings(
    db: Session,
    *,
    org_id: uuid.UUID,
    findings: list[Finding],
    rule: ExceptionRule,
    rule_version: int,
    actor_id: uuid.UUID | None,
    create_cases: bool,
) -> tuple[list[ExceptionRecord], int, int, set[uuid.UUID]]:
    created = 0
    updated = 0
    records: list[ExceptionRecord] = []
    now = utcnow()
    for finding in findings:
        existing = db.scalar(
            select(ExceptionRecord).where(
                ExceptionRecord.org_id == org_id, ExceptionRecord.fingerprint == finding.dedupe_key
            )
        )
        if existing is not None:
            existing.last_detected_at = now
            existing.detection_count += 1
            existing.evidence = finding.evidence
            existing.severity = finding.severity
            existing.rule_version = rule_version
            if existing.status in {ExceptionStatus.RESOLVED, ExceptionStatus.IGNORED}:
                existing.status = ExceptionStatus.OPEN
                existing.resolved_at = None
                existing.resolved_by_id = None
            records.append(existing)
            updated += 1
            continue
        record = ExceptionRecord(
            org_id=org_id,
            exception_type=finding.exception_type,
            severity=finding.severity,
            status=ExceptionStatus.OPEN,
            rule_id=rule.id,
            rule_code=rule.code,
            rule_version=rule_version,
            entity_type=finding.entity_type,
            entity_id=finding.entity_id or uuid.uuid4(),
            title=finding.title,
            description=finding.description,
            evidence=finding.evidence,
            fingerprint=finding.dedupe_key,
            first_detected_at=now,
            last_detected_at=now,
            detection_count=1,
        )
        db.add(record)
        db.flush()
        records.append(record)
        created += 1
        record_audit(
            db,
            org_id=org_id,
            action="exception.detected",
            entity_type="exception",
            entity_id=record.id,
            summary=f"{record.exception_type.value}: {record.title}",
            actor_id=actor_id,
            after={"rule": rule.code, "version": rule_version, "severity": record.severity.value},
        )
        emit_event(
            db,
            org_id=org_id,
            event_type=EventType.EXCEPTION_DETECTED,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            payload={
                "exception_id": str(record.id),
                "exception_type": record.exception_type.value,
                "severity": record.severity.value,
                "title": record.title,
            },
        )

    if create_cases:
        grouped: dict[tuple[str, uuid.UUID], list[ExceptionRecord]] = {}
        for record in records:
            grouped.setdefault((record.entity_type, record.entity_id), []).append(record)
        opened_cases: set[uuid.UUID] = set()
        for (entity_type, entity_id), entity_records in grouped.items():
            case, was_created = _group_into_case(
                db, org_id=org_id, entity_type=entity_type, entity_id=entity_id,
                records=entity_records, actor_id=actor_id,
            )
            if case is not None and was_created:
                opened_cases.add(case.id)
    else:
        opened_cases = set()
    return records, created, updated, opened_cases


def _group_into_case(
    db: Session,
    *,
    org_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    records: list[ExceptionRecord],
    actor_id: uuid.UUID | None,
) -> tuple[Case | None, bool]:
    open_records = [r for r in records if r.case_id is None]
    if not open_records:
        return None, False
    existing_case = db.scalar(
        select(Case)
        .join(CaseLink, CaseLink.case_id == Case.id)
        .where(
            Case.org_id == org_id,
            Case.status.in_(ACTIVE_CASE_STATUSES),
            CaseLink.entity_type == entity_type,
            CaseLink.entity_id == entity_id,
        )
        .limit(1)
    )
    severity_order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]
    highest = next(
        (level for level in severity_order if any(record.severity == level for record in open_records)),
        Severity.MEDIUM,
    )
    priority = PRIORITY_FROM_SEVERITY[highest]

    if existing_case is not None:
        for record in open_records:
            record.case_id = existing_case.id
            if record.status == ExceptionStatus.OPEN:
                record.status = ExceptionStatus.ACKNOWLEDGED
            link_entity(db, case=existing_case, entity_type="EXCEPTION", entity_id=record.id, label=record.title)
        log_activity(
            db,
            case=existing_case,
            actor_id=actor_id,
            activity_type="EXCEPTIONS_ATTACHED",
            summary=f"{len(open_records)} new exception(s) attached automatically",
            payload={"exception_ids": [str(record.id) for record in open_records]},
        )
        return existing_case, False

    entity = _resolve_entity(db, org_id=org_id, entity_type=entity_type, entity_id=entity_id)
    case_title = _case_title(entity_type, entity, open_records)
    links: list[tuple[str, uuid.UUID, str | None]] = [(entity_type, entity_id, None)]
    invoice = entity["invoice"] if entity_type == "INVOICE" else None
    if invoice is not None:
        links.append(("INVOICE", invoice.id, invoice.invoice_number))
        if invoice.vendor_id:
            links.append(("VENDOR", invoice.vendor_id, None))
        if invoice.purchase_order_id:
            links.append(("PURCHASE_ORDER", invoice.purchase_order_id, None))
        if invoice.document_id:
            links.append(("DOCUMENT", invoice.document_id, None))

    case = create_case(
        db,
        org_id=org_id,
        actor_id=actor_id,
        title=case_title,
        description=(
            f"Automatically opened from {len(open_records)} detected exception(s): "
            + ", ".join(sorted({record.exception_type.value for record in open_records}))
        ),
        priority=priority,
        severity=highest,
        tags=["auto-detected", *(sorted({record.exception_type.value.lower() for record in open_records}))][:10],
        links=links,
        exception_ids=[record.id for record in open_records],
    )
    for record in open_records:
        record.case_id = case.id
        record.status = ExceptionStatus.ACKNOWLEDGED
    return case, True


def _resolve_entity(
    db: Session, *, org_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if entity_type == "INVOICE":
        invoice = db.get(Invoice, entity_id)
        if invoice is not None and invoice.org_id == org_id:
            payload["invoice"] = invoice
            payload["label"] = invoice.invoice_number
    elif entity_type == "VENDOR":
        vendor = db.get(Vendor, entity_id)
        if vendor is not None and vendor.org_id == org_id:
            payload["vendor"] = vendor
            payload["label"] = vendor.legal_name
    elif entity_type == "INTEGRATION":
        payload["label"] = "Integration"
    return payload


def _case_title(entity_type: str, entity: dict[str, Any], records: list[ExceptionRecord]) -> str:
    types = sorted({record.exception_type.value.replace("_", " ").title() for record in records})
    label = entity.get("label") or entity_type.title()
    if len(types) == 1:
        return f"{types[0]} – {label}"
    return f"{len(types)} exceptions – {label}"


def detect_for_invoice(
    db: Session,
    *,
    org_id: uuid.UUID,
    invoice: Invoice,
    actor_id: uuid.UUID | None = None,
    create_cases: bool = True,
    opened_cases: set[uuid.UUID] | None = None,
) -> list[ExceptionRecord]:
    org_settings: dict[str, Any] = {}
    from app.models.identity import Organization

    organization = db.get(Organization, org_id)
    if organization is not None:
        org_settings = dict(organization.settings or {})
    vendor = db.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None
    purchase_order = db.get(PurchaseOrder, invoice.purchase_order_id) if invoice.purchase_order_id else None

    records: list[ExceptionRecord] = []
    opened_case_ids: set[uuid.UUID] = opened_cases if opened_cases is not None else set()
    for rule, definition, config, version in _rules_for(db, org_id, "INVOICE"):
        if rule.exception_type.value == "INTEGRATION_FAILURE":
            continue
        ctx = RuleContext(
            db=db,
            org_id=org_id,
            invoice=invoice,
            vendor=vendor,
            purchase_order=purchase_order,
            org_settings=org_settings,
            config=config,
        )
        try:
            findings = definition.evaluate(ctx)
        except Exception as exc:  # noqa: BLE001 - one broken rule must not stop detection
            logger.exception("rule_evaluation_failed", rule=rule.code, invoice_id=str(invoice.id))
            record_audit(
                db,
                org_id=org_id,
                action="exception_rule.failed",
                entity_type="exception_rule",
                entity_id=rule.id,
                summary=f"Rule {rule.code} failed: {type(exc).__name__}",
                actor_id=actor_id,
                context={"error": str(exc)[:500]},
            )
            continue
        if not findings:
            continue
        for finding in findings:
            if finding.entity_type == "VENDOR" and vendor is not None:
                finding.entity_id = vendor.id
        persisted, _created, _updated, opened = _persist_findings(
            db, org_id=org_id, findings=findings, rule=rule, rule_version=version,
            actor_id=actor_id, create_cases=create_cases,
        )
        opened_case_ids.update(opened)
        records.extend(persisted)

    if records:
        highest = max(records, key=lambda record: list(Severity).index(record.severity))
        if invoice.status not in {
            InvoiceStatus.APPROVED,
            InvoiceStatus.READY_FOR_EXPORT,
            InvoiceStatus.REJECTED,
            InvoiceStatus.CANCELLED,
        } and highest.severity in {Severity.HIGH, Severity.CRITICAL}:
            invoice.status = InvoiceStatus.REQUIRES_REVIEW
        if invoice.validation_status != ValidationStatus.FAILED:
            invoice.validation_status = ValidationStatus.WARNING
    return records


def detect_for_vendor(
    db: Session, *, org_id: uuid.UUID, vendor: Vendor, actor_id: uuid.UUID | None = None
) -> list[ExceptionRecord]:
    records: list[ExceptionRecord] = []
    for rule, definition, config, version in _rules_for(db, org_id, "VENDOR"):
        ctx = RuleContext(db=db, org_id=org_id, vendor=vendor, config=config)
        try:
            findings = definition.evaluate(ctx)
        except Exception:  # noqa: BLE001
            logger.exception("vendor_rule_failed", rule=rule.code)
            continue
        if findings:
            persisted, _, _, _ = _persist_findings(
                db, org_id=org_id, findings=findings, rule=rule, rule_version=version,
                actor_id=actor_id, create_cases=True,
            )
            records.extend(persisted)
    return records


def detect_integration_failures(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> list[ExceptionRecord]:
    records: list[ExceptionRecord] = []
    for rule, definition, config, version in _rules_for(db, org_id, "INTEGRATION"):
        ctx = RuleContext(db=db, org_id=org_id, config=config)
        findings = definition.evaluate(ctx)
        if findings:
            persisted, _, _, _ = _persist_findings(
                db, org_id=org_id, findings=findings, rule=rule, rule_version=version,
                actor_id=actor_id, create_cases=True,
            )
            records.extend(persisted)
    return records


def run_detection(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    invoice_id: uuid.UUID | None = None,
    include_invoices: bool = False,
    include_vendors: bool = False,
    include_integrations: bool = False,
    create_cases: bool = True,
    limit: int = 200,
) -> DetectionResult:
    result = DetectionResult()
    opened_case_ids: set[uuid.UUID] = set()
    rule_errors: list[dict[str, str]] = []
    invoices: list[Invoice] = []
    if invoice_id:
        invoice = db.scalar(
            select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == org_id, Invoice.deleted_at.is_(None))
        )
        if invoice is None:
            raise NotFoundError("Invoice not found.", code="invoice_not_found")
        invoices = [invoice]
    elif include_invoices:
        invoices = list(
            db.scalars(
                select(Invoice)
                .where(Invoice.org_id == org_id, Invoice.deleted_at.is_(None))
                .order_by(Invoice.created_at.desc())
                .limit(limit)
            )
        )
    for invoice in invoices:
        try:
            before_ids = {
                record.id
                for record in db.scalars(
                    select(ExceptionRecord).where(
                        ExceptionRecord.org_id == org_id,
                        ExceptionRecord.entity_id == invoice.id,
                        ExceptionRecord.entity_type == "INVOICE",
                    )
                )
            }
            records = detect_for_invoice(
                db, org_id=org_id, invoice=invoice, actor_id=actor_id, create_cases=create_cases,
                opened_cases=opened_case_ids,
            )
            result.scanned_invoices += 1
            for record in records:
                if record.id in before_ids:
                    result.updated_exceptions += 1
                else:
                    result.created_exceptions += 1
                result.exception_ids.append(record.id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("invoice_detection_failed", invoice_id=str(invoice.id))
            rule_errors.append({"invoice_id": str(invoice.id), "error": str(exc)[:300]})

    if include_vendors:
        vendors = db.scalars(
            select(Vendor)
            .where(Vendor.org_id == org_id, Vendor.deleted_at.is_(None))
            .limit(limit)
        ).all()
        for vendor in vendors:
            records = detect_for_vendor(db, org_id=org_id, vendor=vendor, actor_id=actor_id)
            result.scanned_vendors += 1
            result.created_exceptions += len(records)
            result.exception_ids.extend(record.id for record in records)

    if include_integrations:
        records = detect_integration_failures(db, org_id=org_id, actor_id=actor_id)
        result.created_exceptions += len(records)
        result.exception_ids.extend(record.id for record in records)

    result.opened_cases = len(opened_case_ids)
    result.rule_errors = rule_errors
    return result


# ------------------------------------------------------------------------- queries


def list_exceptions(
    db: Session,
    *,
    org_id: uuid.UUID,
    pagination: Pagination,
    search: str | None = None,
    exception_type: list[ExceptionType] | None = None,
    severity: list[Severity] | None = None,
    status: list[ExceptionStatus] | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    case_id: uuid.UUID | None = None,
    unassigned: bool | None = None,
) -> tuple[list[ExceptionOut], int]:
    stmt = select(ExceptionRecord).where(ExceptionRecord.org_id == org_id)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(func.lower(ExceptionRecord.title).like(pattern), func.lower(ExceptionRecord.description).like(pattern))
        )
    if exception_type:
        stmt = stmt.where(ExceptionRecord.exception_type.in_(exception_type))
    if severity:
        stmt = stmt.where(ExceptionRecord.severity.in_(severity))
    if status:
        stmt = stmt.where(ExceptionRecord.status.in_(status))
    if entity_type:
        stmt = stmt.where(ExceptionRecord.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(ExceptionRecord.entity_id == entity_id)
    if case_id:
        stmt = stmt.where(ExceptionRecord.case_id == case_id)
    if unassigned:
        stmt = stmt.where(ExceptionRecord.case_id.is_(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sort_column = {
        "last_detected_at": ExceptionRecord.last_detected_at,
        "first_detected_at": ExceptionRecord.first_detected_at,
        "severity": ExceptionRecord.severity,
        "status": ExceptionRecord.status,
    }.get(pagination.sort or "last_detected_at", ExceptionRecord.last_detected_at)
    ordering = sort_column.asc() if pagination.order == "asc" else sort_column.desc()
    rows = db.scalars(stmt.order_by(ordering).offset(pagination.offset).limit(pagination.page_size)).all()
    case_ids = {record.case_id for record in rows if record.case_id}
    cases = (
        {case.id: case for case in db.scalars(select(Case).where(Case.id.in_(case_ids)))}
        if case_ids
        else {}
    )
    return [
        _exception_out(db, record, case=cases.get(record.case_id)) for record in rows
    ], total


def get_exception(db: Session, *, org_id: uuid.UUID, exception_id: uuid.UUID) -> ExceptionRecord:
    record = db.scalar(
        select(ExceptionRecord).where(ExceptionRecord.id == exception_id, ExceptionRecord.org_id == org_id)
    )
    if record is None:
        raise NotFoundError("Exception not found.", code="exception_not_found")
    return record


def detail(db: Session, *, record: ExceptionRecord) -> ExceptionDetail:
    base = _exception_out(db, record)
    rule = db.get(ExceptionRule, record.rule_id) if record.rule_id else None
    related: dict[str, Any] = {}
    if record.entity_type == "INVOICE":
        invoice = db.get(Invoice, record.entity_id)
        if invoice is not None:
            vendor = db.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None
            document = db.get(Document, invoice.document_id) if invoice.document_id else None
            related = {
                "invoice": {
                    "id": str(invoice.id),
                    "invoice_number": invoice.invoice_number,
                    "status": invoice.status.value,
                    "total": str(invoice.total),
                    "currency": invoice.currency,
                },
                "vendor": {"id": str(vendor.id), "legal_name": vendor.legal_name} if vendor else None,
                "document": {"id": str(document.id), "filename": document.original_filename} if document else None,
            }
    elif record.entity_type == "VENDOR":
        vendor = db.get(Vendor, record.entity_id)
        if vendor is not None:
            related = {
                "vendor": {
                    "id": str(vendor.id),
                    "legal_name": vendor.legal_name,
                    "vendor_number": vendor.vendor_number,
                }
            }
    return ExceptionDetail(**base.model_dump(), rule_name=rule.name if rule else None, related=related)


def update_status(
    db: Session,
    *,
    record: ExceptionRecord,
    status: ExceptionStatus,
    actor_id: uuid.UUID | None,
    note: str | None,
) -> ExceptionRecord:
    allowed: dict[ExceptionStatus, set[ExceptionStatus]] = {
        ExceptionStatus.OPEN: {ExceptionStatus.ACKNOWLEDGED, ExceptionStatus.IGNORED, ExceptionStatus.RESOLVED},
        ExceptionStatus.ACKNOWLEDGED: {ExceptionStatus.LINKED, ExceptionStatus.IGNORED, ExceptionStatus.RESOLVED},
        ExceptionStatus.LINKED: {ExceptionStatus.RESOLVED, ExceptionStatus.IGNORED},
        ExceptionStatus.RESOLVED: {ExceptionStatus.OPEN},
        ExceptionStatus.IGNORED: {ExceptionStatus.OPEN},
    }
    if status == record.status:
        return record
    if status not in allowed.get(record.status, set()):
        raise BadRequestError(
            f"Cannot change an exception from {record.status.value} to {status.value}.",
            code="invalid_exception_transition",
        )
    if status == ExceptionStatus.RESOLVED and not note:
        raise BadRequestError("A resolution note is required.", code="note_required")
    previous = record.status
    record.status = status
    if status == ExceptionStatus.RESOLVED:
        record.resolved_at = utcnow()
        record.resolved_by_id = actor_id
        record.resolution_note = note
    record_audit(
        db,
        org_id=record.org_id,
        action="exception.status_changed",
        entity_type="exception",
        entity_id=record.id,
        summary=f"Exception {previous.value} -> {status.value}",
        actor_id=actor_id,
        before={"status": previous.value},
        after={"status": status.value, "note": note},
    )
    return record


def summary(db: Session, *, org_id: uuid.UUID) -> ExceptionSummary:
    mode = func.count(ExceptionRecord.id)
    severity_rows = db.execute(
        select(ExceptionRecord.severity, mode).where(ExceptionRecord.org_id == org_id).group_by(ExceptionRecord.severity)
    ).all()
    type_rows = db.execute(
        select(ExceptionRecord.exception_type, mode)
        .where(ExceptionRecord.org_id == org_id)
        .group_by(ExceptionRecord.exception_type)
    ).all()
    status_rows = db.execute(
        select(ExceptionRecord.status, mode).where(ExceptionRecord.org_id == org_id).group_by(ExceptionRecord.status)
    ).all()
    total = db.scalar(select(func.count()).select_from(ExceptionRecord).where(ExceptionRecord.org_id == org_id)) or 0
    open_count = db.scalar(
        select(func.count())
        .select_from(ExceptionRecord)
        .where(
            ExceptionRecord.org_id == org_id,
            ExceptionRecord.status.in_([ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED, ExceptionStatus.LINKED]),
        )
    ) or 0
    unassigned = db.scalar(
        select(func.count())
        .select_from(ExceptionRecord)
        .where(ExceptionRecord.org_id == org_id, ExceptionRecord.case_id.is_(None))
    ) or 0
    mean_detections = db.scalar(
        select(func.avg(ExceptionRecord.detection_count)).where(ExceptionRecord.org_id == org_id)
    ) or 0.0
    return ExceptionSummary(
        total=int(total),
        open_count=int(open_count),
        by_severity=[
            ExceptionSummaryRow(key=key.value, label=key.value.title(), count=int(count)) for key, count in severity_rows
        ],
        by_type=[
            ExceptionSummaryRow(
                key=key.value, label=key.value.replace("_", " ").title(), count=int(count)
            )
            for key, count in type_rows
        ],
        by_status=[
            ExceptionSummaryRow(key=key.value, label=key.value.title(), count=int(count)) for key, count in status_rows
        ],
        unassigned_to_case=int(unassigned),
        mean_detections=round(float(mean_detections), 2),
    )


def attach_to_case(
    db: Session, *, record: ExceptionRecord, case: Case, actor_id: uuid.UUID | None
) -> ExceptionRecord:
    record.case_id = case.id
    if record.status == ExceptionStatus.OPEN:
        record.status = ExceptionStatus.ACKNOWLEDGED
    link_entity(db, case=case, entity_type="EXCEPTION", entity_id=record.id, label=record.title)
    log_activity(
        db,
        case=case,
        actor_id=actor_id,
        activity_type="EXCEPTION_LINKED",
        summary=f"Exception linked: {record.title}",
        payload={"exception_id": str(record.id)},
    )
    return record


def notify_detection(db: Session, *, org_id: uuid.UUID, record: ExceptionRecord) -> None:
    if record.severity not in {Severity.HIGH, Severity.CRITICAL}:
        return
    recipients = user_ids_with_permission(db, org_id=org_id, permission="exception:triage")
    for user_id in recipients:
        notify(
            db,
            org_id=org_id,
            user_id=user_id,
            type=NotificationType.HIGH_PRIORITY_CASE,
            title=f"{record.severity.value.title()} exception: {record.title}",
            body=record.description[:500],
            entity_type="EXCEPTION",
            entity_id=record.id,
            send_mail=False,
        )
