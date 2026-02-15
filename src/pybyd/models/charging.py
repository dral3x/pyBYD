"""Charging status model.

Mapped from ``/control/smartCharge/homePage`` response documented in API_MAPPING.md.
"""

from __future__ import annotations

from typing import Any

from pydantic import model_validator

from pybyd.models._base import BydBaseModel, BydTimestamp

# BYD sends the same value under different keys depending on the endpoint.
_KEY_ALIASES: dict[str, str] = {
    "elecPercent": "soc",
    "time": "updateTime",
}


class ChargingStatus(BydBaseModel):
    """Smart charging status for a vehicle."""

    vin: str = ""
    soc: int | None = None
    """State of charge (0-100 percent)."""
    charging_state: int | None = None
    connect_state: int | None = None
    wait_status: int | None = None
    full_hour: int | None = None
    full_minute: int | None = None
    update_time: BydTimestamp = None
    """Last data update timestamp (parsed to UTC datetime)."""

    @property
    def is_connected(self) -> bool:
        return self.connect_state is not None and self.connect_state != 0

    @property
    def is_charging(self) -> bool:
        return self.charging_state is not None and self.charging_state != 15 and self.charging_state > 0

    @property
    def time_to_full_available(self) -> bool:
        return (
            self.full_hour is not None
            and self.full_minute is not None
            and self.full_hour >= 0
            and self.full_minute >= 0
        )

    @model_validator(mode="before")
    @classmethod
    def _normalise_keys(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        normalised: dict[str, Any] = {}
        for k, v in values.items():
            if isinstance(k, str):
                normalised[_KEY_ALIASES.get(k, k)] = v
            else:
                normalised[str(k)] = v
        return normalised
