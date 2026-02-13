"""Push notification state model."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class PushNotificationState:
    """Push notification switch state for a vehicle."""

    vin: str
    """Vehicle Identification Number."""

    push_switch: int | None
    """Push notification toggle (0=off, 1=on)."""

    raw: dict[str, Any]
    """Full API response dict."""

    @property
    def is_enabled(self) -> bool:
        """Whether push notifications are currently enabled."""
        return self.push_switch is not None and self.push_switch == 1
