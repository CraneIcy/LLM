"""Configuration for the Pet Hospital MCP service.

All settings are read from environment variables with sensible defaults.
The MCP service only listens on 127.0.0.1 by default and must remain
configurable for teaching scenarios.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Immutable service configuration.

    Attributes:
        mcp_host: Bind address for the MCP HTTP server. Default 127.0.0.1.
        mcp_port: Port for the MCP HTTP server. Default 8000.
        pet_hospital_base_url: Base URL of the upstream Go REST API.
            Default http://127.0.0.1:8080.
        backend_timeout_seconds: Per-request timeout when calling the Go API.
        backend_max_retries: Maximum number of retry attempts for transient
            backend failures.
        backend_retry_backoff_seconds: Base delay between retries (exponential
            backoff multiplier).
    """

    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000
    pet_hospital_base_url: str = "http://127.0.0.1:8080"
    backend_timeout_seconds: float = 10.0
    backend_max_retries: int = 2
    backend_retry_backoff_seconds: float = 0.5


def load_settings() -> Settings:
    """Build a Settings instance from the current environment.

    Reads MCP_HOST, MCP_PORT and PET_HOSPITAL_BASE_URL. Unknown keys are
    ignored. Values must parse to the correct type or the default is kept.
    """

    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = _parse_int(os.getenv("MCP_PORT"), 8000)
    base_url = os.getenv("PET_HOSPITAL_BASE_URL", "http://127.0.0.1:8080")
    timeout = _parse_float(os.getenv("BACKEND_TIMEOUT_SECONDS"), 10.0)
    retries = _parse_int(os.getenv("BACKEND_MAX_RETRIES"), 2)
    backoff = _parse_float(os.getenv("BACKEND_RETRY_BACKOFF_SECONDS"), 0.5)

    return Settings(
        mcp_host=host,
        mcp_port=port,
        pet_hospital_base_url=base_url.rstrip("/"),
        backend_timeout_seconds=timeout,
        backend_max_retries=max(0, retries),
        backend_retry_backoff_seconds=max(0.0, backoff),
    )


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_float(raw: str | None, default: float) -> float:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default
