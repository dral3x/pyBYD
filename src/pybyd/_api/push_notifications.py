"""Push notification endpoints.

Endpoints:
  - /app/push/getPushSwitchState  (get current state)
  - /app/push/setPushSwitchState  (toggle on/off)
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

from pybyd._api._envelope import build_token_outer_envelope
from pybyd._constants import SESSION_EXPIRED_CODES
from pybyd._crypto.aes import aes_decrypt_utf8
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import (
    BydApiError,
    BydEndpointNotSupportedError,
    BydSessionExpiredError,
)
from pybyd.models.push_notification import PushNotificationState
from pybyd.session import Session

_logger = logging.getLogger(__name__)

_GET_ENDPOINT = "/app/push/getPushSwitchState"
_SET_ENDPOINT = "/app/push/setPushSwitchState"

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


def _build_get_push_inner(
    config: BydConfig,
    vin: str,
    now_ms: int,
) -> dict[str, str]:
    """Build inner payload for get push state."""
    return {
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }


def _build_set_push_inner(
    config: BydConfig,
    vin: str,
    now_ms: int,
    *,
    push_switch: int,
) -> dict[str, str]:
    """Build inner payload for set push state."""
    return {
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "pushSwitch": str(push_switch),
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }


def _parse_push_state(data: dict[str, Any], vin: str) -> PushNotificationState:
    """Parse the push switch state response."""
    return PushNotificationState(
        vin=vin,
        push_switch=_safe_int(data.get("pushSwitch")),
        raw=data,
    )


async def get_push_state(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
) -> PushNotificationState:
    """Fetch the current push notification state for a vehicle.

    Returns
    -------
    PushNotificationState
        Current push notification toggle state.
    """
    now_ms = int(time.time() * 1000)
    inner = _build_get_push_inner(config, vin, now_ms)
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(_GET_ENDPOINT, outer)
    resp_code = str(response.get("code", ""))
    if resp_code != "0":
        if resp_code in SESSION_EXPIRED_CODES:
            raise BydSessionExpiredError(
                f"{_GET_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=_GET_ENDPOINT,
            )
        if resp_code in _NOT_SUPPORTED_CODES:
            raise BydEndpointNotSupportedError(
                f"{_GET_ENDPOINT} not supported for VIN {vin} (code={resp_code})",
                code=resp_code,
                endpoint=_GET_ENDPOINT,
            )
        raise BydApiError(
            f"{_GET_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
            code=resp_code,
            endpoint=_GET_ENDPOINT,
        )

    data = json.loads(aes_decrypt_utf8(response["respondData"], content_key))
    _logger.debug("Push state response vin=%s", vin)
    return _parse_push_state(data if isinstance(data, dict) else {}, vin)


async def set_push_state(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    *,
    enable: bool,
) -> dict[str, Any]:
    """Set the push notification state for a vehicle.

    Parameters
    ----------
    enable : bool
        True to enable push notifications, False to disable.

    Returns
    -------
    dict
        Decoded API response payload.
    """
    now_ms = int(time.time() * 1000)
    inner = _build_set_push_inner(
        config,
        vin,
        now_ms,
        push_switch=1 if enable else 0,
    )
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(_SET_ENDPOINT, outer)
    resp_code = str(response.get("code", ""))
    if resp_code != "0":
        if resp_code in SESSION_EXPIRED_CODES:
            raise BydSessionExpiredError(
                f"{_SET_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=_SET_ENDPOINT,
            )
        if resp_code in _NOT_SUPPORTED_CODES:
            raise BydEndpointNotSupportedError(
                f"{_SET_ENDPOINT} not supported for VIN {vin} (code={resp_code})",
                code=resp_code,
                endpoint=_SET_ENDPOINT,
            )
        raise BydApiError(
            f"{_SET_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
            code=resp_code,
            endpoint=_SET_ENDPOINT,
        )

    encrypted_inner = response.get("respondData")
    if not encrypted_inner:
        return {}
    data = json.loads(aes_decrypt_utf8(encrypted_inner, content_key))
    _logger.debug("Push state set vin=%s enable=%s", vin, enable)
    return data if isinstance(data, dict) else {}
