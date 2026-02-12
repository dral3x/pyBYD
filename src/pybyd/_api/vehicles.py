"""Vehicle list endpoint: /app/account/getAllListByUserId.

Ports buildListRequest from client.js lines 317-327.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from pybyd._api._envelope import build_token_outer_envelope
from pybyd._constants import SESSION_EXPIRED_CODES
from pybyd._crypto.aes import aes_decrypt_utf8
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError, BydSessionExpiredError
from pybyd.models.vehicle import EmpowerRange, Vehicle
from pybyd.session import Session


def _safe_int(value: Any) -> int | None:
    """Convert a value to int, returning None on failure."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


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


def _pick_image_url(item: dict[str, Any], key: str) -> str:
    """Pick image URLs from either top-level or nested cfPic fields."""
    value = item.get(key)
    if value not in (None, ""):
        return str(value)
    nested = item.get("cfPic")
    if isinstance(nested, dict):
        nested_value = nested.get(key)
        if nested_value not in (None, ""):
            return str(nested_value)
    return ""


def _parse_empower_ranges(raw: Any) -> list[EmpowerRange]:
    """Parse the rangeDetailList into EmpowerRange objects."""
    if not isinstance(raw, list):
        return []
    ranges: list[EmpowerRange] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        children = _parse_empower_ranges(item.get("childList"))
        ranges.append(
            EmpowerRange(
                code=str(item.get("code", "")),
                name=str(item.get("name", "")),
                children=children,
            )
        )
    return ranges


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
    resp_code = str(outer_response.get("code", ""))
    if resp_code != "0":
        if resp_code in SESSION_EXPIRED_CODES:
            raise BydSessionExpiredError(
                f"Vehicle list failed: code={resp_code} message={outer_response.get('message', '')}",
                code=resp_code,
                endpoint="/app/account/getAllListByUserId",
            )
        raise BydApiError(
            f"Vehicle list failed: code={resp_code} message={outer_response.get('message', '')}",
            code=resp_code,
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
                pic_main_url=_pick_image_url(item, "picMainUrl"),
                pic_set_url=_pick_image_url(item, "picSetUrl"),
                out_model_type=str(item.get("outModelType", "")),
                total_mileage=_safe_float(item.get("totalMileage")),
                model_id=_safe_int(item.get("modelId")),
                car_type=_safe_int(item.get("carType")),
                default_car=item.get("defaultCar") == 1,
                empower_type=_safe_int(item.get("empowerType")),
                permission_status=_safe_int(item.get("permissionStatus")),
                tbox_version=str(item.get("tboxVersion", "")),
                vehicle_state=str(item.get("vehicleState", "")),
                auto_bought_time=_safe_int(item.get("autoBoughtTime")),
                yun_active_time=_safe_int(item.get("yunActiveTime")),
                empower_id=_safe_int(item.get("empowerId")),
                range_detail_list=_parse_empower_ranges(item.get("rangeDetailList")),
                raw=item,
            )
        )
    return vehicles
