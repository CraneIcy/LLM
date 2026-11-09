"""Tests for the PetHospitalRESTClient.

Covers:
    * Normal call: request path and all filter/sort/pagination params
      are forwarded correctly.
    * Go REST API returns 4xx / 5xx.
    * Timeout and connection exceptions.
    * Backend returns non-JSON or a malformed data field.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pet_hospital_mcp.errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    INTERNAL_ERROR,
)
from pet_hospital_mcp.rest_client import PetHospitalErrorEnvelope
from tests.conftest import (
    build_go_error_response,
    build_go_response,
    sample_list_response,
)


class TestNormalCall:
    @pytest.mark.asyncio
    async def test_request_path_and_params_forwarded(
        self, mock_transport_factory
    ) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            captured["params"] = dict(request.url.params)
            return build_go_response(sample_list_response())

        client = mock_transport_factory(handler)
        data = await client.list_pets(
            {
                "q": "dog",
                "name": "旺财",
                "ownerName": "张三",
                "ownerPhone": "138",
                "species": "犬",
                "doctor": "李医生",
                "disease": "感冒",
                "status": "就诊中",
                "sortBy": "name",
                "order": "asc",
                "page": 2,
                "pageSize": 15,
                "min": 10.0,
                "max": 100.0,
            }
        )

        assert captured["method"] == "GET"
        assert "/api/v1/pets" in captured["url"]
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
        assert data["total"] == 1
        assert data["pageSize"] == 20

    @pytest.mark.asyncio
    async def test_empty_params_still_forwarded(self, mock_transport_factory) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return build_go_response(sample_list_response(items=[]))

        client = mock_transport_factory(handler)
        data = await client.list_pets(
            {
                "q": None,
                "name": None,
                "ownerName": None,
                "ownerPhone": None,
                "species": None,
                "doctor": None,
                "disease": None,
                "status": None,
                "sortBy": None,
                "order": None,
                "page": 1,
                "pageSize": 20,
            }
        )
        assert data["items"] == []


class TestBackend4xx5xx:
    @pytest.mark.asyncio
    async def test_4xx_returns_backend_api_error(
        self, mock_transport_factory
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return build_go_error_response(
                status_code=400, message="bad request"
            )

        client = mock_transport_factory(handler)
        with pytest.raises(PetHospitalErrorEnvelope) as exc_info:
            await client.list_pets({"page": 1, "pageSize": 20})
        assert exc_info.value.envelope.error.code == BACKEND_API_ERROR

    @pytest.mark.asyncio
    async def test_5xx_retried_then_backend_api_error(
        self, mock_transport_factory
    ) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            return build_go_error_response(
                status_code=500, message="internal"
            )

        client = mock_transport_factory(handler)
        with pytest.raises(PetHospitalErrorEnvelope) as exc_info:
            await client.list_pets({"page": 1, "pageSize": 20})
        # 1 initial + 1 retry because backend_max_retries=1 in conftest
        assert attempts["count"] == 2
        assert exc_info.value.envelope.error.code == BACKEND_API_ERROR


class TestTimeoutAndConnection:
    @pytest.mark.asyncio
    async def test_timeout_returns_backend_timeout(
        self, mock_transport_factory
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        client = mock_transport_factory(handler)
        with pytest.raises(PetHospitalErrorEnvelope) as exc_info:
            await client.list_pets({"page": 1, "pageSize": 20})
        assert exc_info.value.envelope.error.code == BACKEND_TIMEOUT

    @pytest.mark.asyncio
    async def test_connect_error_returns_backend_unavailable(
        self, mock_transport_factory
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = mock_transport_factory(handler)
        with pytest.raises(PetHospitalErrorEnvelope) as exc_info:
            await client.list_pets({"page": 1, "pageSize": 20})
        assert exc_info.value.envelope.error.code == BACKEND_UNAVAILABLE


class TestInvalidResponse:
    @pytest.mark.asyncio
    async def test_non_json_returns_backend_invalid_response(
        self, mock_transport_factory
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=200,
                content=b"not json at all",
                headers={"content-type": "text/plain"},
            )

        client = mock_transport_factory(handler)
        with pytest.raises(PetHospitalErrorEnvelope) as exc_info:
            await client.list_pets({"page": 1, "pageSize": 20})
        assert exc_info.value.envelope.error.code == BACKEND_INVALID_RESPONSE

    @pytest.mark.asyncio
    async def test_missing_data_field_returns_empty_dict(
        self, mock_transport_factory
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=200,
                content=json.dumps({"code": 0, "message": "ok"}).encode(),
                headers={"content-type": "application/json"},
            )

        client = mock_transport_factory(handler)
        data = await client.list_pets({"page": 1, "pageSize": 20})
        assert data == {}

    @pytest.mark.asyncio
    async def test_data_not_object_returns_backend_invalid_response(
        self, mock_transport_factory
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=200,
                content=json.dumps(
                    {"code": 0, "message": "ok", "data": [1, 2, 3]}
                ).encode(),
                headers={"content-type": "application/json"},
            )

        client = mock_transport_factory(handler)
        with pytest.raises(PetHospitalErrorEnvelope) as exc_info:
            await client.list_pets({"page": 1, "pageSize": 20})
        assert exc_info.value.envelope.error.code == BACKEND_INVALID_RESPONSE
