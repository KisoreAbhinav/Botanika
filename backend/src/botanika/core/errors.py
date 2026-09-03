"""Application-level errors and the stable problem-detail response schema."""

from __future__ import annotations

from dataclasses import dataclass


class BotanikaError(Exception):
    """Base error for expected application failures with a machine code."""

    code = "internal_error"
    http_status = 500

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class CapabilityUnavailableError(BotanikaError):
    """A requested operation needs a capability that is currently unavailable."""

    code = "capability_unavailable"
    http_status = 503


class ValidationError(BotanikaError):
    """A request was well-formed but semantically invalid."""

    code = "invalid_request"
    http_status = 422


class NotFoundError(BotanikaError):
    """A requested resource does not exist."""

    code = "not_found"
    http_status = 404


@dataclass(frozen=True, slots=True)
class ProblemDetail:
    """Compact RFC-7807-style error body served by the API error handlers."""

    type: str
    title: str
    status: int
    detail: str | None = None
    code: str = "internal_error"
    request_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "code": self.code,
            "request_id": self.request_id,
        }