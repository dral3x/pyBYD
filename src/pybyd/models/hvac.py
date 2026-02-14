"""HVAC / climate control status model.

Mapped from ``/control/getStatusNow`` response documented in API_MAPPING.md.
"""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from pybyd.ingestion.normalize import safe_float, safe_int, to_enum
from pybyd.models.realtime import SeatHeatVentState


class HvacStatus(BaseModel):
    """Current HVAC / climate control state.

    All original data is available in the ``raw`` dict.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=True,
    )

    # --- A/C state ---
    ac_switch: int | None = Field(default=None, validation_alias=AliasChoices("acSwitch", "ac_switch"))
    """A/C master switch (0=off, 1=on)."""
    status: int | None = Field(default=None)
    """Overall HVAC status."""
    air_conditioning_mode: int | None = Field(
        default=None, validation_alias=AliasChoices("airConditioningMode", "air_conditioning_mode")
    )
    """A/C mode."""
    wind_mode: int | None = Field(default=None, validation_alias=AliasChoices("windMode", "wind_mode"))
    """Fan mode."""
    wind_position: int | None = Field(default=None, validation_alias=AliasChoices("windPosition", "wind_position"))
    """Airflow direction."""
    cycle_choice: int | None = Field(default=None, validation_alias=AliasChoices("cycleChoice", "cycle_choice"))
    """Air recirculation mode code (mapping still unconfirmed)."""

    # --- Temperature ---
    main_setting_temp: int | None = Field(
        default=None, validation_alias=AliasChoices("mainSettingTemp", "main_setting_temp")
    )
    """Driver-side set temperature (integer)."""
    main_setting_temp_new: float | None = Field(
        default=None, validation_alias=AliasChoices("mainSettingTempNew", "main_setting_temp_new")
    )
    """Driver-side set temperature (precise, °C)."""
    copilot_setting_temp: int | None = Field(
        default=None, validation_alias=AliasChoices("copilotSettingTemp", "copilot_setting_temp")
    )
    """Passenger-side set temperature (integer)."""
    copilot_setting_temp_new: float | None = Field(
        default=None, validation_alias=AliasChoices("copilotSettingTempNew", "copilot_setting_temp_new")
    )
    """Passenger-side set temperature (precise, °C)."""
    temp_in_car: float | None = Field(default=None, validation_alias=AliasChoices("tempInCar", "temp_in_car"))
    """Interior temperature (°C, -129=unavailable)."""
    temp_out_car: float | None = Field(default=None, validation_alias=AliasChoices("tempOutCar", "temp_out_car"))
    """Exterior temperature (°C)."""
    whether_support_adjust_temp: int | None = Field(
        default=None, validation_alias=AliasChoices("whetherSupportAdjustTemp", "whether_support_adjust_temp")
    )
    """Whether temperature adjustment is supported (1=yes)."""

    # --- Defrost ---
    front_defrost_status: int | None = Field(
        default=None, validation_alias=AliasChoices("frontDefrostStatus", "front_defrost_status")
    )
    """Front defrost active."""
    electric_defrost_status: int | None = Field(
        default=None, validation_alias=AliasChoices("electricDefrostStatus", "electric_defrost_status")
    )
    """Electric defrost active."""
    wiper_heat_status: int | None = Field(
        default=None, validation_alias=AliasChoices("wiperHeatStatus", "wiper_heat_status")
    )
    """Wiper heating active."""

    # --- Seat heating/ventilation ---
    # Observed status scale: 0=off, 2=low, 3=high
    # Value 1 = feature available but inactive (not a SeatHeatVentState member)
    # (Note: command scale is different: 0=off, 1-3=levels)
    main_seat_heat_state: SeatHeatVentState | int | None = Field(
        default=None, validation_alias=AliasChoices("mainSeatHeatState", "main_seat_heat_state")
    )
    """Driver seat heating level (0=off, 2=low, 3=high)."""
    main_seat_ventilation_state: SeatHeatVentState | int | None = Field(
        default=None,
        validation_alias=AliasChoices("mainSeatVentilationState", "main_seat_ventilation_state"),
    )
    """Driver seat ventilation level (0=off, 2=low, 3=high)."""
    copilot_seat_heat_state: SeatHeatVentState | int | None = Field(
        default=None, validation_alias=AliasChoices("copilotSeatHeatState", "copilot_seat_heat_state")
    )
    """Passenger seat heating level (0=off, 2=low, 3=high)."""
    copilot_seat_ventilation_state: SeatHeatVentState | int | None = Field(
        default=None,
        validation_alias=AliasChoices("copilotSeatVentilationState", "copilot_seat_ventilation_state"),
    )
    """Passenger seat ventilation level (0=off, 2=low, 3=high)."""
    steering_wheel_heat_state: SeatHeatVentState | int | None = Field(
        default=None, validation_alias=AliasChoices("steeringWheelHeatState", "steering_wheel_heat_state")
    )
    """Steering wheel heating (0=off, 2=low, 3=high)."""
    lr_seat_heat_state: SeatHeatVentState | int | None = Field(
        default=None, validation_alias=AliasChoices("lrSeatHeatState", "lr_seat_heat_state")
    )
    """Left rear seat heating level (0=off, 2=low, 3=high)."""
    lr_seat_ventilation_state: SeatHeatVentState | int | None = Field(
        default=None, validation_alias=AliasChoices("lrSeatVentilationState", "lr_seat_ventilation_state")
    )
    """Left rear seat ventilation level (0=off, 2=low, 3=high)."""
    rr_seat_heat_state: SeatHeatVentState | int | None = Field(
        default=None, validation_alias=AliasChoices("rrSeatHeatState", "rr_seat_heat_state")
    )
    """Right rear seat heating level (0=off, 2=low, 3=high)."""
    rr_seat_ventilation_state: SeatHeatVentState | int | None = Field(
        default=None, validation_alias=AliasChoices("rrSeatVentilationState", "rr_seat_ventilation_state")
    )
    """Right rear seat ventilation level (0=off, 2=low, 3=high)."""

    # --- Rapid temperature changes ---
    rapid_increase_temp_state: int | None = Field(
        default=None, validation_alias=AliasChoices("rapidIncreaseTempState", "rapid_increase_temp_state")
    )
    """Rapid heating active."""
    rapid_decrease_temp_state: int | None = Field(
        default=None, validation_alias=AliasChoices("rapidDecreaseTempState", "rapid_decrease_temp_state")
    )
    """Rapid cooling active."""

    # --- Refrigerator ---
    refrigerator_state: int | None = Field(
        default=None, validation_alias=AliasChoices("refrigeratorState", "refrigerator_state")
    )
    """Refrigerator active."""
    refrigerator_door_state: int | None = Field(
        default=None, validation_alias=AliasChoices("refrigeratorDoorState", "refrigerator_door_state")
    )
    """Refrigerator door state."""

    # --- Air quality ---
    pm: int | None = Field(default=None)
    """PM2.5 reading."""
    pm25_state_out_car: int | None = Field(
        default=None, validation_alias=AliasChoices("pm25StateOutCar", "pm25_state_out_car")
    )
    """Outside PM2.5 state."""

    raw: dict[str, Any] = Field(default_factory=dict)
    """Full ``statusNow`` dict."""

    @property
    def is_ac_on(self) -> bool:
        """Whether the A/C is currently running.

        Checks both ``ac_switch`` (manual on) and ``status`` (remote-start
        sets ``status=2`` without flipping ``acSwitch``).
        """
        if self.ac_switch == 1:
            return True
        # Remote climate start sets status=2 while acSwitch stays 0
        return bool(self.status is not None and self.status >= 2)

    @property
    def interior_temp_available(self) -> bool:
        """Whether interior temperature reading is valid."""
        return self.temp_in_car is not None and self.temp_in_car != -129

    @model_validator(mode="before")
    @classmethod
    def _unwrap_status_now(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        status_now = values.get("statusNow")
        if isinstance(status_now, dict):
            merged = dict(status_now)
            merged.setdefault("raw", status_now)
            return merged
        merged = dict(values)
        merged.setdefault("raw", values)
        return merged

    @field_validator(
        "ac_switch",
        "status",
        "air_conditioning_mode",
        "wind_mode",
        "wind_position",
        "cycle_choice",
        "main_setting_temp",
        "copilot_setting_temp",
        "whether_support_adjust_temp",
        "front_defrost_status",
        "electric_defrost_status",
        "wiper_heat_status",
        "rapid_increase_temp_state",
        "rapid_decrease_temp_state",
        "refrigerator_state",
        "refrigerator_door_state",
        "pm",
        "pm25_state_out_car",
        mode="before",
    )
    @classmethod
    def _coerce_ints(cls, value: Any) -> int | None:
        return safe_int(value)

    @field_validator(
        "main_setting_temp_new",
        "copilot_setting_temp_new",
        "temp_in_car",
        "temp_out_car",
        mode="before",
    )
    @classmethod
    def _coerce_floats(cls, value: Any) -> float | None:
        return safe_float(value)

    @field_validator(
        "main_seat_heat_state",
        "main_seat_ventilation_state",
        "copilot_seat_heat_state",
        "copilot_seat_ventilation_state",
        "steering_wheel_heat_state",
        "lr_seat_heat_state",
        "lr_seat_ventilation_state",
        "rr_seat_heat_state",
        "rr_seat_ventilation_state",
        mode="before",
    )
    @classmethod
    def _coerce_seat_states(cls, value: Any) -> SeatHeatVentState | int | None:
        return to_enum(SeatHeatVentState, value)
