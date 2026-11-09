"""Tests for the ``get_pet_records`` tool.

Covers registration/schema, the request path, the mechanical field audit,
input validation and upstream failure mapping. No real backend is touched:
every request goes through ``httpx.MockTransport``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.rest_client import PetHospitalRESTClient
from pet_hospital_mcp.server import mcp as default_mcp
from pet_hospital_mcp.tools import get_pet_records

from tests.conftest import build_go_error_response, build_go_response


def _records_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "petId": "p-001",
        "petName": "旺财",
        "ownerName": "张三",
        "count": len(records),
        "records": records,
        "historyText": "2026-03-01 李医生 感冒 对症处理",
    }


def _record(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "r-001",
        "visitDate": "2026-03-01",
        "doctor": "李医生",
        "diagnosis": "上呼吸道感染",
        "symptoms": "打喷嚏",
        "treatment": "雾化 + 口服药物",
        "prescription": ["阿莫西林"],
        "charge": 180.0,
    }
    base.update(overrides)
    return base


def _build_isolated_server(handler: Any) -> tuple[Any, PetHospitalRESTClient]:
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
    get_pet_records.register(server, rest_client)
    return server, rest_client


class TestRegistration:
    def test_tool_is_registered_on_default_server(self) -> None:
        names = {t.name for t in default_mcp._tool_manager.list_tools()}
        assert "get_pet_records" in names

    def test_description_covers_audit_contract(self) -> None:
        tool = default_mcp._tool_manager.get_tool("get_pet_records")
        desc = tool.description
        assert "GET /api/v1/pets/{id}/records" in desc
        for param in ("pet_id", "limit", "offset", "only_incomplete", "include_history_text"):
            assert param in desc, f"missing param {param} in description"

    def test_input_schema_defaults_and_ranges(self) -> None:
        tool = default_mcp._tool_manager.get_tool("get_pet_records")
        props = tool.parameters["properties"]
        assert props["limit"]["default"] == 50
        assert props["offset"]["default"] == 0
        assert props["limit"]["maximum"] == 100
        assert "pet_id" in tool.parameters["required"]


class TestRequestShape:
    @pytest.mark.asyncio
    async def test_calls_records_endpoint(self) -> None:
        from mcp import Client

        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return build_go_response(_records_payload([_record()]))

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool("get_pet_records", {"pet_id": "p-001"})
            assert result.is_error is False
        assert captured["path"] == "/api/v1/pets/p-001/records"


class TestAudit:
    @pytest.mark.asyncio
    async def test_complete_records_report_no_missing_fields(self) -> None:
        from mcp import Client

        def handler(request: httpx.Request) -> httpx.Response:
            return build_go_response(_records_payload([_record(), _record(id="r-002")]))

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool("get_pet_records", {"pet_id": "p-001"})
            payload = result.structured_content
        assert payload["count"] == 2
        assert payload["incomplete_records"] == []
        assert payload["missing_summary"]["missing_doctor"] == 0

    @pytest.mark.asyncio
    async def test_missing_fields_are_counted(self) -> None:
        from mcp import Client

        bad = _record(
            id="r-002",
            doctor="",
            diagnosis="  ",
            prescription=[],
            charge=0,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return build_go_response(_records_payload([_record(), bad]))

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool("get_pet_records", {"pet_id": "p-001"})
            payload = result.structured_content

        assert payload["missing_summary"] == {
            "missing_doctor": 1,
            "missing_diagnosis": 1,
            "missing_treatment": 0,
            "missing_prescription": 1,
            "zero_charge": 1,
        }
        assert len(payload["incomplete_records"]) == 1
        assert "接诊医生" in payload["incomplete_records"][0]["missingFields"]

    @pytest.mark.asyncio
    async def test_limit_and_only_incomplete_shape_the_window(self) -> None:
        from mcp import Client

        records = [_record(id=f"r-{i:03d}") for i in range(1, 6)]
        records[3] = _record(id="r-004", doctor="")

        def handler(request: httpx.Request) -> httpx.Response:
            return build_go_response(_records_payload(records))

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool(
                "get_pet_records",
                {"pet_id": "p-001", "offset": 2, "limit": 3, "only_incomplete": True},
            )
            payload = result.structured_content

        assert payload["count"] == 5
        assert payload["returned"] == 1
        assert payload["records"][0]["id"] == "r-004"


class TestFailures:
    @pytest.mark.asyncio
    async def test_empty_pet_id_is_rejected_at_schema_layer(self) -> None:
        from mcp import Client

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            return build_go_response(_records_payload([]))

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool("get_pet_records", {"pet_id": ""})
        assert result.is_error is True
        assert "pet_id" in _text(result)

    @pytest.mark.asyncio
    async def test_out_of_range_limit_is_rejected_at_schema_layer(self) -> None:
        from mcp import Client

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            return build_go_response(_records_payload([]))

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool("get_pet_records", {"pet_id": "p-001", "limit": 0})
        assert result.is_error is True
        assert "limit" in _text(result)

    @pytest.mark.asyncio
    async def test_upstream_404_maps_to_backend_api_error(self) -> None:
        from mcp import Client

        def handler(request: httpx.Request) -> httpx.Response:
            return build_go_error_response(status_code=404, message="档案不存在")

        server, _ = _build_isolated_server(handler)
        async with Client(server, raise_exceptions=True) as c:
            result = await c.call_tool("get_pet_records", {"pet_id": "p-404"})
        assert result.is_error is True
        assert result.structured_content["error"]["code"] == "BACKEND_API_ERROR"


def _text(result: Any) -> str:
    """Concatenate the textual blocks of a tool result."""

    return "".join(getattr(item, "text", "") for item in (result.content or []))
