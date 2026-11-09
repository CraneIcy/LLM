"""Structured error model for the Pet Hospital MCP service.

Every tool failure surfaces to the MCP client as a single unified shape:

    {
        "error": {
            "code": "ERROR_CODE",
            "message": "Human readable message",
            "details": { ... }
        }
    }

Error codes are stable strings (not Python exception class names) so the
MCP client never sees HTTPX, Pydantic or Python stack internals.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

VALIDATION_ERROR = "VALIDATION_ERROR"
BACKEND_TIMEOUT = "BACKEND_TIMEOUT"
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
BACKEND_API_ERROR = "BACKEND_API_ERROR"
BACKEND_INVALID_RESPONSE = "BACKEND_INVALID_RESPONSE"
INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorPayload(BaseModel):
    """Inner payload of the unified error envelope."""

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable error description.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured details about the failure.",
    )


class ErrorEnvelope(BaseModel):
    """Top-level error envelope returned by every failed tool call."""

    error: ErrorPayload

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for MCP tool output."""

        return self.model_dump(mode="json")


def build_error(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> ErrorEnvelope:
    """Construct an ErrorEnvelope from primitives."""

    return ErrorEnvelope(
        error=ErrorPayload(
            code=code,
            message=message,
            details=details or {},
        )
    )


class PetHospitalError(Exception):
    """Domain error carrying a structured ErrorEnvelope.

    Raising this from inside a tool causes the tool to surface the envelope
    to the MCP client. The message is derived from the envelope so logs
    remain readable.
    """

    def __init__(self, envelope: ErrorEnvelope) -> None:
        self.envelope = envelope
        super().__init__(envelope.error.message)
