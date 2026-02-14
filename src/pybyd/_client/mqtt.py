"""Internal MQTT coordination for BydClient.

Owns:
- starting/stopping the threaded MQTT runtime
- translating MQTT events into state-store updates
- waiters for MQTT-first workflows (realtime + remote control)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from pybyd._api.control import parse_remote_control_result_data
from pybyd._mqtt import BydMqttRuntime, MqttBootstrap, MqttEvent, fetch_mqtt_bootstrap
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.ingestion.mqtt import build_events_from_vehicle_info
from pybyd.models.control import RemoteCommand, RemoteControlResult
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
        self._control_serial_commands: dict[str, tuple[str, RemoteCommand]] = {}
        # Latest pending remote-control issued via pyBYD, keyed by vin.
        # Used when MQTT remoteControl completions omit requestSerial.
        self._control_latest_by_vin: dict[str, tuple[str, RemoteCommand, float]] = {}
        self._realtime_waiters: dict[str, list[asyncio.Event]] = {}
        self._realtime_versions: dict[str, int] = {}
        self._last_realtime_raw: dict[str, dict[str, Any]] = {}

    def remember_remote_control(self, request_serial: str, *, vin: str, command: RemoteCommand) -> None:
        """Remember which command a requestSerial belongs to.

        This is used to apply deterministic state updates when the MQTT
        `remoteControl` completion arrives.
        """

        serial = request_serial.strip()
        if not serial:
            return
        self._control_serial_commands[serial] = (vin, command)
        self._control_latest_by_vin[vin] = (serial, command, time.monotonic())

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

        # Best-effort HVAC cache update.
        #
        # The `vehicleInfo` MQTT payload does not include `status` / `acSwitch`,
        # so HVAC on/off can become stale unless we also react to remoteControl
        # completion events.
        if result.success:
            action: str | None = None

            # 1) Prefer deterministic mapping from the HTTP-issued requestSerial.
            serial_hint = result.request_serial
            if serial_hint is None:
                candidate = respond_data.get("requestSerial")
                serial_hint = candidate if isinstance(candidate, str) else None
            if serial_hint:
                remembered = self._control_serial_commands.pop(serial_hint, None)
                if remembered is not None:
                    _remembered_vin, remembered_cmd = remembered
                    if remembered_cmd == RemoteCommand.STOP_CLIMATE:
                        action = "off"
                    elif remembered_cmd == RemoteCommand.START_CLIMATE:
                        action = "on"

            # Some regions/vehicles omit requestSerial in MQTT completions.
            # In that case, correlate to the most recently issued pyBYD command
            # for this VIN (BYD cloud typically allows only one in-flight control).
            correlated_serial: str | None = None
            correlated_cmd: RemoteCommand | None = None
            if action is None:
                latest = self._control_latest_by_vin.get(vin)
                if latest is not None:
                    cand_serial, cand_cmd, cand_seen = latest
                    # Only trust very recent correlations.
                    if (time.monotonic() - cand_seen) <= 120.0:
                        correlated_serial = cand_serial
                        correlated_cmd = cand_cmd
                        if cand_cmd == RemoteCommand.STOP_CLIMATE:
                            action = "off"
                        elif cand_cmd == RemoteCommand.START_CLIMATE:
                            action = "on"

            # 2) App-initiated remoteControl MQTT may include commandType.
            if action is None:
                cmd_value = respond_data.get("commandType") or data_obj.get("commandType")
                if isinstance(cmd_value, str):
                    cmd_upper = cmd_value.strip().upper()
                    if cmd_upper == RemoteCommand.STOP_CLIMATE.value:
                        action = "off"
                    elif cmd_upper == RemoteCommand.START_CLIMATE.value:
                        action = "on"

            # 3) Last resort (app-initiated, no commandType): message string.
            if action is None:
                msg_value = respond_data.get("message") or respond_data.get("msg")
                if isinstance(msg_value, str):
                    msg_lower = msg_value.strip().lower()
                    if "deactivated" in msg_lower or "turned off" in msg_lower:
                        action = "off"
                    elif "activated" in msg_lower or "turned on" in msg_lower:
                        action = "on"

            if action is not None:
                payload_ts: float | None = None
                ts_raw = event.payload.get("timestamp")
                if isinstance(ts_raw, (int, float)):
                    # BYD uses epoch milliseconds in MQTT envelopes.
                    payload_ts = float(ts_raw) / 1000.0

                hvac_patch: dict[str, Any]
                if action == "off":
                    hvac_patch = {"status": 0, "ac_switch": 0}
                else:
                    # Remote climate start commonly sets status=2 without acSwitch.
                    hvac_patch = {"status": 2}

                self._store_apply(
                    IngestionEvent(
                        vin=vin,
                        section=StateSection.HVAC,
                        source=IngestionSource.MQTT,
                        payload_timestamp=payload_ts,
                        data=hvac_patch,
                        raw=respond_data,
                    )
                )

            # If we correlated a missing-serial completion, also resolve the
            # matching waiter so HTTP-side calls can return quickly.
            if correlated_serial:
                waiter = self._control_waiters.get(correlated_serial)
                if waiter is not None and not waiter.done():
                    waiter.set_result(result)
                # Clear correlation state once we've used it.
                self._control_serial_commands.pop(correlated_serial, None)
                latest = self._control_latest_by_vin.get(vin)
                if latest is not None and latest[0] == correlated_serial:
                    self._control_latest_by_vin.pop(vin, None)

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
            # Best-effort cleanup: if the command never completes via MQTT,
            # avoid keeping the requestSerial mapping forever.
            self._control_serial_commands.pop(request_serial, None)
            # Also drop VIN correlation if it points to this serial.
            for vin, (serial, _cmd, _ts) in list(self._control_latest_by_vin.items()):
                if serial == request_serial:
                    self._control_latest_by_vin.pop(vin, None)
