"""Vehicle realtime data model.

Enum values and field meanings are documented in API_MAPPING.md.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pybyd.models._base import BydBaseModel, BydEnum, BydTimestamp

# ------------------------------------------------------------------
# Enums
# ------------------------------------------------------------------


class OnlineState(BydEnum):
    """Vehicle online/offline state."""

    UNKNOWN = -1
    ONLINE = 1
    OFFLINE = 2


class ConnectState(BydEnum):
    """T-Box connection state.

    Note: observed as ``-1`` even while the vehicle is online and driving.
    The exact semantics of this field vs ``OnlineState`` are unclear.
    """

    UNKNOWN = -1
    DISCONNECTED = 0
    CONNECTED = 1


class VehicleState(BydEnum):
    """Vehicle power state.

    Observed realtime mapping:
    - ``0`` = on
    - ``2`` = off

    Value ``1`` is still observed (e.g. in vehicle-list payloads), but
    realtime semantics for that code remain unclear.
    """

    UNKNOWN = -1
    ON = 0
    OFF = 2


class ChargingState(BydEnum):
    """Charging state indicator.

    Used for both ``charging_state`` and ``charge_state`` fields.
    ``0`` means connected but not actively charging.
    ``15`` means the charge gun is plugged in but not charging.
    """

    UNKNOWN = -1
    NOT_CHARGING = 0
    CHARGING = 1
    GUN_CONNECTED = 15


class TirePressureUnit(BydEnum):
    """Unit used for tire pressure readings."""

    UNKNOWN = -1
    BAR = 1
    PSI = 2
    KPA = 3


class DoorOpenState(BydEnum):
    """Door/trunk open/closed state."""

    UNKNOWN = -1
    CLOSED = 0
    OPEN = 1


class LockState(BydEnum):
    """Door lock state."""

    UNKNOWN = -1
    UNLOCKED = 1
    LOCKED = 2


class WindowState(BydEnum):
    """Window open/closed state."""

    UNKNOWN = -1
    CLOSED = 1
    OPEN = 2


class PowerGear(BydEnum):
    """Transmission gear position.

    Known values from observations.  Unknown values fall back to
    ``UNKNOWN`` via ``BydEnum._missing_``.
    """

    UNKNOWN = -1
    PARKED = 1
    DRIVE = 3


class StearingWheelHeat(BydEnum):
    """Stearing wheel heating level.

    Observed from live API data:
    - 0 = off
    - 1 = on

    """

    UNKNOWN = -1
    OFF = 0
    ON = 1

class SeatHeatVentState(BydEnum):
    """Seat heating / ventilation / steering wheel heat level.

    Observed from live API data:
    - 0 = off
    - 2 = low
    - 3 = high

    Value ``1`` appears when the feature is available but inactive
    (e.g. front seats while driving).
    """

    UNKNOWN = -1
    OFF = 0
    LOW = 2
    HIGH = 3


class AirCirculationMode(BydEnum):
    """Air circulation mode."""

    UNKNOWN = -1
    EXTERNAL = 0
    INTERNAL = 1
    OUTSIDE_FRESH_2 = 2


# ------------------------------------------------------------------
# Key aliases: BYD API key -> canonical camelCase key
# ------------------------------------------------------------------

_KEY_ALIASES: dict[str, str] = {
    "backCover": "trunkLid",
    "leftFrontTirepressure": "leftFrontTirePressure",
    "rightFrontTirepressure": "rightFrontTirePressure",
    "leftRearTirepressure": "leftRearTirePressure",
    "rightRearTirepressure": "rightRearTirePressure",
    "abs": "absWarning",
    "time": "timestamp",
    "recent50kmEnergy": "recent50KmEnergy",
}


class VehicleRealtimeData(BydBaseModel):
    """Realtime telemetry data for a vehicle.

    Numeric fields are ``None`` when the value is absent or
    unparseable from the API response.  All original data is
    available in the ``raw`` dict.
    """

    _KEY_ALIASES: ClassVar[dict[str, str]] = _KEY_ALIASES

    # --- Connection & state ---
    online_state: OnlineState = OnlineState.UNKNOWN
    connect_state: ConnectState = ConnectState.UNKNOWN
    vehicle_state: VehicleState = VehicleState.UNKNOWN
    request_serial: str | None = None

    # --- Battery & range ---
    elec_percent: float | None = None
    """Battery state of charge (0-100 %)."""
    power_battery: float | None = None
    """Alternative battery percentage field."""
    endurance_mileage: float | None = None
    """Estimated remaining EV range (km)."""
    ev_endurance: float | None = None
    """Alternative EV range field."""
    endurance_mileage_v2: float | None = None
    endurance_mileage_v2_unit: str | None = None
    """Unit for endurance_mileage_v2 ('--' when unavailable)."""
    total_mileage: float | None = None
    """Odometer reading (km)."""
    total_mileage_v2: float | None = None
    """V2 odometer field."""
    total_mileage_v2_unit: str | None = None
    """Unit for total_mileage_v2."""

    # --- Driving ---
    speed: float | None = None
    """Current speed (km/h)."""
    power_gear: PowerGear | None = None
    """Gear position (1=parked, 3=drive)."""

    # --- Climate ---
    temp_in_car: float | None = None
    """Interior temperature (deg C). ``-129.0`` means unavailable / car offline."""
    main_setting_temp: int | None = None
    """Driver-side set temperature on BYD scale (1-17)."""
    main_setting_temp_new: float | None = None
    """Driver-side set temperature (°C, precise)."""
    air_run_state: AirCirculationMode | None = None
    """Air circulation mode (0=external, 1=internal)."""

    # --- Seat heating/ventilation ---
    main_seat_heat_state: SeatHeatVentState | None = None
    """Driver seat heating level (0=off, 2=low, 3=high)."""
    main_seat_ventilation_state: SeatHeatVentState | None = None
    """Driver seat ventilation level (0=off, 2=low, 3=high)."""
    copilot_seat_heat_state: SeatHeatVentState | None = None
    """Passenger seat heating level (0=off, 2=low, 3=high)."""
    copilot_seat_ventilation_state: SeatHeatVentState | None = None
    """Passenger seat ventilation level (0=off, 2=low, 3=high)."""
    steering_wheel_heat_state: StearingWheelHeat | None = None
    """Steering wheel heating state (0=off, 2=low, 3=high)."""
    lr_seat_heat_state: SeatHeatVentState | None = None
    """Left rear seat heating level (0=off, 2=low, 3=high)."""
    lr_seat_ventilation_state: SeatHeatVentState | None = None
    """Left rear seat ventilation level (0=off, 2=low, 3=high)."""
    rr_seat_heat_state: SeatHeatVentState | None = None
    """Right rear seat heating level (0=off, 2=low, 3=high)."""
    rr_seat_ventilation_state: SeatHeatVentState | None = None
    """Right rear seat ventilation level (0=off, 2=low, 3=high)."""

    # --- Charging ---
    charging_state: ChargingState = ChargingState.UNKNOWN
    """Charging state (-1=unknown, 0=not charging, 15=gun connected)."""
    charge_state: ChargingState | None = None
    """Charge gun state (-1=unknown, 15=gun plugged in, not charging)."""
    wait_status: int | None = None
    """Charge wait status."""
    full_hour: int | None = None
    """Estimated hours to full charge (-1=N/A)."""
    full_minute: int | None = None
    """Estimated minutes to full charge (-1=N/A)."""
    remaining_hours: int | None = None
    """Remaining hours component."""
    remaining_minutes: int | None = None
    """Remaining minutes component."""
    booking_charge_state: int | None = None
    """Scheduled charging state (0=off)."""
    booking_charging_hour: int | None = None
    """Scheduled charge start hour."""
    booking_charging_minute: int | None = None
    """Scheduled charge start minute."""

    # --- Doors ---
    left_front_door: DoorOpenState | None = None
    right_front_door: DoorOpenState | None = None
    left_rear_door: DoorOpenState | None = None
    right_rear_door: DoorOpenState | None = None
    trunk_lid: DoorOpenState | None = None
    sliding_door: DoorOpenState | None = None
    """Sliding door state (0=closed, 1=open)."""
    forehold: DoorOpenState | None = None
    """Front trunk/frunk state (0=closed, 1=open)."""

    # --- Locks ---
    left_front_door_lock: LockState | None = None
    right_front_door_lock: LockState | None = None
    left_rear_door_lock: LockState | None = None
    right_rear_door_lock: LockState | None = None
    sliding_door_lock: LockState | None = None

    # --- Windows ---
    left_front_window: WindowState | None = None
    right_front_window: WindowState | None = None
    left_rear_window: WindowState | None = None
    right_rear_window: WindowState | None = None
    skylight: WindowState | None = None

    # --- Tire pressure ---
    left_front_tire_pressure: float | None = None
    right_front_tire_pressure: float | None = None
    left_rear_tire_pressure: float | None = None
    right_rear_tire_pressure: float | None = None
    left_front_tire_status: int | None = None
    right_front_tire_status: int | None = None
    left_rear_tire_status: int | None = None
    right_rear_tire_status: int | None = None
    tire_press_unit: TirePressureUnit | None = None
    """1=bar, 2=psi, 3=kPa."""
    tirepressure_system: int | None = None
    """Tire pressure monitoring system state."""
    rapid_tire_leak: int | None = None
    """Rapid tire leak detected (0=no)."""

    # --- Energy consumption ---
    total_power: float | None = None
    total_energy: str | None = None
    """Total energy (string, '--' when unavailable)."""
    nearest_energy_consumption: str | None = None
    """Nearest energy consumption (string, '--' when unavailable)."""
    nearest_energy_consumption_unit: str | None = None
    """Unit for nearest energy consumption."""
    recent_50km_energy: str | None = None
    """Recent 50km energy (string, '--' when unavailable)."""

    # --- Fuel (hybrid vehicles) ---
    oil_endurance: float | None = None
    """Fuel-based range (km)."""
    oil_percent: float | None = None
    """Fuel percentage."""
    total_oil: float | None = None
    """Total fuel consumption."""

    # --- System indicators ---
    power_system: int | None = None
    engine_status: int | None = None
    epb: int | None = None
    """Electronic parking brake."""
    eps: int | None = None
    """Electric power steering warning."""
    esp: int | None = None
    """Electronic stability program warning."""
    abs_warning: int | None = None
    """ABS warning light."""
    svs: int | None = None
    """Service vehicle soon."""
    srs: int | None = None
    """Supplemental restraint system (airbag) warning."""
    ect: int | None = None
    """Engine coolant temperature warning."""
    ect_value: int | None = None
    """Engine coolant temperature value."""
    pwr: int | None = None
    """Power warning."""

    # --- Feature states ---
    sentry_status: int | None = None
    """Sentry/dashcam mode (0=off, 1=on)."""
    battery_heat_state: int | None = None
    """Battery heating state."""
    charge_heat_state: int | None = None
    """Charge heating state."""
    upgrade_status: int | None = None
    """OTA upgrade status."""

    # --- Metadata ---
    timestamp: BydTimestamp = None
    """Data timestamp from the ``time`` field (parsed to UTC datetime)."""

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_ready_raw(vehicle_info: dict[str, Any]) -> bool:
        """Return True if a raw realtime payload appears to contain meaningful data."""
        if not vehicle_info:
            return False
        if vehicle_info.get("onlineState") == int(OnlineState.OFFLINE):
            return False

        tire_fields = [
            "leftFrontTirepressure",
            "rightFrontTirepressure",
            "leftRearTirepressure",
            "rightRearTirepressure",
        ]
        if any(float(vehicle_info.get(f) or 0) > 0 for f in tire_fields):
            return True
        if int(vehicle_info.get("time") or 0) > 0:
            return True
        return float(vehicle_info.get("enduranceMileage") or 0) > 0

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

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
