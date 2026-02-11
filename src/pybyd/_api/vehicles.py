"""Vehicle list endpoint: /app/account/getAllListByUserId.

Ports buildListRequest from client.js lines 317-327.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from pybyd._api._envelope import build_token_outer_envelope
from pybyd._crypto.aes import aes_decrypt_utf8
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError
from pybyd.models.vehicle import Vehicle
from pybyd.session import Session


def build_list_request(
    config: BydConfig,
    session: Session,
    now_ms: int,
) -> tuple[dict[str, Any], str]:
    """Build the outer payload for the vehicle list endpoint.

    Returns
    -------
    tuple[dict, str]
        (outer_payload, content_key) tuple.
    """
    inner: dict[str, str] = {
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
    }
    return build_token_outer_envelope(config, session, inner, now_ms)


def parse_vehicle_list(
    outer_response: dict[str, Any],
    content_key: str,
) -> list[Vehicle]:
    """Parse vehicle list response.

    Parameters
    ----------
    outer_response : dict
        Decoded outer response from the API.
    content_key : str
        AES key for decrypting respondData.

    Returns
    -------
    list[Vehicle]
        List of vehicles.

    Raises
    ------
    BydApiError
        If the API returned a non-zero code.
    """
    if str(outer_response.get("code")) != "0":
        raise BydApiError(
            f"Vehicle list failed: code={outer_response.get('code')} message={outer_response.get('message', '')}",
            code=str(outer_response.get("code", "")),
            endpoint="/app/account/getAllListByUserId",
        )

    respond_data = outer_response.get("respondData", "")
    if not respond_data:
        return []

    inner = json.loads(aes_decrypt_utf8(respond_data, content_key))
    if not isinstance(inner, list):
        return []

    vehicles: list[Vehicle] = []
    for item in inner:
        if not isinstance(item, dict):
            continue
        vehicles.append(
            Vehicle(
                vin=str(item.get("vin", "")),
                model_name=str(item.get("modelName", "")),
                brand_name=str(item.get("brandName", "")),
                energy_type=str(item.get("energyType", "")),
                auto_alias=str(item.get("autoAlias", "")),
                auto_plate=str(item.get("autoPlate", "")),
                raw=item,
            )
        )
    return vehicles
