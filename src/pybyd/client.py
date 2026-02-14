"""High-level async client for the BYD vehicle API."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, TypeVar

import aiohttp

from pybyd._api.login import build_login_request, parse_login_response
from pybyd._client import commands as _commands
from pybyd._client import reads as _reads
from pybyd._client.mqtt import MqttCoordinator
from pybyd._crypto.bangcle import BangcleCodec
from pybyd._crypto.hashing import md5_hex
from pybyd._mqtt import MqttBootstrap, MqttEvent
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydError, BydSessionExpiredError
from pybyd.models.charging import ChargingStatus
from pybyd.models.command_responses import CommandAck, VerifyControlPasswordResponse
from pybyd.models.control import RemoteCommand, RemoteControlResult
from pybyd.models.control_params import (
    BatteryHeatParams,
    ClimateScheduleParams,
    ClimateStartParams,
    ControlCallOptions,
    ControlParams,
    SeatClimateParams,
)
from pybyd.models.energy import EnergyConsumption
from pybyd.models.gps import GpsInfo
from pybyd.models.hvac import HvacStatus
from pybyd.models.push_notification import PushNotificationState
from pybyd.models.realtime import VehicleRealtimeData
from pybyd.models.smart_charging import SmartChargingSchedule
from pybyd.models.vehicle import Vehicle
from pybyd.session import Session
from pybyd.state.events import IngestionEvent, IngestionSource, StateSection
from pybyd.state.store import StateStore

_logger = logging.getLogger(__name__)

T = TypeVar("T")


def _now_ms() -> int:
    """Current epoch timestamp in milliseconds (BYD endpoints use ms stamps)."""
    return int(time.time() * 1000)


class BydClient:
    """Async client for the BYD vehicle API."""

    def __init__(
        self,
        config: BydConfig,
        *,
        session: aiohttp.ClientSession | None = None,
        codec: BangcleCodec | None = None,
        store: StateStore | None = None,
        response_trace_recorder: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._config = config
        self._external_session = session is not None
        self._http_session = session
        self._codec = codec or BangcleCodec()
        self._response_trace_recorder = response_trace_recorder
        self._transport: SecureTransport | None = None
        self._session: Session | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mqtt: MqttCoordinator | None = None
        self._store = store or StateStore()

    async def __aenter__(self) -> BydClient:
        self._loop = asyncio.get_running_loop()
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        self._transport = SecureTransport(
            self._config,
            self._codec,
            self._http_session,
            trace_recorder=self._response_trace_recorder,
        )
        await self._codec.async_load_tables()
        self._mqtt = MqttCoordinator(
            config=self._config,
            loop=self._loop,
            store_apply=self._store.apply,
            logger=_logger,
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._mqtt is not None:
            await self._mqtt.stop()
            self._mqtt = None
        if not self._external_session and self._http_session is not None:
            await self._http_session.close()
            self._http_session = None
        self._transport = None
        self._loop = None

    @property
    def store(self) -> StateStore:
        return self._store

    @property
    def _mqtt_runtime(self) -> Any:  # noqa: SLF001
        """Compatibility shim for internal/tests (runtime owned by `MqttCoordinator`)."""
        coordinator = self._mqtt
        return coordinator.runtime if coordinator is not None else None

    def _require_transport(self) -> SecureTransport:
        """Return initialized transport or raise a clear lifecycle error."""
        if self._transport is None:
            raise BydError("Client not initialized. Use 'async with BydClient(...) as client:'")
        return self._transport

    async def login(self) -> None:
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
        await self._ensure_mqtt_runtime_started()

    async def ensure_session(self) -> Session:
        if self._session is not None and not self._session.is_expired:
            return self._session
        await self.login()
        assert self._session is not None  # noqa: S101
        return self._session

    def invalidate_session(self) -> None:
        self._session = None

    def _resolve_command_pwd(self, command_pwd: str | None) -> str:
        """Normalize control password (uppercase MD5 hex of PIN; raw PIN or digest accepted)."""
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

    @staticmethod
    def _resolve_call_options(
        *,
        options: ControlCallOptions | None,
        command_pwd: str | None,
        poll_attempts: int | None,
        poll_interval: float | None,
    ) -> ControlCallOptions:
        """Merge explicit call kwargs with an options object (explicit kwargs win)."""
        base = options or ControlCallOptions()
        return ControlCallOptions(
            command_pwd=command_pwd if command_pwd is not None else base.command_pwd,
            poll_attempts=poll_attempts if poll_attempts is not None else base.poll_attempts,
            poll_interval=poll_interval if poll_interval is not None else base.poll_interval,
        )

    async def _call_with_reauth(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Run an API call, retrying once if the server reports session expiry."""
        try:
            return await fn()
        except BydSessionExpiredError:
            self.invalidate_session()
            await self.ensure_session()
            return await fn()

    async def get_mqtt_bootstrap(self) -> MqttBootstrap:
        session = await self.ensure_session()
        transport = self._require_transport()
        coordinator = self._mqtt
        if coordinator is None:
            raise BydError("Client not initialized. Use 'async with BydClient(...) as client:'")
        return await coordinator.get_bootstrap(session, transport)

    async def _ensure_mqtt_runtime_started(self) -> None:
        """Best-effort MQTT startup (optional enrichment; failures must not break REST)."""
        coordinator = self._mqtt
        loop = self._loop or asyncio.get_running_loop()
        self._loop = loop
        session = self._session
        transport = self._transport
        if coordinator is None or session is None or transport is None:
            return
        await coordinator.ensure_started(session, transport)

    def _on_mqtt_event(self, event: MqttEvent) -> None:
        """Internal hook used by tests to inject decrypted MQTT events."""
        coordinator = self._mqtt
        if coordinator is not None:
            coordinator._on_event(event)

    async def apply_optimistic(
        self,
        vin: str,
        *,
        section: StateSection,
        patch: dict[str, Any],
        ttl_seconds: float | None = None,
    ) -> None:
        """Apply an optimistic overlay.

        By default, optimistic overlays expire after the store's configured TTL.
        When ``ttl_seconds`` is set and <= 0, the overlay becomes "sticky" and
        will not expire on its own (but is still cleared by any non-optimistic
        update for the same section).
        """
        self._store.apply(
            IngestionEvent(
                vin=vin,
                section=section,
                source=IngestionSource.OPTIMISTIC,
                payload_timestamp=None,
                data=patch,
                raw={"patch": patch, "__pybyd_optimistic_ttl_s": ttl_seconds},
            )
        )

    async def get_vehicles(self) -> list[Vehicle]:
        return await _reads.get_vehicles(self)

    async def get_vehicle_realtime(
        self, vin: str, *, poll_attempts: int = 10, poll_interval: float = 1.5, stale_after: float | None = None
    ) -> VehicleRealtimeData:
        return await _reads.get_vehicle_realtime(
            self,
            vin=vin,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
            stale_after=stale_after,
        )

    async def get_gps_info(self, vin: str, *, poll_attempts: int = 10, poll_interval: float = 1.5) -> GpsInfo:
        return await _reads.get_gps_info(self, vin=vin, poll_attempts=poll_attempts, poll_interval=poll_interval)

    async def get_hvac_status(self, vin: str) -> HvacStatus:
        return await _reads.get_hvac_status(self, vin=vin)

    async def get_charging_status(self, vin: str) -> ChargingStatus:
        return await _reads.get_charging_status(self, vin=vin)

    async def get_energy_consumption(self, vin: str) -> EnergyConsumption:
        return await _reads.get_energy_consumption(self, vin=vin)

    async def get_push_state(self, vin: str) -> PushNotificationState:
        return await _reads.get_push_state(self, vin=vin)

    async def set_push_state(self, vin: str, *, enable: bool) -> CommandAck:
        return await _reads.set_push_state(self, vin=vin, enable=enable)

    async def verify_control_password(
        self, vin: str, *, command_pwd: str | None = None
    ) -> VerifyControlPasswordResponse:
        return await _commands.verify_control_password(self, vin=vin, command_pwd=command_pwd)

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
        return await _commands._remote_control(
            self,
            vin=vin,
            command=command,
            control_params=control_params,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def lock(
        self,
        vin: str,
        *,
        options: ControlCallOptions | None = None,
        command_pwd: str | None = None,
        poll_attempts: int | None = None,
        poll_interval: float | None = None,
    ) -> RemoteControlResult:
        return await _commands.lock(
            self,
            vin=vin,
            options=options,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def unlock(
        self,
        vin: str,
        *,
        options: ControlCallOptions | None = None,
        command_pwd: str | None = None,
        poll_attempts: int | None = None,
        poll_interval: float | None = None,
    ) -> RemoteControlResult:
        return await _commands.unlock(
            self,
            vin=vin,
            options=options,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def start_climate(
        self,
        vin: str,
        *,
        params: ClimateStartParams | None = None,
        preset: Literal["max_heat", "max_cool"] | None = None,
        options: ControlCallOptions | None = None,
        temperature: int | None = None,
        temperature_c: float | None = None,
        copilot_temperature: int | None = None,
        copilot_temperature_c: float | None = None,
        cycle_mode: int | None = None,
        time_span: int | None = None,
        ac_switch: int | None = None,
        air_accuracy: int | None = None,
        air_conditioning_mode: int | None = None,
        remote_mode: int | None = None,
        wind_level: int | None = None,
        wind_position: int | None = None,
        command_pwd: str | None = None,
        poll_attempts: int | None = None,
        poll_interval: float | None = None,
    ) -> RemoteControlResult:
        return await _commands.start_climate(
            self,
            vin=vin,
            params=params,
            preset=preset,
            options=options,
            temperature=temperature,
            temperature_c=temperature_c,
            copilot_temperature=copilot_temperature,
            copilot_temperature_c=copilot_temperature_c,
            cycle_mode=cycle_mode,
            time_span=time_span,
            ac_switch=ac_switch,
            air_accuracy=air_accuracy,
            air_conditioning_mode=air_conditioning_mode,
            remote_mode=remote_mode,
            wind_level=wind_level,
            wind_position=wind_position,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def stop_climate(
        self,
        vin: str,
        *,
        options: ControlCallOptions | None = None,
        command_pwd: str | None = None,
        poll_attempts: int | None = None,
        poll_interval: float | None = None,
    ) -> RemoteControlResult:
        return await _commands.stop_climate(
            self,
            vin=vin,
            options=options,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def flash_lights(
        self,
        vin: str,
        *,
        options: ControlCallOptions | None = None,
        command_pwd: str | None = None,
        poll_attempts: int | None = None,
        poll_interval: float | None = None,
    ) -> RemoteControlResult:
        return await _commands.flash_lights(
            self,
            vin=vin,
            options=options,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def close_windows(
        self,
        vin: str,
        *,
        options: ControlCallOptions | None = None,
        command_pwd: str | None = None,
        poll_attempts: int | None = None,
        poll_interval: float | None = None,
    ) -> RemoteControlResult:
        return await _commands.close_windows(
            self,
            vin=vin,
            options=options,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def find_car(
        self,
        vin: str,
        *,
        options: ControlCallOptions | None = None,
        command_pwd: str | None = None,
        poll_attempts: int | None = None,
        poll_interval: float | None = None,
    ) -> RemoteControlResult:
        return await _commands.find_car(
            self,
            vin=vin,
            options=options,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def schedule_climate(
        self,
        vin: str,
        *,
        params: ClimateScheduleParams | None = None,
        options: ControlCallOptions | None = None,
        booking_id: int | None = None,
        booking_time: int | None = None,
        command_pwd: str | None = None,
        poll_attempts: int | None = None,
        poll_interval: float | None = None,
    ) -> RemoteControlResult:
        return await _commands.schedule_climate(
            self,
            vin=vin,
            params=params,
            options=options,
            booking_id=booking_id,
            booking_time=booking_time,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def set_seat_climate(
        self,
        vin: str,
        *,
        params: SeatClimateParams | None = None,
        options: ControlCallOptions | None = None,
        main_heat: int | None = None,
        main_ventilation: int | None = None,
        copilot_heat: int | None = None,
        copilot_ventilation: int | None = None,
        lr_seat_heat: int | None = None,
        lr_seat_ventilation: int | None = None,
        rr_seat_heat: int | None = None,
        rr_seat_ventilation: int | None = None,
        steering_wheel_heat: int | None = None,
        command_pwd: str | None = None,
        poll_attempts: int | None = None,
        poll_interval: float | None = None,
    ) -> RemoteControlResult:
        return await _commands.set_seat_climate(
            self,
            vin=vin,
            params=params,
            options=options,
            main_heat=main_heat,
            main_ventilation=main_ventilation,
            copilot_heat=copilot_heat,
            copilot_ventilation=copilot_ventilation,
            lr_seat_heat=lr_seat_heat,
            lr_seat_ventilation=lr_seat_ventilation,
            rr_seat_heat=rr_seat_heat,
            rr_seat_ventilation=rr_seat_ventilation,
            steering_wheel_heat=steering_wheel_heat,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def set_battery_heat(
        self,
        vin: str,
        *,
        params: BatteryHeatParams | None = None,
        options: ControlCallOptions | None = None,
        on: bool | None = None,
        command_pwd: str | None = None,
        poll_attempts: int | None = None,
        poll_interval: float | None = None,
    ) -> RemoteControlResult:
        return await _commands.set_battery_heat(
            self,
            vin=vin,
            params=params,
            options=options,
            on=on,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def save_charging_schedule(
        self,
        vin: str,
        schedule: SmartChargingSchedule | None = None,
        *,
        target_soc: int | None = None,
        start_hour: int | None = None,
        start_minute: int | None = None,
        end_hour: int | None = None,
        end_minute: int | None = None,
    ) -> CommandAck:
        return await _commands.save_charging_schedule(
            self,
            vin=vin,
            schedule=schedule,
            target_soc=target_soc,
            start_hour=start_hour,
            start_minute=start_minute,
            end_hour=end_hour,
            end_minute=end_minute,
        )

    async def toggle_smart_charging(self, vin: str, *, enable: bool) -> CommandAck:
        return await _commands.toggle_smart_charging(self, vin=vin, enable=enable)

    async def rename_vehicle(self, vin: str, *, name: str) -> CommandAck:
        return await _commands.rename_vehicle(self, vin=vin, name=name)
