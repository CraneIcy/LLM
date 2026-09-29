"""Tests for the structured logging and sensitive-data redaction."""

from __future__ import annotations

from typing import Any

from pet_hospital_mcp.logging_config import (
    REDACTED_PLACEHOLDER,
    build_tool_log_entry,
    redact,
)


class TestRedaction:
    def test_owner_phone_redacted(self) -> None:
        data = {"ownerPhone": "13800000000", "name": "旺财"}
        result = redact(data)
        assert result["ownerPhone"] == REDACTED_PLACEHOLDER
        assert result["name"] == "旺财"

    def test_owner_phone_snake_case_redacted(self) -> None:
        data = {"owner_phone": "13800000000"}
        result = redact(data)
        assert result["owner_phone"] == REDACTED_PLACEHOLDER

    def test_owner_addr_redacted(self) -> None:
        data = {"ownerAddr": "北京市朝阳区"}
        result = redact(data)
        assert result["ownerAddr"] == REDACTED_PLACEHOLDER

    def test_chip_no_redacted(self) -> None:
        data = {"chipNo": "CHIP-001"}
        result = redact(data)
        assert result["chipNo"] == REDACTED_PLACEHOLDER

    def test_nested_dict_redacted(self) -> None:
        data = {
            "outer": {
                "ownerPhone": "13800000000",
                "inner": {"chipNo": "X"},
            },
            "list": [{"ownerAddr": "addr"}],
        }
        result = redact(data)
        assert result["outer"]["ownerPhone"] == REDACTED_PLACEHOLDER
        assert result["outer"]["inner"]["chipNo"] == REDACTED_PLACEHOLDER
        assert result["list"][0]["ownerAddr"] == REDACTED_PLACEHOLDER

    def test_non_sensitive_fields_preserved(self) -> None:
        data = {"name": "旺财", "species": "犬", "page": 1}
        result = redact(data)
        assert result == data


class TestToolLogEntry:
    def test_entry_contains_required_fields(self) -> None:
        entry = build_tool_log_entry(
            tool_name="list_pets",
            params={"page": 1, "ownerPhone": "13800000000"},
            status="ok",
            duration_ms=12.5,
            total=1,
        )
        assert entry["tool_name"] == "list_pets"
        assert entry["status"] == "ok"
        assert entry["duration_ms"] == 12.5
        assert entry["params"]["ownerPhone"] == REDACTED_PLACEHOLDER
        assert entry["params"]["page"] == 1
        assert entry["total"] == 1
