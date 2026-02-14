"""Charging status model.

Mapped from ``/control/smartCharge/homePage`` response documented in API_MAPPING.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from pybyd.ingestion.normalize import safe_int


class ChargingStatus(BaseModel):
    """Smart charging status for a vehicle.

    Provides current SOC, charge connector state, and estimated
    time-to-full. All original data is available in the ``raw`` dict.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=True,
    )

    vin: str = Field(default="", validation_alias=AliasChoices("vin"))
    """Vehicle Identification Number."""
    soc: int | None = Field(default=None, validation_alias=AliasChoices("soc", "elecPercent"))
    """State of charge (0-100 percent)."""
    charging_state: int | None = Field(default=None, validation_alias=AliasChoices("chargingState", "charging_state"))
    """Charging state (15=not charging, other values vary)."""
    connect_state: int | None = Field(default=None, validation_alias=AliasChoices("connectState", "connect_state"))
    """Charger connection (0=not connected)."""
    wait_status: int | None = Field(default=None, validation_alias=AliasChoices("waitStatus", "wait_status"))
    """Charge wait status."""
    full_hour: int | None = Field(default=None, validation_alias=AliasChoices("fullHour", "full_hour"))
    """Estimated hours to full (-1=N/A)."""
    full_minute: int | None = Field(default=None, validation_alias=AliasChoices("fullMinute", "full_minute"))
    """Estimated minutes to full (-1=N/A)."""
    update_time: int | None = Field(default=None, validation_alias=AliasChoices("updateTime", "update_time", "time"))
    """Unix timestamp of last data update."""

    raw: dict[str, Any] = Field(default_factory=dict)
    """Full API response dict."""

    @property
    def is_connected(self) -> bool:
        """Whether the vehicle is connected to a charger."""
        return self.connect_state is not None and self.connect_state != 0

    @property
    def is_charging(self) -> bool:
        """Whether the vehicle is actively charging."""
        return self.charging_state is not None and self.charging_state != 15 and self.charging_state > 0

    @property
    def time_to_full_available(self) -> bool:
        """Whether estimated time-to-full is available."""
        return (
            self.full_hour is not None
            and self.full_minute is not None
            and self.full_hour >= 0
            and self.full_minute >= 0
        )

    @property
    def update_datetime_utc(self) -> datetime | None:
        """Return ``update_time`` as UTC datetime (supports seconds/ms epochs)."""
        if self.update_time is None:
            return None
        timestamp = self.update_time
        if timestamp > 1_000_000_000_000:
            timestamp = int(timestamp / 1000)
        return datetime.fromtimestamp(timestamp, tz=UTC)

    @model_validator(mode="before")
    @classmethod
    def _ensure_raw(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        merged = dict(values)
        merged.setdefault("raw", values)
        return merged

    @field_validator(
        "soc",
        "charging_state",
        "connect_state",
        "wait_status",
        "full_hour",
        "full_minute",
        "update_time",
        mode="before",
    )
    @classmethod
    def _coerce_ints(cls, value: Any) -> int | None:
        return safe_int(value)
