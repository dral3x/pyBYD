"""Pydantic request models for client entrypoints.

These models provide a consistent "validate → normalize → execute" flow.
They are used internally by :class:`pybyd.client.BydClient`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VinRequest(BaseModel):
    """Request containing a VIN."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        str_strip_whitespace=True,
    )

    vin: str

    @field_validator("vin")
    @classmethod
    def _vin_non_empty(cls, value: str) -> str:
        vin = value.strip()
        if not vin:
            raise ValueError("vin must be non-empty")
        return vin


class PollingRequest(VinRequest):
    """VIN request with polling controls."""

    poll_attempts: int = Field(default=10, ge=1)
    poll_interval: float = Field(default=1.5, ge=0)


class VehicleRealtimeRequest(PollingRequest):
    stale_after: float | None = Field(default=None, gt=0)


class GpsInfoRequest(PollingRequest):
    pass


class SetPushStateRequest(VinRequest):
    enable: bool


class RenameVehicleRequest(VinRequest):
    name: str

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("name must be non-empty")
        return name


class ToggleSmartChargingRequest(VinRequest):
    enable: bool
