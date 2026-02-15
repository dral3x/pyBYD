"""HVAC / climate control status model.

Mapped from ``/control/getStatusNow`` response documented in API_MAPPING.md.
"""

from __future__ import annotations

from typing import Any

from pydantic import model_validator

from pybyd._constants import celsius_to_scale
from pybyd.models._base import BydBaseModel, BydEnum
from pybyd.models.realtime import AirCirculationMode, SeatHeatVentState, StearingWheelHeat

__all__ = [
    "AcSwitch",
    "AirConditioningMode",
    "HvacOverallStatus",
    "HvacStatus",
    "HvacWindMode",
    "HvacWindPosition",
    "celsius_to_scale",
]


class AcSwitch(BydEnum):
    """AcSwitch on/off state."""

    UNKNOWN = -1
    OFF = 0
    ON = 1


class HvacOverallStatus(BydEnum):
    """Overall HVAC system status.

    Only a subset of values are confirmed. Unknown values are preserved
    by typing fields as ``HvacOverallStatus | int | None``.
    """

    UNKNOWN = -1
    MODE_2 = 2 // find out.


class AirConditioningMode(BydEnum):
    """A/C mode code.

    Only value ``1`` has been observed so far.
    """

    UNKNOWN = -1
    MODE_1 = 1 // find out.


class HvacWindMode(BydEnum):
    """Fan (wind) mode code.

    Only value ``3`` has been observed so far.
    """

    UNKNOWN = -1
    MODE_3 = 3 // find out.


class HvacWindPosition(BydEnum):
    """Airflow direction code (wind position).

    Mapping not confirmed yet; keep ``| int`` in the model to preserve
    raw codes.
    """

    UNKNOWN = -1


class HvacStatus(BydBaseModel):
    """Current HVAC / climate control state."""

    # --- A/C state ---
    ac_switch: AcSwitch | int | None = None
    status: HvacOverallStatus | int | None = None
    air_conditioning_mode: AirConditioningMode | int | None = None
    wind_mode: HvacWindMode | int | None = None
    wind_position: HvacWindPosition | int | None = None
    cycle_choice: AirCirculationMode | int | None = None

    # --- Temperature ---
    main_setting_temp: float | None = None
    """Driver-side set temperature on BYD scale (1-17)."""
    main_setting_temp_new: float | None = None
    """Driver-side set temperature (°C, precise)."""
    copilot_setting_temp: float | None = None
    """Passenger-side set temperature on BYD scale (1-17)."""
    copilot_setting_temp_new: float | None = None
    """Passenger-side set temperature (°C, precise)."""
    temp_in_car: float | None = None
    temp_out_car: float | None = None
    whether_support_adjust_temp: int | None = None

    # --- Defrost ---
    front_defrost_status: int | None = None
    electric_defrost_status: int | None = None
    wiper_heat_status: int | None = None

    # --- Seat heating / ventilation ---
    main_seat_heat_state: SeatHeatVentState | None = None
    main_seat_ventilation_state: SeatHeatVentState | None = None
    copilot_seat_heat_state: SeatHeatVentState | None = None
    copilot_seat_ventilation_state: SeatHeatVentState | None = None
    steering_wheel_heat_state: StearingWheelHeat | None = None
    lr_seat_heat_state: SeatHeatVentState | None = None
    lr_seat_ventilation_state: SeatHeatVentState | None = None
    rr_seat_heat_state: SeatHeatVentState | None = None
    rr_seat_ventilation_state: SeatHeatVentState | None = None

    # --- Rapid temperature changes ---
    rapid_increase_temp_state: int | None = None
    rapid_decrease_temp_state: int | None = None

    # --- Refrigerator ---
    refrigerator_state: int | None = None
    refrigerator_door_state: int | None = None

    # --- Air quality ---
    pm: float | None = None
    pm25_state_out_car: float | None = None

    @property
    def is_ac_on(self) -> bool:
        if self.ac_switch == AcSwitch.ON:
            return True
        return bool(self.status is not None and self.status >= 2)

    @property
    def interior_temp_available(self) -> bool:
        return self.temp_in_car is not None and self.temp_in_car != -129

    @model_validator(mode="before")
    @classmethod
    def _unwrap_status_now(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        status_now = values.get("statusNow")
        if isinstance(status_now, dict):
            return status_now
        return values
