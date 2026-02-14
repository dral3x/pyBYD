"""Energy consumption data model."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from pybyd.ingestion.normalize import safe_float


class EnergyConsumption(BaseModel):
    """Energy consumption data for a vehicle.

    Numeric fields are ``None`` when the value is absent or
    unparseable from the API response. All original data is
    available in the ``raw`` dict.

    Parameters
    ----------
    vin : str
        Vehicle Identification Number.
    total_energy : float or None
        Total energy consumption.
    avg_energy_consumption : float or None
        Average energy consumption.
    electricity_consumption : float or None
        Electricity portion of consumption.
    fuel_consumption : float or None
        Fuel portion of consumption.
    raw : dict
        Full API response dict.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=True,
    )

    vin: str = Field(default="", validation_alias=AliasChoices("vin"))
    total_energy: float | None = Field(default=None, validation_alias=AliasChoices("totalEnergy", "total_energy"))
    avg_energy_consumption: float | None = Field(
        default=None, validation_alias=AliasChoices("avgEnergyConsumption", "avg_energy_consumption")
    )
    electricity_consumption: float | None = Field(
        default=None, validation_alias=AliasChoices("electricityConsumption", "electricity_consumption")
    )
    fuel_consumption: float | None = Field(
        default=None,
        validation_alias=AliasChoices("fuelConsumption", "fuel_consumption"),
    )
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _ensure_raw(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        merged = dict(values)
        merged.setdefault("raw", values)
        return merged

    @field_validator(
        "total_energy",
        "avg_energy_consumption",
        "electricity_consumption",
        "fuel_consumption",
        mode="before",
    )
    @classmethod
    def _coerce_floats(cls, value: Any) -> float | None:
        return safe_float(value)
