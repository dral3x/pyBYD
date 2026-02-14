"""Vehicle realtime data model.

Enum values and field meanings are documented in API_MAPPING.md.
"""

from __future__ import annotations

import enum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from pybyd.ingestion.normalize import (
    non_negative_or_zero,
    safe_float,
    safe_int,
    safe_str,
    to_enum,
)


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

    Observed realtime mapping:
    - ``0`` = on
    - ``2`` = off

    Value ``1`` is still observed (e.g. in vehicle-list payloads), but
    realtime semantics for that code remain unclear.
    """

    ON = 0
    UNKNOWN_1 = 1
    OFF = 2


class ChargingState(enum.IntEnum):
    """Charging state indicator.

    Used for both ``charging_state`` and ``charge_state`` fields.
    ``-1`` indicates the charge gun is disconnected.
    ``0`` means connected but not actively charging.
    ``15`` means the charge gun is plugged in but not charging.
    """

    DISCONNECTED = -1
    NOT_CHARGING = 0
    CHARGING = 1
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

    UNKNOWN = 0
    UNLOCKED = 1
    LOCKED = 2


class WindowState(enum.IntEnum):
    """Window open/closed state."""

    UNKNOWN = 0
    CLOSED = 1
    OPEN = 2


class PowerGear(enum.IntEnum):
    """Transmission gear position.

    Known values from observations. Unknown values fall through
    as raw ``int`` via ``_to_enum``.
    """

    UNKNOWN = 0
    PARKED = 1
    DRIVE = 3


class SeatHeatVentState(enum.IntEnum):
    """Seat heating / ventilation / steering wheel heat level.

    Observed from live API data:
    - 0 = off
    - 2 = low
    - 3 = high

    Value ``1`` appears when the feature is available but inactive
    (e.g. front seats while driving).
    """

    OFF = 0
    LOW = 2
    HIGH = 3


class AirCirculationMode(enum.IntEnum):
    """Air circulation mode."""

    EXTERNAL = 0
    INTERNAL = 1
    OUTSIDE_FRESH_2 = 2


class VehicleRealtimeData(BaseModel):
    """Realtime telemetry data for a vehicle.

    Numeric fields are ``None`` when the value is absent or
    unparseable from the API response. All original data is
    available in the ``raw`` dict.
    """

    model_config = ConfigDict(frozen=True)

    # --- Connection & state ---
    online_state: OnlineState | int
    connect_state: ConnectState | int
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
    power_gear: PowerGear | int | None
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
    # Value 1 = feature available but inactive
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
    left_front_door: DoorOpenState | int | None
    right_front_door: DoorOpenState | int | None
    left_rear_door: DoorOpenState | int | None
    right_rear_door: DoorOpenState | int | None
    trunk_lid: DoorOpenState | int | None
    sliding_door: DoorOpenState | int | None
    """Sliding door state (0=closed, 1=open)."""
    forehold: DoorOpenState | int | None
    """Front trunk/frunk state (0=closed, 1=open)."""

    # --- Locks ---
    left_front_door_lock: LockState | int | None
    right_front_door_lock: LockState | int | None
    left_rear_door_lock: LockState | int | None
    right_rear_door_lock: LockState | int | None
    sliding_door_lock: LockState | int | None

    # --- Windows ---
    left_front_window: WindowState | int | None
    right_front_window: WindowState | int | None
    left_rear_window: WindowState | int | None
    right_rear_window: WindowState | int | None
    skylight: WindowState | int | None

    # --- Tire pressure ---
    left_front_tire_pressure: float | None
    right_front_tire_pressure: float | None
    left_rear_tire_pressure: float | None
    right_rear_tire_pressure: float | None
    left_front_tire_status: int | None
    right_front_tire_status: int | None
    left_rear_tire_status: int | None
    right_rear_tire_status: int | None
    tire_press_unit: TirePressureUnit | int | None
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

    @classmethod
    def is_ready_raw(cls, vehicle_info: dict[str, Any]) -> bool:
        """Return True if a raw realtime payload appears to contain meaningful data."""

        if not vehicle_info:
            return False
        if safe_int(vehicle_info.get("onlineState")) == int(OnlineState.OFFLINE):
            return False

        tire_fields = [
            "leftFrontTirepressure",
            "rightFrontTirepressure",
            "leftRearTirepressure",
            "rightRearTirepressure",
        ]
        if any((safe_float(vehicle_info.get(f)) or 0) > 0 for f in tire_fields):
            return True
        if (safe_int(vehicle_info.get("time")) or 0) > 0:
            return True
        return (safe_float(vehicle_info.get("enduranceMileage")) or 0) > 0

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> VehicleRealtimeData:
        """Parse a raw API realtime dict into a typed model.

        This is the single normalization boundary for realtime payloads, used by both
        HTTP polling and MQTT enrichment.
        """

        return cls(
            # Connection & state
            online_state=cast(OnlineState | int, to_enum(OnlineState, data.get("onlineState"), OnlineState.UNKNOWN)),
            connect_state=cast(
                ConnectState | int,
                to_enum(ConnectState, data.get("connectState"), ConnectState.UNKNOWN),
            ),
            vehicle_state=cast(VehicleState | int, to_enum(VehicleState, data.get("vehicleState"), VehicleState.ON)),
            request_serial=safe_str(data.get("requestSerial")),
            # Battery & range
            elec_percent=safe_float(data.get("elecPercent")),
            power_battery=safe_float(data.get("powerBattery")),
            endurance_mileage=safe_float(data.get("enduranceMileage")),
            ev_endurance=safe_float(data.get("evEndurance")),
            endurance_mileage_v2=safe_float(data.get("enduranceMileageV2")),
            endurance_mileage_v2_unit=safe_str(data.get("enduranceMileageV2Unit")),
            total_mileage=safe_float(data.get("totalMileage")),
            total_mileage_v2=safe_float(data.get("totalMileageV2")),
            total_mileage_v2_unit=safe_str(data.get("totalMileageV2Unit")),
            # Driving
            speed=safe_float(data.get("speed")),
            power_gear=to_enum(PowerGear, data.get("powerGear")),
            # Climate
            temp_in_car=safe_float(data.get("tempInCar")),
            main_setting_temp=safe_int(data.get("mainSettingTemp")),
            main_setting_temp_new=safe_float(data.get("mainSettingTempNew")),
            air_run_state=to_enum(AirCirculationMode, data.get("airRunState")),
            # Seat heating/ventilation
            main_seat_heat_state=to_enum(SeatHeatVentState, data.get("mainSeatHeatState")),
            main_seat_ventilation_state=to_enum(SeatHeatVentState, data.get("mainSeatVentilationState")),
            copilot_seat_heat_state=to_enum(SeatHeatVentState, data.get("copilotSeatHeatState")),
            copilot_seat_ventilation_state=to_enum(SeatHeatVentState, data.get("copilotSeatVentilationState")),
            steering_wheel_heat_state=to_enum(SeatHeatVentState, data.get("steeringWheelHeatState")),
            lr_seat_heat_state=to_enum(SeatHeatVentState, data.get("lrSeatHeatState")),
            lr_seat_ventilation_state=to_enum(SeatHeatVentState, data.get("lrSeatVentilationState")),
            rr_seat_heat_state=to_enum(SeatHeatVentState, data.get("rrSeatHeatState")),
            rr_seat_ventilation_state=to_enum(SeatHeatVentState, data.get("rrSeatVentilationState")),
            # Charging
            charging_state=cast(
                ChargingState | int,
                to_enum(ChargingState, data.get("chargingState"), ChargingState.DISCONNECTED),
            ),
            charge_state=to_enum(ChargingState, data.get("chargeState")),
            wait_status=safe_int(data.get("waitStatus")),
            full_hour=non_negative_or_zero(data.get("fullHour")),
            full_minute=non_negative_or_zero(data.get("fullMinute")),
            charge_remaining_hours=non_negative_or_zero(data.get("remainingHours")),
            charge_remaining_minutes=non_negative_or_zero(data.get("remainingMinutes")),
            booking_charge_state=safe_int(data.get("bookingChargeState")),
            booking_charging_hour=safe_int(data.get("bookingChargingHour")),
            booking_charging_minute=safe_int(data.get("bookingChargingMinute")),
            # Doors
            left_front_door=to_enum(DoorOpenState, data.get("leftFrontDoor")),
            right_front_door=to_enum(DoorOpenState, data.get("rightFrontDoor")),
            left_rear_door=to_enum(DoorOpenState, data.get("leftRearDoor")),
            right_rear_door=to_enum(DoorOpenState, data.get("rightRearDoor")),
            trunk_lid=to_enum(
                DoorOpenState,
                data.get("trunkLid") if data.get("trunkLid") is not None else data.get("backCover"),
            ),
            sliding_door=to_enum(DoorOpenState, data.get("slidingDoor")),
            forehold=to_enum(DoorOpenState, data.get("forehold")),
            # Locks
            left_front_door_lock=to_enum(LockState, data.get("leftFrontDoorLock")),
            right_front_door_lock=to_enum(LockState, data.get("rightFrontDoorLock")),
            left_rear_door_lock=to_enum(LockState, data.get("leftRearDoorLock")),
            right_rear_door_lock=to_enum(LockState, data.get("rightRearDoorLock")),
            sliding_door_lock=to_enum(LockState, data.get("slidingDoorLock")),
            # Windows
            left_front_window=to_enum(WindowState, data.get("leftFrontWindow")),
            right_front_window=to_enum(WindowState, data.get("rightFrontWindow")),
            left_rear_window=to_enum(WindowState, data.get("leftRearWindow")),
            right_rear_window=to_enum(WindowState, data.get("rightRearWindow")),
            skylight=to_enum(WindowState, data.get("skylight")),
            # Tire pressure
            left_front_tire_pressure=safe_float(data.get("leftFrontTirepressure")),
            right_front_tire_pressure=safe_float(data.get("rightFrontTirepressure")),
            left_rear_tire_pressure=safe_float(data.get("leftRearTirepressure")),
            right_rear_tire_pressure=safe_float(data.get("rightRearTirepressure")),
            left_front_tire_status=safe_int(data.get("leftFrontTireStatus")),
            right_front_tire_status=safe_int(data.get("rightFrontTireStatus")),
            left_rear_tire_status=safe_int(data.get("leftRearTireStatus")),
            right_rear_tire_status=safe_int(data.get("rightRearTireStatus")),
            tire_press_unit=to_enum(TirePressureUnit, data.get("tirePressUnit")),
            tirepressure_system=safe_int(data.get("tirepressureSystem")),
            rapid_tire_leak=safe_int(data.get("rapidTireLeak")),
            # Power & misc
            total_power=safe_float(data.get("totalPower")),
            total_energy=safe_str(data.get("totalEnergy")),
            nearest_energy_consumption=safe_str(data.get("nearestEnergyConsumption")),
            nearest_energy_consumption_unit=safe_str(data.get("nearestEnergyConsumptionUnit")),
            recent_50km_energy=safe_str(data.get("recent50kmEnergy")),
            oil_endurance=safe_float(data.get("oilEndurance")),
            oil_percent=safe_float(data.get("oilPercent")),
            total_oil=safe_float(data.get("totalOil")),
            power_system=safe_int(data.get("powerSystem")),
            engine_status=safe_int(data.get("engineStatus")),
            epb=safe_int(data.get("epb")),
            eps=safe_int(data.get("eps")),
            esp=safe_int(data.get("esp")),
            abs_warning=safe_int(data.get("abs")),
            svs=safe_int(data.get("svs")),
            srs=safe_int(data.get("srs")),
            ect=safe_int(data.get("ect")),
            ect_value=safe_int(data.get("ectValue")),
            pwr=safe_int(data.get("pwr")),
            sentry_status=safe_int(data.get("sentryStatus")),
            battery_heat_state=safe_int(data.get("batteryHeatState")),
            charge_heat_state=safe_int(data.get("chargeHeatState")),
            upgrade_status=safe_int(data.get("upgradeStatus")),
            timestamp=safe_int(data.get("time")),
            raw=data,
        )

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
