"""AI evaluation lab endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.modules.ai_evaluation import service
from app.modules.ai_evaluation.schemas import (
    ComparisonRow,
    DatasetCreate,
    DatasetDetail,
    DatasetOut,
    EvaluationRunCreate,
    EvaluationRunDetail,
    EvaluationRunOut,
)

router = APIRouter(prefix="/evaluation", tags=["AI Evaluation"])

EvaluationReader = Annotated[Principal, Depends(require_permission("evaluation:read"))]
EvaluationRunner = Annotated[Principal, Depends(require_permission("evaluation:run"))]


@router.get("/datasets", response_model=list[DatasetOut], summary="Evaluation datasets")
def list_datasets(principal: EvaluationReader, db: Annotated[Session, Depends(get_db)]) -> list[DatasetOut]:
    return service.list_datasets(db, org_id=principal.org_id)


@router.post("/datasets", response_model=DatasetDetail, status_code=201, summary="Create a dataset")
def create_dataset(
    payload: DatasetCreate,
    principal: EvaluationRunner,
    db: Annotated[Session, Depends(get_db)],
) -> DatasetDetail:
    detail = service.create_dataset(db, org_id=principal.org_id, actor_id=principal.user_id, payload=payload)
    db.commit()
    return detail


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail, summary="Dataset with samples")
def get_dataset(
    dataset_id: uuid.UUID, principal: EvaluationReader, db: Annotated[Session, Depends(get_db)]
) -> DatasetDetail:
    dataset = service.get_dataset(db, org_id=principal.org_id, dataset_id=dataset_id)
    return service.dataset_detail(db, dataset)


@router.get("/runs", response_model=Page[EvaluationRunOut], summary="Evaluation runs")
def list_runs(
    principal: EvaluationReader,
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    dataset_id: uuid.UUID | None = Query(None),
) -> Page[EvaluationRunOut]:
    items, total = service.list_runs(
        db, org_id=principal.org_id, pagination=pagination, dataset_id=dataset_id
    )
    return Page.build(items, total, pagination)


@router.post("/runs", response_model=EvaluationRunOut, status_code=201, summary="Start an evaluation run")
def create_run(
    payload: EvaluationRunCreate,
    principal: EvaluationRunner,
    db: Annotated[Session, Depends(get_db)],
) -> EvaluationRunOut:
    run = service.create_run(db, org_id=principal.org_id, actor_id=principal.user_id, payload=payload)
    db.commit()
    return service.run_out(db, run)


@router.get("/runs/{run_id}", response_model=EvaluationRunDetail, summary="Run detail and results")
def get_run(
    run_id: uuid.UUID, principal: EvaluationReader, db: Annotated[Session, Depends(get_db)]
) -> EvaluationRunDetail:
    run = service.get_run(db, org_id=principal.org_id, run_id=run_id)
    return service.run_detail(db, run)


@router.get("/compare", response_model=list[ComparisonRow], summary="Compare evaluation runs")
def compare(
    principal: EvaluationReader,
    db: Annotated[Session, Depends(get_db)],
    ids: list[uuid.UUID] = Query(min_length=1, max_length=10),
) -> list[ComparisonRow]:
    return [ComparisonRow(**row) for row in service.compare_runs(db, org_id=principal.org_id, run_ids=ids)]
