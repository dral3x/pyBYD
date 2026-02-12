"""HVAC / climate control status model.

Mapped from ``/control/getStatusNow`` response documented in API_MAPPING.md.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from pybyd.models.realtime import SeatHeatVentState


@dataclasses.dataclass(frozen=True)
class HvacStatus:
    """Current HVAC / climate control state.

    All original data is available in the ``raw`` dict.
    """

    # --- A/C state ---
    ac_switch: int | None
    """A/C master switch (0=off, 1=on)."""
    status: int | None
    """Overall HVAC status."""
    air_conditioning_mode: int | None
    """A/C mode."""
    wind_mode: int | None
    """Fan mode."""
    wind_position: int | None
    """Airflow direction."""
    cycle_choice: int | None
    """Air recirculation mode code (mapping still unconfirmed)."""

    # --- Temperature ---
    main_setting_temp: int | None
    """Driver-side set temperature (integer)."""
    main_setting_temp_new: float | None
    """Driver-side set temperature (precise, °C)."""
    copilot_setting_temp: int | None
    """Passenger-side set temperature (integer)."""
    copilot_setting_temp_new: float | None
    """Passenger-side set temperature (precise, °C)."""
    temp_in_car: float | None
    """Interior temperature (°C, -129=unavailable)."""
    temp_out_car: float | None
    """Exterior temperature (°C)."""
    whether_support_adjust_temp: int | None
    """Whether temperature adjustment is supported (1=yes)."""

    # --- Defrost ---
    front_defrost_status: int | None
    """Front defrost active."""
    electric_defrost_status: int | None
    """Electric defrost active."""
    wiper_heat_status: int | None
    """Wiper heating active."""

    # --- Seat heating/ventilation ---
    # Observed status scale: 0=off, 2=low, 3=high
    # Value 1 = feature available but inactive (not a SeatHeatVentState member)
    # (Note: command scale is different: 0=off, 1-3=levels)
    main_seat_heat_state: SeatHeatVentState | int | None
    """Driver seat heating level (0=off, 2=low, 3=high)."""
    main_seat_ventilation_state: SeatHeatVentState | int | None
    """Driver seat ventilation level (0=off, 2=low, 3=high)."""
    copilot_seat_heat_state: SeatHeatVentState | int | None
    """Passenger seat heating level (0=off, 2=low, 3=high)."""
    copilot_seat_ventilation_state: SeatHeatVentState | int | None
    """Passenger seat ventilation level (0=off, 2=low, 3=high)."""
    steering_wheel_heat_state: SeatHeatVentState | int | None
    """Steering wheel heating (0=off, 2=low, 3=high)."""
    lr_seat_heat_state: SeatHeatVentState | int | None
    """Left rear seat heating level (0=off, 2=low, 3=high)."""
    lr_seat_ventilation_state: SeatHeatVentState | int | None
    """Left rear seat ventilation level (0=off, 2=low, 3=high)."""
    rr_seat_heat_state: SeatHeatVentState | int | None
    """Right rear seat heating level (0=off, 2=low, 3=high)."""
    rr_seat_ventilation_state: SeatHeatVentState | int | None
    """Right rear seat ventilation level (0=off, 2=low, 3=high)."""

    # --- Rapid temperature changes ---
    rapid_increase_temp_state: int | None
    """Rapid heating active."""
    rapid_decrease_temp_state: int | None
    """Rapid cooling active."""

    # --- Refrigerator ---
    refrigerator_state: int | None
    """Refrigerator active."""
    refrigerator_door_state: int | None
    """Refrigerator door state."""

    # --- Air quality ---
    pm: int | None
    """PM2.5 reading."""
    pm25_state_out_car: int | None
    """Outside PM2.5 state."""

    raw: dict[str, Any]
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
        if self.status is not None and self.status >= 2:
            return True
        return False

    @property
    def interior_temp_available(self) -> bool:
        """Whether interior temperature reading is valid."""
        return self.temp_in_car is not None and self.temp_in_car != -129
