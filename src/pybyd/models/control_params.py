"""Typed models for remote-control ``controlParamsMap`` payloads.

BYD's remote-control endpoints accept an optional ``controlParamsMap`` field
inside the inner payload. The server expects this value to be a **JSON string**
representing an object of command-specific parameters.

pyBYD serialises these dicts in :func:`pybyd._api.control._build_control_inner`.
This module provides typed helpers so downstream apps can build validated,
command-appropriate param maps without manually dealing with BYD key names.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


class ControlParams(BaseModel):
    """Base class for control-parameter models."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        str_strip_whitespace=True,
    )

    def to_control_params_map(self) -> dict[str, Any]:
        """Return a dict that can be JSON-encoded into ``controlParamsMap``."""
        return self.model_dump(by_alias=True, exclude_none=True)


class ClimateStartParams(ControlParams):
    """Parameters for starting HVAC (commandType ``OPENAIR``).

    Public API is expressed in Python-friendly names; :meth:`to_control_params_map`
    encodes the BYD key names.

    Notes
    -----
    BYD uses a temperature *scale* (1-17) rather than °C for command payloads.
    hass-byd and existing probe scripts use the same scale.
    """

    TEMP_MIN_C: ClassVar[float] = 15.0
    TEMP_MAX_C: ClassVar[float] = 31.0
    TEMP_OFFSET_C: ClassVar[float] = 14.0
    SCALE_MIN: ClassVar[int] = 1
    SCALE_MAX: ClassVar[int] = 17

    # --- Commonly used knobs (known from hass-byd + probe scripts) ---
    preset: Literal["max_heat", "max_cool"] | None = Field(default=None, exclude=True)
    """Convenience preset.

    - ``max_heat`` maps to BYD scale 17 (≈31°C)
    - ``max_cool`` maps to BYD scale 1 (≈15°C)

    Mutually exclusive with explicit temperature inputs.
    """

    temperature: int | None = Field(default=None, serialization_alias="mainSettingTemp")
    """Driver temperature setpoint on BYD scale (1-17)."""

    temperature_c: float | None = Field(default=None, exclude=True)
    """Driver temperature setpoint in °C (15-31). Converted to scale if set."""

    copilot_temperature: int | None = Field(default=None, serialization_alias="copilotSettingTemp")
    """Passenger temperature setpoint on BYD scale (1-17)."""

    copilot_temperature_c: float | None = Field(default=None, exclude=True)
    """Passenger temperature setpoint in °C (15-31). Converted to scale if set."""

    cycle_mode: int | None = Field(default=None, serialization_alias="cycleMode")
    """Air recirculation/cycle mode code (mapping unconfirmed)."""

    time_span: int | None = Field(default=None, serialization_alias="timeSpan")
    """Run duration.

    BYD encodes duration as a small integer code in ``timeSpan``:

    - 1 = 10 minutes
    - 2 = 15 minutes
    - 3 = 20 minutes
    - 4 = 25 minutes
    - 5 = 30 minutes

    For convenience, callers may pass either the code (1-5) or a supported
    minute value (10/15/20/25/30); pyBYD will normalize to the code.
    """

    @staticmethod
    def _normalize_time_span(value: int) -> int:
        code_to_minutes = {1: 10, 2: 15, 3: 20, 4: 25, 5: 30}
        minutes_to_code = {v: k for k, v in code_to_minutes.items()}

        raw = int(value)
        if raw in code_to_minutes:
            return raw
        if raw in minutes_to_code:
            return minutes_to_code[raw]
        raise ValueError("time_span must be one of 1..5 (code) or 10/15/20/25/30 (minutes)")

    # --- Extended knobs (observed in raw captures) ---
    ac_switch: int | None = Field(default=None, serialization_alias="acSwitch")
    """A/C switch (0/1). Some vehicles report remote starts without flipping this."""

    air_accuracy: int | None = Field(default=None, serialization_alias="airAccuracy")
    """Air accuracy code (mapping unconfirmed)."""

    air_conditioning_mode: int | None = Field(default=None, serialization_alias="airConditioningMode")
    """Air conditioning mode code (mapping unconfirmed)."""

    remote_mode: int | None = Field(default=None, serialization_alias="remoteMode")
    """Remote mode code (mapping unconfirmed; 2 observed in captures)."""

    wind_level: int | None = Field(default=None, serialization_alias="windLevel")
    """Fan speed level code (mapping unconfirmed)."""

    wind_position: int | None = Field(default=None, serialization_alias="windPosition")
    """Airflow direction code (mapping unconfirmed)."""

    @staticmethod
    def _celsius_to_scale(temp_c: float) -> int:
        value = float(temp_c)
        if not ClimateStartParams.TEMP_MIN_C <= value <= ClimateStartParams.TEMP_MAX_C:
            raise ValueError(
                f"temperature_c must be between {ClimateStartParams.TEMP_MIN_C} and {ClimateStartParams.TEMP_MAX_C}"
            )
        scale = int(round(value - ClimateStartParams.TEMP_OFFSET_C))
        return max(ClimateStartParams.SCALE_MIN, min(ClimateStartParams.SCALE_MAX, scale))

    @model_validator(mode="before")
    @classmethod
    def _convert_celsius_inputs(cls, data: Any) -> Any:
        """Convert optional °C inputs into the BYD scale during validation."""
        if not isinstance(data, dict):
            return data

        preset = data.get("preset")
        if preset is not None:
            if data.get("temperature") is not None or data.get("temperature_c") is not None:
                raise ValueError("preset cannot be combined with temperature/temperature_c")
            if preset not in ("max_heat", "max_cool"):
                raise ValueError("preset must be 'max_heat' or 'max_cool'")
            data = {
                **data,
                "temperature": cls.SCALE_MAX if preset == "max_heat" else cls.SCALE_MIN,
            }

        if data.get("temperature") is not None and data.get("temperature_c") is not None:
            raise ValueError("Provide either temperature (scale) or temperature_c, not both")
        if data.get("copilot_temperature") is not None and data.get("copilot_temperature_c") is not None:
            raise ValueError("Provide either copilot_temperature (scale) or copilot_temperature_c, not both")

        if data.get("temperature") is None and data.get("temperature_c") is not None:
            data = {**data, "temperature": cls._celsius_to_scale(float(data["temperature_c"]))}
        if data.get("copilot_temperature") is None and data.get("copilot_temperature_c") is not None:
            data = {**data, "copilot_temperature": cls._celsius_to_scale(float(data["copilot_temperature_c"]))}

        if data.get("time_span") is not None:
            data = {**data, "time_span": cls._normalize_time_span(int(data["time_span"]))}

        return data

    @model_validator(mode="after")
    def _validate_ranges(self) -> ClimateStartParams:
        def _check_scale(name: str, value: int | None) -> None:
            if value is None:
                return
            if not self.SCALE_MIN <= int(value) <= self.SCALE_MAX:
                raise ValueError(f"{name} must be between {self.SCALE_MIN} and {self.SCALE_MAX}")

        _check_scale("temperature", self.temperature)
        _check_scale("copilot_temperature", self.copilot_temperature)

        if self.time_span is not None:
            # Already normalized in the before validator; keep this as a guard.
            self._normalize_time_span(int(self.time_span))

        if self.ac_switch is not None and int(self.ac_switch) not in (0, 1):
            raise ValueError("ac_switch must be 0 or 1")

        for field_name in (
            "air_accuracy",
            "air_conditioning_mode",
            "cycle_mode",
            "remote_mode",
            "wind_level",
            "wind_position",
        ):
            value = getattr(self, field_name)
            if value is not None and int(value) < 0:
                raise ValueError(f"{field_name} must be >= 0")

        return self

    @field_serializer("time_span")
    def _serialize_time_span(self, value: int | None) -> int | None:
        if value is None:
            return None
        return self._normalize_time_span(int(value))

    def optimistic_hvac_patch_on(self) -> dict[str, Any]:
        """Best-effort optimistic HVAC patch for the state store."""
        patch: dict[str, Any] = {"status": 2}
        if self.temperature is not None:
            patch["main_setting_temp"] = int(self.temperature)
            patch["main_setting_temp_new"] = float(int(self.temperature) + self.TEMP_OFFSET_C)
        if self.copilot_temperature is not None:
            patch["copilot_setting_temp"] = int(self.copilot_temperature)
            patch["copilot_setting_temp_new"] = float(int(self.copilot_temperature) + self.TEMP_OFFSET_C)
        return patch

    @classmethod
    def from_inputs(
        cls,
        *,
        params: ClimateStartParams | None = None,
        preset: Literal["max_heat", "max_cool"] | None = None,
        temperature: int | None = None,
        temperature_c: float | None = None,
        copilot_temperature: int | None = None,
        copilot_temperature_c: float | None = None,
        cycle_mode: int | None = None,
        time_span: int | None = None,
        ac_switch: int | None = None,
        air_accuracy: int | None = None,
        air_conditioning_mode: int | None = None,
        remote_mode: int | None = None,
        wind_level: int | None = None,
        wind_position: int | None = None,
    ) -> ClimateStartParams:
        if params is not None:
            extras = {
                "preset": preset,
                "temperature": temperature,
                "temperature_c": temperature_c,
                "copilot_temperature": copilot_temperature,
                "copilot_temperature_c": copilot_temperature_c,
                "cycle_mode": cycle_mode,
                "time_span": time_span,
                "ac_switch": ac_switch,
                "air_accuracy": air_accuracy,
                "air_conditioning_mode": air_conditioning_mode,
                "remote_mode": remote_mode,
                "wind_level": wind_level,
                "wind_position": wind_position,
            }
            if any(v is not None for v in extras.values()):
                raise ValueError("Pass either params=... or individual climate arguments, not both")
            return params

        return cls(
            preset=preset,
            temperature=temperature,
            temperature_c=temperature_c,
            copilot_temperature=copilot_temperature,
            copilot_temperature_c=copilot_temperature_c,
            cycle_mode=cycle_mode,
            time_span=time_span,
            ac_switch=ac_switch,
            air_accuracy=air_accuracy,
            air_conditioning_mode=air_conditioning_mode,
            remote_mode=remote_mode,
            wind_level=wind_level,
            wind_position=wind_position,
        )


class ClimateScheduleParams(ClimateStartParams):
    """Parameters for scheduling HVAC (commandType ``BOOKINGAIR``)."""

    booking_id: int = Field(..., ge=1, serialization_alias="bookingId")
    """Schedule booking ID."""

    booking_time: int = Field(..., ge=1, serialization_alias="bookingTime")
    """Schedule time as epoch seconds."""

    @classmethod
    def from_schedule_inputs(
        cls,
        *,
        params: ClimateScheduleParams | None = None,
        preset: Literal["max_heat", "max_cool"] | None = None,
        temperature: int | None = None,
        temperature_c: float | None = None,
        copilot_temperature: int | None = None,
        copilot_temperature_c: float | None = None,
        cycle_mode: int | None = None,
        time_span: int | None = None,
        ac_switch: int | None = None,
        air_accuracy: int | None = None,
        air_conditioning_mode: int | None = None,
        remote_mode: int | None = None,
        wind_level: int | None = None,
        wind_position: int | None = None,
        booking_id: int | None = None,
        booking_time: int | None = None,
    ) -> ClimateScheduleParams:
        if params is None:
            if booking_id is None or booking_time is None:
                raise ValueError("booking_id and booking_time are required when params is not provided")
            return cls(
                booking_id=booking_id,
                booking_time=booking_time,
                preset=preset,
                temperature=temperature,
                temperature_c=temperature_c,
                copilot_temperature=copilot_temperature,
                copilot_temperature_c=copilot_temperature_c,
                cycle_mode=cycle_mode,
                time_span=time_span,
                ac_switch=ac_switch,
                air_accuracy=air_accuracy,
                air_conditioning_mode=air_conditioning_mode,
                remote_mode=remote_mode,
                wind_level=wind_level,
                wind_position=wind_position,
            )

        extras = {
            "preset": preset,
            "temperature": temperature,
            "temperature_c": temperature_c,
            "copilot_temperature": copilot_temperature,
            "copilot_temperature_c": copilot_temperature_c,
            "cycle_mode": cycle_mode,
            "time_span": time_span,
            "ac_switch": ac_switch,
            "air_accuracy": air_accuracy,
            "air_conditioning_mode": air_conditioning_mode,
            "remote_mode": remote_mode,
            "wind_level": wind_level,
            "wind_position": wind_position,
        }
        if booking_id is not None or booking_time is not None or any(v is not None for v in extras.values()):
            raise ValueError("Pass either params=... or individual schedule arguments, not both")
        if not isinstance(params, ClimateScheduleParams):
            raise TypeError("params must be a ClimateScheduleParams instance")
        return params


class SeatClimateParams(ControlParams):
    """Parameters for seat heating/ventilation (commandType ``VENTILATIONHEATING``).

    Values use the *command* scale observed by hass-byd:
    - 0 = off
    - 1 = low
    - 3 = high

    (Status scale returned by the API differs; callers should map status → command.
    hass-byd does this when building a full snapshot.)

    The exact BYD key names are based on observed naming patterns but remain
    partially unconfirmed. If you capture a trace showing different keys,
    update :meth:`to_control_params_map`.
    """

    main_heat: int | None = Field(default=None, serialization_alias="mainHeat")
    main_ventilation: int | None = Field(default=None, serialization_alias="mainVentilation")
    copilot_heat: int | None = Field(default=None, serialization_alias="copilotHeat")
    copilot_ventilation: int | None = Field(default=None, serialization_alias="copilotVentilation")
    lr_seat_heat: int | None = Field(default=None, serialization_alias="lrSeatHeat")
    lr_seat_ventilation: int | None = Field(default=None, serialization_alias="lrSeatVentilation")
    rr_seat_heat: int | None = Field(default=None, serialization_alias="rrSeatHeat")
    rr_seat_ventilation: int | None = Field(default=None, serialization_alias="rrSeatVentilation")
    steering_wheel_heat: int | None = Field(default=None, serialization_alias="steeringWheelHeat")

    @model_validator(mode="after")
    def _validate_levels(self) -> SeatClimateParams:
        for name in (
            "main_heat",
            "main_ventilation",
            "copilot_heat",
            "copilot_ventilation",
            "lr_seat_heat",
            "lr_seat_ventilation",
            "rr_seat_heat",
            "rr_seat_ventilation",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            level = int(value)
            if level not in (0, 1, 2, 3):
                raise ValueError(f"{name} must be one of 0, 1, 2, 3")

        if self.steering_wheel_heat is not None and int(self.steering_wheel_heat) not in (0, 1):
            raise ValueError("steering_wheel_heat must be 0 or 1")

        return self

    @classmethod
    def from_inputs(
        cls,
        *,
        params: SeatClimateParams | None = None,
        main_heat: int | None = None,
        main_ventilation: int | None = None,
        copilot_heat: int | None = None,
        copilot_ventilation: int | None = None,
        lr_seat_heat: int | None = None,
        lr_seat_ventilation: int | None = None,
        rr_seat_heat: int | None = None,
        rr_seat_ventilation: int | None = None,
        steering_wheel_heat: int | None = None,
    ) -> SeatClimateParams:
        if params is not None:
            extras = {
                "main_heat": main_heat,
                "main_ventilation": main_ventilation,
                "copilot_heat": copilot_heat,
                "copilot_ventilation": copilot_ventilation,
                "lr_seat_heat": lr_seat_heat,
                "lr_seat_ventilation": lr_seat_ventilation,
                "rr_seat_heat": rr_seat_heat,
                "rr_seat_ventilation": rr_seat_ventilation,
                "steering_wheel_heat": steering_wheel_heat,
            }
            if any(v is not None for v in extras.values()):
                raise ValueError("Pass either params=... or individual seat arguments, not both")
            return params

        # If nothing is provided, default to a full "off" snapshot.
        if all(
            v is None
            for v in (
                main_heat,
                main_ventilation,
                copilot_heat,
                copilot_ventilation,
                lr_seat_heat,
                lr_seat_ventilation,
                rr_seat_heat,
                rr_seat_ventilation,
                steering_wheel_heat,
            )
        ):
            return cls(
                main_heat=0,
                main_ventilation=0,
                copilot_heat=0,
                copilot_ventilation=0,
                lr_seat_heat=0,
                lr_seat_ventilation=0,
                rr_seat_heat=0,
                rr_seat_ventilation=0,
                steering_wheel_heat=0,
            )

        return cls(
            main_heat=main_heat,
            main_ventilation=main_ventilation,
            copilot_heat=copilot_heat,
            copilot_ventilation=copilot_ventilation,
            lr_seat_heat=lr_seat_heat,
            lr_seat_ventilation=lr_seat_ventilation,
            rr_seat_heat=rr_seat_heat,
            rr_seat_ventilation=rr_seat_ventilation,
            steering_wheel_heat=steering_wheel_heat,
        )


class BatteryHeatParams(ControlParams):
    """Parameters for battery heating (commandType ``BATTERYHEAT``)."""

    on: bool = Field(..., serialization_alias="batteryHeatSwitch")

    @field_serializer("on")
    def _serialize_on(self, value: bool) -> int:
        return 1 if value else 0

    @classmethod
    def from_inputs(
        cls,
        *,
        params: BatteryHeatParams | None = None,
        on: bool | None = None,
    ) -> BatteryHeatParams:
        if params is None:
            if on is None:
                raise ValueError("on must be provided when params is not provided")
            return cls(on=bool(on))
        if on is not None:
            raise ValueError("Pass either params=... or on=..., not both")
        return params


class ControlCallOptions(BaseModel):
    """Shared options for issuing a remote command."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        str_strip_whitespace=True,
    )

    command_pwd: str | None = None
    poll_attempts: int = 10
    poll_interval: float = 1.5
