"""MCPServer assembly for the Pet Hospital MCP service.

Uses the official Python SDK 2.x ``MCPServer`` with the stateless
Streamable HTTP transport. No FastMCP, no ``initialize``, no
``Mcp-Session-Id``, no session storage.

The module exposes:
    * ``mcp`` – the ``MCPServer`` instance with the ``list_pets`` tool
      registered.
    * ``rest_client`` – the ``PetHospitalRESTClient`` bound to the
      configured Go backend.
    * ``app`` – a Starlette ASGI application that mounts the MCP endpoint
      at ``/mcp`` and a ``/health`` endpoint next to it.
"""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount

from mcp.server import MCPServer

from .config import Settings, load_settings
from .logging_config import configure_logging, get_logger
from .rest_client import PetHospitalRESTClient
from .tools import list_pets

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

settings: Settings = load_settings()
configure_logging()

mcp = MCPServer("pet-hospital-mcp")
rest_client = PetHospitalRESTClient(settings)

# Register the single tool for this phase.
list_pets.register(mcp, rest_client)


# ---------------------------------------------------------------------------
# Custom HTTP routes
# ---------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    """Health check endpoint.

    Returns 200 with a JSON body describing MCP and upstream status.
    The upstream reachability is best-effort: a failure is reported as
    ``"upstream": "unavailable"`` but the HTTP status stays 200 so
    orchestrators do not kill the pod before it can be debugged.
    """

    upstream_data: dict[str, Any]
    try:
        upstream_data = await rest_client.health()
        upstream_status = "ok" if upstream_data else "unknown"
    except Exception:  # pragma: no cover - defensive
        upstream_data = {}
        upstream_status = "unavailable"

    body = {
        "status": "ok",
        "service": "pet-hospital-mcp",
        "mcp_sdk_version": "2.0.0",
        "mcp_protocol_version": "2026-07-28",
        "transport": "streamable-http",
        "endpoint": "/mcp",
        "upstream": upstream_status,
        "upstream_base_url": settings.pet_hospital_base_url,
    }
    return JSONResponse(body)


# ---------------------------------------------------------------------------
# ASGI app (used by uvicorn and tests)
# ---------------------------------------------------------------------------


def create_app() -> Any:
    """Build the ASGI application.

    ``mcp.streamable_http_app()`` returns a Starlette app with the
    ``/mcp`` route and the ``/health`` custom route. We return it
    directly so uvicorn can serve it.

    ``stateless_http=True`` disables session management: no
    ``Mcp-Session-Id`` header, no ``initialize`` handshake, no
    server-side session storage. Each request is self-contained.
    """

    return mcp.streamable_http_app(stateless_http=True)


app = create_app()
