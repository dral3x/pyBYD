"""Vehicle realtime data endpoints.

Endpoints:
  - /vehicleInfo/vehicle/vehicleRealTimeRequest (trigger)
  - /vehicleInfo/vehicle/vehicleRealTimeResult (poll)
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any

from pybyd._api._envelope import build_token_outer_envelope
from pybyd._cache import VehicleDataCache
from pybyd._constants import SESSION_EXPIRED_CODES
from pybyd._crypto.aes import aes_decrypt_utf8
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError, BydSessionExpiredError
from pybyd.models.realtime import (
    AirCirculationMode,
    ChargingState,
    ConnectState,
    DoorOpenState,
    LockState,
    OnlineState,
    PowerGear,
    SeatHeatVentState,
    TirePressureUnit,
    VehicleRealtimeData,
    VehicleState,
    WindowState,
)
from pybyd.session import Session

_logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None on failure."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
        if result != result:  # NaN check
            return None
        return result
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> int | None:
    """Convert a value to int, returning None on failure."""
    f = _safe_float(value)
    if f is None:
        return None
    return int(f)


def _non_negative_or_zero(value: Any) -> int | None:
    """Convert value to int, mapping negative sentinel values to zero."""
    parsed = _safe_int(value)
    if parsed is None:
        return None
    if parsed < 0:
        return 0
    return parsed


def _build_realtime_inner(
    config: BydConfig,
    vin: str,
    now_ms: int,
    request_serial: str | None = None,
) -> dict[str, str]:
    """Build the inner payload for realtime endpoints."""
    inner: dict[str, str] = {
        "deviceType": config.device.device_type,
        "energyType": "0",
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "tboxVersion": config.tbox_version,
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }
    if request_serial:
        inner["requestSerial"] = request_serial
    return inner


def _is_realtime_data_ready(vehicle_info: dict[str, Any]) -> bool:
    """Check if realtime data has meaningful content.

    Mirrors client.js isRealtimeDataReady (lines 363-389).
    """
    if not vehicle_info:
        return False
    if _safe_int(vehicle_info.get("onlineState")) == 2:
        return False

    tire_fields = [
        "leftFrontTirepressure",
        "rightFrontTirepressure",
        "leftRearTirepressure",
        "rightRearTirepressure",
    ]
    if any(_safe_float(vehicle_info.get(f)) and _safe_float(vehicle_info.get(f)) > 0 for f in tire_fields):  # type: ignore[operator]
        return True
    if (_safe_int(vehicle_info.get("time")) or 0) > 0:
        return True
    return (_safe_float(vehicle_info.get("enduranceMileage")) or 0) > 0


def _to_enum(enum_cls: type, value: Any, default: Any = None) -> Any:
    """Safely coerce a value into an IntEnum, returning default on failure."""
    v = _safe_int(value)
    if v is None:
        return default
    try:
        return enum_cls(v)
    except ValueError:
        return v  # Return raw int if not a known enum member


def _safe_str(value: Any) -> str | None:
    """Return string value, or None if missing/placeholder."""
    if value is None:
        return None
    s = str(value)
    return s if s else None


def _parse_vehicle_info(data: dict[str, Any]) -> VehicleRealtimeData:
    """Parse raw vehicle info dict into a typed dataclass.

    Uses enum coercion for known integer-enum fields per API_MAPPING.md.
    Energy consumption fields (totalEnergy, nearestEnergyConsumption,
    recent50kmEnergy) are kept as strings since the API returns ``"--"``
    when values are unavailable.
    """
    return VehicleRealtimeData(
        # Connection & state
        online_state=_to_enum(OnlineState, data.get("onlineState"), OnlineState.UNKNOWN),
        connect_state=_to_enum(ConnectState, data.get("connectState"), ConnectState.UNKNOWN),
        vehicle_state=_to_enum(VehicleState, data.get("vehicleState"), VehicleState.STANDBY),
        request_serial=data.get("requestSerial"),
        # Battery & range
        elec_percent=_safe_float(data.get("elecPercent")),
        power_battery=_safe_float(data.get("powerBattery")),
        endurance_mileage=_safe_float(data.get("enduranceMileage")),
        ev_endurance=_safe_float(data.get("evEndurance")),
        endurance_mileage_v2=_safe_float(data.get("enduranceMileageV2")),
        endurance_mileage_v2_unit=_safe_str(data.get("enduranceMileageV2Unit")),
        total_mileage=_safe_float(data.get("totalMileage")),
        total_mileage_v2=_safe_float(data.get("totalMileageV2")),
        total_mileage_v2_unit=_safe_str(data.get("totalMileageV2Unit")),
        # Driving
        speed=_safe_float(data.get("speed")),
        power_gear=_to_enum(PowerGear, data.get("powerGear")),
        # Climate
        temp_in_car=_safe_float(data.get("tempInCar")),
        main_setting_temp=_safe_int(data.get("mainSettingTemp")),
        main_setting_temp_new=_safe_float(data.get("mainSettingTempNew")),
        air_run_state=_to_enum(AirCirculationMode, data.get("airRunState")),
        # Seat heating/ventilation
        main_seat_heat_state=_to_enum(SeatHeatVentState, data.get("mainSeatHeatState")),
        main_seat_ventilation_state=_to_enum(SeatHeatVentState, data.get("mainSeatVentilationState")),
        copilot_seat_heat_state=_to_enum(SeatHeatVentState, data.get("copilotSeatHeatState")),
        copilot_seat_ventilation_state=_to_enum(SeatHeatVentState, data.get("copilotSeatVentilationState")),
        steering_wheel_heat_state=_to_enum(SeatHeatVentState, data.get("steeringWheelHeatState")),
        lr_seat_heat_state=_to_enum(SeatHeatVentState, data.get("lrSeatHeatState")),
        lr_seat_ventilation_state=_to_enum(SeatHeatVentState, data.get("lrSeatVentilationState")),
        rr_seat_heat_state=_to_enum(SeatHeatVentState, data.get("rrSeatHeatState")),
        rr_seat_ventilation_state=_to_enum(SeatHeatVentState, data.get("rrSeatVentilationState")),
        # Charging
        charging_state=_to_enum(ChargingState, data.get("chargingState"), ChargingState.DISCONNECTED),
        charge_state=_to_enum(ChargingState, data.get("chargeState")),
        wait_status=_safe_int(data.get("waitStatus")),
        full_hour=_non_negative_or_zero(data.get("fullHour")),
        full_minute=_non_negative_or_zero(data.get("fullMinute")),
        charge_remaining_hours=_non_negative_or_zero(data.get("remainingHours")),
        charge_remaining_minutes=_non_negative_or_zero(data.get("remainingMinutes")),
        booking_charge_state=_safe_int(data.get("bookingChargeState")),
        booking_charging_hour=_safe_int(data.get("bookingChargingHour")),
        booking_charging_minute=_safe_int(data.get("bookingChargingMinute")),
        # Doors
        left_front_door=_to_enum(DoorOpenState, data.get("leftFrontDoor")),
        right_front_door=_to_enum(DoorOpenState, data.get("rightFrontDoor")),
        left_rear_door=_to_enum(DoorOpenState, data.get("leftRearDoor")),
        right_rear_door=_to_enum(DoorOpenState, data.get("rightRearDoor")),
        trunk_lid=_to_enum(
            DoorOpenState, data.get("trunkLid") if data.get("trunkLid") is not None else data.get("backCover")
        ),
        sliding_door=_to_enum(DoorOpenState, data.get("slidingDoor")),
        forehold=_to_enum(DoorOpenState, data.get("forehold")),
        # Locks
        left_front_door_lock=_to_enum(LockState, data.get("leftFrontDoorLock")),
        right_front_door_lock=_to_enum(LockState, data.get("rightFrontDoorLock")),
        left_rear_door_lock=_to_enum(LockState, data.get("leftRearDoorLock")),
        right_rear_door_lock=_to_enum(LockState, data.get("rightRearDoorLock")),
        sliding_door_lock=_to_enum(LockState, data.get("slidingDoorLock")),
        # Windows
        left_front_window=_to_enum(WindowState, data.get("leftFrontWindow")),
        right_front_window=_to_enum(WindowState, data.get("rightFrontWindow")),
        left_rear_window=_to_enum(WindowState, data.get("leftRearWindow")),
        right_rear_window=_to_enum(WindowState, data.get("rightRearWindow")),
        skylight=_to_enum(WindowState, data.get("skylight")),
        # Tire pressure
        left_front_tire_pressure=_safe_float(data.get("leftFrontTirepressure")),
        right_front_tire_pressure=_safe_float(data.get("rightFrontTirepressure")),
        left_rear_tire_pressure=_safe_float(data.get("leftRearTirepressure")),
        right_rear_tire_pressure=_safe_float(data.get("rightRearTirepressure")),
        left_front_tire_status=_safe_int(data.get("leftFrontTireStatus")),
        right_front_tire_status=_safe_int(data.get("rightFrontTireStatus")),
        left_rear_tire_status=_safe_int(data.get("leftRearTireStatus")),
        right_rear_tire_status=_safe_int(data.get("rightRearTireStatus")),
        tire_press_unit=_to_enum(TirePressureUnit, data.get("tirePressUnit")),
        tirepressure_system=_safe_int(data.get("tirepressureSystem")),
        rapid_tire_leak=_safe_int(data.get("rapidTireLeak")),
        # Energy consumption (kept as strings — API returns "--" when unavailable)
        total_power=_safe_float(data.get("totalPower")),
        total_energy=_safe_str(data.get("totalEnergy")),
        nearest_energy_consumption=_safe_str(data.get("nearestEnergyConsumption")),
        nearest_energy_consumption_unit=_safe_str(data.get("nearestEnergyConsumptionUnit")),
        recent_50km_energy=_safe_str(data.get("recent50kmEnergy")),
        # Fuel (hybrid)
        oil_endurance=_safe_float(data.get("oilEndurance")),
        oil_percent=_safe_float(data.get("oilPercent")),
        total_oil=_safe_float(data.get("totalOil")),
        # System indicators
        power_system=_safe_int(data.get("powerSystem")),
        engine_status=_safe_int(data.get("engineStatus")),
        epb=_safe_int(data.get("epb")),
        eps=_safe_int(data.get("eps")),
        esp=_safe_int(data.get("esp")),
        abs_warning=_safe_int(data.get("abs")),
        svs=_safe_int(data.get("svs")),
        srs=_safe_int(data.get("srs")),
        ect=_safe_int(data.get("ect")),
        ect_value=_safe_int(data.get("ectValue")),
        pwr=_safe_int(data.get("pwr")),
        # Feature states
        sentry_status=_safe_int(data.get("sentryStatus")),
        battery_heat_state=_safe_int(data.get("batteryHeatState")),
        charge_heat_state=_safe_int(data.get("chargeHeatState")),
        upgrade_status=_safe_int(data.get("upgradeStatus")),
        # Metadata
        timestamp=_safe_int(data.get("time")),
        raw=data,
    )


async def _fetch_realtime_endpoint(
    endpoint: str,
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    request_serial: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Fetch a single realtime endpoint, returning (vehicle_info_dict, next_serial)."""
    import time

    now_ms = int(time.time() * 1000)
    inner = _build_realtime_inner(config, vin, now_ms, request_serial)
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(endpoint, outer)
    resp_code = str(response.get("code", ""))
    if resp_code != "0":
        if resp_code in SESSION_EXPIRED_CODES:
            raise BydSessionExpiredError(
                f"{endpoint} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=endpoint,
            )
        raise BydApiError(
            f"{endpoint} failed: code={resp_code} message={response.get('message', '')}",
            code=resp_code,
            endpoint=endpoint,
        )

    vehicle_info = json.loads(aes_decrypt_utf8(response["respondData"], content_key))
    next_serial = (vehicle_info.get("requestSerial") if isinstance(vehicle_info, dict) else None) or request_serial

    return vehicle_info, next_serial


async def poll_vehicle_realtime(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    *,
    poll_attempts: int = 10,
    poll_interval: float = 1.5,
    cache: VehicleDataCache | None = None,
    stale_after: float | None = None,
) -> VehicleRealtimeData:
    """Poll vehicle realtime data until ready or attempts exhausted.

    Parameters
    ----------
    config : BydConfig
        Client configuration.
    session : Session
        Authenticated session.
    transport : SecureTransport
        HTTP transport.
    vin : str
        Vehicle Identification Number.
    poll_attempts : int
        Maximum number of result poll attempts.
    poll_interval : float
        Seconds between poll attempts.

    Returns
    -------
    VehicleRealtimeData
        The latest vehicle telemetry data.

    Raises
    ------
    BydApiError
        If the API returns an error.
    """
    if cache is not None:
        now_ms = int(time.time() * 1000)
        threshold = poll_interval if stale_after is None else stale_after
        if threshold is not None and threshold > 0:
            age = cache.get_realtime_age_seconds(vin, now_ms)
            if age is not None and age <= threshold:
                cached = cache.get_realtime(vin)
                if cached:
                    _logger.debug(
                        "Realtime polling skipped due to fresh cache vin=%s age_s=%.2f threshold_s=%.2f",
                        vin,
                        age,
                        threshold,
                    )
                    return _parse_vehicle_info(cached)
    # Phase 1: Trigger request
    vehicle_info, serial = await _fetch_realtime_endpoint(
        "/vehicleInfo/vehicle/vehicleRealTimeRequest",
        config,
        session,
        transport,
        vin,
    )
    merged_latest = (
        cache.merge_realtime(vin, vehicle_info)
        if cache is not None and isinstance(vehicle_info, dict)
        else (vehicle_info if isinstance(vehicle_info, dict) else {})
    )
    _logger.debug(
        "Realtime request: onlineState=%s serial=%s",
        vehicle_info.get("onlineState") if isinstance(vehicle_info, dict) else None,
        serial,
    )

    if isinstance(vehicle_info, dict) and _is_realtime_data_ready(vehicle_info):
        _logger.debug("Realtime data ready immediately after request vin=%s", vin)
        return _parse_vehicle_info(merged_latest)

    if not serial:
        _logger.debug("Realtime request returned without serial vin=%s; returning latest snapshot", vin)
        return _parse_vehicle_info(merged_latest)

    # Phase 2: Poll for results
    _logger.debug(
        "Realtime polling started vin=%s attempts=%d interval_s=%.2f",
        vin,
        poll_attempts,
        poll_interval,
    )
    latest = vehicle_info
    ready = False
    for attempt in range(1, poll_attempts + 1):
        if poll_interval > 0:
            await asyncio.sleep(poll_interval)

        try:
            latest, serial = await _fetch_realtime_endpoint(
                "/vehicleInfo/vehicle/vehicleRealTimeResult",
                config,
                session,
                transport,
                vin,
                serial,
            )
            if cache is not None and isinstance(latest, dict):
                merged_latest = cache.merge_realtime(vin, latest)
            elif isinstance(latest, dict):
                merged_latest = latest
            _logger.debug(
                "Realtime poll attempt=%d onlineState=%s serial=%s",
                attempt,
                latest.get("onlineState") if isinstance(latest, dict) else None,
                serial,
            )
            if isinstance(latest, dict) and _is_realtime_data_ready(latest):
                ready = True
                _logger.debug("Realtime polling finished with ready data vin=%s attempt=%d", vin, attempt)
                break
        except BydSessionExpiredError:
            raise
        except BydApiError:
            _logger.debug("Realtime poll attempt=%d failed", attempt, exc_info=True)

    if not ready:
        _logger.debug("Realtime polling exhausted without confirmed ready data vin=%s", vin)

    return _parse_vehicle_info(merged_latest if isinstance(merged_latest, dict) else {})
