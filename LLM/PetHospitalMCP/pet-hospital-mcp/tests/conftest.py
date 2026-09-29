"""Shared pytest fixtures for the Pet Hospital MCP service tests.

Tests must never touch the real Go backend. The REST client is given an
``httpx.MockTransport`` that returns canned responses, or respx is used
to intercept requests. The MCP server is exercised in-process via the
SDK 2.x ``Client``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
import pytest_asyncio

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.rest_client import PetHospitalRESTClient


def _default_settings() -> Settings:
    return Settings(
        mcp_host="127.0.0.1",
        mcp_port=8000,
        pet_hospital_base_url="http://127.0.0.1:8080",
        backend_timeout_seconds=2.0,
        backend_max_retries=1,
        backend_retry_backoff_seconds=0.0,
    )


def make_mock_transport(
    handler: Any,
) -> httpx.MockTransport:
    """Wrap a callable in an httpx.MockTransport.

    ``handler`` receives the ``httpx.Request`` and returns either an
    ``httpx.Response`` or raises an exception that the client should
    observe.
    """

    return httpx.MockTransport(handler)


def build_go_response(
    data: Any,
    *,
    status_code: int = 200,
    message: str = "success",
    code: int = 0,
) -> httpx.Response:
    """Build a Go-style JSON response: {code, message, data}."""

    payload = json.dumps({"code": code, "message": message, "data": data})
    return httpx.Response(
        status_code=status_code,
        content=payload,
        headers={"content-type": "application/json"},
    )


def build_go_error_response(
    *,
    status_code: int,
    message: str = "error",
    code: int = 1,
    data: Any = None,
) -> httpx.Response:
    """Build a Go-style error response."""

    payload = json.dumps({"code": code, "message": message, "data": data})
    return httpx.Response(
        status_code=status_code,
        content=payload,
        headers={"content-type": "application/json"},
    )


def sample_pet_payload() -> dict[str, Any]:
    """A minimal pet object that mirrors the Go model."""

    return {
        "id": "p-001",
        "name": "旺财",
        "species": "犬",
        "breed": "中华田园犬",
        "gender": "male",
        "ageMonths": 24,
        "color": "棕色",
        "chipNo": "CHIP-001",
        "ownerName": "张三",
        "ownerPhone": "13800000000",
        "ownerAddr": "北京市朝阳区",
        "doctor": "李医生",
        "disease": "感冒",
        "status": "就诊中",
        "allergy": "",
        "note": "",
        "records": None,
        "charges": None,
        "totalCost": 120.5,
        "visitCount": 2,
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-06-01T00:00:00Z",
    }


def sample_list_response(
    *,
    items: list[dict[str, Any]] | None = None,
    total: int = 1,
    page: int = 1,
    page_size: int = 20,
    total_pages: int = 1,
    total_cost: float = 120.5,
) -> dict[str, Any]:
    """Build the Go ``store.Result``-shaped data payload."""

    return {
        "items": items if items is not None else [sample_pet_payload()],
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "totalCost": total_cost,
    }


@pytest.fixture
def settings() -> Settings:
    return _default_settings()


@pytest.fixture
def mock_transport_factory():
    """Return a factory that builds a REST client with a custom handler."""

    def _factory(handler: Any) -> PetHospitalRESTClient:
        transport = make_mock_transport(handler)
        return PetHospitalRESTClient(_default_settings(), transport=transport)

    return _factory
