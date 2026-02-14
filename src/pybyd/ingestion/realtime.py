"""Realtime polling ingestion.

This module owns the "trigger + poll" loop for realtime telemetry.
The underlying HTTP endpoints live in :mod:`pybyd._api.realtime`.

Keeping the polling loop here makes the public client thinner and keeps
"how data enters" (ingestion) separate from "how it is merged" (state store).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pybyd._api.realtime import _fetch_realtime_endpoint
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydSessionExpiredError
from pybyd.models.realtime import VehicleRealtimeData
from pybyd.session import Session

_logger = logging.getLogger(__name__)


async def poll_vehicle_realtime(
    *,
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    poll_attempts: int = 10,
    poll_interval: float = 1.5,
    mqtt_pre_waiter: Callable[[str, float], Awaitable[bool]] | None = None,
    mqtt_pre_wait_seconds: float = 0.0,
    mqtt_last_raw_getter: Callable[[str], dict[str, Any] | None] | None = None,
    on_http_snapshot: Callable[[VehicleRealtimeData, dict[str, Any]], None] | None = None,
) -> VehicleRealtimeData:
    """Trigger a realtime request and poll until data is ready.

    Parameters
    ----------
    mqtt_pre_waiter
        Optional callback used as a short-circuit before HTTP polling (MQTT-first).
        It should resolve to True when a newer MQTT snapshot has been observed.
    mqtt_last_raw_getter
        Optional callback returning the latest raw realtime payload for the VIN.
        Used only when mqtt_pre_waiter returns True.
    on_http_snapshot
        Optional callback invoked for each HTTP snapshot (trigger + poll results).
        This is commonly used to update the state store.
    """

    # Phase 1: Trigger
    raw, serial = await _fetch_realtime_endpoint(
        "/vehicleInfo/vehicle/vehicleRealTimeRequest",
        config,
        session,
        transport,
        vin,
        None,
    )
    model = VehicleRealtimeData.from_api(raw)

    if on_http_snapshot is not None:
        on_http_snapshot(model, raw)

    if VehicleRealtimeData.is_ready_raw(raw) or not serial:
        return model

    # Phase 1.5: MQTT pre-wait
    if mqtt_pre_waiter is not None and mqtt_pre_wait_seconds > 0:
        try:
            mqtt_updated = await mqtt_pre_waiter(vin, mqtt_pre_wait_seconds)
        except Exception:
            _logger.debug("Realtime MQTT pre-wait failed; falling back to HTTP polling", exc_info=True)
            mqtt_updated = False

        if mqtt_updated and mqtt_last_raw_getter is not None:
            mqtt_raw = mqtt_last_raw_getter(vin)
            if isinstance(mqtt_raw, dict) and mqtt_raw:
                return VehicleRealtimeData.from_api(mqtt_raw)
            _logger.debug("Realtime MQTT update observed without raw payload; polling")

    # Phase 2: Poll
    latest_raw: dict[str, Any] = raw
    latest_serial: str | None = serial

    for _attempt in range(1, poll_attempts + 1):
        if poll_interval > 0:
            await asyncio.sleep(poll_interval)

        try:
            fetched, latest_serial = await _fetch_realtime_endpoint(
                "/vehicleInfo/vehicle/vehicleRealTimeResult",
                config,
                session,
                transport,
                vin,
                latest_serial,
            )
            latest_raw = fetched

            latest_model = VehicleRealtimeData.from_api(latest_raw)
            if on_http_snapshot is not None:
                on_http_snapshot(latest_model, latest_raw)

            if VehicleRealtimeData.is_ready_raw(latest_raw):
                return latest_model
        except BydSessionExpiredError:
            raise
        except Exception:
            _logger.debug("Realtime poll attempt failed", exc_info=True)

    return VehicleRealtimeData.from_api(latest_raw)
