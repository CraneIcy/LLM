"""HTTP client for the upstream Go Pet Hospital REST API.

The client is the single boundary between the MCP service and the Go
backend. It owns timeout and retry policy and converts low-level httpx
failures into the structured ErrorEnvelope used by tools.

Design notes:
    * Stateless: each call builds its own request; no session cookies,
      no Mcp-Session-Id, no initialize handshake.
    * Only the GET /api/v1/pets endpoint is supported in this phase.
    * Transient failures (connect errors, read timeouts, 5xx) are retried
      with exponential backoff up to backend_max_retries.
    * 4xx responses are not retried; they surface as BACKEND_API_ERROR.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from .config import Settings
from .errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    INTERNAL_ERROR,
    build_error,
)

# HTTP status codes considered transient (retryable).
_RETRYABLE_STATUS: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})


class PetHospitalRESTClient:
    """Thin async wrapper around httpx.AsyncClient targeting the Go API."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def base_url(self) -> str:
        return self._settings.pet_hospital_base_url

    async def list_pets(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Call GET /api/v1/pets and return the parsed `data` object.

        Args:
            params: Already-validated query parameters. Empty values are
                dropped before sending so the Go backend applies its own
                defaults.

        Returns:
            The decoded `data` field of the Go response envelope.

        Raises:
            PetHospitalError: On any upstream failure, timeout, or invalid
                response. The envelope is populated with the proper code.
        """

        query = {key: value for key, value in params.items() if value is not None}
        path = "/api/v1/pets"

        return await self._get_with_retry(path, query)

    async def _get_with_retry(
        self,
        path: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        last_error_envelope = None
        for attempt in range(self._settings.backend_max_retries + 1):
            try:
                return await self._get_once(path, params)
            except _TransientBackendError as exc:
                last_error_envelope = exc.envelope
                if attempt < self._settings.backend_max_retries:
                    delay = self._settings.backend_retry_backoff_seconds * (
                        2 ** attempt
                    )
                    await asyncio.sleep(delay)
                    continue
                raise PetHospitalErrorEnvelope(last_error_envelope)  # type: ignore[arg-type]
            except _FinalBackendError as exc:
                raise PetHospitalErrorEnvelope(exc.envelope) from None
            except httpx.TimeoutException as exc:
                envelope = build_error(
                    BACKEND_TIMEOUT,
                    f"Backend timed out calling {path}: {exc.__class__.__name__}",
                    {"path": path, "attempt": attempt + 1},
                )
                if attempt < self._settings.backend_max_retries:
                    delay = self._settings.backend_retry_backoff_seconds * (
                        2 ** attempt
                    )
                    await asyncio.sleep(delay)
                    continue
                raise PetHospitalErrorEnvelope(envelope) from None
            except httpx.ConnectError as exc:
                envelope = build_error(
                    BACKEND_UNAVAILABLE,
                    f"Cannot reach backend at {self.base_url}: {exc.__class__.__name__}",
                    {"base_url": self.base_url, "attempt": attempt + 1},
                )
                if attempt < self._settings.backend_max_retries:
                    delay = self._settings.backend_retry_backoff_seconds * (
                        2 ** attempt
                    )
                    await asyncio.sleep(delay)
                    continue
                raise PetHospitalErrorEnvelope(envelope) from None
            except httpx.HTTPError as exc:
                envelope = build_error(
                    INTERNAL_ERROR,
                    f"Unexpected HTTP transport error: {exc.__class__.__name__}",
                    {"path": path},
                )
                raise PetHospitalErrorEnvelope(envelope) from None
            except Exception as exc:  # pragma: no cover - defensive
                envelope = build_error(
                    INTERNAL_ERROR,
                    f"Unexpected failure in REST client: {exc.__class__.__name__}",
                    {"path": path},
                )
                raise PetHospitalErrorEnvelope(envelope) from None

        # Should be unreachable; backstop.
        envelope = build_error(
            INTERNAL_ERROR,
            "Retry loop exhausted without resolution",
            {"path": path},
        )
        raise PetHospitalErrorEnvelope(envelope)

    async def _get_once(
        self,
        path: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(self._settings.backend_timeout_seconds)
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=self._transport,
        ) as client:
            try:
                response = await client.get(path, params=params)
            except httpx.TimeoutException:
                raise
            except httpx.ConnectError:
                raise
            except httpx.HTTPError as exc:
                raise _FinalBackendError(
                    build_error(
                        INTERNAL_ERROR,
                        f"HTTP transport error: {exc.__class__.__name__}",
                        {"path": path},
                    )
                )

        if response.status_code in _RETRYABLE_STATUS:
            raise _TransientBackendError(
                build_error(
                    BACKEND_API_ERROR,
                    f"Backend returned HTTP {response.status_code}",
                    {
                        "status": response.status_code,
                        "path": path,
                        "body_preview": _safe_body_preview(response),
                    },
                )
            )

        if response.status_code >= 400:
            raise _FinalBackendError(
                build_error(
                    BACKEND_API_ERROR,
                    f"Backend returned HTTP {response.status_code}",
                    {
                        "status": response.status_code,
                        "path": path,
                        "body_preview": _safe_body_preview(response),
                    },
                )
            )

        try:
            payload = response.json()
        except Exception as exc:
            raise _FinalBackendError(
                build_error(
                    BACKEND_INVALID_RESPONSE,
                    "Backend returned non-JSON response",
                    {
                        "path": path,
                        "parse_error": exc.__class__.__name__,
                        "body_preview": _safe_body_preview(response),
                    },
                )
            )

        return _extract_data(payload, path)

    async def health(self) -> dict[str, Any]:
        """Probe the Go backend /health endpoint.

        Used internally by the MCP /health route when it wants to report
        upstream reachability. Failures return an empty dict so the MCP
        /health endpoint can format the message itself.
        """

        timeout = httpx.Timeout(self._settings.backend_timeout_seconds)
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout,
                transport=self._transport,
            ) as client:
                response = await client.get("/health")
                if response.status_code == 200:
                    try:
                        return response.json().get("data", {})
                    except Exception:
                        return {}
                return {}
        except Exception:
            return {}


def _extract_data(payload: Any, path: str) -> dict[str, Any]:
    """Pull the `data` object out of the Go response envelope.

    The Go API wraps responses as ``{"code": int, "message": str, "data": ...}``.
    The `data` for GET /api/v1/pets is always a JSON object with the
    pagination/totalCost fields. We defensively coerce dict-like payloads.
    """

    if not isinstance(payload, dict):
        raise _FinalBackendError(
            build_error(
                BACKEND_INVALID_RESPONSE,
                "Backend response was not a JSON object",
                {"path": path, "payload_type": type(payload).__name__},
            )
        )

    data = payload.get("data")
    if data is None:
        # Treat a missing data field as an empty success payload.
        return {}

    if not isinstance(data, dict):
        raise _FinalBackendError(
            build_error(
                BACKEND_INVALID_RESPONSE,
                "Backend response `data` was not a JSON object",
                {"path": path, "data_type": type(data).__name__},
            )
        )

    return data


def _safe_body_preview(response: httpx.Response, *, max_chars: int = 200) -> str:
    """Return a short, sanitized preview of the response body for logs."""

    try:
        text = response.text
    except Exception:
        return "<unreadable>"
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


class _TransientBackendError(Exception):
    """Internal sentinel: retryable backend failure."""

    def __init__(self, envelope: Any) -> None:
        self.envelope = envelope
        super().__init__()


class _FinalBackendError(Exception):
    """Internal sentinel: non-retryable backend failure."""

    def __init__(self, envelope: Any) -> None:
        self.envelope = envelope
        super().__init__()


class PetHospitalErrorEnvelope(Exception):
    """Public exception carrying an ErrorEnvelope out of the REST client.

    Tools catch this to surface the envelope to the MCP client.
    """

    def __init__(self, envelope: Any) -> None:
        self.envelope = envelope
        super().__init__(_envelope_message(envelope))


def _envelope_message(envelope: Any) -> str:
    message = getattr(envelope, "error", None)
    if message is not None:
        inner = getattr(message, "message", None)
        if isinstance(inner, str):
            return inner
    if isinstance(envelope, dict):
        inner = envelope.get("error")
        if isinstance(inner, dict):
            msg = inner.get("message")
            if isinstance(msg, str):
                return msg
    return "Pet Hospital backend error"
