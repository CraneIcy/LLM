"""Structured logging for the Pet Hospital MCP service.

Uses structlog to emit JSON lines containing at least:
    timestamp, tool_name, params, status, duration_ms.

Sensitive fields (ownerPhone, ownerAddr, chipNo and their snake_case
variants) are recursively redacted from log payloads so logs never carry
complete personal data.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Iterable

import structlog

# Field names (lowercased) that must be redacted from any logged dict.
SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "ownerphone",
        "owner_phone",
        "owneraddr",
        "owner_addr",
        "chipno",
        "chip_no",
    }
)

REDACTED_PLACEHOLDER: str = "***REDACTED***"


def redact(value: Any) -> Any:
    """Recursively replace sensitive fields in nested structures.

    Lists, tuples and mappings are walked depth-first. Scalars are returned
    untouched. Strings that look like a phone number (>=7 digits) are masked
    when they appear as the value of a sensitive key.
    """

    if isinstance(value, Mapping):
        return {key: _redact_pair(key, val) for key, val in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def _redact_pair(key: Any, value: Any) -> Any:
    if isinstance(key, str) and key.lower() in SENSITIVE_FIELDS:
        return REDACTED_PLACEHOLDER
    return redact(value)


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog with JSON rendering and stdlib integration."""

    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        stream=None,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _redact_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that redacts sensitive keys recursively."""

    return redact(event_dict)  # type: ignore[return-value]


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger; configure_logging must have been called."""

    return structlog.get_logger(name)  # type: ignore[no-any-return]


def build_tool_log_entry(
    tool_name: str,
    params: Mapping[str, Any],
    status: str,
    duration_ms: float,
    **extra: Any,
) -> dict[str, Any]:
    """Build a structured log entry for a tool invocation.

    The returned dict includes an ``event`` key so it can be unpacked
    directly into ``logger.info(**entry)`` — structlog requires ``event``
    as the first positional argument.
    """

    entry: dict[str, Any] = {
        "event": "tool_call",
        "tool_name": tool_name,
        "params": redact(dict(params)),
        "status": status,
        "duration_ms": round(duration_ms, 3),
    }
    entry.update(extra)
    return entry
