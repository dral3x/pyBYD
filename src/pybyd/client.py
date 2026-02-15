"""High-level async client for the BYD vehicle API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

import aiohttp

from pybyd._api import charging as _charging_api
from pybyd._api import control as _control_api
from pybyd._api import energy as _energy_api
from pybyd._api import gps as _gps_api
from pybyd._api import hvac as _hvac_api
from pybyd._api import push_notifications as _push_api
from pybyd._api import realtime as _realtime_api
from pybyd._api import smart_charging as _smart_api
from pybyd._api import vehicle_settings as _settings_api
from pybyd._api._common import fetch_vehicle_list
from pybyd._api.login import build_login_request, parse_login_response
from pybyd._crypto.bangcle import BangcleCodec
from pybyd._crypto.hashing import md5_hex
from pybyd._mqtt import BydMqttRuntime, MqttEvent, fetch_mqtt_bootstrap
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydError, BydSessionExpiredError
from pybyd.models.charging import ChargingStatus
from pybyd.models.control import (
    BatteryHeatParams,
    ClimateScheduleParams,
    ClimateStartParams,
    CommandAck,
    ControlParams,
    RemoteCommand,
    RemoteControlResult,
    SeatClimateParams,
    VerifyControlPasswordResponse,
)
from pybyd.models.energy import EnergyConsumption
from pybyd.models.gps import GpsInfo
from pybyd.models.hvac import HvacStatus
from pybyd.models.push_notification import PushNotificationState
from pybyd.models.realtime import VehicleRealtimeData
from pybyd.models.smart_charging import SmartChargingSchedule
from pybyd.models.vehicle import Vehicle
from pybyd.session import Session

_logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(slots=True)
class _MqttWaiter:
    """A pending MQTT wait registered by a client method.

    Matching rules: every non-None field must match the incoming event.
    ``serial`` is matched against a derived request serial which usually
    comes from ``respondData.requestSerial`` but for some event types
    (notably ``remoteControl``) is carried as ``data.uuid``.
    """

    vin: str
    future: asyncio.Future[dict[str, Any]]
    event_type: str | None = None
    serial: str | None = None
    created_at: float = field(default_factory=time.monotonic)


def _now_ms() -> int:
    """Current epoch timestamp in milliseconds."""
    return int(time.time() * 1000)


class BydClient:
    """Async client for the BYD vehicle API.

    Usage::

        async with BydClient(config) as client:
            await client.login()
            vehicles = await client.get_vehicles()
    """

    _REMOTE_CONTROL_OPPORTUNISTIC_WINDOW_S: float = 2.0

    def __init__(
        self,
        config: BydConfig,
        *,
        session: aiohttp.ClientSession | None = None,
        on_vehicle_info: Callable[[str, VehicleRealtimeData], None] | None = None,
        on_mqtt_event: Callable[[str, str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._config = config
        self._external_session = session is not None
        self._http_session = session
        self._codec = BangcleCodec()
        self._transport: SecureTransport | None = None
        self._session: Session | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mqtt_runtime: BydMqttRuntime | None = None
        self._mqtt_waiters: list[_MqttWaiter] = []
        self._on_vehicle_info = on_vehicle_info
        self._on_mqtt_event_cb = on_mqtt_event

    # ------------------------------------------------------------------
    # Context manager lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> BydClient:
        self._loop = asyncio.get_running_loop()
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        self._transport = SecureTransport(
            self._config,
            self._codec,
            self._http_session,
        )
        await self._codec.async_load_tables()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self._stop_mqtt()
        if not self._external_session and self._http_session is not None:
            await self._http_session.close()
            self._http_session = None
        self._transport = None
        self._loop = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def login(self) -> None:
        """Authenticate against the BYD API and obtain session tokens."""
        transport = self._require_transport()
        outer = build_login_request(self._config, _now_ms())
        response = await transport.post_secure("/app/account/login", outer)
        token = parse_login_response(response, self._config.password)

        ttl = self._config.session_ttl if self._config.session_ttl > 0 else float("inf")
        self._session = Session(
            user_id=token.user_id,
            sign_token=token.sign_token,
            encry_token=token.encry_token,
            ttl=ttl,
        )
        await self._ensure_mqtt_started()

    async def ensure_session(self) -> Session:
        """Return an active session, re-authenticating if expired."""
        if self._session is not None and not self._session.is_expired:
            return self._session
        await self.login()
        assert self._session is not None  # noqa: S101
        return self._session

    def invalidate_session(self) -> None:
        """Force session invalidation (next call will re-authenticate)."""
        self._session = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_transport(self) -> SecureTransport:
        if self._transport is None:
            raise BydError("Client not initialized. Use 'async with BydClient(...) as client:'")
        return self._transport

    def _resolve_command_pwd(self, command_pwd: str | None) -> str:
        """Normalize control password (uppercase MD5 hex of PIN)."""
        if command_pwd is not None:
            stripped = command_pwd.strip()
            if len(stripped) == 32 and all(ch in "0123456789abcdefABCDEF" for ch in stripped):
                return stripped.upper()
            return md5_hex(stripped)
        if self._config.control_pin:
            return md5_hex(self._config.control_pin)
        return ""

    def _require_command_pwd(self, command_pwd: str | None) -> str:
        resolved = self._resolve_command_pwd(command_pwd)
        if not resolved:
            raise ValueError("No control PIN available (set config.control_pin or pass command_pwd)")
        return resolved

    async def _call_with_reauth(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Run an API call, retrying once on session expiry."""
        try:
            return await fn()
        except BydSessionExpiredError:
            self.invalidate_session()
            await self.ensure_session()
            return await fn()

    # ------------------------------------------------------------------
    # MQTT (inline — replaces the deleted MqttCoordinator)
    # ------------------------------------------------------------------

    async def _ensure_mqtt_started(self) -> None:
        """Best-effort MQTT startup (failures must not break REST flow)."""
        if not self._config.mqtt_enabled:
            return
        if self._mqtt_runtime is not None and self._mqtt_runtime.is_running:
            return
        session = self._session
        transport = self._transport
        loop = self._loop or asyncio.get_running_loop()
        if session is None or transport is None:
            return
        try:
            bootstrap = await fetch_mqtt_bootstrap(self._config, session, transport)
            runtime = BydMqttRuntime(
                loop=loop,
                decrypt_key_hex=session.content_key(),
                on_event=self._on_mqtt_event,
                keepalive=self._config.mqtt_keepalive,
                logger=_logger,
            )
            runtime.start(bootstrap)
            self._mqtt_runtime = runtime
        except Exception:
            _logger.debug("MQTT startup failed", exc_info=True)

    def _stop_mqtt(self) -> None:
        runtime = self._mqtt_runtime
        self._mqtt_runtime = None
        if runtime is not None:
            runtime.stop()
        # Cancel any pending MQTT waiters so callers don't hang
        for w in self._mqtt_waiters:
            if not w.future.done():
                w.future.cancel()
        self._mqtt_waiters.clear()

    def _on_mqtt_event(self, event: MqttEvent) -> None:
        """Handle a decrypted MQTT event (called from the MQTT thread via call_soon_threadsafe)."""
        # BYD wraps payloads in data.respondData
        data = event.payload.get("data")
        respond_data_raw = data.get("respondData") if isinstance(data, dict) else event.payload

        if not isinstance(respond_data_raw, dict):
            return

        # Normalise to a standalone dict (avoid mutating the original payload)
        respond_data: dict[str, Any] = dict(respond_data_raw)

        # Derive correlation serial used by _mqtt_wait.
        # Most events include respondData.requestSerial, but remoteControl often uses data.uuid.
        serial: str | None = None
        serial_value = respond_data.get("requestSerial")
        if isinstance(serial_value, str) and serial_value:
            serial = serial_value
        elif isinstance(data, dict):
            for key in ("requestSerial", "uuid"):
                candidate = data.get(key)
                if isinstance(candidate, str) and candidate:
                    serial = candidate
                    break

        if serial:
            respond_data.setdefault("requestSerial", serial)

        # Generic callback — fire for every MQTT event
        if self._on_mqtt_event_cb is not None and event.vin:
            try:
                self._on_mqtt_event_cb(event.event, event.vin, respond_data)
            except Exception:
                _logger.debug("on_mqtt_event callback failed", exc_info=True)

        # vehicleInfo callback for on_vehicle_info
        if event.event == "vehicleInfo" and event.vin and self._on_vehicle_info is not None:
            try:
                realtime = VehicleRealtimeData.model_validate(respond_data)
                self._on_vehicle_info(event.vin, realtime)
            except Exception:
                _logger.debug("Failed to parse MQTT vehicleInfo", exc_info=True)

        # Dispatch to generic MQTT waiters
        serial_value = respond_data.get("requestSerial")
        serial = serial_value if isinstance(serial_value, str) and serial_value else None

        matched: list[_MqttWaiter] = []
        remaining: list[_MqttWaiter] = []
        opportunistic_used = False
        now = time.monotonic()
        for w in self._mqtt_waiters:
            if w.future.done():
                remaining.append(w)
                continue

            if w.vin != event.vin:
                remaining.append(w)
                continue

            if w.event_type is not None and w.event_type != event.event:
                remaining.append(w)
                continue

            # Normal case: strict correlation on requestSerial.
            if w.serial is None or w.serial == serial:
                matched.append(w)
                continue

            # Opportunistic fallback (remoteControl only): some MQTT payloads omit uuid/requestSerial.
            # To avoid accidentally resolving unrelated commands, only match the oldest pending waiter
            # within a short window, and only when the incoming event provides no serial.
            if (
                not opportunistic_used
                and serial is None
                and event.event == "remoteControl"
                and (now - w.created_at) <= self._REMOTE_CONTROL_OPPORTUNISTIC_WINDOW_S
            ):
                matched.append(w)
                opportunistic_used = True
                continue

            remaining.append(w)
        self._mqtt_waiters = remaining
        for w in matched:
            if not w.future.done():
                w.future.set_result(respond_data)

    async def _mqtt_wait(
        self,
        vin: str,
        *,
        event_type: str | None = None,
        serial: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Wait for an MQTT event matching the given criteria.

        Parameters
        ----------
        vin
            Vehicle to match.
        event_type
            MQTT event name to match (e.g. ``"vehicleInfo"``,
            ``"remoteControl"``).  ``None`` matches any event.
        serial
            ``requestSerial`` to match.  ``None`` matches any serial.
        timeout
            Seconds to wait.  Falls back to ``config.mqtt_timeout``.

        Returns
        -------
        dict or None
            The ``respondData`` dict from the MQTT payload, or ``None``
            on timeout / MQTT disabled.
        """
        runtime = self._mqtt_runtime
        effective_timeout = timeout if timeout is not None else self._config.mqtt_timeout
        if runtime is None or not runtime.is_running or effective_timeout <= 0:
            return None
        loop = self._loop or asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        waiter = _MqttWaiter(vin=vin, event_type=event_type, serial=serial, future=fut)
        self._mqtt_waiters.append(waiter)
        try:
            return await asyncio.wait_for(fut, effective_timeout)
        except TimeoutError:
            return None
        finally:
            with contextlib.suppress(ValueError):
                self._mqtt_waiters.remove(waiter)

    # ------------------------------------------------------------------
    # Read endpoints
    # ------------------------------------------------------------------

    async def get_vehicles(self) -> list[Vehicle]:
        """Fetch all vehicles associated with the account."""

        async def _call() -> list[Vehicle]:
            session = await self.ensure_session()
            transport = self._require_transport()
            return await fetch_vehicle_list(self._config, session, transport)

        return await self._call_with_reauth(_call)

    async def get_vehicle_realtime(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
        mqtt_timeout: float | None = None,
    ) -> VehicleRealtimeData:
        """Trigger + wait for realtime vehicle data.

        Sends a trigger request, then waits up to *mqtt_timeout* seconds
        for an MQTT ``vehicleInfo`` push.  Falls back to HTTP polling of
        ``vehicleRealTimeResult`` only if MQTT doesn't deliver in time.
        """

        async def _call() -> VehicleRealtimeData:
            session = await self.ensure_session()
            transport = self._require_transport()

            # Phase 1: Trigger
            trigger_info, serial = await _realtime_api._fetch_realtime_endpoint(
                "/vehicleInfo/vehicle/vehicleRealTimeRequest",
                self._config,
                session,
                transport,
                vin,
            )
            merged_latest = trigger_info if isinstance(trigger_info, dict) else {}

            if isinstance(trigger_info, dict) and VehicleRealtimeData.is_ready_raw(trigger_info):
                return VehicleRealtimeData.model_validate(merged_latest)

            if not serial:
                return VehicleRealtimeData.model_validate(merged_latest)

            # Phase 2: MQTT wait (preferred)
            mqtt_raw = await self._mqtt_wait(vin, event_type="vehicleInfo", serial=serial, timeout=mqtt_timeout)
            if isinstance(mqtt_raw, dict) and mqtt_raw:
                _logger.debug("Realtime data received via MQTT for vin=%s", vin)
                return VehicleRealtimeData.model_validate(mqtt_raw)

            # Phase 3: HTTP poll fallback
            _logger.debug("MQTT timeout; falling back to HTTP polling for vin=%s", vin)
            for attempt in range(1, poll_attempts + 1):
                if poll_interval > 0:
                    await asyncio.sleep(poll_interval)
                try:
                    latest, serial = await _realtime_api._fetch_realtime_endpoint(
                        "/vehicleInfo/vehicle/vehicleRealTimeResult",
                        self._config,
                        session,
                        transport,
                        vin,
                        serial,
                    )
                    if isinstance(latest, dict):
                        merged_latest = latest
                    if isinstance(latest, dict) and VehicleRealtimeData.is_ready_raw(latest):
                        _logger.debug("Realtime ready via HTTP vin=%s attempt=%d", vin, attempt)
                        break
                except BydSessionExpiredError:
                    raise
                except Exception:
                    _logger.debug("Realtime poll attempt=%d failed", attempt, exc_info=True)

            return VehicleRealtimeData.model_validate(merged_latest)

        return await self._call_with_reauth(_call)

    async def get_gps_info(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
        mqtt_timeout: float | None = None,
    ) -> GpsInfo:
        """Trigger + wait for GPS info.

        Sends a trigger request, then waits for an MQTT push carrying
        the ``requestSerial``.  Falls back to HTTP polling of
        ``getGpsInfoResult`` if MQTT doesn't deliver in time.
        """

        async def _call() -> GpsInfo:
            session = await self.ensure_session()
            transport = self._require_transport()

            # Phase 1: Trigger
            trigger_info, serial = await _gps_api._fetch_gps_endpoint(
                "/control/getGpsInfo",
                self._config,
                session,
                transport,
                vin,
            )
            merged_latest = trigger_info if isinstance(trigger_info, dict) else {}

            if isinstance(trigger_info, dict) and _gps_api._is_gps_info_ready(trigger_info):
                return GpsInfo.model_validate(merged_latest)

            if not serial:
                return GpsInfo.model_validate(merged_latest)

            # Phase 2: MQTT wait (preferred — match by serial, any event)
            mqtt_raw = await self._mqtt_wait(vin, serial=serial, timeout=mqtt_timeout)
            if isinstance(mqtt_raw, dict) and _gps_api._is_gps_info_ready(mqtt_raw):
                _logger.debug("GPS data received via MQTT for vin=%s", vin)
                return GpsInfo.model_validate(mqtt_raw)

            # Phase 3: HTTP poll fallback
            _logger.debug("MQTT timeout; falling back to HTTP polling for GPS vin=%s", vin)
            for attempt in range(1, poll_attempts + 1):
                if poll_interval > 0:
                    await asyncio.sleep(poll_interval)
                try:
                    latest, serial = await _gps_api._fetch_gps_endpoint(
                        "/control/getGpsInfoResult",
                        self._config,
                        session,
                        transport,
                        vin,
                        serial,
                    )
                    if isinstance(latest, dict):
                        merged_latest = latest
                    if isinstance(latest, dict) and _gps_api._is_gps_info_ready(latest):
                        _logger.debug("GPS ready via HTTP vin=%s attempt=%d", vin, attempt)
                        break
                except BydSessionExpiredError:
                    raise
                except Exception:
                    _logger.debug("GPS poll attempt=%d failed", attempt, exc_info=True)

            return GpsInfo.model_validate(merged_latest)

        return await self._call_with_reauth(_call)

    async def get_hvac_status(self, vin: str) -> HvacStatus:
        """Fetch HVAC / climate status."""

        async def _call() -> HvacStatus:
            session = await self.ensure_session()
            transport = self._require_transport()
            return await _hvac_api.fetch_hvac_status(self._config, session, transport, vin)

        return await self._call_with_reauth(_call)

    async def get_charging_status(self, vin: str) -> ChargingStatus:
        """Fetch charging status."""

        async def _call() -> ChargingStatus:
            session = await self.ensure_session()
            transport = self._require_transport()
            return await _charging_api.fetch_charging_status(self._config, session, transport, vin)

        return await self._call_with_reauth(_call)

    async def get_energy_consumption(self, vin: str) -> EnergyConsumption:
        """Fetch energy consumption data."""

        async def _call() -> EnergyConsumption:
            session = await self.ensure_session()
            transport = self._require_transport()
            return await _energy_api.fetch_energy_consumption(self._config, session, transport, vin)

        return await self._call_with_reauth(_call)

    async def get_push_state(self, vin: str) -> PushNotificationState:
        """Fetch push notification state."""

        async def _call() -> PushNotificationState:
            session = await self.ensure_session()
            transport = self._require_transport()
            return await _push_api.get_push_state(self._config, session, transport, vin)

        return await self._call_with_reauth(_call)

    async def set_push_state(self, vin: str, *, enable: bool) -> CommandAck:
        """Enable or disable push notifications."""

        async def _call() -> CommandAck:
            session = await self.ensure_session()
            transport = self._require_transport()
            return await _push_api.set_push_state(self._config, session, transport, vin, enable=enable)

        return await self._call_with_reauth(_call)

    # ------------------------------------------------------------------
    # Control commands
    # ------------------------------------------------------------------

    async def verify_control_password(
        self,
        vin: str,
        *,
        command_pwd: str | None = None,
    ) -> VerifyControlPasswordResponse:
        """Verify the remote control PIN."""
        pwd = self._require_command_pwd(command_pwd)

        async def _call() -> VerifyControlPasswordResponse:
            session = await self.ensure_session()
            transport = self._require_transport()
            return await _control_api.verify_control_password(self._config, session, transport, vin, pwd)

        return await self._call_with_reauth(_call)

    async def _remote_control(
        self,
        vin: str,
        command: RemoteCommand,
        *,
        control_params: Mapping[str, Any] | ControlParams | None = None,
        command_pwd: str | None = None,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
    ) -> RemoteControlResult:
        """Internal: send a remote command and poll/wait for result."""
        params_dict: dict[str, Any] | None = None
        if control_params is not None:
            if isinstance(control_params, ControlParams):
                params_dict = control_params.to_control_params_map()
            else:
                params_dict = dict(control_params)

        async def _mqtt_result_waiter(serial: str | None) -> RemoteControlResult | None:
            """Adapter: generic _mqtt_wait → RemoteControlResult."""
            if serial is None:
                return None
            raw = await self._mqtt_wait(vin, event_type="remoteControl", serial=serial)
            if raw is None:
                return None
            return RemoteControlResult.model_validate(raw)

        async def _call() -> RemoteControlResult:
            session = await self.ensure_session()
            transport = self._require_transport()
            return await _control_api.poll_remote_control(
                self._config,
                session,
                transport,
                vin,
                command,
                control_params=params_dict,
                command_pwd=command_pwd,
                poll_attempts=poll_attempts,
                poll_interval=poll_interval,
                mqtt_result_waiter=_mqtt_result_waiter,
            )

        return await self._call_with_reauth(_call)

    async def lock(
        self,
        vin: str,
        *,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Lock the vehicle."""
        pwd = self._require_command_pwd(command_pwd)
        return await self._remote_control(vin, RemoteCommand.LOCK, command_pwd=pwd)

    async def unlock(
        self,
        vin: str,
        *,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Unlock the vehicle."""
        pwd = self._require_command_pwd(command_pwd)
        return await self._remote_control(vin, RemoteCommand.UNLOCK, command_pwd=pwd)

    async def start_climate(
        self,
        vin: str,
        *,
        params: ClimateStartParams,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Start climate control with the given parameters."""
        pwd = self._require_command_pwd(command_pwd)
        return await self._remote_control(
            vin,
            RemoteCommand.START_CLIMATE,
            control_params=params,
            command_pwd=pwd,
        )

    async def stop_climate(
        self,
        vin: str,
        *,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Stop climate control."""
        pwd = self._require_command_pwd(command_pwd)
        return await self._remote_control(vin, RemoteCommand.STOP_CLIMATE, command_pwd=pwd)

    async def flash_lights(
        self,
        vin: str,
        *,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Flash vehicle lights."""
        pwd = self._require_command_pwd(command_pwd)
        return await self._remote_control(vin, RemoteCommand.FLASH_LIGHTS, command_pwd=pwd)

    async def close_windows(
        self,
        vin: str,
        *,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Close all windows."""
        pwd = self._require_command_pwd(command_pwd)
        return await self._remote_control(vin, RemoteCommand.CLOSE_WINDOWS, command_pwd=pwd)

    async def find_car(
        self,
        vin: str,
        *,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Activate find-my-car (horn + lights)."""
        pwd = self._require_command_pwd(command_pwd)
        return await self._remote_control(vin, RemoteCommand.FIND_CAR, command_pwd=pwd)

    async def schedule_climate(
        self,
        vin: str,
        *,
        params: ClimateScheduleParams,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Schedule climate control."""
        pwd = self._require_command_pwd(command_pwd)
        return await self._remote_control(
            vin,
            RemoteCommand.SCHEDULE_CLIMATE,
            control_params=params,
            command_pwd=pwd,
        )

    async def set_seat_climate(
        self,
        vin: str,
        *,
        params: SeatClimateParams,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Set seat heating/ventilation."""
        pwd = self._require_command_pwd(command_pwd)
        return await self._remote_control(
            vin,
            RemoteCommand.SEAT_CLIMATE,
            control_params=params,
            command_pwd=pwd,
        )

    async def set_battery_heat(
        self,
        vin: str,
        *,
        params: BatteryHeatParams,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Enable or disable battery heating."""
        pwd = self._require_command_pwd(command_pwd)
        return await self._remote_control(
            vin,
            RemoteCommand.BATTERY_HEAT,
            control_params=params,
            command_pwd=pwd,
        )

    async def save_charging_schedule(
        self,
        vin: str,
        schedule: SmartChargingSchedule,
    ) -> CommandAck:
        """Save a smart charging schedule."""
        if (
            schedule.target_soc is None
            or schedule.start_hour is None
            or schedule.start_minute is None
            or schedule.end_hour is None
            or schedule.end_minute is None
        ):
            raise ValueError("SmartChargingSchedule must have all time fields set")
        target_soc = schedule.target_soc
        start_hour = schedule.start_hour
        start_minute = schedule.start_minute
        end_hour = schedule.end_hour
        end_minute = schedule.end_minute

        async def _call() -> CommandAck:
            session = await self.ensure_session()
            transport = self._require_transport()
            return await _smart_api.save_charging_schedule(
                self._config,
                session,
                transport,
                vin,
                target_soc=target_soc,
                start_hour=start_hour,
                start_minute=start_minute,
                end_hour=end_hour,
                end_minute=end_minute,
            )

        return await self._call_with_reauth(_call)

    async def toggle_smart_charging(self, vin: str, *, enable: bool) -> CommandAck:
        """Enable or disable smart charging."""

        async def _call() -> CommandAck:
            session = await self.ensure_session()
            transport = self._require_transport()
            return await _smart_api.toggle_smart_charging(self._config, session, transport, vin, enable=enable)

        return await self._call_with_reauth(_call)

    async def rename_vehicle(self, vin: str, *, name: str) -> CommandAck:
        """Rename a vehicle."""

        async def _call() -> CommandAck:
            session = await self.ensure_session()
            transport = self._require_transport()
            return await _settings_api.rename_vehicle(self._config, session, transport, vin, name=name)

        return await self._call_with_reauth(_call)
