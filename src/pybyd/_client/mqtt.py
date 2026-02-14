"""Internal MQTT coordination for BydClient.

Owns:
- starting/stopping the threaded MQTT runtime
- translating MQTT events into state-store updates
- waiters for MQTT-first workflows (realtime + remote control)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from pybyd._api.control import parse_remote_control_result_data
from pybyd._mqtt import BydMqttRuntime, MqttBootstrap, MqttEvent, fetch_mqtt_bootstrap
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.ingestion.mqtt import build_events_from_vehicle_info
from pybyd.models.control import RemoteControlResult
from pybyd.session import Session
from pybyd.state.events import IngestionEvent, IngestionSource, StateSection


class MqttCoordinator:
    def __init__(
        self,
        *,
        config: BydConfig,
        loop: asyncio.AbstractEventLoop,
        store_apply: Callable[[IngestionEvent], None],
        logger: logging.Logger,
    ) -> None:
        self._config = config
        self._loop = loop
        self._store_apply = store_apply
        self._logger = logger
        self._runtime: BydMqttRuntime | None = None

        self._control_waiters: dict[str, asyncio.Future[RemoteControlResult]] = {}
        self._realtime_waiters: dict[str, list[asyncio.Event]] = {}
        self._realtime_versions: dict[str, int] = {}
        self._last_realtime_raw: dict[str, dict[str, Any]] = {}

    @property
    def runtime(self) -> BydMqttRuntime | None:
        return self._runtime

    def last_realtime_raw(self, vin: str) -> dict[str, Any] | None:
        return self._last_realtime_raw.get(vin)

    async def get_bootstrap(self, session: Session, transport: SecureTransport) -> MqttBootstrap:
        return await fetch_mqtt_bootstrap(self._config, session, transport)

    async def ensure_started(self, session: Session, transport: SecureTransport) -> None:
        if not self._config.mqtt_enabled:
            return

        try:
            bootstrap = await self.get_bootstrap(session, transport)
            runtime = BydMqttRuntime(
                loop=self._loop,
                decrypt_key_hex=session.content_key(),
                on_event=self._on_event,
                keepalive=self._config.mqtt_keepalive,
                logger=self._logger,
            )
            previous = self._runtime
            await self._loop.run_in_executor(None, runtime.start, bootstrap)
            self._runtime = runtime
            if previous is not None:
                await self._loop.run_in_executor(None, previous.stop)
        except Exception:
            self._logger.debug("MQTT runtime start failed", exc_info=True)

    async def stop(self) -> None:
        runtime = self._runtime
        self._runtime = None
        if runtime is None:
            return
        try:
            await self._loop.run_in_executor(None, runtime.stop)
        except Exception:
            self._logger.debug("MQTT runtime stop failed", exc_info=True)

    def _on_event(self, event: MqttEvent) -> None:
        if event.event == "vehicleInfo":
            self._handle_vehicle_info(event)
            return
        if event.event == "remoteControl":
            self._handle_remote_control(event)
            return

    def _handle_vehicle_info(self, event: MqttEvent) -> None:
        vin = event.vin
        if not vin:
            return

        events, raw = build_events_from_vehicle_info(vin=vin, payload=event.payload)
        for ev in events:
            self._store_apply(ev)

        if isinstance(raw, dict):
            self._last_realtime_raw[vin] = raw
        self._notify_realtime(vin)

    def _notify_realtime(self, vin: str) -> None:
        self._realtime_versions[vin] = self._realtime_versions.get(vin, 0) + 1
        waiters = self._realtime_waiters.pop(vin, [])
        for waiter in waiters:
            if not waiter.is_set():
                waiter.set()

    async def wait_for_realtime(self, vin: str, timeout_seconds: float) -> bool:
        runtime = self._runtime
        if runtime is None or not runtime.is_running or timeout_seconds <= 0:
            return False

        baseline = self._realtime_versions.get(vin, 0)
        waiter = asyncio.Event()
        self._realtime_waiters.setdefault(vin, []).append(waiter)

        if self._realtime_versions.get(vin, 0) != baseline:
            waiter.set()

        try:
            await asyncio.wait_for(waiter.wait(), timeout_seconds)
            return True
        except TimeoutError:
            return False
        finally:
            pending = self._realtime_waiters.get(vin)
            if pending is not None:
                self._realtime_waiters[vin] = [cand for cand in pending if cand is not waiter]
                if not self._realtime_waiters[vin]:
                    self._realtime_waiters.pop(vin, None)

    def _handle_remote_control(self, event: MqttEvent) -> None:
        vin = event.vin
        if not vin:
            return
        data_obj = event.payload.get("data")
        if not isinstance(data_obj, dict):
            return
        respond_data = data_obj.get("respondData")
        if not isinstance(respond_data, dict):
            return

        result = parse_remote_control_result_data(respond_data)
        self._store_apply(
            IngestionEvent(
                vin=vin,
                section=StateSection.CONTROL,
                source=IngestionSource.MQTT,
                payload_timestamp=None,
                data=result.model_dump(exclude={"raw"}),
                raw=respond_data,
            )
        )

        serial = result.request_serial
        if serial is None:
            candidate = respond_data.get("requestSerial")
            serial = candidate if isinstance(candidate, str) else None
        if not serial:
            return
        waiter = self._control_waiters.get(serial)
        if waiter is not None and not waiter.done():
            waiter.set_result(result)

    async def wait_for_remote_control(self, request_serial: str | None) -> RemoteControlResult | None:
        runtime = self._runtime
        if runtime is None or not runtime.is_running or not request_serial:
            return None

        existing = self._control_waiters.get(request_serial)
        waiter = existing if existing is not None else self._loop.create_future()
        self._control_waiters[request_serial] = waiter

        try:
            return await asyncio.wait_for(waiter, self._config.mqtt_command_timeout)
        except TimeoutError:
            return None
        finally:
            current = self._control_waiters.get(request_serial)
            if current is waiter and waiter.done():
                self._control_waiters.pop(request_serial, None)
