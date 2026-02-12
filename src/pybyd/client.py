"""High-level async client for the BYD vehicle API."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from pybyd._api.charging import fetch_charging_status
from pybyd._api.control import poll_remote_control
from pybyd._api.control import verify_control_password as verify_control_password_api
from pybyd._api.energy import energy_from_realtime_cache, fetch_energy_consumption
from pybyd._api.gps import poll_gps_info
from pybyd._api.hvac import fetch_hvac_status
from pybyd._api.login import build_login_request, parse_login_response
from pybyd._api.realtime import poll_vehicle_realtime
from pybyd._api.vehicles import build_list_request, parse_vehicle_list
from pybyd._cache import VehicleDataCache
from pybyd._constants import SESSION_EXPIRED_CODES
from pybyd._crypto.bangcle import BangcleCodec
from pybyd._crypto.hashing import md5_hex
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import (
    BydApiError,
    BydEndpointNotSupportedError,
    BydError,
    BydRateLimitError,
)
from pybyd.models.charging import ChargingStatus
from pybyd.models.control import RemoteCommand, RemoteControlResult
from pybyd.models.energy import EnergyConsumption
from pybyd.models.gps import GpsInfo
from pybyd.models.hvac import HvacStatus
from pybyd.models.realtime import VehicleRealtimeData
from pybyd.models.token import AuthToken
from pybyd.models.vehicle import Vehicle
from pybyd.session import Session

_logger = logging.getLogger(__name__)


def _validate_climate_temperature(value: int, name: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an int in range 1-17 (BYD level scale)")
    if value < 1 or value > 17:
        raise ValueError(f"{name} must be in range 1-17 (BYD level scale)")
    return value


class BydClient:
    """Async client for the BYD vehicle telemetry API.

    Use as an async context manager::

        async with BydClient(BydConfig.from_env()) as client:
            token = await client.login()
            vehicles = await client.get_vehicles()
            status = await client.get_vehicle_realtime(vehicles[0].vin)

    Parameters
    ----------
    config : BydConfig
        Client configuration with credentials and settings.
    session : aiohttp.ClientSession or None
        Optional externally managed HTTP session (e.g. for Home
        Assistant integrations). If not provided, a new session is
        created and closed automatically.
    codec : BangcleCodec or None
        Optional Bangcle codec instance. If not provided, one is
        created with default table loading.
    debug_recorder : callable or None
        Optional callback for recording control command payloads.
    """

    def __init__(
        self,
        config: BydConfig,
        *,
        session: aiohttp.ClientSession | None = None,
        codec: BangcleCodec | None = None,
        debug_recorder: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._config = config
        self._external_session = session is not None
        self._http_session = session
        self._codec = codec or BangcleCodec()
        self._transport: SecureTransport | None = None
        self._session: Session | None = None
        self._cache = VehicleDataCache()
        self._unsupported: dict[str, set[str]] = {}
        self._vehicle_permission_codes: dict[str, set[str]] = {}
        self._debug_recorder = debug_recorder

    @staticmethod
    def _flatten_permission_codes(vehicle: Vehicle) -> set[str]:
        """Flatten range detail permission codes for a vehicle."""
        codes: set[str] = set()
        stack = list(vehicle.range_detail_list)
        while stack:
            node = stack.pop()
            code = (node.code or "").strip()
            if code:
                codes.add(code)
            stack.extend(node.children)
        return codes

    @staticmethod
    def _control_unsupported_key(command: RemoteCommand) -> str:
        return f"control:{command.value}"

    def _mark_control_unsupported(self, vin: str, command: RemoteCommand) -> None:
        self._unsupported.setdefault(vin, set()).add(self._control_unsupported_key(command))

    def _is_control_unsupported(self, vin: str, command: RemoteCommand) -> bool:
        return self._control_unsupported_key(command) in self._unsupported.get(vin, set())

    def _is_shared_basic_control_only(self, vin: str) -> bool:
        """Whether shared-account permissions indicate only basic controls.

        Observed permission shape for shared users:
        - "2" parent scope: Keys and control
        - "21" child scope: Basic control
        """
        codes = self._vehicle_permission_codes.get(vin)
        if not codes:
            return False
        control_children = {code for code in codes if code.startswith("2") and code != "2"}
        return "2" in codes and control_children == {"21"}

    async def __aenter__(self) -> BydClient:
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        self._transport = SecureTransport(self._config, self._codec, self._http_session)
        await self._codec.async_load_tables()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if not self._external_session and self._http_session is not None:
            await self._http_session.close()
            self._http_session = None
        self._transport = None

    def _require_transport(self) -> SecureTransport:
        """Return the transport or raise if not initialized."""
        if self._transport is None:
            raise BydError("Client not initialized. Use 'async with BydClient(...) as client:'")
        return self._transport

    @property
    def is_logged_in(self) -> bool:
        """Whether the client has an active, non-expired session."""
        return self._session is not None and not self._session.is_expired

    async def login(self) -> AuthToken:
        """Authenticate with the BYD API.

        Creates a new session, replacing any existing one.  Prefer
        :meth:`ensure_session` for normal usage — it only logs in
        when necessary.

        Returns
        -------
        AuthToken
            The authentication token with user ID and session tokens.

        Raises
        ------
        BydAuthenticationError
            If login fails.
        """
        transport = self._require_transport()
        now_ms = int(time.time() * 1000)
        outer = build_login_request(self._config, now_ms)
        response = await transport.post_secure("/app/account/login", outer)
        token = parse_login_response(response, self._config.password)

        ttl = self._config.session_ttl if self._config.session_ttl > 0 else float("inf")
        self._session = Session(
            user_id=token.user_id,
            sign_token=token.sign_token,
            encry_token=token.encry_token,
            ttl=ttl,
        )
        _logger.debug("Login succeeded for user_id=%s", token.user_id)
        return token

    async def ensure_session(self) -> Session:
        """Return a valid session, logging in automatically if needed.

        * First call → performs login.
        * Subsequent calls → returns the cached session.
        * Expired session → performs a fresh login.

        This is the recommended way to obtain a session for API calls.
        All public data-fetching methods call this internally, so
        explicit login is no longer required.

        Returns
        -------
        Session
            An active, non-expired session.

        Raises
        ------
        BydAuthenticationError
            If login fails.
        """
        if self._session is not None and not self._session.is_expired:
            return self._session
        if self._session is not None:
            _logger.info(
                "Session expired after %.0f s — re-authenticating",
                self._session.age,
            )
        await self.login()
        assert self._session is not None  # login() always sets this  # noqa: S101
        return self._session

    def invalidate_session(self) -> None:
        """Discard the current session, forcing re-login on next call."""
        self._session = None

    async def get_vehicles(self) -> list[Vehicle]:
        """Fetch all vehicles associated with the account.

        Returns
        -------
        list[Vehicle]
            List of vehicles.

        Raises
        ------
        BydApiError
            If the API returns an error.
        BydError
            If not logged in.
        """
        session = await self.ensure_session()
        transport = self._require_transport()
        try:
            now_ms = int(time.time() * 1000)
            outer, content_key = build_list_request(self._config, session, now_ms)
            response = await transport.post_secure("/app/account/getAllListByUserId", outer)
            vehicles = parse_vehicle_list(response, content_key)
        except BydApiError as exc:
            if exc.code not in SESSION_EXPIRED_CODES:
                raise
            _logger.debug("Session rejected (code %s) — re-authenticating", exc.code)
            self.invalidate_session()
            session = await self.ensure_session()
            now_ms = int(time.time() * 1000)
            outer, content_key = build_list_request(self._config, session, now_ms)
            response = await transport.post_secure("/app/account/getAllListByUserId", outer)
            vehicles = parse_vehicle_list(response, content_key)
        for vehicle in vehicles:
            if isinstance(vehicle.raw, dict) and vehicle.vin:
                self._cache.merge_vehicle(vehicle.vin, vehicle.raw)
                self._vehicle_permission_codes[vehicle.vin] = self._flatten_permission_codes(vehicle)
        return vehicles

    async def get_vehicle_realtime(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
        stale_after: float | None = None,
    ) -> VehicleRealtimeData:
        """Fetch realtime telemetry data for a vehicle.

        Triggers a data request and polls until fresh data arrives
        or the poll limit is reached.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        poll_attempts : int
            Maximum number of result poll attempts (default 10).
        poll_interval : float
            Seconds between poll attempts (default 1.5).
        stale_after : float or None
            If set, skip polling when cached data is newer than this
            number of seconds. Defaults to ``poll_interval``.

        Returns
        -------
        VehicleRealtimeData
            The latest vehicle telemetry data.

        Raises
        ------
        BydApiError
            If the API returns an error.
        BydError
            If not logged in.
        """
        session = await self.ensure_session()
        transport = self._require_transport()
        try:
            return await poll_vehicle_realtime(
                self._config,
                session,
                transport,
                vin,
                poll_attempts=poll_attempts,
                poll_interval=poll_interval,
                cache=self._cache,
                stale_after=stale_after,
            )
        except BydApiError as exc:
            if exc.code not in SESSION_EXPIRED_CODES:
                raise
            _logger.debug("Session rejected (code %s) — re-authenticating", exc.code)
            self.invalidate_session()
            session = await self.ensure_session()
            return await poll_vehicle_realtime(
                self._config,
                session,
                transport,
                vin,
                poll_attempts=poll_attempts,
                poll_interval=poll_interval,
                cache=self._cache,
                stale_after=stale_after,
            )

    async def get_gps_info(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
        stale_after: float | None = None,
    ) -> GpsInfo:
        """Fetch GPS location data for a vehicle.

        Triggers a GPS request and polls until data arrives or the
        poll limit is reached.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        poll_attempts : int
            Maximum number of result poll attempts (default 10).
        poll_interval : float
            Seconds between poll attempts (default 1.5).
        stale_after : float or None
            If set, skip polling when cached data is newer than this
            number of seconds. Defaults to ``poll_interval``.

        Returns
        -------
        GpsInfo
            The latest GPS data.

        Raises
        ------
        BydApiError
            If the API returns an error.
        BydError
            If not logged in.
        """
        session = await self.ensure_session()
        transport = self._require_transport()
        try:
            return await poll_gps_info(
                self._config,
                session,
                transport,
                vin,
                poll_attempts=poll_attempts,
                poll_interval=poll_interval,
                cache=self._cache,
                stale_after=stale_after,
            )
        except BydApiError as exc:
            if exc.code not in SESSION_EXPIRED_CODES:
                raise
            _logger.debug("Session rejected (code %s) — re-authenticating", exc.code)
            self.invalidate_session()
            session = await self.ensure_session()
            return await poll_gps_info(
                self._config,
                session,
                transport,
                vin,
                poll_attempts=poll_attempts,
                poll_interval=poll_interval,
                cache=self._cache,
                stale_after=stale_after,
            )

    async def get_energy_consumption(self, vin: str) -> EnergyConsumption:
        """Fetch energy consumption data for a vehicle.

        If the dedicated energy endpoint is not supported (code 1001),
        a best-effort ``EnergyConsumption`` is built from cached
        realtime data instead.  The fallback is remembered so
        subsequent calls skip the failing endpoint entirely.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.

        Returns
        -------
        EnergyConsumption
            Energy consumption data.

        Raises
        ------
        BydApiError
            If the API returns an error other than not-supported.
        BydError
            If not logged in.
        """
        if "energy" in self._unsupported.get(vin, set()):
            return energy_from_realtime_cache(vin, self._cache)

        session = await self.ensure_session()
        transport = self._require_transport()
        try:
            return await fetch_energy_consumption(
                self._config,
                session,
                transport,
                vin,
                cache=self._cache,
            )
        except BydEndpointNotSupportedError:
            _logger.info(
                "Energy endpoint not supported for %s — using realtime fallback",
                vin,
            )
            self._unsupported.setdefault(vin, set()).add("energy")
            return energy_from_realtime_cache(vin, self._cache)
        except BydApiError as exc:
            if exc.code not in SESSION_EXPIRED_CODES:
                raise
            _logger.debug("Session rejected (code %s) — re-authenticating", exc.code)
            self.invalidate_session()
            session = await self.ensure_session()
            return await fetch_energy_consumption(
                self._config,
                session,
                transport,
                vin,
                cache=self._cache,
            )

    def _resolve_command_pwd(self, command_pwd: str | None) -> str:
        """Resolve the command password (MD5-hashed control PIN).

        If *command_pwd* is provided, this method accepts either:
        - a raw PIN/plaintext (will be MD5-hashed), or
        - an already-hashed 32-char hex digest (normalized to uppercase).

        Otherwise the PIN from ``config.control_pin`` is MD5-hashed
        automatically.

        Returns
        -------
        str
            MD5 uppercase hex of the control PIN, or empty string
            if no PIN is configured.
        """
        if command_pwd is not None:
            stripped = command_pwd.strip()
            if len(stripped) == 32 and all(ch in "0123456789abcdefABCDEF" for ch in stripped):
                return stripped.upper()
            return md5_hex(stripped)
        if self._config.control_pin:
            return md5_hex(self._config.control_pin)
        return ""

    async def _verify_control_password(self, vin: str, resolved_pwd: str) -> bool:
        """Verify control password for a VIN."""
        if not resolved_pwd:
            return False

        session = await self.ensure_session()
        transport = self._require_transport()
        try:
            await verify_control_password_api(
                self._config,
                session,
                transport,
                vin,
                resolved_pwd,
            )
        except BydApiError as exc:
            if exc.code not in SESSION_EXPIRED_CODES:
                raise
            _logger.debug("Session rejected (code %s) — re-authenticating", exc.code)
            self.invalidate_session()
            session = await self.ensure_session()
            await verify_control_password_api(
                self._config,
                session,
                transport,
                vin,
                resolved_pwd,
            )
        return True

    async def verify_control_password(
        self,
        vin: str,
        *,
        command_pwd: str | None = None,
    ) -> bool:
        """Verify remote control password for a VIN.

        Uses ``command_pwd`` if provided, otherwise ``config.control_pin``.
        Returns ``True`` when verification succeeds, ``False`` when no
        control PIN/password is configured.
        """
        resolved_pwd = self._resolve_command_pwd(command_pwd)
        return await self._verify_control_password(vin, resolved_pwd)

    def _optimistic_merge_realtime(self, vin: str, data: dict[str, Any]) -> None:
        if not data:
            return
        payload = dict(data)
        payload.setdefault("time", int(time.time()))
        self._cache.merge_realtime(vin, payload)

    def _optimistic_merge_hvac(self, vin: str, data: dict[str, Any]) -> None:
        if not data:
            return
        payload = dict(data)
        payload.setdefault("time", int(time.time()))
        self._cache.merge_hvac(vin, payload)

    def _optimistic_merge_charging(self, vin: str, data: dict[str, Any]) -> None:
        if not data:
            return
        payload = dict(data)
        payload.setdefault("updateTime", int(time.time()))
        payload.setdefault("vin", vin)
        self._cache.merge_charging(vin, payload)

    def _apply_optimistic_command_state(
        self,
        vin: str,
        command: RemoteCommand,
        *,
        control_params: dict[str, Any] | None = None,
    ) -> None:
        """Apply optimistic cache updates for successful remote commands."""
        if command == RemoteCommand.LOCK:
            self._optimistic_merge_realtime(
                vin,
                {
                    "leftFrontDoorLock": 2,
                    "rightFrontDoorLock": 2,
                    "leftRearDoorLock": 2,
                    "rightRearDoorLock": 2,
                    "slidingDoorLock": 2,
                },
            )
            return

        if command == RemoteCommand.UNLOCK:
            self._optimistic_merge_realtime(
                vin,
                {
                    "leftFrontDoorLock": 1,
                    "rightFrontDoorLock": 1,
                    "leftRearDoorLock": 1,
                    "rightRearDoorLock": 1,
                    "slidingDoorLock": 1,
                },
            )
            return

        if command == RemoteCommand.CLOSE_WINDOWS:
            self._optimistic_merge_realtime(
                vin,
                {
                    "leftFrontWindow": 1,
                    "rightFrontWindow": 1,
                    "leftRearWindow": 1,
                    "rightRearWindow": 1,
                    "skylight": 1,
                },
            )
            return

        if command == RemoteCommand.START_CLIMATE:
            params = control_params or {}
            main_temp = params.get("mainSettingTemp")
            copilot_temp = params.get("copilotSettingTemp")
            cycle_mode = params.get("cycleMode")
            hvac_patch: dict[str, Any] = {
                "acSwitch": 1,
                "status": 2,
                "airConditioningMode": 1,
            }
            realtime_patch: dict[str, Any] = {}
            if isinstance(main_temp, int):
                hvac_patch["mainSettingTemp"] = main_temp
                realtime_patch["mainSettingTemp"] = main_temp
            if isinstance(copilot_temp, int):
                hvac_patch["copilotSettingTemp"] = copilot_temp
            if isinstance(cycle_mode, int):
                hvac_patch["cycleChoice"] = cycle_mode
                realtime_patch["airRunState"] = cycle_mode
            self._optimistic_merge_hvac(vin, hvac_patch)
            self._optimistic_merge_realtime(vin, realtime_patch)
            return

        if command == RemoteCommand.STOP_CLIMATE:
            params = control_params or {}
            main_temp = params.get("mainSettingTemp")
            copilot_temp = params.get("copilotSettingTemp")
            cycle_mode = params.get("cycleMode")
            hvac_patch = {
                "acSwitch": 0,
                "status": 0,
                "airConditioningMode": 0,
            }
            realtime_patch: dict[str, Any] = {}
            if isinstance(main_temp, int):
                hvac_patch["mainSettingTemp"] = main_temp
                realtime_patch["mainSettingTemp"] = main_temp
            if isinstance(copilot_temp, int):
                hvac_patch["copilotSettingTemp"] = copilot_temp
            if isinstance(cycle_mode, int):
                hvac_patch["cycleChoice"] = cycle_mode
                realtime_patch["airRunState"] = cycle_mode
            self._optimistic_merge_hvac(vin, hvac_patch)
            self._optimistic_merge_realtime(vin, realtime_patch)
            return

        if command == RemoteCommand.SEAT_CLIMATE:
            params = control_params or {}
            seat_field_map = {
                "mainHeat": "mainSeatHeatState",
                "mainVentilation": "mainSeatVentilationState",
                "copilotHeat": "copilotSeatHeatState",
                "copilotVentilation": "copilotSeatVentilationState",
                "lrSeatHeatState": "lrSeatHeatState",
                "lrSeatVentilationState": "lrSeatVentilationState",
                "rrSeatHeatState": "rrSeatHeatState",
                "rrSeatVentilationState": "rrSeatVentilationState",
                "steeringWheelHeatState": "steeringWheelHeatState",
            }
            hvac_patch: dict[str, Any] = {}
            realtime_patch: dict[str, Any] = {}
            for source_key, target_key in seat_field_map.items():
                value = params.get(source_key)
                if isinstance(value, int):
                    hvac_patch[target_key] = value
                    realtime_patch[target_key] = value
            if hvac_patch:
                self._optimistic_merge_hvac(vin, hvac_patch)
            if realtime_patch:
                self._optimistic_merge_realtime(vin, realtime_patch)
            return

        if command == RemoteCommand.BATTERY_HEAT:
            params = control_params or {}
            battery_heat = params.get("batteryHeat")
            if isinstance(battery_heat, int):
                self._optimistic_merge_realtime(vin, {"batteryHeatState": battery_heat})

    def _finalize_remote_control_result(
        self,
        vin: str,
        command: RemoteCommand,
        result: RemoteControlResult,
        *,
        control_params: dict[str, Any] | None = None,
    ) -> RemoteControlResult:
        """Apply post-command side effects before returning a result."""
        if result.success:
            self._apply_optimistic_command_state(
                vin,
                command,
                control_params=control_params,
            )
        return result

    async def remote_control(
        self,
        vin: str,
        command: RemoteCommand,
        *,
        control_params: dict[str, Any] | None = None,
        command_pwd: str | None = None,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
        rate_limit_retries: int = 3,
        rate_limit_delay: float = 5.0,
        command_retries: int = 3,
        command_retry_delay: float = 3.0,
    ) -> RemoteControlResult:
        """Send a remote control command to a vehicle.

        Triggers the command and polls until the vehicle confirms
        success/failure or the poll limit is reached.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        command : RemoteCommand
            The remote command to send.
        control_params : dict or None
            Command-specific parameters (serialised as
            ``controlParamsMap``).
        command_pwd : str or None
            Pre-hashed control password. If ``None``, the
            ``control_pin`` from config is MD5-hashed automatically.
        poll_attempts : int
            Maximum number of result poll attempts (default 10).
        poll_interval : float
            Seconds between poll attempts (default 1.5).
        rate_limit_retries : int
            How many times to retry on code 6024 (default 3).
        rate_limit_delay : float
            Seconds to wait between rate-limit retries (default 5.0).
        command_retries : int
            How many times to retry the whole command on failure
            (controlState=2). Default 3.
        command_retry_delay : float
            Seconds to wait between command retries (default 3.0).

        Returns
        -------
        RemoteControlResult
            The command result.

        Raises
        ------
        BydRemoteControlError
            If the command fails (controlState=2) after all retries.
        BydRateLimitError
            If rate-limited after all retries (code 6024).
        BydApiError
            If the API returns an error.
        BydError
            If not logged in.
        """
        if self._is_control_unsupported(vin, command):
            raise BydEndpointNotSupportedError(
                f"Remote control command {command.name} is marked unsupported for {vin}",
                code="1001",
                endpoint="/control/remoteControl",
            )

        session = await self.ensure_session()
        transport = self._require_transport()
        resolved_pwd = self._resolve_command_pwd(command_pwd)
        try:
            result = await poll_remote_control(
                self._config,
                session,
                transport,
                vin,
                command,
                control_params=control_params,
                command_pwd=resolved_pwd,
                poll_attempts=poll_attempts,
                poll_interval=poll_interval,
                rate_limit_retries=rate_limit_retries,
                rate_limit_delay=rate_limit_delay,
                command_retries=command_retries,
                command_retry_delay=command_retry_delay,
                debug_recorder=self._debug_recorder,
            )
            return self._finalize_remote_control_result(
                vin,
                command,
                result,
                control_params=control_params,
            )
        except BydEndpointNotSupportedError:
            self._mark_control_unsupported(vin, command)
            raise
        except BydApiError as exc:
            if exc.code not in SESSION_EXPIRED_CODES:
                raise
            _logger.debug("Session rejected (code %s) — re-authenticating", exc.code)
            self.invalidate_session()
            session = await self.ensure_session()
            try:
                result = await poll_remote_control(
                    self._config,
                    session,
                    transport,
                    vin,
                    command,
                    control_params=control_params,
                    command_pwd=resolved_pwd,
                    poll_attempts=poll_attempts,
                    poll_interval=poll_interval,
                    rate_limit_retries=rate_limit_retries,
                    rate_limit_delay=rate_limit_delay,
                    command_retries=command_retries,
                    command_retry_delay=command_retry_delay,
                    debug_recorder=self._debug_recorder,
                )
                return self._finalize_remote_control_result(
                    vin,
                    command,
                    result,
                    control_params=control_params,
                )
            except BydEndpointNotSupportedError:
                self._mark_control_unsupported(vin, command)
                raise

    # ── Simple commands (no controlParamsMap) ────────────────

    async def lock(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Lock the vehicle doors."""
        return await self.remote_control(
            vin,
            RemoteCommand.LOCK,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def unlock(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Unlock the vehicle doors."""
        return await self.remote_control(
            vin,
            RemoteCommand.UNLOCK,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def flash_lights(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
    ) -> RemoteControlResult:
        """Flash the vehicle lights (without horn)."""
        return await self.remote_control(
            vin,
            RemoteCommand.FLASH_LIGHTS,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def find_car(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
    ) -> RemoteControlResult:
        """Flash lights and honk horn to locate the vehicle."""
        return await self.remote_control(
            vin,
            RemoteCommand.FIND_CAR,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def close_windows(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
    ) -> RemoteControlResult:
        """Close all windows."""
        return await self.remote_control(
            vin,
            RemoteCommand.CLOSE_WINDOWS,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    # ── Climate control ──────────────────────────────────────

    async def start_climate(
        self,
        vin: str,
        *,
        temperature: int = 7,
        copilot_temperature: int | None = None,
        cycle_mode: int = 2,
        time_span: int = 1,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Start climate control with temperature settings.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        temperature : int
            Driver-side temperature level (1=~15 °C fast cool,
            7=~21 °C default, 17=max heat).
        copilot_temperature : int or None
            Passenger-side temperature. Defaults to ``temperature``.
        cycle_mode : int
            Air circulation (1=internal/recirculate, 2=external/fresh).
        time_span : int
            Duration setting (1=default).
        """
        temperature = _validate_climate_temperature(temperature, "temperature")
        if copilot_temperature is not None:
            copilot_temperature = _validate_climate_temperature(
                copilot_temperature,
                "copilot_temperature",
            )
        params = {
            "airSet": None,
            "remoteMode": 4,
            "timeSpan": time_span,
            "mainSettingTemp": temperature,
            "copilotSettingTemp": (copilot_temperature if copilot_temperature is not None else temperature),
            "cycleMode": cycle_mode,
            "airAccuracy": 1,
            "airConditioningMode": 1,
        }
        return await self.remote_control(
            vin,
            RemoteCommand.START_CLIMATE,
            control_params=params,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def stop_climate(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Stop climate control."""
        params = {
            "airSet": None,
            "remoteMode": 4,
            "timeSpan": 0,
            "mainSettingTemp": 7,
            "copilotSettingTemp": 7,
            "cycleMode": 2,
            "airAccuracy": 1,
            "airConditioningMode": 0,
        }
        return await self.remote_control(
            vin,
            RemoteCommand.STOP_CLIMATE,
            control_params=params,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    # ── Seat / steering wheel heating ────────────────────────

    async def set_seat_climate(
        self,
        vin: str,
        *,
        main_heat: int = 0,
        main_ventilation: int = 0,
        copilot_heat: int = 0,
        copilot_ventilation: int = 0,
        lr_seat_heat: int = 0,
        lr_seat_ventilation: int = 0,
        rr_seat_heat: int = 0,
        rr_seat_ventilation: int = 0,
        lr_third_heat: int = 0,
        lr_third_ventilation: int = 0,
        rr_third_heat: int = 0,
        rr_third_ventilation: int = 0,
        steering_wheel_heat: int = 0,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Set seat heating/ventilation and steering wheel heating.

        All heating/ventilation levels are 0=off, 1–3 for intensity.
        Steering wheel heating is 0=off, 1=on.
        """
        any_active = any(
            [
                main_heat,
                main_ventilation,
                copilot_heat,
                copilot_ventilation,
                lr_seat_heat,
                lr_seat_ventilation,
                rr_seat_heat,
                rr_seat_ventilation,
                lr_third_heat,
                lr_third_ventilation,
                rr_third_heat,
                rr_third_ventilation,
                steering_wheel_heat,
            ]
        )
        params = {
            "chairType": "5",
            "remoteMode": 1 if any_active else 0,
            "mainHeat": main_heat,
            "mainVentilation": main_ventilation,
            "copilotHeat": copilot_heat,
            "copilotVentilation": copilot_ventilation,
            "lrSeatHeatState": lr_seat_heat,
            "lrSeatVentilationState": lr_seat_ventilation,
            "rrSeatHeatState": rr_seat_heat,
            "rrSeatVentilationState": rr_seat_ventilation,
            "lrThirdHeatState": lr_third_heat,
            "lrThirdVentilationState": lr_third_ventilation,
            "rrThirdHeatState": rr_third_heat,
            "rrThirdVentilationState": rr_third_ventilation,
            "steeringWheelHeatState": steering_wheel_heat,
        }
        return await self.remote_control(
            vin,
            RemoteCommand.SEAT_CLIMATE,
            control_params=params,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    # ── Battery preheating ───────────────────────────────────

    async def set_battery_heat(
        self,
        vin: str,
        *,
        on: bool = True,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
        command_pwd: str | None = None,
    ) -> RemoteControlResult:
        """Enable or disable battery preheating.

        Parameters
        ----------
        on : bool
            True to enable, False to disable.
        """
        if self._is_shared_basic_control_only(vin):
            self._mark_control_unsupported(vin, RemoteCommand.BATTERY_HEAT)
            raise BydEndpointNotSupportedError(
                f"Battery heat appears unsupported for {vin} under shared 'Basic control' permission scope",
                code="1001",
                endpoint="/control/remoteControl",
            )

        params = {"batteryHeat": 1 if on else 0}
        try:
            return await self.remote_control(
                vin,
                RemoteCommand.BATTERY_HEAT,
                control_params=params,
                command_pwd=command_pwd,
                poll_attempts=poll_attempts,
                poll_interval=poll_interval,
            )
        except BydRateLimitError as exc:
            if self._is_shared_basic_control_only(vin):
                self._mark_control_unsupported(vin, RemoteCommand.BATTERY_HEAT)
                raise BydEndpointNotSupportedError(
                    (
                        f"Battery heat likely unsupported for {vin}; repeated "
                        "BATTERY_HEAT rate limits under basic shared control"
                    ),
                    code="1001",
                    endpoint="/control/remoteControl",
                ) from exc
            raise

    # ── Read-only status endpoints ───────────────────────────

    async def get_hvac_status(self, vin: str) -> HvacStatus | None:
        """Fetch current HVAC / climate control status.

        Uses ``/control/getStatusNow``.  Returns ``None`` when the
        endpoint is not supported for this vehicle.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.

        Returns
        -------
        HvacStatus or None
            Current climate control state, or None if unsupported.
        """
        if "hvac" in self._unsupported.get(vin, set()):
            return None

        session = await self.ensure_session()
        transport = self._require_transport()
        try:
            return await fetch_hvac_status(self._config, session, transport, vin, cache=self._cache)
        except BydEndpointNotSupportedError:
            _logger.info("HVAC endpoint not supported for %s", vin)
            self._unsupported.setdefault(vin, set()).add("hvac")
            return None
        except BydApiError as exc:
            if exc.code not in SESSION_EXPIRED_CODES:
                raise
            _logger.debug("Session rejected (code %s) — re-authenticating", exc.code)
            self.invalidate_session()
            session = await self.ensure_session()
            return await fetch_hvac_status(self._config, session, transport, vin, cache=self._cache)

    async def get_charging_status(self, vin: str) -> ChargingStatus | None:
        """Fetch smart charging status (SOC, charge state, time-to-full).

        Uses ``/control/smartCharge/homePage``.  Returns ``None`` when
        the endpoint is not supported for this vehicle.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.

        Returns
        -------
        ChargingStatus or None
            Battery and charging state, or None if unsupported.
        """
        if "charging" in self._unsupported.get(vin, set()):
            return None

        session = await self.ensure_session()
        transport = self._require_transport()
        try:
            return await fetch_charging_status(self._config, session, transport, vin, cache=self._cache)
        except BydEndpointNotSupportedError:
            _logger.info("Charging endpoint not supported for %s", vin)
            self._unsupported.setdefault(vin, set()).add("charging")
            return None
        except BydApiError as exc:
            if exc.code not in SESSION_EXPIRED_CODES:
                raise
            _logger.debug("Session rejected (code %s) — re-authenticating", exc.code)
            self.invalidate_session()
            session = await self.ensure_session()
            return await fetch_charging_status(self._config, session, transport, vin, cache=self._cache)
