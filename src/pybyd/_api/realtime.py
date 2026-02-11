"""Vehicle realtime data endpoints.

Ports pollVehicleRealtime from client.js lines 391-463.

Endpoints:
  - /vehicleInfo/vehicle/vehicleRealTimeRequest (trigger)
  - /vehicleInfo/vehicle/vehicleRealTimeResult (poll)
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Any

from pybyd._api._envelope import build_token_outer_envelope
from pybyd._crypto.aes import aes_decrypt_utf8
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError
from pybyd.models.realtime import VehicleRealtimeData
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


def _parse_vehicle_info(data: dict[str, Any]) -> VehicleRealtimeData:
    """Parse raw vehicle info dict into a typed dataclass."""
    return VehicleRealtimeData(
        online_state=_safe_int(data.get("onlineState")) or 0,
        vehicle_state=str(data.get("vehicleState", "")),
        elec_percent=_safe_float(data.get("elecPercent") or data.get("powerBattery")),
        endurance_mileage=_safe_float(data.get("enduranceMileage") or data.get("evEndurance")),
        total_mileage=_safe_float(data.get("totalMileageV2") or data.get("totalMileage")),
        speed=_safe_float(data.get("speed")),
        temp_in_car=_safe_float(data.get("tempInCar")),
        charging_state=str(data.get("chargingState") or data.get("chargeState") or ""),
        left_front_door=str(data.get("leftFrontDoor", "")),
        right_front_door=str(data.get("rightFrontDoor", "")),
        left_rear_door=str(data.get("leftRearDoor", "")),
        right_rear_door=str(data.get("rightRearDoor", "")),
        trunk_lid=str(data.get("trunkLid", "")),
        left_front_tire_pressure=_safe_float(data.get("leftFrontTirepressure")),
        right_front_tire_pressure=_safe_float(data.get("rightFrontTirepressure")),
        left_rear_tire_pressure=_safe_float(data.get("leftRearTirepressure")),
        right_rear_tire_pressure=_safe_float(data.get("rightRearTirepressure")),
        timestamp=_safe_int(data.get("time")),
        request_serial=data.get("requestSerial"),
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
    if str(response.get("code")) != "0":
        raise BydApiError(
            f"{endpoint} failed: code={response.get('code')} message={response.get('message', '')}",
            code=str(response.get("code", "")),
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
    # Phase 1: Trigger request
    vehicle_info, serial = await _fetch_realtime_endpoint(
        "/vehicleInfo/vehicle/vehicleRealTimeRequest",
        config,
        session,
        transport,
        vin,
    )
    _logger.debug(
        "Realtime request: onlineState=%s serial=%s",
        vehicle_info.get("onlineState") if isinstance(vehicle_info, dict) else None,
        serial,
    )

    if isinstance(vehicle_info, dict) and _is_realtime_data_ready(vehicle_info):
        return _parse_vehicle_info(vehicle_info)

    if not serial:
        return _parse_vehicle_info(vehicle_info if isinstance(vehicle_info, dict) else {})

    # Phase 2: Poll for results
    latest = vehicle_info
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
            _logger.debug(
                "Realtime poll attempt=%d onlineState=%s serial=%s",
                attempt,
                latest.get("onlineState") if isinstance(latest, dict) else None,
                serial,
            )
            if isinstance(latest, dict) and _is_realtime_data_ready(latest):
                break
        except BydApiError:
            _logger.debug("Realtime poll attempt=%d failed", attempt, exc_info=True)

    return _parse_vehicle_info(latest if isinstance(latest, dict) else {})
