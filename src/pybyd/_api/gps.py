"""GPS info endpoints.

Ports pollGpsInfo from client.js lines 479-583.

Endpoints:
  - /control/getGpsInfo (trigger)
  - /control/getGpsInfoResult (poll)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pybyd._api._common import build_inner_base, post_token_json
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError, BydSessionExpiredError
from pybyd.models.gps import GpsInfo
from pybyd.session import Session

_logger = logging.getLogger(__name__)


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


async def _fetch_gps_endpoint(
    endpoint: str,
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    request_serial: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Fetch a single GPS endpoint, returning (gps_info_dict, next_serial)."""
    inner = build_inner_base(config, vin=vin, request_serial=request_serial)
    decoded = await post_token_json(
        endpoint=endpoint,
        config=config,
        session=session,
        transport=transport,
        inner=inner,
        vin=vin,
    )
    if not isinstance(decoded, dict):
        return {}, request_serial
    next_serial = decoded.get("requestSerial") if isinstance(decoded.get("requestSerial"), str) else request_serial
    return decoded, next_serial


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

    merged_latest = gps_info if isinstance(gps_info, dict) else {}

    _logger.debug(
        "GPS request: keys=%s serial=%s",
        list(gps_info.keys()) if isinstance(gps_info, dict) else [],
        serial,
    )

    if isinstance(gps_info, dict) and _is_gps_info_ready(gps_info):
        _logger.debug("GPS data ready immediately after request vin=%s", vin)
        return GpsInfo.model_validate(merged_latest)

    if not serial:
        _logger.debug("GPS request returned without serial vin=%s; returning latest snapshot", vin)
        return GpsInfo.model_validate(merged_latest)

    # Phase 2: Poll for results
    _logger.debug(
        "GPS polling started vin=%s attempts=%d interval_s=%.2f",
        vin,
        poll_attempts,
        poll_interval,
    )
    latest = gps_info
    ready = False
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
            if isinstance(latest, dict):
                merged_latest = latest
            _logger.debug(
                "GPS poll attempt=%d keys=%s serial=%s",
                attempt,
                list(latest.keys()) if isinstance(latest, dict) else [],
                serial,
            )
            if isinstance(latest, dict) and _is_gps_info_ready(latest):
                ready = True
                _logger.debug("GPS polling finished with ready data vin=%s attempt=%d", vin, attempt)
                break
        except BydSessionExpiredError:
            raise
        except BydApiError:
            _logger.debug("GPS poll attempt=%d failed", attempt, exc_info=True)

    if not ready:
        _logger.debug("GPS polling exhausted without confirmed ready data vin=%s", vin)

    return GpsInfo.model_validate(merged_latest if isinstance(merged_latest, dict) else {})
