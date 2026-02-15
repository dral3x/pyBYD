"""Vehicle model."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from pybyd.models._base import BydBaseModel, BydTimestamp

# BYD sometimes sends "childList" instead of "children".
_KEY_ALIASES: dict[str, str] = {
    "childList": "children",
}


class EmpowerRange(BydBaseModel):
    """A permission scope granted to a shared user."""

    code: str = ""
    name: str = ""
    children: list[EmpowerRange] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise_keys(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        normalised: dict[str, Any] = {}
        for k, v in values.items():
            normalised[_KEY_ALIASES.get(k, k)] = v
        return normalised


class Vehicle(BydBaseModel):
    """A vehicle associated with the user's account."""

    vin: str = ""
    model_name: str = ""
    brand_name: str = ""
    energy_type: str = ""
    auto_alias: str = ""
    auto_plate: str = ""
    pic_main_url: str = ""
    pic_set_url: str = ""
    out_model_type: str = ""
    total_mileage: float | None = None
    model_id: int | None = None
    car_type: int | None = None
    default_car: bool = False
    empower_type: int | None = None
    permission_status: int | None = None
    tbox_version: str = ""
    vehicle_state: str = ""
    auto_bought_time: BydTimestamp = None
    yun_active_time: BydTimestamp = None
    empower_id: int | None = None
    range_detail_list: list[EmpowerRange] = Field(default_factory=list)

    @property
    def is_shared(self) -> bool:
        return self.empower_type is not None and self.empower_type < 0

    @model_validator(mode="after")
    def _fill_missing_pics(self) -> Vehicle:
        if self.pic_main_url and self.pic_set_url:
            return self
        nested = self.raw.get("cfPic")
        if not isinstance(nested, dict):
            return self
        pic_main = self.pic_main_url or str(nested.get("picMainUrl") or nested.get("pic_main_url") or "")
        pic_set = self.pic_set_url or str(nested.get("picSetUrl") or nested.get("pic_set_url") or "")
        return self.model_copy(update={"pic_main_url": pic_main, "pic_set_url": pic_set})

    @field_validator("default_car", mode="before")
    @classmethod
    def _coerce_default_car(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return int(value) == 1
