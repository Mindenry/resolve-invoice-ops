"""AI investigation endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.prompts import INVESTIGATION_PROMPT_VERSION
from app.ai.registry import build_llm_provider, provider_status
from app.config.settings import settings
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.modules.cases.service import get_case
from app.modules.investigation import service
from app.modules.investigation.schemas import (
    AcceptSuggestionRequest,
    InvestigationOut,
    InvestigationRunRequest,
)

router = APIRouter(tags=["Investigation"])

InvestigationReader = Annotated[Principal, Depends(require_permission("investigation:read"))]
InvestigationRunner = Annotated[Principal, Depends(require_permission("investigation:run"))]
ResolutionProposer = Annotated[Principal, Depends(require_permission("resolution:propose"))]


@router.get("/investigations/ai-status", summary="AI provider availability")
async def ai_status(principal: InvestigationReader) -> dict[str, object]:
    status = provider_status()
    provider = build_llm_provider()
    healthy = False
    detail = "No provider configured"
    if provider is not None:
        try:
            healthy, detail = await provider.health()
        except Exception as exc:  # noqa: BLE001
            healthy, detail = False, str(exc)[:200]
    return {
        "configured": settings.ai_configured,
        "provider": status.llm_provider,
        "model": status.llm_model,
        "available": healthy,
        "detail": detail,
        "deterministic_stub": status.is_stub,
        "prompt_version": INVESTIGATION_PROMPT_VERSION,
    }


@router.post(
    "/cases/{case_id}/investigations",
    response_model=InvestigationOut,
    status_code=201,
    summary="Queue an AI investigation for a case",
)
def start_investigation(
    case_id: uuid.UUID,
    payload: InvestigationRunRequest,
    principal: InvestigationRunner,
    db: Annotated[Session, Depends(get_db)],
) -> InvestigationOut:
    case = get_case(db, org_id=principal.org_id, case_id=case_id)
    investigation = service.create_investigation(db, case=case, actor_id=principal.user_id)
    db.commit()
    return service.investigation_out(db, investigation)


@router.get(
    "/cases/{case_id}/investigations",
    response_model=list[InvestigationOut],
    summary="Investigations for a case",
)
def list_investigations(
    case_id: uuid.UUID,
    principal: InvestigationReader,
    db: Annotated[Session, Depends(get_db)],
) -> list[InvestigationOut]:
    case = get_case(db, org_id=principal.org_id, case_id=case_id)
    return [service.investigation_out(db, item) for item in service.list_for_case(db, case=case)]


@router.get(
    "/investigations/{investigation_id}",
    response_model=InvestigationOut,
    summary="Investigation detail with validated evidence",
)
def get_investigation(
    investigation_id: uuid.UUID,
    principal: InvestigationReader,
    db: Annotated[Session, Depends(get_db)],
) -> InvestigationOut:
    investigation = service.get_investigation(
        db, org_id=principal.org_id, investigation_id=investigation_id
    )
    return service.investigation_out(db, investigation)


@router.post(
    "/investigations/{investigation_id}/suggestions/{suggestion_index}/accept",
    summary="Turn an AI suggestion into a resolution proposal",
)
def accept_suggestion(
    investigation_id: uuid.UUID,
    suggestion_index: int,
    payload: AcceptSuggestionRequest,
    principal: ResolutionProposer,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    investigation = service.get_investigation(
        db, org_id=principal.org_id, investigation_id=investigation_id
    )
    resolution = service.accept_suggestion(
        db,
        investigation=investigation,
        suggestion_index=suggestion_index,
        actor_id=principal.user_id,
        case_id=payload.case_id,
    )
    db.commit()
    return {"resolution_id": str(resolution.id), "status": resolution.status.value}
