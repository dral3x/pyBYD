"""Smart charging status endpoint.

Endpoint:
  - /control/smartCharge/homePage
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
from pybyd.models.charging import ChargingStatus
from pybyd.session import Session

_logger = logging.getLogger(__name__)

_ENDPOINT = "/control/smartCharge/homePage"

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


def _build_charging_inner(config: BydConfig, vin: str, now_ms: int) -> dict[str, str]:
    return {
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }


def _parse_charging_status(data: dict[str, Any]) -> ChargingStatus:
    """Parse the smart charge homepage response."""
    return ChargingStatus(
        vin=str(data.get("vin", "")),
        soc=_safe_int(data.get("soc")),
        charging_state=_safe_int(data.get("chargingState")),
        connect_state=_safe_int(data.get("connectState")),
        wait_status=_safe_int(data.get("waitStatus")),
        full_hour=_safe_int(data.get("fullHour")),
        full_minute=_safe_int(data.get("fullMinute")),
        update_time=_safe_int(data.get("updateTime")),
        raw=data,
    )


async def fetch_charging_status(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    cache: VehicleDataCache | None = None,
) -> ChargingStatus:
    """Fetch smart charging status (SOC, charge state, time-to-full)."""
    now_ms = int(time.time() * 1000)
    inner = _build_charging_inner(config, vin, now_ms)
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
    _logger.debug("Charging response decoded vin=%s keys=%s", vin, list(data.keys()) if isinstance(data, dict) else [])
    if cache is not None and isinstance(data, dict):
        data = cache.merge_charging(vin, data)
    return _parse_charging_status(data if isinstance(data, dict) else {})
