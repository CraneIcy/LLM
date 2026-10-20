"""Input validation tests for the ``list_pets`` tool.

Covers:
    * Pydantic rejects unknown fields, wrong types, NaN, Infinity.
    * species / status / sortBy / order must be in the allowed value set.
    * page >= 1 and 1 <= pageSize <= 500.
    * min and max are non-negative and min <= max.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from pydantic import ValidationError

from pet_hospital_mcp.tools.list_pets import ListPetsInput


class TestSpeciesValidation:
    def test_valid_species_accepted(self) -> None:
        for value in ("犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"):
            ListPetsInput(species=value)

    def test_invalid_species_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ListPetsInput(species="dragon")
        assert "species" in str(exc_info.value)

    def test_none_species_accepted(self) -> None:
        ListPetsInput(species=None)

    def test_empty_string_species_normalized_to_none(self) -> None:
        obj = ListPetsInput(species="")
        assert obj.species is None


class TestStatusValidation:
    def test_valid_status_accepted(self) -> None:
        for value in (
            "待就诊",
            "就诊中",
            "住院中",
            "已康复",
            "慢性病随访",
        ):
            ListPetsInput(status=value)

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(status="flying")


class TestSortByValidation:
    def test_valid_sort_by_accepted(self) -> None:
        for value in (
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
        ):
            ListPetsInput(sort_by=value)

    def test_invalid_sort_by_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(sort_by="random")


class TestOrderValidation:
    def test_valid_order_accepted(self) -> None:
        ListPetsInput(order="asc")
        ListPetsInput(order="desc")

    def test_invalid_order_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(order="ascending")


class TestPageValidation:
    def test_page_defaults_to_1(self) -> None:
        obj = ListPetsInput()
        assert obj.page == 1

    def test_page_must_be_at_least_1(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(page=0)
        with pytest.raises(ValidationError):
            ListPetsInput(page=-5)

    def test_page_accepts_large_values(self) -> None:
        ListPetsInput(page=10_000)


class TestPageSizeValidation:
    def test_page_size_defaults_to_20(self) -> None:
        obj = ListPetsInput()
        assert obj.page_size == 20

    def test_page_size_minimum_is_1(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(page_size=0)

    def test_page_size_maximum_is_500(self) -> None:
        ListPetsInput(page_size=500)

    def test_page_size_above_500_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(page_size=501)


class TestMinMaxValidation:
    def test_non_negative_min(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(min=-1.0)

    def test_non_negative_max(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(max=-0.5)

    def test_min_le_max(self) -> None:
        ListPetsInput(min=10.0, max=20.0)
        ListPetsInput(min=10.0, max=10.0)

    def test_min_greater_than_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(min=20.0, max=10.0)

    def test_nan_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(min=math.nan)
        with pytest.raises(ValidationError):
            ListPetsInput(max=math.nan)

    def test_infinity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(min=math.inf)
        with pytest.raises(ValidationError):
            ListPetsInput(max=-math.inf)


class TestExtraFieldsAndTypes:
    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(foobar=42)  # type: ignore[call-arg]

    def test_wrong_type_page_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(page="abc")  # type: ignore[arg-type]

    def test_wrong_type_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(min="cheap")  # type: ignore[arg-type]


class TestQueryParamsTranslation:
    def test_camelcase_forwarding(self) -> None:
        obj = ListPetsInput(
            q="dog",
            name="旺财",
            owner_name="张三",
            owner_phone="138",
            species="犬",
            doctor="李医生",
            disease="感冒",
            status="就诊中",
            sort_by="name",
            order="asc",
            page=2,
            page_size=10,
        )
        params = obj.to_query_params()
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
        assert params["page"] == 2
        assert params["pageSize"] == 10

    def test_min_max_forwarded_when_set(self) -> None:
        params = ListPetsInput(min=10.0, max=100.0).to_query_params()
        assert params["min"] == 10.0
        assert params["max"] == 100.0

    def test_min_max_omitted_when_none(self) -> None:
        params = ListPetsInput().to_query_params()
        assert "min" not in params
        assert "max" not in params
