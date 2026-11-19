"""Task registry shared by Celery workers and the inline development runner."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.errors import AppError

TaskPayload = dict[str, Any]
TaskResult = dict[str, Any]
TaskHandler = Callable[[TaskPayload, uuid.UUID], TaskResult]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    name: str
    handler: TaskHandler
    description: str = ""
    timeout_seconds: int = 900
    max_attempts: int = 3


_REGISTRY: dict[str, TaskSpec] = {}


def register_task(
    name: str, *, description: str = "", timeout_seconds: int = 900, max_attempts: int = 3
) -> Callable[[TaskHandler], TaskHandler]:
    def _decorator(handler: TaskHandler) -> TaskHandler:
        if name in _REGISTRY:
            raise RuntimeError(f"Task '{name}' is already registered.")
        _REGISTRY[name] = TaskSpec(
            name=name,
            handler=handler,
            description=description,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        return handler

    return _decorator


def get_task(name: str) -> TaskSpec:
    _ensure_loaded()
    spec = _REGISTRY.get(name)
    if spec is None:
        raise AppError(f"Unknown background task '{name}'.", code="unknown_task", status_code=500)
    return spec


def registered_tasks() -> list[TaskSpec]:
    _ensure_loaded()
    return sorted(_REGISTRY.values(), key=lambda spec: spec.name)


def _ensure_loaded() -> None:
    if not _REGISTRY:
        import app.workers.tasks  # noqa: F401  (registers task handlers)
