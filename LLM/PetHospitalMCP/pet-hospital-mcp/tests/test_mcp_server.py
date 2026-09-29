"""MCP server-level tests.

Covers:
    * Tool registration: name, description, JSON schema.
    * /health endpoint returns 200 with service metadata.
    * SDK 2.x in-process client can discover and call ``list_pets``.
    * Backend failures surface as the unified error envelope through the
      MCP tool result.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.rest_client import PetHospitalRESTClient
from pet_hospital_mcp.server import mcp as default_mcp
from pet_hospital_mcp.tools import list_pets
from tests.conftest import build_go_response, sample_list_response


def _build_isolated_server(
    handler: Any,
) -> tuple[Any, PetHospitalRESTClient]:
    """Build an isolated MCPServer + REST client with a mock transport."""

    from mcp.server import MCPServer

    settings = Settings(
        mcp_host="127.0.0.1",
        mcp_port=8000,
        pet_hospital_base_url="http://127.0.0.1:8080",
        backend_timeout_seconds=2.0,
        backend_max_retries=0,
        backend_retry_backoff_seconds=0.0,
    )
    transport = httpx.MockTransport(handler)
    rest_client = PetHospitalRESTClient(settings, transport=transport)
    server = MCPServer("pet-hospital-mcp-test")
    list_pets.register(server, rest_client)
    return server, rest_client


class TestToolRegistration:
    def test_tool_name_is_snake_case(self) -> None:
        tool_names = {t.name for t in default_mcp._tool_manager.list_tools()}
        assert "list_pets" in tool_names

    def test_tool_description_documents_params_and_returns(self) -> None:
        tool = default_mcp._tool_manager.get_tool("list_pets")
        desc = tool.description
        assert "GET /api/v1/pets" in desc
        assert "species" in desc
        assert "status" in desc
        assert "page" in desc
        assert "page_size" in desc
        assert "items" in desc
        assert "total" in desc

    def test_tool_input_schema_has_required_fields(self) -> None:
        tool = default_mcp._tool_manager.get_tool("list_pets")
        schema = tool.parameters
        assert "properties" in schema
        props = schema["properties"]
        for field in (
            "q",
            "name",
            "owner_name",
            "owner_phone",
            "species",
            "doctor",
            "disease",
            "status",
            "min",
            "max",
            "sort_by",
            "order",
            "page",
            "page_size",
        ):
            assert field in props, f"missing field {field} in schema"

    def test_tool_input_schema_has_defaults(self) -> None:
        tool = default_mcp._tool_manager.get_tool("list_pets")
        schema = tool.parameters
        props = schema["properties"]
        assert "default" in props["page"]
        assert props["page"]["default"] == 1
        assert "default" in props["page_size"]
        assert props["page_size"]["default"] == 20


class TestHealthEndpoint:
    def test_health_returns_200_with_metadata(self) -> None:
        app = default_mcp.streamable_http_app(stateless_http=True)
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["service"] == "pet-hospital-mcp"
        assert body["mcp_sdk_version"] == "2.0.0"
        assert body["mcp_protocol_version"] == "2026-07-28"
        assert body["transport"] == "streamable-http"
        assert body["endpoint"] == "/mcp"


class TestInProcessMCPClient:
    """Use the SDK 2.x in-memory Client to exercise discovery and calls."""

    @pytest.mark.asyncio
    async def test_discover_lists_list_pets_tool(self) -> None:
        from mcp import Client

        def handler(request: httpx.Request) -> httpx.Response:
            return build_go_response(sample_list_response())

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            tools_result = await c.list_tools()
            names = [t.name for t in tools_result.tools]
            assert "list_pets" in names

    @pytest.mark.asyncio
    async def test_call_list_pets_returns_structured_content(self) -> None:
        from mcp import Client

        def handler(request: httpx.Request) -> httpx.Response:
            return build_go_response(sample_list_response())

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool(
                "list_pets",
                {"page": 1, "page_size": 10, "species": "犬"},
            )
            assert result.is_error is False
            structured = result.structured_content
            assert structured is not None
            assert "items" in structured
            assert structured["total"] == 1
            assert structured["pageSize"] == 20
            assert structured["totalCost"] == 120.5

    @pytest.mark.asyncio
    async def test_call_list_pets_with_all_params(self) -> None:
        from mcp import Client

        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return build_go_response(sample_list_response())

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool(
                "list_pets",
                {
                    "q": "dog",
                    "name": "旺财",
                    "owner_name": "张三",
                    "owner_phone": "138",
                    "species": "犬",
                    "doctor": "李医生",
                    "disease": "感冒",
                    "status": "就诊中",
                    "min": 10.0,
                    "max": 100.0,
                    "sort_by": "name",
                    "order": "asc",
                    "page": 2,
                    "page_size": 15,
                },
            )
            assert result.is_error is False
            params = captured["params"]
            assert params["q"] == "dog"
            assert params["name"] == "旺财"
            assert params["ownerName"] == "张三"
            assert params["ownerPhone"] == "138"
            assert params["species"] == "犬"
            assert params["doctor"] == "李医生"
            assert params["disease"] == "感冒"
            assert params["status"] == "就诊中"
            assert params["sortBy"] == "name"
            assert params["order"] == "asc"
            assert params["page"] == "2"
            assert params["pageSize"] == "15"
            assert params["min"] == "10.0"
            assert params["max"] == "100.0"


class TestBackendFailureThroughMCP:
    @pytest.mark.asyncio
    async def test_backend_5xx_surfaces_as_error_envelope(self) -> None:
        from mcp import Client

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=500,
                content=json.dumps(
                    {"code": 1, "message": "error", "data": None}
                ).encode(),
                headers={"content-type": "application/json"},
            )

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool("list_pets", {"page": 1, "page_size": 10})
            assert result.is_error is True
            structured = result.structured_content
            assert structured is not None
            assert "error" in structured
            assert structured["error"]["code"] == "BACKEND_API_ERROR"

    @pytest.mark.asyncio
    async def test_backend_timeout_surfaces_as_error_envelope(self) -> None:
        from mcp import Client

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool("list_pets", {"page": 1, "page_size": 10})
            assert result.is_error is True
            structured = result.structured_content
            assert structured is not None
            assert structured["error"]["code"] == "BACKEND_TIMEOUT"

    @pytest.mark.asyncio
    async def test_invalid_input_surfaces_as_error_envelope(self) -> None:
        from mcp import Client

        def handler(request: httpx.Request) -> httpx.Response:
            return build_go_response(sample_list_response())

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool(
                "list_pets",
                {"species": "dragon"},  # invalid species
            )
            assert result.is_error is True
            structured = result.structured_content
            assert structured is not None
            assert "error" in structured
            assert structured["error"]["code"] == "VALIDATION_ERROR"
