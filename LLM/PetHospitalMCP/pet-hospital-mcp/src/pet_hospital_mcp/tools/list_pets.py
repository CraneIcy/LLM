"""``list_pets`` MCP tool.

Wraps the Go REST API ``GET /api/v1/pets`` endpoint. Exposes a single
snake_case tool to the MCP client with strict Pydantic validation and a
structured output model that mirrors the Go ``store.Result`` payload.

Only the query parameters listed in the Go backend are forwarded; no
adapter-private fields are accepted.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..errors import (
    BACKEND_INVALID_RESPONSE,
    INTERNAL_ERROR,
    VALIDATION_ERROR,
    build_error,
)
from ..logging_config import build_tool_log_entry, get_logger
from ..rest_client import PetHospitalErrorEnvelope, PetHospitalRESTClient

# ---------------------------------------------------------------------------
# Allowed enum values (mirror internal/model/model.go)
# ---------------------------------------------------------------------------

SPECIES_VALUES: tuple[str, ...] = (
    "犬",
    "猫",
    "兔",
    "鸟",
    "仓鼠",
    "爬宠",
    "其他",
)

STATUS_VALUES: tuple[str, ...] = (
    "待就诊",
    "就诊中",
    "住院中",
    "已康复",
    "慢性病随访",
)

SORT_BY_VALUES: tuple[str, ...] = (
    "id",
    "name",
    "ownerName",
    "species",
    "doctor",
    "disease",
    "status",
    "totalCost",
    "visitCount",
    "createdAt",
    "updatedAt",
)

ORDER_VALUES: tuple[str, ...] = ("asc", "desc")


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class ListPetsInput(BaseModel):
    """Input schema for the ``list_pets`` tool.

    Field names are snake_case to satisfy the MCP naming convention, but
    the values are forwarded to the Go backend under its camelCase names.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    q: str | None = Field(
        default=None,
        description="Free-text full-search query (matches across multiple fields).",
    )
    name: str | None = Field(
        default=None,
        description="Substring match on the pet's name (case-insensitive).",
    )
    owner_name: str | None = Field(
        default=None,
        description="Substring match on the owner's name (case-insensitive).",
    )
    owner_phone: str | None = Field(
        default=None,
        description="Substring match on the owner's phone number.",
    )
    species: str | None = Field(
        default=None,
        description="Exact species filter. Must be one of the allowed values.",
    )
    doctor: str | None = Field(
        default=None,
        description="Substring match on the treating doctor's name.",
    )
    disease: str | None = Field(
        default=None,
        description="Substring match on the disease / diagnosis field.",
    )
    status: str | None = Field(
        default=None,
        description="Exact visit status filter. Must be one of the allowed values.",
    )
    min: float | None = Field(
        default=None,
        ge=0,
        description="Minimum total cost (inclusive). Must be non-negative.",
    )
    max: float | None = Field(
        default=None,
        ge=0,
        description="Maximum total cost (inclusive). Must be non-negative.",
    )
    sort_by: str | None = Field(
        default=None,
        description="Field to sort results by. Must be one of the allowed values.",
    )
    order: str | None = Field(
        default=None,
        description="Sort direction: 'asc' or 'desc'.",
    )
    page: int = Field(
        default=1,
        ge=1,
        description="1-based page number. Must be >= 1.",
    )
    page_size: int = Field(
        default=20,
        ge=1,
        le=500,
        description="Number of items per page. Must be between 1 and 500.",
    )

    @field_validator("species")
    @classmethod
    def _validate_species(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in SPECIES_VALUES:
            raise ValueError(
                f"species must be one of {list(SPECIES_VALUES)}; got {value!r}"
            )
        return value

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in STATUS_VALUES:
            raise ValueError(
                f"status must be one of {list(STATUS_VALUES)}; got {value!r}"
            )
        return value

    @field_validator("sort_by")
    @classmethod
    def _validate_sort_by(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in SORT_BY_VALUES:
            raise ValueError(
                f"sortBy must be one of {list(SORT_BY_VALUES)}; got {value!r}"
            )
        return value

    @field_validator("order")
    @classmethod
    def _validate_order(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in ORDER_VALUES:
            raise ValueError(
                f"order must be one of {list(ORDER_VALUES)}; got {value!r}"
            )
        return value

    @field_validator("min", "max")
    @classmethod
    def _reject_non_finite(cls, value: float | None) -> float | None:
        if value is None:
            return None
        import math

        if math.isnan(value) or math.isinf(value):
            raise ValueError("NaN and Infinity are not allowed for min/max")
        return value

    @model_validator(mode="after")
    def _check_min_max(self) -> "ListPetsInput":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must be <= max")
        return self

    def to_query_params(self) -> dict[str, Any]:
        """Translate the validated input into Go API query parameters."""

        params: dict[str, Any] = {
            "q": self.q,
            "name": self.name,
            "ownerName": self.owner_name,
            "ownerPhone": self.owner_phone,
            "species": self.species,
            "doctor": self.doctor,
            "disease": self.disease,
            "status": self.status,
            "sortBy": self.sort_by,
            "order": self.order,
            "page": self.page,
            "pageSize": self.page_size,
        }
        if self.min is not None:
            params["min"] = self.min
        if self.max is not None:
            params["max"] = self.max
        return params


class TreatmentItem(BaseModel):
    """A single charge line from the Go ``Treatment`` model."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    item: str | None = None
    category: str | None = None
    amount: float | None = None
    doctor: str | None = None
    date: str | None = None
    note: str | None = None


class MedicalRecordItem(BaseModel):
    """A single medical record from the Go ``MedicalRecord`` model."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str | None = None
    visit_date: str | None = Field(default=None, alias="visitDate")
    doctor: str | None = None
    diagnosis: str | None = None
    symptoms: str | None = None
    treatment: str | None = None
    prescription: list[str] | None = None
    weight_kg: float | None = Field(default=None, alias="weightKg")
    temperature: float | None = None
    follow_up: str | None = Field(default=None, alias="followUp")
    charge: float | None = None
    created_at: str | None = Field(default=None, alias="createdAt")


class PetItem(BaseModel):
    """A single ``Pet`` row from the Go REST API.

    ``records`` and ``charges`` may be ``null`` or a list in the real Go
    response; we normalize them to empty lists for downstream consumers.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str | None = None
    name: str | None = None
    species: str | None = None
    breed: str | None = None
    gender: str | None = None
    age_months: int | None = Field(default=None, alias="ageMonths")
    color: str | None = None
    chip_no: str | None = Field(default=None, alias="chipNo")
    owner_name: str | None = Field(default=None, alias="ownerName")
    owner_phone: str | None = Field(default=None, alias="ownerPhone")
    owner_addr: str | None = Field(default=None, alias="ownerAddr")
    doctor: str | None = None
    disease: str | None = None
    status: str | None = None
    allergy: str | None = None
    note: str | None = None
    records: list[MedicalRecordItem] = Field(default_factory=list)
    charges: list[TreatmentItem] = Field(default_factory=list)
    total_cost: float | None = Field(default=None, alias="totalCost")
    visit_count: int | None = Field(default=None, alias="visitCount")
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")

    @field_validator("records", "charges", mode="before")
    @classmethod
    def _normalize_null_lists(cls, value: Any) -> Any:
        if value is None:
            return []
        return value


class ListPetsSuccess(BaseModel):
    """Successful output payload mirroring the Go ``store.Result`` data field."""

    model_config = ConfigDict(populate_by_name=True)

    items: list[PetItem] = Field(default_factory=list)
    total: int = 0
    page: int = 0
    page_size: int = Field(default=0, alias="pageSize")
    total_pages: int = Field(default=0, alias="totalPages")
    total_cost: float = Field(default=0.0, alias="totalCost")


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

TOOL_NAME = "list_pets"

TOOL_DESCRIPTION = """List pets from the pet hospital REST API (GET /api/v1/pets).

Use this tool to query the pet hospital database with filtering, sorting
and pagination. It is read-only and safe to call repeatedly.

Parameters (all optional):
  q            : Free-text full-search query across multiple fields.
  name         : Substring match on the pet's name.
  owner_name   : Substring match on the owner's name.
  owner_phone  : Substring match on the owner's phone number.
  species      : Exact species filter. Allowed values:
                 犬, 猫, 兔, 鸟, 仓鼠, 爬宠, 其他.
  doctor       : Substring match on the treating doctor's name.
  disease      : Substring match on the disease / diagnosis field.
  status       : Exact status filter. Allowed values:
                 待就诊, 就诊中, 住院中, 已康复, 慢性病随访.
  min          : Minimum total cost (>= 0). Ignored unless max is also set.
  max          : Maximum total cost (>= 0). Must be >= min.
  sort_by      : Sort field. Allowed values: id, name, ownerName, species,
                 doctor, disease, status, totalCost, visitCount, createdAt,
                 updatedAt.
  order        : Sort direction: 'asc' or 'desc'.
  page         : 1-based page number (>= 1). Default 1.
  page_size    : Page size (1 <= n <= 500). Default 20.

Returns a structured object with:
  items        : Array of pet records (may be empty).
  total        : Total matching records after filtering.
  page         : Current page number.
  page_size    : Page size used.
  total_pages  : Total number of pages.
  total_cost   : Sum of totalCost across all matched pets.

On failure the tool returns an error envelope:
  {"error": {"code": "...", "message": "...", "details": {}}}
"""


def register(mcp: Any, rest_client: PetHospitalRESTClient) -> None:
    """Register the ``list_pets`` tool on the given MCPServer."""

    @mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)
    async def list_pets(
        q: str | None = None,
        name: str | None = None,
        owner_name: str | None = None,
        owner_phone: str | None = None,
        species: str | None = None,
        doctor: str | None = None,
        disease: str | None = None,
        status: str | None = None,
        min: float | None = None,
        max: float | None = None,
        sort_by: str | None = None,
        order: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ):
        """Adapter for ``GET /api/v1/pets``.

        All parameters are validated by Pydantic inside this function.
        Any failure is translated to the unified error envelope.
        """

        logger = get_logger("list_pets")
        start = time.perf_counter()

        # Validate input with the Pydantic model (enum checks, cross-field, etc.)
        try:
            input_model = ListPetsInput(
                q=q,
                name=name,
                owner_name=owner_name,
                owner_phone=owner_phone,
                species=species,
                doctor=doctor,
                disease=disease,
                status=status,
                min=min,
                max=max,
                sort_by=sort_by,
                order=order,
                page=page,
                page_size=page_size,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            envelope = build_error(
                VALIDATION_ERROR,
                f"Input validation failed: {exc}",
                {"tool": TOOL_NAME},
            )
            logger.info(
                **_log_entry(
                    params={"q": q, "name": name, "species": species, "status": status},
                    status="error",
                    duration_ms=duration_ms,
                    error_code=VALIDATION_ERROR,
                )
            )
            return _error_result(envelope.to_dict())

        params = input_model.to_query_params()

        try:
            data = await rest_client.list_pets(params)
        except PetHospitalErrorEnvelope as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                **_log_entry(
                    params=params,
                    status="error",
                    duration_ms=duration_ms,
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
                **_log_entry(
                    params=params,
                    status="error",
                    duration_ms=duration_ms,
                    error_code=INTERNAL_ERROR,
                    exc_info=exc,
                )
            )
            return _error_result(envelope.to_dict())

        try:
            success = ListPetsSuccess.model_validate(data)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            envelope = build_error(
                BACKEND_INVALID_RESPONSE,
                "Backend response did not match the expected schema",
                {
                    "tool": TOOL_NAME,
                    "validation_error": str(exc),
                },
            )
            logger.error(
                **_log_entry(
                    params=params,
                    status="error",
                    duration_ms=duration_ms,
                    error_code=BACKEND_INVALID_RESPONSE,
                    exc_info=exc,
                )
            )
            return _error_result(envelope.to_dict())

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            **_log_entry(
                params=params,
                status="ok",
                duration_ms=duration_ms,
                total=success.total,
                items_returned=len(success.items),
            )
        )
        return _success_result(success.model_dump(by_alias=True))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_entry(
    *,
    params: dict[str, Any],
    status: str,
    duration_ms: float,
    **extra: Any,
) -> dict[str, Any]:
    """Build a structured log entry for a tool invocation."""

    return build_tool_log_entry(
        tool_name=TOOL_NAME,
        params=params,
        status=status,
        duration_ms=duration_ms,
        **extra,
    )


def _envelope_code(envelope: Any) -> str:
    inner = getattr(envelope, "error", None)
    if inner is not None:
        code = getattr(inner, "code", None)
        if isinstance(code, str):
            return code
    if isinstance(envelope, dict):
        inner = envelope.get("error")
        if isinstance(inner, dict):
            code = inner.get("code")
            if isinstance(code, str):
                return code
    return "UNKNOWN"


def _envelope_dict(envelope: Any) -> dict[str, Any]:
    if hasattr(envelope, "to_dict"):
        return envelope.to_dict()
    if isinstance(envelope, dict):
        return envelope
    return build_error(INTERNAL_ERROR, "Malformed error envelope").to_dict()


def _success_result(payload: dict[str, Any]) -> CallToolResult:
    """Build a successful ``CallToolResult`` with structured content."""

    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=False,
    )


def _error_result(payload: dict[str, Any]) -> CallToolResult:
    """Build an error ``CallToolResult`` with structured content."""

    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=True,
    )
