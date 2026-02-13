"""HVAC status endpoint.

Endpoint:
  - /control/getStatusNow
"""

from __future__ import annotations

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
from pybyd.exceptions import (
    BydApiError,
    BydEndpointNotSupportedError,
    BydSessionExpiredError,
)
from pybyd.models.hvac import HvacStatus
from pybyd.models.realtime import SeatHeatVentState
from pybyd.session import Session

_logger = logging.getLogger(__name__)

_ENDPOINT = "/control/getStatusNow"

#: API error codes indicating the endpoint is not supported for this vehicle.
_NOT_SUPPORTED_CODES: frozenset[str] = frozenset({"1001"})


def _safe_int(value: Any) -> int | None:
    """Parse a value to int, returning None for missing/invalid."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
        if result != result:  # NaN check
            return None
        return int(result)
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any) -> float | None:
    """Parse a value to float, returning None for missing/invalid."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
        if result != result:
            return None
        return result
    except (ValueError, TypeError):
        return None


def _to_enum(enum_cls: type, value: Any, default: Any = None) -> Any:
    """Safely coerce a value into an IntEnum, returning default on failure."""
    v = _safe_int(value)
    if v is None:
        return default
    try:
        return enum_cls(v)
    except ValueError:
        return v  # Return raw int if not a known enum member


def _build_hvac_inner(config: BydConfig, vin: str, now_ms: int) -> dict[str, str]:
    return {
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }


def _parse_hvac_status(data: dict[str, Any]) -> HvacStatus:
    """Parse the ``statusNow`` object from the API response."""
    # The response wraps the status in a "statusNow" key
    status = data.get("statusNow", data) if isinstance(data, dict) else data

    return HvacStatus(
        ac_switch=_safe_int(status.get("acSwitch")),
        status=_safe_int(status.get("status")),
        air_conditioning_mode=_safe_int(status.get("airConditioningMode")),
        wind_mode=_safe_int(status.get("windMode")),
        wind_position=_safe_int(status.get("windPosition")),
        cycle_choice=_safe_int(status.get("cycleChoice")),
        main_setting_temp=_safe_int(status.get("mainSettingTemp")),
        main_setting_temp_new=_safe_float(status.get("mainSettingTempNew")),
        copilot_setting_temp=_safe_int(status.get("copilotSettingTemp")),
        copilot_setting_temp_new=_safe_float(status.get("copilotSettingTempNew")),
        temp_in_car=_safe_float(status.get("tempInCar")),
        temp_out_car=_safe_float(status.get("tempOutCar")),
        whether_support_adjust_temp=_safe_int(status.get("whetherSupportAdjustTemp")),
        front_defrost_status=_safe_int(status.get("frontDefrostStatus")),
        electric_defrost_status=_safe_int(status.get("electricDefrostStatus")),
        wiper_heat_status=_safe_int(status.get("wiperHeatStatus")),
        main_seat_heat_state=_to_enum(SeatHeatVentState, status.get("mainSeatHeatState")),
        main_seat_ventilation_state=_to_enum(SeatHeatVentState, status.get("mainSeatVentilationState")),
        copilot_seat_heat_state=_to_enum(SeatHeatVentState, status.get("copilotSeatHeatState")),
        copilot_seat_ventilation_state=_to_enum(SeatHeatVentState, status.get("copilotSeatVentilationState")),
        steering_wheel_heat_state=_to_enum(SeatHeatVentState, status.get("steeringWheelHeatState")),
        lr_seat_heat_state=_to_enum(SeatHeatVentState, status.get("lrSeatHeatState")),
        lr_seat_ventilation_state=_to_enum(SeatHeatVentState, status.get("lrSeatVentilationState")),
        rr_seat_heat_state=_to_enum(SeatHeatVentState, status.get("rrSeatHeatState")),
        rr_seat_ventilation_state=_to_enum(SeatHeatVentState, status.get("rrSeatVentilationState")),
        rapid_increase_temp_state=_safe_int(status.get("rapidIncreaseTempState")),
        rapid_decrease_temp_state=_safe_int(status.get("rapidDecreaseTempState")),
        refrigerator_state=_safe_int(status.get("refrigeratorState")),
        refrigerator_door_state=_safe_int(status.get("refrigeratorDoorState")),
        pm=_safe_int(status.get("pm")),
        pm25_state_out_car=_safe_int(status.get("pm25StateOutCar")),
        raw=status,
    )


async def fetch_hvac_status(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    cache: VehicleDataCache | None = None,
) -> HvacStatus:
    """Fetch current HVAC/climate control status for a vehicle."""
    now_ms = int(time.time() * 1000)
    inner = _build_hvac_inner(config, vin, now_ms)
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(_ENDPOINT, outer)
    resp_code = str(response.get("code", ""))
    if resp_code != "0":
        if resp_code in SESSION_EXPIRED_CODES:
            raise BydSessionExpiredError(
                f"{_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=_ENDPOINT,
            )
        if resp_code in _NOT_SUPPORTED_CODES:
            raise BydEndpointNotSupportedError(
                f"{_ENDPOINT} not supported for VIN {vin} (code={resp_code})",
                code=resp_code,
                endpoint=_ENDPOINT,
            )
        raise BydApiError(
            f"{_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
            code=resp_code,
            endpoint=_ENDPOINT,
        )

    data = json.loads(aes_decrypt_utf8(response["respondData"], content_key))
    _logger.debug("HVAC response decoded vin=%s keys=%s", vin, list(data.keys()) if isinstance(data, dict) else [])
    status = data.get("statusNow", data) if isinstance(data, dict) else {}
    if cache is not None and isinstance(status, dict):
        status = cache.merge_hvac(vin, status)
    return _parse_hvac_status(status if isinstance(status, dict) else {})
