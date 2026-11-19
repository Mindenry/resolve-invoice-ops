"""Typed application errors and a single, consistent API error envelope."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, client-facing application errors."""

    status_code = 400
    code = "bad_request"
    message = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details
        super().__init__(self.message)

    def to_dict(self, request_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details is not None:
            payload["details"] = self.details
        if request_id:
            payload["request_id"] = request_id
        return {"error": payload}


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"
    message = "The request is invalid."


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Authentication is required."


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state of the resource."


class UnprocessableError(AppError):
    status_code = 422
    code = "unprocessable"
    message = "The request could not be processed."


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please retry later."


class AIUnavailableError(AppError):
    status_code = 503
    code = "ai_unavailable"
    message = "AI capabilities are unavailable because no provider is configured or the provider failed."


class AIOutputError(AppError):
    status_code = 502
    code = "ai_invalid_output"
    message = "The AI provider returned output that did not satisfy the required schema."


class IntegrationError(AppError):
    status_code = 502
    code = "integration_error"
    message = "The external integration failed."


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "A required dependency is unavailable. Please retry later."


class StorageError(AppError):
    status_code = 500
    code = "storage_error"
    message = "The document storage backend failed."


class ConfigurationError(AppError):
    status_code = 500
    code = "configuration_error"
    message = "The server is missing required configuration."
