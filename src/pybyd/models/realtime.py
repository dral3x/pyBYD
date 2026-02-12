"""Vehicle realtime data model.

Enum values and field meanings are documented in API_MAPPING.md.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any


class OnlineState(enum.IntEnum):
    """Vehicle online/offline state."""

    UNKNOWN = 0
    ONLINE = 1
    OFFLINE = 2


class ConnectState(enum.IntEnum):
    """T-Box connection state.

    Note: observed as ``-1`` even while the vehicle is online and driving.
    The exact semantics of this field vs ``OnlineState`` are unclear.
    """

    UNKNOWN = -1
    DISCONNECTED = 0
    CONNECTED = 1


class VehicleState(enum.IntEnum):
    """Vehicle power state.

    Note: observed as ``0`` even while the vehicle is actively driving,
    so the semantics are unclear. Do not rely on this for on/off detection.
    """

    STANDBY = 0
    ACTIVE = 1


class ChargingState(enum.IntEnum):
    """Charging state indicator.

    Used for both ``charging_state`` and ``charge_state`` fields.
    ``-1`` indicates the charge gun is disconnected.
    ``0`` means connected but not actively charging.
    ``15`` means the charge gun is plugged in but not charging.
    """

    DISCONNECTED = -1
    NOT_CHARGING = 0
    GUN_CONNECTED = 15


class TirePressureUnit(enum.IntEnum):
    """Unit used for tire pressure readings."""

    BAR = 1
    PSI = 2
    KPA = 3


class DoorOpenState(enum.IntEnum):
    """Door/trunk open/closed state."""

    CLOSED = 0
    OPEN = 1


class LockState(enum.IntEnum):
    """Door lock state."""

    LOCKED = 2
    UNLOCKED = 1


class WindowState(enum.IntEnum):
    """Window open/closed state."""

    CLOSED = 1
    OPEN = 2


class PowerGear(enum.IntEnum):
    """Transmission gear position.

    Known values from observations. Unknown values fall through
    as raw ``int`` via ``_to_enum``.
    """

    PARKED = 1
    DRIVE = 3


class SeatHeatVentState(enum.IntEnum):
    """Seat heating / ventilation / steering wheel heat level.

    Observed from live API data:
    - 0 = off
    - 2 = low
    - 3 = high

    Value ``1`` appears when the feature is available but inactive
    (e.g. front seats while driving); it is not a defined member
    and will be returned as a raw ``int`` by the parser.
    """

    OFF = 0
    LOW = 2
    HIGH = 3


class AirCirculationMode(enum.IntEnum):
    """Air circulation mode."""

    EXTERNAL = 0
    INTERNAL = 1


@dataclasses.dataclass(frozen=True)
class VehicleRealtimeData:
    """Realtime telemetry data for a vehicle.

    Numeric fields are ``None`` when the value is absent or
    unparseable from the API response. All original data is
    available in the ``raw`` dict.
    """

    # --- Connection & state ---
    online_state: OnlineState
    connect_state: ConnectState
    vehicle_state: VehicleState | int
    request_serial: str | None

    # --- Battery & range ---
    elec_percent: float | None
    """Battery state of charge (0–100 %)."""  # noqa: RUF002
    power_battery: float | None
    """Alternative battery percentage field."""
    endurance_mileage: float | None
    """Estimated remaining EV range (km)."""
    ev_endurance: float | None
    """Alternative EV range field."""
    endurance_mileage_v2: float | None
    """V2 range field (may use different units)."""
    endurance_mileage_v2_unit: str | None
    """Unit for endurance_mileage_v2 ('--' when unavailable)."""
    total_mileage: float | None
    """Odometer reading (km)."""
    total_mileage_v2: float | None
    """V2 odometer field."""
    total_mileage_v2_unit: str | None
    """Unit for total_mileage_v2."""

    # --- Driving ---
    speed: float | None
    """Current speed (km/h)."""
    power_gear: PowerGear | None
    """Gear position (1=parked, 3=drive)."""

    # --- Climate ---
    temp_in_car: float | None
    """Interior temperature (°C). ``-129.0`` means unavailable / car offline."""
    main_setting_temp: int | None
    """Driver-side set temperature for cabin A/C (integer)."""
    main_setting_temp_new: float | None
    """Driver-side set temperature (precise, °C)."""
    air_run_state: AirCirculationMode | int | None
    """Air circulation mode (0=external, 1=internal; unknown values kept as int)."""

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
    """Steering wheel heating state (0=off, 2=low, 3=high)."""
    lr_seat_heat_state: SeatHeatVentState | int | None
    """Left rear seat heating level (0=off, 2=low, 3=high)."""
    lr_seat_ventilation_state: SeatHeatVentState | int | None
    """Left rear seat ventilation level (0=off, 2=low, 3=high)."""
    rr_seat_heat_state: SeatHeatVentState | int | None
    """Right rear seat heating level (0=off, 2=low, 3=high)."""
    rr_seat_ventilation_state: SeatHeatVentState | int | None
    """Right rear seat ventilation level (0=off, 2=low, 3=high)."""

    # --- Charging ---
    charging_state: ChargingState | int
    """Charging state (-1=disconnected, 0=not charging, 15=gun connected)."""
    charge_state: ChargingState | int | None
    """Charge gun state (-1=disconnected, 15=gun plugged in, not charging)."""
    wait_status: int | None
    """Charge wait status."""
    full_hour: int | None
    """Estimated hours to full charge (-1=N/A)."""
    full_minute: int | None
    """Estimated minutes to full charge (-1=N/A)."""
    charge_remaining_hours: int | None
    """Remaining hours component."""
    charge_remaining_minutes: int | None
    """Remaining minutes component."""
    booking_charge_state: int | None
    """Scheduled charging state (0=off)."""
    booking_charging_hour: int | None
    """Scheduled charge start hour."""
    booking_charging_minute: int | None
    """Scheduled charge start minute."""

    # --- Doors ---
    left_front_door: DoorOpenState | None
    right_front_door: DoorOpenState | None
    left_rear_door: DoorOpenState | None
    right_rear_door: DoorOpenState | None
    trunk_lid: DoorOpenState | None
    sliding_door: DoorOpenState | None
    """Sliding door state (0=closed, 1=open)."""
    forehold: DoorOpenState | None
    """Front trunk/frunk state (0=closed, 1=open)."""

    # --- Locks ---
    left_front_door_lock: LockState | None
    right_front_door_lock: LockState | None
    left_rear_door_lock: LockState | None
    right_rear_door_lock: LockState | None
    sliding_door_lock: LockState | None

    # --- Windows ---
    left_front_window: WindowState | None
    right_front_window: WindowState | None
    left_rear_window: WindowState | None
    right_rear_window: WindowState | None
    skylight: WindowState | None

    # --- Tire pressure ---
    left_front_tire_pressure: float | None
    right_front_tire_pressure: float | None
    left_rear_tire_pressure: float | None
    right_rear_tire_pressure: float | None
    left_front_tire_status: int | None
    right_front_tire_status: int | None
    left_rear_tire_status: int | None
    right_rear_tire_status: int | None
    tire_press_unit: TirePressureUnit | None
    """1=bar, 2=psi, 3=kPa."""
    tirepressure_system: int | None
    """Tire pressure monitoring system state."""
    rapid_tire_leak: int | None
    """Rapid tire leak detected (0=no)."""

    # --- Energy consumption ---
    total_power: float | None
    total_energy: str | None
    """Total energy (string, '--' when unavailable)."""
    nearest_energy_consumption: str | None
    """Nearest energy consumption (string, '--' when unavailable)."""
    nearest_energy_consumption_unit: str | None
    """Unit for nearest energy consumption."""
    recent_50km_energy: str | None
    """Recent 50km energy (string, '--' when unavailable)."""

    # --- Fuel (hybrid vehicles) ---
    oil_endurance: float | None
    """Fuel-based range (km)."""
    oil_percent: float | None
    """Fuel percentage."""
    total_oil: float | None
    """Total fuel consumption."""

    # --- System indicators ---
    power_system: int | None
    engine_status: int | None
    epb: int | None
    """Electronic parking brake."""
    eps: int | None
    """Electric power steering warning."""
    esp: int | None
    """Electronic stability program warning."""
    abs_warning: int | None
    """ABS warning light."""
    svs: int | None
    """Service vehicle soon."""
    srs: int | None
    """Supplemental restraint system (airbag) warning."""
    ect: int | None
    """Engine coolant temperature warning."""
    ect_value: int | None
    """Engine coolant temperature value."""
    pwr: int | None
    """Power warning."""

    # --- Feature states ---
    sentry_status: int | None
    """Sentry/dashcam mode (0=off, 1=on)."""
    battery_heat_state: int | None
    """Battery heating state."""
    charge_heat_state: int | None
    """Charge heating state."""
    upgrade_status: int | None
    """OTA upgrade status."""

    # --- Metadata ---
    timestamp: int | None
    """Data timestamp from the ``time`` field."""
    raw: dict[str, Any]
    """Full API response dict."""

    # --- Convenience properties ---

    @property
    def is_online(self) -> bool:
        """Whether the vehicle is reporting as online."""
        return self.online_state == OnlineState.ONLINE

    @property
    def is_charging(self) -> bool:
        """Whether the vehicle is currently charging.

        Returns ``True`` when ``charging_state`` is positive and **not**
        equal to ``GUN_CONNECTED`` (15), which indicates the plug is
        inserted but charging is not active.
        """
        return self.charging_state > 0 and self.charging_state != ChargingState.GUN_CONNECTED

    @property
    def interior_temp_available(self) -> bool:
        """Whether interior temperature reading is valid (not sentinel)."""
        return self.temp_in_car is not None and self.temp_in_car != -129.0

    @property
    def is_locked(self) -> bool:
        """Whether all doors are locked (True if all known locks == LOCKED)."""
        locks = [
            self.left_front_door_lock,
            self.right_front_door_lock,
            self.left_rear_door_lock,
            self.right_rear_door_lock,
        ]
        known = [lk for lk in locks if lk is not None]
        return len(known) > 0 and all(lk == LockState.LOCKED for lk in known)

    @property
    def is_any_door_open(self) -> bool:
        """Whether any door/trunk/frunk is open."""
        doors = [
            self.left_front_door,
            self.right_front_door,
            self.left_rear_door,
            self.right_rear_door,
            self.trunk_lid,
            self.sliding_door,
            self.forehold,
        ]
        return any(d == DoorOpenState.OPEN for d in doors if d is not None)

    @property
    def is_any_window_open(self) -> bool:
        """Whether any window is open."""
        windows = [
            self.left_front_window,
            self.right_front_window,
            self.left_rear_window,
            self.right_rear_window,
            self.skylight,
        ]
        return any(w == WindowState.OPEN for w in windows if w is not None)
