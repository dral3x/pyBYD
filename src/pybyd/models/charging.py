"""Charging status model.

Mapped from ``/control/smartCharge/homePage`` response documented
in PROTOCOL.md under "Smart Charge".
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class ChargingStatus:
    """Smart charging status for a vehicle.

    Provides current SOC, charge connector state, and estimated
    time-to-full. All original data is available in the ``raw`` dict.
    """

    vin: str
    """Vehicle Identification Number."""
    soc: int | None
    """State of charge (0-100 percent)."""
    charging_state: int | None
    """Charging state (15=not charging, other values vary)."""
    connect_state: int | None
    """Charger connection (0=not connected)."""
    wait_status: int | None
    """Charge wait status."""
    full_hour: int | None
    """Estimated hours to full (-1=N/A)."""
    full_minute: int | None
    """Estimated minutes to full (-1=N/A)."""
    update_time: int | None
    """Unix timestamp of last data update."""

    raw: dict[str, Any]
    """Full API response dict."""

    @property
    def is_connected(self) -> bool:
        """Whether the vehicle is connected to a charger."""
        return self.connect_state is not None and self.connect_state != 0

    @property
    def is_charging(self) -> bool:
        """Whether the vehicle is actively charging."""
        return (
            self.charging_state is not None
            and self.charging_state != 15
            and self.charging_state > 0
        )

    @property
    def time_to_full_available(self) -> bool:
        """Whether estimated time-to-full is available."""
        return (
            self.full_hour is not None
            and self.full_minute is not None
            and self.full_hour >= 0
            and self.full_minute >= 0
        )
