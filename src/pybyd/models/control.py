"""Remote control data models."""

from __future__ import annotations

import dataclasses
import enum
from typing import Any


class RemoteCommand(enum.StrEnum):
    """Remote control instruction codes.

    Each value corresponds to the ``instructionCode`` string sent
    to the BYD API.
    """

    LOCK = "10"
    UNLOCK = "11"
    FLASH_LIGHTS = "20"
    HORN = "21"
    START_CLIMATE = "30"
    STOP_CLIMATE = "31"


@dataclasses.dataclass(frozen=True)
class RemoteControlResult:
    """Result of a remote control command.

    Parameters
    ----------
    control_state : int
        0 = pending, 1 = success, 2 = failed.
    success : bool
        Whether the command completed successfully.
    request_serial : str or None
        Serial for follow-up polling.
    raw : dict
        Full API response dict.
    """

    control_state: int
    success: bool
    request_serial: str | None
    raw: dict[str, Any]
