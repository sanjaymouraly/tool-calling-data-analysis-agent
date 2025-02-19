"""Application error hierarchy.

Every failure surfaced to the API or to the agent loop is expressed as an
``AppError`` so that the HTTP layer can render a stable, machine readable
payload and the agent can decide whether the failure is recoverable.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all expected application errors."""

    status_code: int = 400
    code: str = "app_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class PermissionError_(AppError):
    status_code = 403
    code = "forbidden"


class ResourceLimitError(AppError):
    status_code = 413
    code = "resource_limit"


class SecurityError(AppError):
    """Raised when a request violates the restricted-tool security model."""

    status_code = 403
    code = "security_violation"


class ToolExecutionError(AppError):
    status_code = 422
    code = "tool_error"


class ProviderError(AppError):
    status_code = 502
    code = "provider_error"


class BudgetExceededError(AppError):
    status_code = 429
    code = "budget_exceeded"
