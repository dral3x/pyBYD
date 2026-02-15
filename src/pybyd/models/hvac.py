"""HVAC / climate control status model.

Mapped from ``/control/getStatusNow`` response documented in API_MAPPING.md.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import model_validator

from pybyd._constants import celsius_to_scale
from pybyd.models._base import COMMON_KEY_ALIASES, BydBaseModel, BydEnum, is_temp_sentinel
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
    """AcSwitch on/off state.

    From BYD SDK ``getAcStartState()`` (section 6.6.6).
    """

    UNKNOWN = -1
    OFF = 0  # assumed from BYD SDK: AC_POWER_OFF
    ON = 1  # assumed from BYD SDK: AC_POWER_ON


class HvacOverallStatus(BydEnum):
    """Overall HVAC status.

    API_MAPPING notes: ``2`` observed while A/C active (confirmed).
    """

    UNKNOWN = -1
    ACTIVE = 2


class AirConditioningMode(BydEnum):
    """A/C control mode code.

    From BYD SDK ``getAcControlMode()`` (section 6.6.7).
    ``1`` observed in live data (confirmed), assumed AUTO per SDK.
    """

    UNKNOWN = -1
    AUTO = 1  # observed value=1 per API_MAPPING; assumed from BYD SDK: AC_CTRLMODE_AUTO
    MANUAL = 2  # assumed from BYD SDK: AC_CTRLMODE_MANUAL


class HvacWindMode(BydEnum):
    """Fan (wind) mode — airflow direction.

    From BYD SDK ``getAcWindMode()`` (section 6.6.9).
    Value ``3`` observed in live data (confirmed).
    """

    UNKNOWN = -1
    FACE = 1  # assumed from BYD SDK: AC_WINDMODE_FACE (blow to face)
    FACE_FOOT = 2  # assumed from BYD SDK: AC_WINDMODE_FACEFOOT (face + feet)
    FOOT = 3  # observed value=3 per API_MAPPING; assumed from BYD SDK: AC_WINDMODE_FOOT
    FOOT_DEFROST = 4  # assumed from BYD SDK: AC_WINDMODE_FOOTDEFROST (feet + defrost)
    DEFROST = 5  # assumed from BYD SDK: AC_WINDMODE_DEFROST


class HvacWindPosition(BydEnum):
    """Airflow direction code (wind position).

    API_MAPPING notes: airflow direction (unconfirmed).
    May overlap with ``HvacWindMode``; exact semantics still unclear.
    """

    UNKNOWN = -1


class HvacStatus(BydBaseModel):
    """Current HVAC / climate control state."""

    _KEY_ALIASES: ClassVar[dict[str, str]] = {
        **COMMON_KEY_ALIASES,
    }

    _SENTINEL_RULES: ClassVar[dict[str, Callable[..., bool]]] = {
        "temp_in_car": is_temp_sentinel,
    }

    # --- A/C state ---
    ac_switch: AcSwitch | int | None = None
    """0=off, 1=on (confirmed)."""
    status: HvacOverallStatus | int | None = None
    """Overall HVAC status; ``2`` observed while A/C active (confirmed)."""
    air_conditioning_mode: AirConditioningMode | int | None = None
    """Mode code; ``1`` observed (confirmed)."""
    wind_mode: HvacWindMode | int | None = None
    """Fan mode code; ``3`` observed (confirmed)."""
    wind_position: HvacWindPosition | int | None = None
    """Airflow direction (unconfirmed)."""
    cycle_choice: AirCirculationMode | int | None = None
    """``2`` observed in live capture (confirmed); exact mapping still unconfirmed."""

    # --- Temperature ---
    main_setting_temp: float | None = None
    """Set temp integer on BYD scale (1-17) (confirmed)."""
    main_setting_temp_new: float | None = None
    """Set temp (°C, precise) (confirmed)."""
    copilot_setting_temp: float | None = None
    """Passenger set temp on BYD scale (1-17) (confirmed)."""
    copilot_setting_temp_new: float | None = None
    """Passenger set temp (°C, precise) (confirmed)."""
    temp_in_car: float | None = None
    """Interior °C; ``-129`` means unavailable (confirmed)."""
    temp_out_car: float | None = None
    """Exterior °C (confirmed)."""
    whether_support_adjust_temp: int | None = None
    """1=supported (confirmed)."""

    # --- Defrost ---
    front_defrost_status: int | None = None
    """Front defrost status.  0=off, 1=on (confirmed).
    BYD SDK ``getAcDefrostState(FRONT)`` (section 6.6.10)."""
    electric_defrost_status: int | None = None
    """Rear (electric) defrost status.  0=off (confirmed).
    BYD SDK ``getAcDefrostState(REAR)`` (section 6.6.10)."""
    wiper_heat_status: int | None = None
    """Wiper heater status.  0=off (confirmed)."""

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
    """PM2.5 value; 0 observed (confirmed).
    BYD SDK ``getPM25Value()`` (section 6.7.5)."""
    pm25_state_out_car: float | None = None
    """Outside PM2.5 state; 0 observed (confirmed).
    BYD SDK ``getPM25Level(OUT)`` (section 6.7.4)."""

    @property
    def is_ac_on(self) -> bool:
        # Prefer the explicit switch state when present.
        # Some vehicles/reporting paths appear to leave `status` at an
        # "active" code briefly after the switch flips off, so treating
        # `status>=2` as authoritative can cause false positives.
        if self.ac_switch is not None:
            try:
                if int(self.ac_switch) == int(AcSwitch.ON):
                    return True
                if int(self.ac_switch) == int(AcSwitch.OFF):
                    return False
            except (TypeError, ValueError):
                # Fall through to status-based heuristic.
                pass

        if self.status is None:
            return False
        try:
            return int(self.status) >= int(HvacOverallStatus.ACTIVE)
        except (TypeError, ValueError):
            return False

    @property
    def is_climate_active(self) -> bool:
        """Whether the HVAC system appears active.

        This is a more permissive signal than :pyattr:`is_ac_on` and is
        intended for consumers that want a best-effort "climate running"
        indicator even when the explicit switch field is missing or
        temporarily inconsistent.
        """

        if self.ac_switch is not None:
            try:
                if int(self.ac_switch) == int(AcSwitch.ON):
                    return True
            except (TypeError, ValueError):
                pass

        if self.status is None:
            return False
        try:
            return int(self.status) >= int(HvacOverallStatus.ACTIVE)
        except (TypeError, ValueError):
            return False

    @property
    def interior_temp_available(self) -> bool:
        """Whether interior temperature reading is valid.

        After sentinel normalisation ``temp_in_car`` is ``None`` when
        the BYD API returned ``-129``, so a simple ``is not None`` suffices.
        """
        return self.temp_in_car is not None

    @property
    def is_steering_wheel_heating(self) -> bool | None:
        """Whether steering wheel heating is active.

        Returns ``None`` when the state is unknown.
        """
        if self.steering_wheel_heat_state is None:
            return None
        return self.steering_wheel_heat_state == StearingWheelHeat.ON

    @model_validator(mode="before")
    @classmethod
    def _unwrap_status_now(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        status_now = values.get("statusNow")
        if isinstance(status_now, dict):
            # The parent _clean_byd_values ran on the outer dict before
            # this validator.  Re-clean the inner dict so sentinel values
            # (e.g. "--", "") inside statusNow are properly stripped.
            aliases: dict[str, str] = getattr(cls, "_KEY_ALIASES", {})
            return BydBaseModel._clean_dict(status_now, aliases)
        return values
