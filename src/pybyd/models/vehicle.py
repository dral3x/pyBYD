"""Vehicle model."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from pybyd.ingestion.normalize import safe_float, safe_int


class EmpowerRange(BaseModel):
    """A permission scope granted to a shared user."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=True,
    )

    code: str = Field(default="", validation_alias=AliasChoices("code"))
    """Category code (e.g. ``"2"`` = Keys and control)."""
    name: str = Field(default="", validation_alias=AliasChoices("name"))
    """Human-readable category name."""
    children: list[EmpowerRange] = Field(default_factory=list, validation_alias=AliasChoices("children", "childList"))
    """Child permission items."""


class Vehicle(BaseModel):
    """A vehicle associated with the user's account.

    Fields are mapped from the ``/app/account/getAllListByUserId``
    response documented in API_MAPPING.md.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=True,
    )

    vin: str = Field(default="", validation_alias=AliasChoices("vin"))
    """Vehicle Identification Number."""
    model_name: str = Field(default="", validation_alias=AliasChoices("modelName", "model_name"))
    """Model name (e.g. ``"Tang EV"``)."""
    brand_name: str = Field(default="", validation_alias=AliasChoices("brandName", "brand_name"))
    """Brand name (e.g. ``"BYD"``)."""
    energy_type: str = Field(default="", validation_alias=AliasChoices("energyType", "energy_type"))
    """Energy type identifier (``"0"`` for EV)."""
    auto_alias: str = Field(default="", validation_alias=AliasChoices("autoAlias", "auto_alias"))
    """User-defined vehicle alias."""
    auto_plate: str = Field(default="", validation_alias=AliasChoices("autoPlate", "auto_plate"))
    """License plate."""
    pic_main_url: str = Field(default="", validation_alias=AliasChoices("picMainUrl", "pic_main_url"))
    """Primary image URL."""
    pic_set_url: str = Field(default="", validation_alias=AliasChoices("picSetUrl", "pic_set_url"))
    """Alternate image URL."""
    out_model_type: str = Field(default="", validation_alias=AliasChoices("outModelType", "out_model_type"))
    """External model type label."""
    total_mileage: float | None = Field(default=None, validation_alias=AliasChoices("totalMileage", "total_mileage"))
    """Odometer reading in km."""
    model_id: int | None = Field(default=None, validation_alias=AliasChoices("modelId", "model_id"))
    """Internal model identifier."""
    car_type: int | None = Field(default=None, validation_alias=AliasChoices("carType", "car_type"))
    """Car type identifier."""
    default_car: bool = Field(default=False, validation_alias=AliasChoices("defaultCar", "default_car"))
    """Whether this is the user's default vehicle."""
    empower_type: int | None = Field(default=None, validation_alias=AliasChoices("empowerType", "empower_type"))
    """Sharing/empowerment type (``2`` = owner, ``-1`` = shared)."""
    permission_status: int | None = Field(
        default=None,
        validation_alias=AliasChoices("permissionStatus", "permission_status"),
    )
    """Permission status (``2`` = full)."""
    tbox_version: str = Field(default="", validation_alias=AliasChoices("tboxVersion", "tbox_version"))
    """T-Box hardware version (e.g. ``"3"``)."""
    vehicle_state: str = Field(default="", validation_alias=AliasChoices("vehicleState", "vehicle_state"))
    """Vehicle state string (e.g. ``"1"``)."""
    auto_bought_time: int | None = Field(
        default=None,
        validation_alias=AliasChoices("autoBoughtTime", "auto_bought_time"),
    )
    """Vehicle purchase timestamp (epoch ms)."""
    yun_active_time: int | None = Field(default=None, validation_alias=AliasChoices("yunActiveTime", "yun_active_time"))
    """Cloud activation timestamp (epoch ms)."""
    empower_id: int | None = Field(default=None, validation_alias=AliasChoices("empowerId", "empower_id"))
    """Empower relationship ID (present only for shared vehicles)."""
    range_detail_list: list[EmpowerRange] = Field(
        default_factory=list,
        validation_alias=AliasChoices("rangeDetailList", "range_detail_list"),
    )
    """Permission scopes granted to a shared user (empty for owners)."""

    raw: dict[str, Any] = Field(default_factory=dict)
    """Full API response dict for access to additional fields."""

    @property
    def is_shared(self) -> bool:
        """Whether this vehicle is shared (empowered) rather than owned."""
        return self.empower_type is not None and self.empower_type < 0

    @model_validator(mode="before")
    @classmethod
    def _ensure_raw(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        merged = dict(values)
        merged.setdefault("raw", values)
        return merged

    @model_validator(mode="after")
    def _fill_missing_pics(self) -> Vehicle:
        if self.pic_main_url and self.pic_set_url:
            return self
        raw = dict(self.raw)
        nested = raw.get("cfPic")
        if not isinstance(nested, dict):
            return self
        pic_main = self.pic_main_url or str(nested.get("picMainUrl") or nested.get("pic_main_url") or "")
        pic_set = self.pic_set_url or str(nested.get("picSetUrl") or nested.get("pic_set_url") or "")
        return self.model_copy(update={"pic_main_url": pic_main, "pic_set_url": pic_set})

    @field_validator(
        "total_mileage",
        mode="before",
    )
    @classmethod
    def _coerce_float(cls, value: Any) -> float | None:
        return safe_float(value)

    @field_validator(
        "model_id",
        "car_type",
        "empower_type",
        "permission_status",
        "auto_bought_time",
        "yun_active_time",
        "empower_id",
        mode="before",
    )
    @classmethod
    def _coerce_ints(cls, value: Any) -> int | None:
        return safe_int(value)

    @field_validator("default_car", mode="before")
    @classmethod
    def _coerce_default_car(cls, value: Any) -> bool:
        if value in (True, False):
            return bool(value)
        parsed = safe_int(value)
        return bool(parsed == 1)
