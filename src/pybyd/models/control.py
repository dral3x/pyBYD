"""Remote control models, parameter builders, and command responses.

Consolidates enums, result models, typed ``controlParamsMap`` payloads,
and lightweight acknowledgement wrappers.
"""

from __future__ import annotations

import enum
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_serializer, model_validator
from pydantic.alias_generators import to_camel

from pybyd._constants import celsius_to_scale
from pybyd.models._base import BydBaseModel

# ------------------------------------------------------------------
# Enums
# ------------------------------------------------------------------


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


# ------------------------------------------------------------------
# Command result
# ------------------------------------------------------------------


class RemoteControlResult(BydBaseModel):
    """Result of a remote control command."""

    control_state: ControlState = Field(validation_alias="controlState")
    success: bool
    request_serial: str | None = Field(default=None, validation_alias="requestSerial")

    @model_validator(mode="before")
    @classmethod
    def _normalize_shapes(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        merged = dict(values)

        # Immediate result format: {"res": 2, ...}
        if "res" in merged and "controlState" not in merged and "control_state" not in merged:
            res_val = int(merged["res"])
            state = ControlState.SUCCESS if res_val == 2 else ControlState.FAILURE
            merged["controlState"] = int(state)
            merged.setdefault("success", state == ControlState.SUCCESS)

        # Standard polled format: {"controlState": 0/1/2, ...}
        if "controlState" in merged and "success" not in merged:
            try:
                state = ControlState(int(merged["controlState"]))
            except ValueError:
                state = ControlState.PENDING
            merged["controlState"] = int(state)
            merged["success"] = state == ControlState.SUCCESS

        return merged


# ------------------------------------------------------------------
# Command acknowledgement responses
# ------------------------------------------------------------------


class CommandAck(BydBaseModel):
    """Generic acknowledgement response for write/toggle endpoints."""

    vin: str = ""
    result: str | None = None


class VerifyControlPasswordResponse(BydBaseModel):
    """Response from the control password verification endpoint."""

    vin: str = ""
    ok: bool | None = None


# ------------------------------------------------------------------
# Control parameter payloads (serialised to ``controlParamsMap``)
# ------------------------------------------------------------------


class ControlParams(BaseModel):
    """Base class for control-parameter models."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        str_strip_whitespace=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )

    def to_control_params_map(self) -> dict[str, Any]:
        """Return a dict that can be JSON-encoded into ``controlParamsMap``."""
        return self.model_dump(by_alias=True, exclude_none=True)


class ClimateStartParams(ControlParams):
    """Parameters for starting HVAC (commandType ``OPENAIR``).

    Temperatures are specified in °C (15-31) and automatically converted
    to BYD's internal scale (1-17) on serialisation.
    """

    temperature: float | None = Field(default=None, ge=15.0, le=31.0)
    """Driver temperature setpoint in °C (15-31)."""

    copilot_temperature: float | None = Field(default=None, ge=15.0, le=31.0)
    """Passenger temperature setpoint in °C (15-31)."""

    cycle_mode: int | None = Field(default=None, ge=0)
    """Air recirculation/cycle mode code."""

    time_span: int | None = Field(default=None, ge=1, le=5)
    """Run duration code (1=10min, 2=15min, 3=20min, 4=25min, 5=30min)."""

    ac_switch: int | None = Field(default=None, ge=0, le=1)
    air_accuracy: int | None = Field(default=None, ge=0)
    air_conditioning_mode: int | None = Field(default=None, ge=0)
    remote_mode: int | None = Field(default=None, ge=0)
    wind_level: int | None = Field(default=None, ge=0)
    wind_position: int | None = Field(default=None, ge=0)

    @field_serializer("temperature")
    def _serialize_temperature(self, value: float | None) -> int | None:
        return celsius_to_scale(value) if value is not None else None

    @field_serializer("copilot_temperature")
    def _serialize_copilot_temperature(self, value: float | None) -> int | None:
        return celsius_to_scale(value) if value is not None else None

    def to_control_params_map(self) -> dict[str, Any]:
        """Return a dict that can be JSON-encoded into ``controlParamsMap``."""
        data = self.model_dump(by_alias=True, exclude_none=True)
        # Map temperature fields to BYD's expected keys.
        if "temperature" in data:
            data["mainSettingTemp"] = data.pop("temperature")
        if "copilotTemperature" in data:
            data["copilotSettingTemp"] = data.pop("copilotTemperature")
        return data


class ClimateScheduleParams(ClimateStartParams):
    """Parameters for scheduling HVAC (commandType ``BOOKINGAIR``)."""

    booking_id: int = Field(..., ge=1)
    """Schedule booking ID."""

    booking_time: int = Field(..., ge=1)
    """Schedule time as epoch seconds."""


def _coerce_int(value: Any) -> int:
    """Coerce BYD command inputs to an int.

    This keeps the previous behaviour where values like "1" are accepted.
    """

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("must be an integer") from exc


SeatLevel: TypeAlias = Annotated[Literal[0, 1, 2, 3], BeforeValidator(_coerce_int)]
OnOffInt: TypeAlias = Annotated[Literal[0, 1], BeforeValidator(_coerce_int)]


class SeatClimateParams(ControlParams):
    """Parameters for seat heating/ventilation (commandType ``VENTILATIONHEATING``).

    Values use the *command* scale:
    - 0 = off
    - 1 = low
    - 2 = medium
    - 3 = high
    """

    main_heat: SeatLevel | None = None
    main_ventilation: SeatLevel | None = None
    copilot_heat: SeatLevel | None = None
    copilot_ventilation: SeatLevel | None = None
    lr_seat_heat: SeatLevel | None = None
    lr_seat_ventilation: SeatLevel | None = None
    rr_seat_heat: SeatLevel | None = None
    rr_seat_ventilation: SeatLevel | None = None
    steering_wheel_heat: OnOffInt | None = None


class BatteryHeatParams(ControlParams):
    """Parameters for battery heating (commandType ``BATTERYHEAT``)."""

    on: bool = Field(..., serialization_alias="batteryHeatSwitch")

    @field_serializer("on")
    def _serialize_on(self, value: bool) -> int:
        return 1 if value else 0
