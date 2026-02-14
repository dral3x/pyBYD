"""Smart charging control endpoints.

Endpoints:
  - /control/smartCharge/changeChargeStatue  (toggle on/off)
  - /control/smartCharge/saveOrUpdate        (save schedule)
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
from pybyd.session import Session

_logger = logging.getLogger(__name__)

_TOGGLE_ENDPOINT = "/control/smartCharge/changeChargeStatue"
_SAVE_ENDPOINT = "/control/smartCharge/saveOrUpdate"

_NOT_SUPPORTED_CODES: frozenset[str] = frozenset({"1001"})


def _build_toggle_inner(
    config: BydConfig,
    vin: str,
    now_ms: int,
    *,
    smart_charge_switch: int,
) -> dict[str, str]:
    """Build inner payload for smart charge toggle."""
    return {
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "smartChargeSwitch": str(smart_charge_switch),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }


def _build_save_schedule_inner(
    config: BydConfig,
    vin: str,
    now_ms: int,
    *,
    target_soc: int,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
) -> dict[str, str]:
    """Build inner payload for smart charge schedule save."""
    return {
        "deviceType": config.device.device_type,
        "endHour": str(end_hour),
        "endMinute": str(end_minute),
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "startHour": str(start_hour),
        "startMinute": str(start_minute),
        "targetSoc": str(target_soc),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }


async def toggle_smart_charging(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    *,
    enable: bool,
) -> dict[str, Any]:
    """Toggle smart charging on or off.

    Parameters
    ----------
    enable : bool
        True to enable smart charging, False to disable.

    Returns
    -------
    dict
        Decoded API response payload.
    """
    now_ms = int(time.time() * 1000)
    inner = _build_toggle_inner(
        config,
        vin,
        now_ms,
        smart_charge_switch=1 if enable else 0,
    )
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(_TOGGLE_ENDPOINT, outer)
    resp_code = str(response.get("code", ""))
    if resp_code != "0":
        if resp_code in SESSION_EXPIRED_CODES:
            raise BydSessionExpiredError(
                f"{_TOGGLE_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=_TOGGLE_ENDPOINT,
            )
        if resp_code in _NOT_SUPPORTED_CODES:
            raise BydEndpointNotSupportedError(
                f"{_TOGGLE_ENDPOINT} not supported for VIN {vin} (code={resp_code})",
                code=resp_code,
                endpoint=_TOGGLE_ENDPOINT,
            )
        raise BydApiError(
            f"{_TOGGLE_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
            code=resp_code,
            endpoint=_TOGGLE_ENDPOINT,
        )

    encrypted_inner = response.get("respondData")
    if not encrypted_inner:
        return {}
    data = json.loads(aes_decrypt_utf8(encrypted_inner, content_key))
    _logger.debug("Smart charge toggle response vin=%s enable=%s", vin, enable)
    return data if isinstance(data, dict) else {}


async def save_charging_schedule(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    *,
    target_soc: int,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
) -> dict[str, Any]:
    """Save a smart charging schedule.

    Parameters
    ----------
    target_soc : int
        Target state of charge (0-100).
    start_hour : int
        Scheduled start hour (0-23).
    start_minute : int
        Scheduled start minute (0-59).
    end_hour : int
        Scheduled end hour (0-23).
    end_minute : int
        Scheduled end minute (0-59).

    Returns
    -------
    dict
        Decoded API response payload.
    """
    now_ms = int(time.time() * 1000)
    inner = _build_save_schedule_inner(
        config,
        vin,
        now_ms,
        target_soc=target_soc,
        start_hour=start_hour,
        start_minute=start_minute,
        end_hour=end_hour,
        end_minute=end_minute,
    )
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(_SAVE_ENDPOINT, outer)
    resp_code = str(response.get("code", ""))
    if resp_code != "0":
        if resp_code in SESSION_EXPIRED_CODES:
            raise BydSessionExpiredError(
                f"{_SAVE_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=_SAVE_ENDPOINT,
            )
        if resp_code in _NOT_SUPPORTED_CODES:
            raise BydEndpointNotSupportedError(
                f"{_SAVE_ENDPOINT} not supported for VIN {vin} (code={resp_code})",
                code=resp_code,
                endpoint=_SAVE_ENDPOINT,
            )
        raise BydApiError(
            f"{_SAVE_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
            code=resp_code,
            endpoint=_SAVE_ENDPOINT,
        )

    encrypted_inner = response.get("respondData")
    if not encrypted_inner:
        return {}
    data = json.loads(aes_decrypt_utf8(encrypted_inner, content_key))
    _logger.debug("Smart charge schedule saved vin=%s target_soc=%d", vin, target_soc)
    return data if isinstance(data, dict) else {}
