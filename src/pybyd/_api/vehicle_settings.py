"""Vehicle settings endpoints.

Endpoints:
  - /control/vehicle/modifyAutoAlias  (rename vehicle)
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

_RENAME_ENDPOINT = "/control/vehicle/modifyAutoAlias"

_NOT_SUPPORTED_CODES: frozenset[str] = frozenset({"1001"})


def _build_rename_inner(
    config: BydConfig,
    vin: str,
    now_ms: int,
    *,
    auto_alias: str,
) -> dict[str, str]:
    """Build inner payload for vehicle rename."""
    return {
        "autoAlias": auto_alias,
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }


async def rename_vehicle(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    *,
    name: str,
) -> dict[str, Any]:
    """Rename a vehicle (set its alias).

    Parameters
    ----------
    name : str
        New display name for the vehicle.

    Returns
    -------
    dict
        Decoded API response payload.
    """
    now_ms = int(time.time() * 1000)
    inner = _build_rename_inner(config, vin, now_ms, auto_alias=name)
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(_RENAME_ENDPOINT, outer)
    resp_code = str(response.get("code", ""))
    if resp_code != "0":
        if resp_code in SESSION_EXPIRED_CODES:
            raise BydSessionExpiredError(
                f"{_RENAME_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=_RENAME_ENDPOINT,
            )
        if resp_code in _NOT_SUPPORTED_CODES:
            raise BydEndpointNotSupportedError(
                f"{_RENAME_ENDPOINT} not supported for VIN {vin} (code={resp_code})",
                code=resp_code,
                endpoint=_RENAME_ENDPOINT,
            )
        raise BydApiError(
            f"{_RENAME_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
            code=resp_code,
            endpoint=_RENAME_ENDPOINT,
        )

    encrypted_inner = response.get("respondData")
    if not encrypted_inner:
        return {}
    data = json.loads(aes_decrypt_utf8(encrypted_inner, content_key))
    _logger.debug("Vehicle renamed vin=%s name=%s", vin, name)
    return data if isinstance(data, dict) else {}
