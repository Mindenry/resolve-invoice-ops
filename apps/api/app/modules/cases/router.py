"""Case management endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.domain.enums import CaseStatus, CommentVisibility, Priority, Severity
from app.modules.cases import service
from app.modules.cases.schemas import (
    BulkAssignRequest,
    CaseAssignRequest,
    CaseCommentCreate,
    CaseCommentOut,
    CaseCreate,
    CaseDetail,
    CaseEscalateRequest,
    CaseMergeRequest,
    CaseResolveRequest,
    CaseSummary,
    CaseTransitionRequest,
    CaseUpdate,
    TimelineItem,
)
from app.schemas.common import APIMessage, BulkIds

router = APIRouter(prefix="/cases", tags=["Cases"])

CaseReader = Annotated[Principal, Depends(require_permission("case:read"))]
CaseCreator = Annotated[Principal, Depends(require_permission("case:create"))]
CaseEditor = Annotated[Principal, Depends(require_permission("case:update"))]
CaseAssigner = Annotated[Principal, Depends(require_permission("case:assign"))]
CaseCommenter = Annotated[Principal, Depends(require_permission("case:comment"))]
CaseCloser = Annotated[Principal, Depends(require_permission("case:close"))]


@router.get("", response_model=Page[CaseSummary], summary="List cases")
def list_cases(
    principal: CaseReader,
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    status: list[CaseStatus] | None = Query(None),
    priority: list[Priority] | None = Query(None),
    assigned_user_id: uuid.UUID | None = Query(None),
    search: str | None = Query(None, max_length=160),
    tag: str | None = Query(None, max_length=40),
    breached: bool | None = Query(None),
    open_only: bool = Query(False),
) -> Page[CaseSummary]:
    items, total = service.list_cases(
        db,
        org_id=principal.org_id,
        pagination=pagination,
        status=status,
        priority=priority,
        assigned_user_id=assigned_user_id,
        search=search,
        tag=tag,
        breached=breached,
        open_only=open_only,
    )
    return Page.build(items, total, pagination)


@router.post("", response_model=CaseDetail, status_code=201, summary="Create a case")
def create_case(
    payload: CaseCreate,
    principal: CaseCreator,
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetail:
    links: list[tuple[str, uuid.UUID, str | None]] = []
    if payload.invoice_id:
        from app.modules.invoices.service import get_invoice

        invoice = get_invoice(db, org_id=principal.org_id, invoice_id=payload.invoice_id)
        links.append(("INVOICE", invoice.id, invoice.invoice_number))
        if invoice.vendor_id:
            links.append(("VENDOR", invoice.vendor_id, None))
        if invoice.purchase_order_id:
            links.append(("PURCHASE_ORDER", invoice.purchase_order_id, None))
        if invoice.document_id:
            links.append(("DOCUMENT", invoice.document_id, None))
    case = service.create_case(
        db,
        org_id=principal.org_id,
        actor_id=principal.user_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        severity=payload.severity,
        assigned_user_id=payload.assigned_user_id,
        tags=payload.tags,
        sla_hours=payload.sla_hours,
        links=links,
        exception_ids=payload.exception_ids,
    )
    db.commit()
    return service.detail(db, case)


@router.get("/{case_id}", response_model=CaseDetail, summary="Case detail workspace")
def get_case(
    case_id: uuid.UUID, principal: CaseReader, db: Annotated[Session, Depends(get_db)]
) -> CaseDetail:
    case = service.get_case(db, org_id=principal.org_id, case_id=case_id)
    detail = service.detail(db, case)
    if case.status not in {CaseStatus.RESOLVED, CaseStatus.CLOSED, CaseStatus.CANCELLED} and case.due_at:
        from app.core.security import as_utc

        breached = (as_utc(case.due_at) or service.utcnow()) < service.utcnow()
        if breached != case.sla_breached:
            case.sla_breached = breached
            db.commit()
    return detail


@router.patch("/{case_id}", response_model=CaseDetail, summary="Update case fields")
def update_case(
    case_id: uuid.UUID,
    payload: CaseUpdate,
    principal: CaseEditor,
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetail:
    case = service.get_case(db, org_id=principal.org_id, case_id=case_id)
    service.update_case(
        db,
        case=case,
        actor_id=principal.user_id,
        changes=payload.model_dump(exclude_unset=True),
        summary="Case fields updated",
    )
    db.commit()
    return service.detail(db, case)


@router.post("/{case_id}/transition", response_model=CaseDetail, summary="Change case status")
def transition_case(
    case_id: uuid.UUID,
    payload: CaseTransitionRequest,
    principal: CaseCloser,
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetail:
    case = service.get_case(db, org_id=principal.org_id, case_id=case_id)
    service.transition(
        db,
        case=case,
        new_status=payload.status,
        actor_id=principal.user_id,
        note=payload.note,
        resolution_summary=payload.resolution_summary,
    )
    db.commit()
    return service.detail(db, case)


@router.post("/{case_id}/resolve", response_model=CaseDetail, summary="Resolve a case")
def resolve_case(
    case_id: uuid.UUID,
    payload: CaseResolveRequest,
    principal: CaseCloser,
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetail:
    case = service.get_case(db, org_id=principal.org_id, case_id=case_id)
    service.transition(
        db,
        case=case,
        new_status=CaseStatus.RESOLVED,
        actor_id=principal.user_id,
        resolution_summary=payload.resolution_summary,
    )
    if payload.close:
        service.transition(
            db, case=case, new_status=CaseStatus.CLOSED, actor_id=principal.user_id, note="Closed after resolution"
        )
    db.commit()
    return service.detail(db, case)


@router.post("/{case_id}/assign", response_model=CaseDetail, summary="Assign or reassign a case")
def assign_case(
    case_id: uuid.UUID,
    payload: CaseAssignRequest,
    principal: CaseAssigner,
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetail:
    case = service.get_case(db, org_id=principal.org_id, case_id=case_id)
    service.assign_case(
        db, case=case, user_id=payload.user_id, actor_id=principal.user_id, reason=payload.reason
    )
    db.commit()
    return service.detail(db, case)


@router.post("/{case_id}/comments", response_model=CaseCommentOut, status_code=201, summary="Add a comment")
def add_comment(
    case_id: uuid.UUID,
    payload: CaseCommentCreate,
    principal: CaseCommenter,
    db: Annotated[Session, Depends(get_db)],
) -> CaseCommentOut:
    case = service.get_case(db, org_id=principal.org_id, case_id=case_id)
    comment = service.add_comment(
        db, case=case, author=principal.user, body=payload.body, visibility=payload.visibility
    )
    db.commit()
    return CaseCommentOut(
        id=comment.id,
        author_id=principal.user_id,
        author_name=principal.user.full_name,
        body=comment.body,
        visibility=comment.visibility,
        created_at=comment.created_at,
        edited_at=comment.edited_at,
    )


@router.post("/{case_id}/escalate", response_model=CaseDetail, summary="Escalate a case")
def escalate(
    case_id: uuid.UUID,
    payload: CaseEscalateRequest,
    principal: CaseAssigner,
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetail:
    case = service.get_case(db, org_id=principal.org_id, case_id=case_id)
    service.escalate_case(
        db, case=case, actor_id=principal.user_id, reason=payload.reason, priority=payload.priority
    )
    db.commit()
    return service.detail(db, case)


@router.post("/{case_id}/merge", response_model=CaseDetail, summary="Merge another case into this one")
def merge_case(
    case_id: uuid.UUID,
    payload: CaseMergeRequest,
    principal: Annotated[Principal, Depends(require_permission("case:merge"))],
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetail:
    target = service.get_case(db, org_id=principal.org_id, case_id=case_id)
    source = service.get_case(db, org_id=principal.org_id, case_id=payload.source_case_id)
    service.merge_cases(
        db, target=target, source=source, actor_id=principal.user_id, note=payload.note
    )
    db.commit()
    return service.detail(db, target)


@router.post("/{case_id}/exceptions", response_model=CaseDetail, summary="Attach exceptions to a case")
def attach_exceptions(
    case_id: uuid.UUID,
    payload: BulkIds,
    principal: CaseEditor,
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetail:
    case = service.get_case(db, org_id=principal.org_id, case_id=case_id)
    ids = [uuid.UUID(value) for value in payload.ids]
    attached = service.attach_exceptions(db, case=case, exception_ids=ids)
    service.log_activity(
        db,
        case=case,
        actor_id=principal.user_id,
        activity_type="EXCEPTIONS_ATTACHED",
        summary=f"{attached} exception(s) attached",
    )
    db.commit()
    return service.detail(db, case)


@router.get("/{case_id}/timeline", response_model=list[TimelineItem], summary="Case activity timeline")
def get_timeline(
    case_id: uuid.UUID, principal: CaseReader, db: Annotated[Session, Depends(get_db)]
) -> list[TimelineItem]:
    case = service.get_case(db, org_id=principal.org_id, case_id=case_id)
    return service.timeline(db, case)


@router.post("/bulk/assign", response_model=APIMessage, summary="Bulk assign cases")
def bulk_assign(
    payload: BulkAssignRequest,
    principal: CaseAssigner,
    db: Annotated[Session, Depends(get_db)],
) -> APIMessage:
    assigned = 0
    for case_id in payload.case_ids:
        case = service.get_case(db, org_id=principal.org_id, case_id=case_id)
        service.assign_case(
            db, case=case, user_id=payload.user_id, actor_id=principal.user_id, reason="Bulk assignment"
        )
        assigned += 1
    db.commit()
    return APIMessage(message=f"{assigned} case(s) assigned.")


# Re-exported for OpenAPI consumers that filter comments by visibility.
_ = CommentVisibility, Severity
