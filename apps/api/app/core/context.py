"""Per-request context propagated to logs and audit records."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
org_id_var: ContextVar[str | None] = ContextVar("org_id", default=None)
http_context_var: ContextVar[RequestContext | None] = ContextVar("http_context", default=None)


@dataclass(slots=True)
class RequestContext:
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    correlation_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    path: str | None = None
    method: str | None = None


def current_request_id() -> str | None:
    return request_id_var.get()


def bind_identity(user_id: uuid.UUID | None, org_id: uuid.UUID | None) -> None:
    user_id_var.set(str(user_id) if user_id else None)
    org_id_var.set(str(org_id) if org_id else None)


def clear_identity() -> None:
    user_id_var.set(None)
    org_id_var.set(None)


def get_http_context() -> RequestContext | None:
    return http_context_var.get()
