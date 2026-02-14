"""Remote control data models."""

from __future__ import annotations

import enum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from pybyd.ingestion.normalize import safe_int


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


class RemoteControlResult(BaseModel):
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

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=True,
    )

    control_state: ControlState = Field(validation_alias=AliasChoices("controlState", "control_state"))
    success: bool
    request_serial: str | None = Field(default=None, validation_alias=AliasChoices("requestSerial", "request_serial"))
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_shapes(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        merged = dict(values)
        merged.setdefault("raw", values)

        # Immediate result format: {"res": 2, ...}
        if "res" in merged and "controlState" not in merged and "control_state" not in merged:
            res_val = safe_int(merged.get("res"))
            state = ControlState.SUCCESS if res_val == 2 else ControlState.FAILURE
            merged["controlState"] = int(state)
            merged.setdefault("success", state == ControlState.SUCCESS)

        # Standard polled format: {"controlState": 0/1/2, ...}
        if "controlState" in merged and "success" not in merged:
            raw_state = safe_int(merged.get("controlState")) or 0
            try:
                state = ControlState(raw_state)
            except ValueError:
                state = ControlState.PENDING
            merged["controlState"] = int(state)
            merged["success"] = state == ControlState.SUCCESS

        return merged
