"""GPS info endpoints.

Ports pollGpsInfo from client.js lines 479-583.

Endpoints:
  - /control/getGpsInfo (trigger)
  - /control/getGpsInfoResult (poll)
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
from pybyd.models.gps import GpsInfo
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


def _build_gps_inner(
    config: BydConfig,
    vin: str,
    now_ms: int,
    request_serial: str | None = None,
) -> dict[str, str]:
    """Build the inner payload for GPS endpoints."""
    inner: dict[str, str] = {
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }
    if request_serial:
        inner["requestSerial"] = request_serial
    return inner


def _is_gps_info_ready(gps_info: dict[str, Any]) -> bool:
    """Check if GPS data has meaningful content.

    Mirrors client.js isGpsInfoReady (lines 465-477).
    """
    if not gps_info:
        return False
    keys = list(gps_info.keys())
    if not keys:
        return False
    return not (len(keys) == 1 and keys[0] == "requestSerial")


def _parse_gps_info(data: dict[str, Any]) -> GpsInfo:
    """Parse raw GPS dict into a typed dataclass."""
    # GPS data may be nested under a 'data' key
    nested = data.get("data")
    gps_data: dict[str, Any] = nested if isinstance(nested, dict) else data

    return GpsInfo(
        latitude=_safe_float(gps_data.get("latitude") or gps_data.get("lat") or gps_data.get("gpsLatitude")),
        longitude=_safe_float(
            gps_data.get("longitude") or gps_data.get("lng") or gps_data.get("lon") or gps_data.get("gpsLongitude")
        ),
        speed=_safe_float(gps_data.get("speed") or gps_data.get("gpsSpeed")),
        direction=_safe_float(gps_data.get("direction") or gps_data.get("heading") or gps_data.get("course")),
        gps_timestamp=_safe_int(
            gps_data.get("gpsTimeStamp")
            or gps_data.get("gpsTimestamp")
            or gps_data.get("gpsTime")
            or gps_data.get("time")
            or gps_data.get("uploadTime")
        ),
        request_serial=data.get("requestSerial"),
        raw=data,
    )


async def _fetch_gps_endpoint(
    endpoint: str,
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    request_serial: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Fetch a single GPS endpoint, returning (gps_info_dict, next_serial)."""
    import time

    now_ms = int(time.time() * 1000)
    inner = _build_gps_inner(config, vin, now_ms, request_serial)
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(endpoint, outer)
    if str(response.get("code")) != "0":
        raise BydApiError(
            f"{endpoint} failed: code={response.get('code')} message={response.get('message', '')}",
            code=str(response.get("code", "")),
            endpoint=endpoint,
        )

    gps_info = json.loads(aes_decrypt_utf8(response["respondData"], content_key))
    next_serial = (gps_info.get("requestSerial") if isinstance(gps_info, dict) else None) or request_serial

    return gps_info, next_serial


async def poll_gps_info(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    *,
    poll_attempts: int = 10,
    poll_interval: float = 1.5,
) -> GpsInfo:
    """Poll GPS info until ready or attempts exhausted.

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
    GpsInfo
        The latest GPS data.

    Raises
    ------
    BydApiError
        If the initial GPS request fails.
    """
    # Phase 1: Trigger request
    try:
        gps_info, serial = await _fetch_gps_endpoint(
            "/control/getGpsInfo",
            config,
            session,
            transport,
            vin,
        )
    except BydApiError:
        _logger.debug("GPS request failed", exc_info=True)
        raise

    _logger.debug(
        "GPS request: keys=%s serial=%s",
        list(gps_info.keys()) if isinstance(gps_info, dict) else [],
        serial,
    )

    if isinstance(gps_info, dict) and _is_gps_info_ready(gps_info):
        return _parse_gps_info(gps_info)

    if not serial:
        return _parse_gps_info(gps_info if isinstance(gps_info, dict) else {})

    # Phase 2: Poll for results
    latest = gps_info
    for attempt in range(1, poll_attempts + 1):
        if poll_interval > 0:
            await asyncio.sleep(poll_interval)

        try:
            latest, serial = await _fetch_gps_endpoint(
                "/control/getGpsInfoResult",
                config,
                session,
                transport,
                vin,
                serial,
            )
            _logger.debug(
                "GPS poll attempt=%d keys=%s serial=%s",
                attempt,
                list(latest.keys()) if isinstance(latest, dict) else [],
                serial,
            )
            if isinstance(latest, dict) and _is_gps_info_ready(latest):
                break
        except BydApiError:
            _logger.debug("GPS poll attempt=%d failed", attempt, exc_info=True)

    return _parse_gps_info(latest if isinstance(latest, dict) else {})
