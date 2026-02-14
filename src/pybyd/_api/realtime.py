"""Vehicle realtime data endpoints.

Endpoints:
  - /vehicleInfo/vehicle/vehicleRealTimeRequest (trigger)
  - /vehicleInfo/vehicle/vehicleRealTimeResult (poll)

Note:
This module keeps HTTP request/response envelope logic.
All payload parsing/normalization lives on the realtime Pydantic model
(:class:`pybyd.models.realtime.VehicleRealtimeData`).
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

from pybyd._api._common import post_token_json
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.models.realtime import VehicleRealtimeData
from pybyd.session import Session

_logger = logging.getLogger(__name__)


def _build_realtime_inner(
    config: BydConfig,
    vin: str,
    now_ms: int,
    request_serial: str | None = None,
) -> dict[str, str]:
    """Build the inner payload for realtime endpoints."""
    inner: dict[str, str] = {
        "deviceType": config.device.device_type,
        "energyType": "0",
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "tboxVersion": config.tbox_version,
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }
    if request_serial:
        inner["requestSerial"] = request_serial
    return inner


def _is_realtime_data_ready(vehicle_info: dict[str, Any]) -> bool:
    """Backwards-compatible wrapper for ingestion readiness logic."""

    return VehicleRealtimeData.is_ready_raw(vehicle_info)


def _parse_vehicle_info(data: dict[str, Any]) -> VehicleRealtimeData:
    """Backwards-compatible wrapper for ingestion parsing."""

    return VehicleRealtimeData.from_api(data)


async def _fetch_realtime_endpoint(
    endpoint: str,
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    request_serial: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Fetch a single realtime endpoint, returning (vehicle_info_dict, next_serial)."""

    now_ms = int(time.time() * 1000)
    inner = _build_realtime_inner(config, vin, now_ms, request_serial)

    decoded = await post_token_json(
        endpoint=endpoint,
        config=config,
        session=session,
        transport=transport,
        inner=inner,
        now_ms=now_ms,
        vin=vin,
    )
    vehicle_info: dict[str, Any] = decoded if isinstance(decoded, dict) else {}
    next_serial = vehicle_info.get("requestSerial") or request_serial

    return vehicle_info, next_serial
