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
from pybyd._crypto.aes import aes_decrypt_utf8
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError
from pybyd.models.charging import ChargingStatus
from pybyd.session import Session

_logger = logging.getLogger(__name__)

_ENDPOINT = "/control/smartCharge/homePage"


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
    config: BydConfig, session: Session, transport: SecureTransport, vin: str,
) -> ChargingStatus:
    """Fetch smart charging status (SOC, charge state, time-to-full)."""
    now_ms = int(time.time() * 1000)
    inner = _build_charging_inner(config, vin, now_ms)
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(_ENDPOINT, outer)
    if str(response.get("code")) != "0":
        raise BydApiError(
            f"{_ENDPOINT} failed: code={response.get('code')} message={response.get('message', '')}",
            code=str(response.get("code", "")), endpoint=_ENDPOINT,
        )

    data = json.loads(aes_decrypt_utf8(response["respondData"], content_key))
    _logger.debug("Charging status response keys=%s", list(data.keys()) if isinstance(data, dict) else [])
    return _parse_charging_status(data if isinstance(data, dict) else {})
