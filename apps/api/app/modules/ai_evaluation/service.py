"""AI evaluation lab: real runs over labelled synthetic samples.

Metrics are computed only from actual provider responses. A failed provider run records the
error and produces no scores. The deterministic stub provider exists so the harness can be
exercised without credentials; runs using it are labelled `deterministic_stub` and are not
evidence of a real model's quality.
"""

from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.base import ChatMessage
from app.ai.client import calculate_cost, record_usage, run_coroutine_safely, structured_completion
from app.ai.prompts import INVESTIGATION_INSTRUCTIONS, INVESTIGATION_PROMPT_VERSION, INVESTIGATION_SYSTEM
from app.ai.registry import build_llm_provider
from app.core.errors import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.core.pagination import Pagination
from app.core.security import utcnow
from app.domain.enums import JobStatus
from app.models.evaluation import (
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    EvaluationSample,
)
from app.modules.ai_evaluation.schemas import (
    DatasetCreate,
    DatasetDetail,
    DatasetOut,
    EvaluationResultOut,
    EvaluationRunDetail,
    EvaluationRunOut,
    EvaluationSampleOut,
)
from app.modules.investigation.schemas import InvestigationModelOutput
from app.services.audit import record_audit

logger = get_logger(__name__)


def _norm(value: str) -> str:
    return " ".join(re.sub(r"[^0-9a-zก-๙]+", " ", (value or "").lower()).split())


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def create_dataset(db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID | None, payload: DatasetCreate) -> DatasetDetail:
    existing = db.scalar(
        select(EvaluationDataset).where(
            EvaluationDataset.org_id == org_id, EvaluationDataset.name == payload.name
        )
    )
    if existing is not None:
        raise BadRequestError("A dataset with this name already exists.", code="dataset_name_taken")
    dataset = EvaluationDataset(
        org_id=org_id,
        name=payload.name,
        description=payload.description,
        version=payload.version,
        is_synthetic=payload.is_synthetic,
        sample_count=len(payload.samples),
        created_by_id=actor_id,
    )
    db.add(dataset)
    db.flush()
    for sample in payload.samples:
        db.add(
            EvaluationSample(
                dataset_id=dataset.id,
                sample_key=sample.sample_key,
                case_context=sample.case_context,
                expected_exception_types=sample.expected_exception_types,
                expected_root_cause=sample.expected_root_cause,
                expected_evidence=sample.expected_evidence,
                expected_recommendations=sample.expected_recommendations,
                notes=sample.notes,
            )
        )
    record_audit(
        db,
        org_id=org_id,
        action="evaluation.dataset_created",
        entity_type="evaluation_dataset",
        entity_id=dataset.id,
        summary=f"Evaluation dataset '{dataset.name}' created with {dataset.sample_count} samples",
        actor_id=actor_id,
    )
    db.flush()
    return dataset_detail(db, dataset)


def list_datasets(db: Session, *, org_id: uuid.UUID) -> list[DatasetOut]:
    rows = db.scalars(
        select(EvaluationDataset)
        .where(EvaluationDataset.org_id == org_id)
        .order_by(EvaluationDataset.created_at.desc())
    ).all()
    return [DatasetOut.model_validate(row) for row in rows]


def get_dataset(db: Session, *, org_id: uuid.UUID, dataset_id: uuid.UUID) -> EvaluationDataset:
    dataset = db.scalar(
        select(EvaluationDataset).where(
            EvaluationDataset.id == dataset_id, EvaluationDataset.org_id == org_id
        )
    )
    if dataset is None:
        raise NotFoundError("Evaluation dataset not found.", code="dataset_not_found")
    return dataset


def dataset_detail(db: Session, dataset: EvaluationDataset) -> DatasetDetail:
    samples = db.scalars(
        select(EvaluationSample)
        .where(EvaluationSample.dataset_id == dataset.id)
        .order_by(EvaluationSample.sample_key)
    ).all()
    return DatasetDetail(
        **DatasetOut.model_validate(dataset).model_dump(),
        samples=[
            EvaluationSampleOut(
                id=sample.id,
                sample_key=sample.sample_key,
                case_context=sample.case_context,
                expected_exception_types=sample.expected_exception_types,
                expected_root_cause=sample.expected_root_cause,
                expected_evidence=sample.expected_evidence,
                expected_recommendations=sample.expected_recommendations,
                notes=sample.notes,
            )
            for sample in samples
        ],
    )


def create_run(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID | None, payload: Any
) -> EvaluationRun:
    from app.config.settings import settings

    dataset = get_dataset(db, org_id=org_id, dataset_id=payload.dataset_id)
    run = EvaluationRun(
        org_id=org_id,
        dataset_id=dataset.id,
        name=payload.name,
        provider=settings.AI_PROVIDER,
        model=settings.AI_MODEL if settings.ai_configured else None,
        prompt_version=payload.prompt_version or INVESTIGATION_PROMPT_VERSION,
        retrieval_config=payload.retrieval_config,
        status=JobStatus.QUEUED,
        sample_total=dataset.sample_count,
        created_by_id=actor_id,
    )
    db.add(run)
    db.flush()
    from app.services.deferred import queue_task_after_commit

    queue_task_after_commit(db, "run_evaluation", {"run_id": str(run.id)}, org_id)
    record_audit(
        db,
        org_id=org_id,
        action="evaluation.run_started",
        entity_type="evaluation_run",
        entity_id=run.id,
        summary=f"Evaluation run '{run.name}' queued",
        actor_id=actor_id,
        after={"dataset_id": str(dataset.id), "prompt_version": run.prompt_version},
    )
    return run


def _score_sample(
    *,
    sample: EvaluationSample,
    predicted: InvestigationModelOutput,
    context_text: str,
) -> dict[str, Any]:
    expected_types = set(sample.expected_exception_types)
    predicted_types = {value.value for value in predicted.exception_types}
    true_positive = len(expected_types & predicted_types)
    precision = true_positive / len(predicted_types) if predicted_types else 0.0
    recall = true_positive / len(expected_types) if expected_types else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    root_cause_score = _similar(sample.expected_root_cause, predicted.root_cause or "") if sample.expected_root_cause else 0.0
    root_cause_correct = root_cause_score >= 0.6

    expected_quotes = [str(item.get("quote", "")) for item in sample.expected_evidence if item.get("quote")]
    predicted_quotes = [item.quote for item in predicted.evidence]
    evidence_hits = 0
    for quote in expected_quotes:
        if any(_similar(quote, predicted_quote) >= 0.55 for predicted_quote in predicted_quotes):
            evidence_hits += 1
    evidence_accuracy = evidence_hits / len(expected_quotes) if expected_quotes else 0.0

    normalized_context = _norm(context_text)
    valid_citations = 0
    for item in predicted.evidence:
        if _norm(item.quote) and _norm(item.quote) in normalized_context:
            valid_citations += 1
    citation_accuracy = valid_citations / len(predicted_quotes) if predicted_quotes else 0.0

    expected_actions = {str(item) for item in sample.expected_recommendations}
    predicted_actions = {item.action_type.value for item in predicted.suggested_resolutions}
    recommendation_acceptance = (
        len(expected_actions & predicted_actions) / len(expected_actions) if expected_actions else 0.0
    )
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "exception_types_correct": true_positive == len(expected_types) and bool(expected_types),
        "root_cause_correct": root_cause_correct,
        "root_cause_similarity": round(root_cause_score, 4),
        "evidence_accuracy": round(evidence_accuracy, 4),
        "citation_accuracy": round(citation_accuracy, 4),
        "recommendation_acceptance": round(recommendation_acceptance, 4),
        "groundedness": round(citation_accuracy, 4),
        "predicted_types": sorted(predicted_types),
        "expected_types": sorted(expected_types),
    }


def evaluate_run(db: Session, run: EvaluationRun) -> EvaluationRun:
    dataset = db.get(EvaluationDataset, run.dataset_id)
    if dataset is None:
        run.status = JobStatus.FAILED
        run.error = "Dataset was deleted."
        run.finished_at = utcnow()
        return run
    provider = build_llm_provider()
    if provider is None:
        run.status = JobStatus.FAILED
        run.error = "No LLM provider is configured; evaluation cannot run."
        run.finished_at = utcnow()
        return run
    samples = db.scalars(
        select(EvaluationSample)
        .where(EvaluationSample.dataset_id == dataset.id)
        .order_by(EvaluationSample.sample_key)
    ).all()
    run.status = JobStatus.RUNNING
    run.started_at = utcnow()
    run.sample_total = len(samples)
    run.sample_completed = 0
    db.flush()

    scores: list[dict[str, Any]] = []
    errors = 0
    latencies: list[int] = []
    total_input = 0
    total_output = 0
    total_cost = Decimal("0")
    for sample in samples:
        existing = db.scalar(
            select(EvaluationResult).where(
                EvaluationResult.run_id == run.id, EvaluationResult.sample_id == sample.id
            )
        )
        if existing is not None:
            continue
        context_json = json.dumps(
            {"task": "investigation", **sample.case_context}, ensure_ascii=False, default=str
        )
        messages = [
            ChatMessage(role="system", content=INVESTIGATION_SYSTEM),
            ChatMessage(
                role="user",
                content=(
                    INVESTIGATION_INSTRUCTIONS.replace(
                        "{allowed_actions}",
                        ", ".join(
                            ["REQUEST_VENDOR_CONFIRMATION", "REQUEST_MISSING_DOCUMENTS", "ESCALATE_CASE", "NOTIFY_TEAM"]
                        ),
                    )
                    + "\n\n<context_json>\n"
                    + context_json
                    + "\n</context_json>"
                ),
            ),
        ]
        try:
            parsed, result, _attempts = run_coroutine_safely(
                structured_completion(
                    provider=provider,
                    messages=messages,
                    schema=InvestigationModelOutput,
                    schema_json=InvestigationModelOutput.model_json_schema(),
                )
            )
            sample_scores = _score_sample(
                sample=sample, predicted=parsed, context_text=context_json
            )
            scores.append(sample_scores)
            latencies.append(result.latency_ms)
            total_input += result.input_tokens
            total_output += result.output_tokens
            total_cost += calculate_cost(result.input_tokens, result.output_tokens)
            db.add(
                EvaluationResult(
                    run_id=run.id,
                    sample_id=sample.id,
                    predicted=parsed.model_dump(mode="json"),
                    expected={
                        "exception_types": sample.expected_exception_types,
                        "root_cause": sample.expected_root_cause,
                        "evidence": sample.expected_evidence,
                        "recommendations": sample.expected_recommendations,
                    },
                    scores=sample_scores,
                    latency_ms=result.latency_ms,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_usd=calculate_cost(result.input_tokens, result.output_tokens),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one bad sample must not kill the run
            errors += 1
            logger.warning("evaluation_sample_failed", run_id=str(run.id), sample=sample.sample_key, error=str(exc))
            db.add(
                EvaluationResult(
                    run_id=run.id,
                    sample_id=sample.id,
                    predicted={},
                    expected={"exception_types": sample.expected_exception_types},
                    scores={},
                    error=str(exc)[:2000],
                )
            )
        run.sample_completed += 1
        db.flush()

    successful = len(scores)
    metrics: dict[str, Any] = {
        "samples": successful,
        "errors": errors,
        "deterministic_stub": provider.name == "stub",
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": run.prompt_version,
    }
    if successful:
        def mean(key: str) -> float:
            return round(sum(float(score[key]) for score in scores) / successful, 4)

        true_positives = 0
        false_positives = 0
        false_negatives = 0
        for score in scores:
            expected = set(score["expected_types"])
            predicted = set(score["predicted_types"])
            true_positives += len(expected & predicted)
            false_positives += len(predicted - expected)
            false_negatives += len(expected - predicted)
        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else 0.0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        metrics.update(
            {
                "exception_classification_accuracy": round(
                    sum(1 for score in scores if score["exception_types_correct"]) / successful, 4
                ),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "root_cause_accuracy": round(
                    sum(1 for score in scores if score["root_cause_correct"]) / successful, 4
                ),
                "evidence_accuracy": mean("evidence_accuracy"),
                "citation_accuracy": mean("citation_accuracy"),
                "groundedness": mean("groundedness"),
                "recommendation_acceptance": mean("recommendation_acceptance"),
                "latency_ms_avg": round(sum(latencies) / len(latencies), 1) if latencies else 0,
                "tokens_total": total_input + total_output,
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cost_usd_total": float(total_cost),
            }
        )
    run.metrics = metrics
    run.status = JobStatus.FAILED if successful == 0 and errors else JobStatus.SUCCEEDED
    if run.status == JobStatus.FAILED:
        run.error = "Every sample failed; see per-sample errors."
    run.finished_at = utcnow()
    record_usage(
        db,
        org_id=run.org_id,
        user_id=run.created_by_id,
        purpose="evaluation_run",
        provider=provider.name,
        model=provider.model,
        prompt_version=run.prompt_version,
        input_tokens=total_input,
        output_tokens=total_output,
        latency_ms=int(metrics.get("latency_ms_avg", 0) or 0),
        status="SUCCEEDED" if successful else "FAILED",
        error=run.error,
    )
    record_audit(
        db,
        org_id=run.org_id,
        action="evaluation.run_completed",
        entity_type="evaluation_run",
        entity_id=run.id,
        summary=f"Evaluation run '{run.name}' finished with {successful}/{len(samples)} samples",
        actor_id=run.created_by_id,
        after={"metrics": metrics},
    )
    return run


def run_evaluation_job(run_id: uuid.UUID, org_id: uuid.UUID) -> dict[str, Any]:
    from app.db.session import session_scope

    with session_scope() as db:
        run = db.scalar(
            select(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.org_id == org_id)
        )
        if run is None:
            return {"status": "skipped", "reason": "run_not_found"}
        if run.status == JobStatus.SUCCEEDED:
            return {"status": "skipped", "reason": "already_completed"}
        evaluate_run(db, run)
        return {"status": run.status.value, "run_id": str(run.id), "metrics": run.metrics}


def run_out(db: Session, run: EvaluationRun) -> EvaluationRunOut:
    dataset = db.get(EvaluationDataset, run.dataset_id)
    return EvaluationRunOut(
        id=run.id,
        dataset_id=run.dataset_id,
        dataset_name=dataset.name if dataset else None,
        name=run.name,
        provider=run.provider,
        model=run.model,
        prompt_version=run.prompt_version,
        retrieval_config=run.retrieval_config or {},
        status=run.status,
        metrics=run.metrics or {},
        sample_total=run.sample_total,
        sample_completed=run.sample_completed,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


def run_detail(db: Session, run: EvaluationRun) -> EvaluationRunDetail:
    rows = db.execute(
        select(EvaluationResult, EvaluationSample)
        .join(EvaluationSample, EvaluationSample.id == EvaluationResult.sample_id)
        .where(EvaluationResult.run_id == run.id)
        .order_by(EvaluationSample.sample_key)
    ).all()
    base = run_out(db, run)
    return EvaluationRunDetail(
        **base.model_dump(),
        results=[
            EvaluationResultOut(
                id=result.id,
                sample_key=sample.sample_key,
                predicted=result.predicted or {},
                expected=result.expected or {},
                scores=result.scores or {},
                latency_ms=result.latency_ms,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=float(result.cost_usd) if result.cost_usd is not None else None,
                error=result.error,
            )
            for result, sample in rows
        ],
    )


def list_runs(
    db: Session, *, org_id: uuid.UUID, pagination: Pagination, dataset_id: uuid.UUID | None = None
) -> tuple[list[EvaluationRunOut], int]:
    stmt = select(EvaluationRun).where(EvaluationRun.org_id == org_id)
    if dataset_id:
        stmt = stmt.where(EvaluationRun.dataset_id == dataset_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(EvaluationRun.created_at.desc()).offset(pagination.offset).limit(pagination.page_size)
    ).all()
    return [run_out(db, row) for row in rows], total


def get_run(db: Session, *, org_id: uuid.UUID, run_id: uuid.UUID) -> EvaluationRun:
    run = db.scalar(
        select(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.org_id == org_id)
    )
    if run is None:
        raise NotFoundError("Evaluation run not found.", code="run_not_found")
    return run


def compare_runs(db: Session, *, org_id: uuid.UUID, run_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
    runs = db.scalars(
        select(EvaluationRun).where(EvaluationRun.org_id == org_id, EvaluationRun.id.in_(run_ids))
    ).all()
    return [
        {
            "run_id": str(run.id),
            "name": run.name,
            "provider": run.provider,
            "model": run.model,
            "prompt_version": run.prompt_version,
            "status": run.status.value,
            "metrics": run.metrics or {},
            "created_at": run.created_at.isoformat() if run.created_at else None,
        }
        for run in runs
    ]
