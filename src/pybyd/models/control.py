"""Remote control data models."""

from __future__ import annotations

import dataclasses
import enum
from typing import Any


class RemoteCommand(enum.StrEnum):
    """Remote control instruction codes.

    Each value corresponds to the ``instructionCode`` string sent
    to the BYD API (per PROTOCOL.md).
    """

    LOCK = "101"
    UNLOCK = "102"
    START_CLIMATE = "111"
    STOP_CLIMATE = "112"
    OPEN_TRUNK = "121"
    CLOSE_WINDOWS = "141"
    FLASH_LIGHTS = "301"
    HORN = "302"


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
