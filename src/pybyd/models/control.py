"""Remote control data models."""

from __future__ import annotations

import dataclasses
import enum
from typing import Any


class RemoteCommand(enum.StrEnum):
    """Remote control ``commandType`` values.

    Each value corresponds to the ``commandType`` string sent to
    ``/control/remoteControl`` on the BYD API, as confirmed by
    Niek (BYD-re) and TA2k's APK analysis.

    """

    LOCK = "LOCKDOOR"
    UNLOCK = "OPENDOOR"
    START_CLIMATE = "OPENAIR"
    STOP_CLIMATE = "CLOSEAIR"
    SCHEDULE_CLIMATE = "BOOKINGAIR"
    FIND_CAR = "FINDCAR"
    FLASH_LIGHTS = "FLASHLIGHTNOWHISTLE"
    CLOSE_WINDOWS = "CLOSEWINDOW"
    SEAT_CLIMATE = "VENTILATIONHEATING"
    BATTERY_HEAT = "BATTERYHEAT"


class ControlState(enum.IntEnum):
    """Control command execution state."""

    PENDING = 0
    SUCCESS = 1
    FAILURE = 2


@dataclasses.dataclass(frozen=True)
class RemoteControlResult:
    """Result of a remote control command.

    Parameters
    ----------
    control_state : ControlState
        PENDING(0), SUCCESS(1), or FAILURE(2).
    success : bool
        Whether the command completed successfully.
    request_serial : str or None
        Serial for follow-up polling.
    raw : dict
        Full API response dict.
    """

    control_state: ControlState
    success: bool
    request_serial: str | None
    raw: dict[str, Any]
