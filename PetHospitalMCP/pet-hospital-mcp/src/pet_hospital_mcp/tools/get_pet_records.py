"""``get_pet_records`` MCP tool.

Reads ``GET /api/v1/pets/{id}/records`` (the Go handler that returns the
full medical-record timeline of one pet) and turns the raw records into a
self-inspection payload for veterinary clinic compliance work.

The audit is deliberately mechanical: it only reports which statutory
record fields (attending vet, diagnosis, treatment, prescription, charge)
are empty, so the calling agent can cite the exact article rather than
guessing. It never judges clinical correctness.
"""

from __future__ import annotations

import json
import time
from typing import Annotated, Any

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, Field

from ..errors import (
    BACKEND_INVALID_RESPONSE,
    INTERNAL_ERROR,
    VALIDATION_ERROR,
    build_error,
)
from ..logging_config import build_tool_log_entry, get_logger
from ..rest_client import PetHospitalErrorEnvelope, PetHospitalRESTClient

TOOL_NAME = "get_pet_records"

# Fields checked by the mechanical audit. Keys are the Go JSON field
# names, values are the human-readable labels reported back to the model.
AUDITED_FIELDS: tuple[tuple[str, str], ...] = (
    ("visitDate", "就诊日期"),
    ("doctor", "接诊医生"),
    ("diagnosis", "诊断结论"),
    ("treatment", "处置方案"),
)


class GetPetRecordsInput(BaseModel):
    """Input schema for the ``get_pet_records`` tool."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pet_id: str = Field(
        min_length=1,
        max_length=64,
        description="Pet archive ID returned by list_pets (for example 'p-001'). Required.",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of records to return. Range 1-100. Default 50.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of records to skip from the newest record. Must be >= 0.",
    )
    only_incomplete: bool = Field(
        default=False,
        description=(
            "When true, return only records that failed the field audit; "
            "the summary counters always cover the full record set."
        ),
    )
    include_history_text: bool = Field(
        default=False,
        description=(
            "When true, also return the backend-rendered one-line history "
            "text (historyText) for citation inside reports."
        ),
    )


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _audit_record(record: dict[str, Any]) -> list[str]:
    """Return the list of missing statutory fields for one record."""

    missing: list[str] = []
    for field, label in AUDITED_FIELDS:
        if _is_blank(record.get(field)):
            missing.append(label)
    if _is_blank(record.get("prescription")):
        missing.append("处方")
    charge = record.get("charge")
    if charge is None or float(charge) <= 0:
        missing.append("本次费用")
    return missing


def _success_result(payload: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structuredContent=payload,
        isError=False,
    )


def _error_result(payload: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structuredContent=payload,
        isError=True,
    )


def _envelope_dict(envelope: Any) -> dict[str, Any]:
    if hasattr(envelope, "to_dict"):
        return envelope.to_dict()  # type: ignore[no-any-return]
    return dict(envelope)


def _envelope_code(envelope: Any) -> str:
    if hasattr(envelope, "code"):
        return str(envelope.code)
    inner = envelope.get("error", {}) if isinstance(envelope, dict) else {}
    return str(inner.get("code") or "INTERNAL_ERROR")


def register(mcp: Any, rest_client: PetHospitalRESTClient) -> None:
    """Register the ``get_pet_records`` tool on the given MCPServer."""

    @mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def get_pet_records(
        pet_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=64,
                description="Pet archive ID returned by list_pets, e.g. 'p-001'. Required.",
            ),
        ],
        limit: Annotated[
            int,
            Field(ge=1, le=100, description="Maximum number of records. 1-100, default 50."),
        ] = 50,
        offset: Annotated[
            int,
            Field(ge=0, description="Records to skip from the newest one. Default 0."),
        ] = 0,
        only_incomplete: Annotated[
            bool,
            Field(
                description=(
                    "True returns only records failing the field audit; "
                    "summary counters always cover the whole set."
                )
            ),
        ] = False,
        include_history_text: Annotated[
            bool,
            Field(description="True also returns the backend-rendered historyText."),
        ] = False,
    ):
        """Adapter for ``GET /api/v1/pets/{id}/records``."""

        logger = get_logger(TOOL_NAME)
        start = time.perf_counter()

        try:
            input_model = GetPetRecordsInput(
                pet_id=pet_id,
                limit=limit,
                offset=offset,
                only_incomplete=only_incomplete,
                include_history_text=include_history_text,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            envelope = build_error(
                VALIDATION_ERROR,
                f"Input validation failed: {exc}",
                {"tool": TOOL_NAME},
            )
            logger.info(
                **build_tool_log_entry(
                    TOOL_NAME,
                    {"pet_id": pet_id},
                    "error",
                    duration_ms,
                    error_code=VALIDATION_ERROR,
                )
            )
            return _error_result(_envelope_dict(envelope))

        try:
            data = await rest_client.get_records(input_model.pet_id)
        except PetHospitalErrorEnvelope as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                **build_tool_log_entry(
                    TOOL_NAME,
                    {"pet_id": input_model.pet_id},
                    "error",
                    duration_ms,
                    error_code=_envelope_code(exc.envelope),
                )
            )
            return _error_result(_envelope_dict(exc.envelope))
        except Exception as exc:  # pragma: no cover - defensive
            duration_ms = (time.perf_counter() - start) * 1000
            envelope = build_error(
                INTERNAL_ERROR,
                f"Unexpected internal failure: {exc.__class__.__name__}",
                {"tool": TOOL_NAME},
            )
            logger.error(
                **build_tool_log_entry(
                    TOOL_NAME,
                    {"pet_id": input_model.pet_id},
                    "error",
                    duration_ms,
                    error_code=INTERNAL_ERROR,
                    exc_info=exc,
                )
            )
            return _error_result(_envelope_dict(envelope))

        try:
            payload = _build_payload(input_model, data)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            envelope = build_error(
                BACKEND_INVALID_RESPONSE,
                f"Backend payload could not be interpreted: {exc.__class__.__name__}",
                {"tool": TOOL_NAME},
            )
            logger.error(
                **build_tool_log_entry(
                    TOOL_NAME,
                    {"pet_id": input_model.pet_id},
                    "error",
                    duration_ms,
                    error_code=BACKEND_INVALID_RESPONSE,
                )
            )
            return _error_result(_envelope_dict(envelope))

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            **build_tool_log_entry(
                TOOL_NAME,
                {"pet_id": input_model.pet_id},
                "ok",
                duration_ms,
                record_count=payload["count"],
                incomplete_count=len(payload["incomplete_records"]),
            )
        )
        return _success_result(payload)


def _build_payload(
    input_model: GetPetRecordsInput,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Shape the backend response into the audit payload."""

    if not isinstance(data, dict):
        raise TypeError("data is not an object")

    raw_records = data.get("records")
    if raw_records is None:
        raw_records = []
    if not isinstance(raw_records, list):
        raise TypeError("records is not a list")

    records: list[dict[str, Any]] = []
    for index, record in enumerate(raw_records):
        if not isinstance(record, dict):
            raise TypeError(f"records[{index}] is not an object")
        records.append(record)

    window = records[input_model.offset : input_model.offset + input_model.limit]

    incomplete: list[dict[str, Any]] = []
    counters = {"missing_doctor": 0, "missing_diagnosis": 0, "missing_treatment": 0,
                "missing_prescription": 0, "zero_charge": 0}

    for record in records:
        missing = _audit_record(record)
        if not missing:
            continue
        incomplete.append(
            {
                "id": record.get("id"),
                "visitDate": record.get("visitDate"),
                "doctor": record.get("doctor"),
                "missingFields": missing,
            }
        )
        if "接诊医生" in missing:
            counters["missing_doctor"] += 1
        if "诊断结论" in missing:
            counters["missing_diagnosis"] += 1
        if "处置方案" in missing:
            counters["missing_treatment"] += 1
        if "处方" in missing:
            counters["missing_prescription"] += 1
        if "本次费用" in missing:
            counters["zero_charge"] += 1

    if input_model.only_incomplete:
        incomplete_ids = {item["id"] for item in incomplete}
        window = [record for record in window if record.get("id") in incomplete_ids]

    payload: dict[str, Any] = {
        "pet_id": data.get("petId"),
        "pet_name": data.get("petName"),
        "owner_name": data.get("ownerName"),
        "count": len(records),
        "offset": input_model.offset,
        "limit": input_model.limit,
        "returned": len(window),
        "records": window,
        "incomplete_records": incomplete,
        "missing_summary": counters,
    }
    if input_model.include_history_text:
        payload["history_text"] = data.get("historyText") or ""
    return payload


TOOL_DESCRIPTION = """读取一只宠物的完整就诊病历（对应上游 GET /api/v1/pets/{id}/records），
并按“病历规范性”做机械自查。

用途：动物诊疗机构做合规自查时，按病历号（档案 ID）取出该宠物的历史
病历，检查法定记录项是否缺失，供后续对照条款逐条说明。

参数：
  pet_id               : 宠物档案 ID（由 list_pets 返回，必填）。
  limit                : 返回条数上限，1-100，默认 50。
  offset               : 从最新一条往前跳过的条数，>= 0，默认 0。
  only_incomplete      : 为 true 时只返回自查不通过的病历；汇总计数始终覆盖全部病历。
  include_history_text : 为 true 时一并返回后端渲染的一行病史文本，便于在报告中引用。

返回结构：
  pet_id / pet_name / owner_name : 档案基本信息。
  count                          : 该宠物病历总条数。
  offset / limit / returned      : 请求窗口与实际返回条数。
  records                        : 当前窗口内的原始病历（visitDate/doctor/diagnosis/
                                   symptoms/treatment/prescription/charge 等）。
  incomplete_records             : 自查不通过的病历清单，含缺失项中文名称。
  missing_summary                : {missing_doctor, missing_diagnosis, missing_treatment,
                                   missing_prescription, zero_charge} 计数。
  history_text                   : 仅当 include_history_text=true 时返回。

本工具只判断“字段是否为空”，不对诊断是否合理作任何判断。
失败时返回统一错误信封：{"error": {"code": "...", "message": "...", "details": {}}}。
"""
