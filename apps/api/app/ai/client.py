"""Structured completion helper: bounded retries, timeouts, JSON extraction, schema validation."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.ai.base import ChatMessage, LLMProvider, LLMResult, ProviderError
from app.config.settings import settings
from app.core.errors import AIOutputError, AIUnavailableError
from app.core.logging import get_logger
from app.models.ai import AIUsageEvent

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass(slots=True)
class CompletionOutcome:
    parsed: BaseModel
    result: LLMResult
    attempts: int
    cost_usd: Decimal


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = _FENCE_RE.sub("", text).strip()
    try:
        value = json.loads(cleaned)
        if not isinstance(value, dict):
            raise ValueError("root value is not an object")
        return value
    except (json.JSONDecodeError, ValueError):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise AIOutputError("AI output did not contain a JSON object.", code="ai_invalid_json") from None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AIOutputError(
                "AI output was not valid JSON.", code="ai_invalid_json", details=str(exc)[:300]
            ) from exc
        if not isinstance(value, dict):
            raise AIOutputError("AI output was not a JSON object.", code="ai_invalid_json")
        return value


def calculate_cost(input_tokens: int, output_tokens: int) -> Decimal:
    input_cost = Decimal(str(settings.AI_INPUT_COST_PER_1K)) * Decimal(input_tokens) / Decimal(1000)
    output_cost = Decimal(str(settings.AI_OUTPUT_COST_PER_1K)) * Decimal(output_tokens) / Decimal(1000)
    return (input_cost + output_cost).quantize(Decimal("0.000001"))


def record_usage(
    db: Session,
    *,
    org_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    purpose: str,
    provider: str,
    model: str | None,
    prompt_version: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int | None = None,
    status: str = "SUCCEEDED",
    error: str | None = None,
) -> AIUsageEvent:
    event = AIUsageEvent(
        org_id=org_id,
        user_id=user_id,
        purpose=purpose,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=calculate_cost(input_tokens, output_tokens),
        latency_ms=latency_ms,
        status=status,
        error=(error or "")[:400] or None,
    )
    db.add(event)
    return event


async def structured_completion(
    *,
    provider: LLMProvider,
    messages: list[ChatMessage],
    schema: type[T],
    schema_json: dict[str, Any] | None = None,
    max_attempts: int | None = None,
    timeout: float | None = None,
    temperature: float | None = None,
) -> tuple[T, LLMResult, int]:
    """Call the provider and validate its JSON against a Pydantic schema.

    Retries cover transport failures, invalid JSON and schema violations. Each retry adds a
    repair instruction describing the validation error. The number of attempts is bounded.
    """
    attempts_limit = max(1, (max_attempts if max_attempts is not None else settings.AI_MAX_RETRIES + 1))
    timeout_s = timeout or settings.AI_TIMEOUT_SECONDS
    working_messages = list(messages)
    last_error: Exception | None = None

    for attempt in range(1, attempts_limit + 1):
        try:
            result = await asyncio.wait_for(
                provider.complete(
                    working_messages,
                    temperature=settings.AI_TEMPERATURE if temperature is None else temperature,
                    max_tokens=settings.AI_MAX_OUTPUT_TOKENS,
                    json_mode=True,
                    schema=schema_json,
                    timeout=timeout_s,
                ),
                timeout=timeout_s + 5,
            )
        except ProviderError as exc:
            last_error = exc
            logger.warning("ai_provider_error", attempt=attempt, retryable=exc.retryable, error=str(exc))
            if not exc.retryable or attempt == attempts_limit:
                raise AIUnavailableError(str(exc), details={"attempts": attempt}) from exc
            await asyncio.sleep(min(2 ** (attempt - 1) * 0.5, 4.0))
            continue
        except TimeoutError as exc:
            last_error = exc
            if attempt == attempts_limit:
                raise AIUnavailableError("AI provider call exceeded the configured timeout.") from exc
            await asyncio.sleep(0.5)
            continue

        try:
            payload = extract_json_object(result.content)
            parsed = schema.model_validate(payload)
            return parsed, result, attempt
        except (AIOutputError, ValidationError) as exc:
            last_error = exc
            detail = str(exc)[:400]
            logger.warning("ai_output_invalid", attempt=attempt, error=detail)
            working_messages = [
                *messages,
                ChatMessage(role="assistant", content=result.content[:4000]),
                ChatMessage(
                    role="user",
                    content=(
                        "Your previous response could not be accepted. Reason: "
                        f"{detail}\nReturn only a corrected JSON object that conforms to the schema."
                    ),
                ),
            ]

    raise AIOutputError(
        "The AI provider did not return a valid structured response within the retry budget.",
        details={"last_error": str(last_error)[:300] if last_error else None},
    )


def run_coroutine_safely(coro):  # type: ignore[no-untyped-def]
    """Run an async AI pipeline from sync code (Celery task, CLI, tests)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # A loop is already running in this thread; execute in a dedicated loop thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
