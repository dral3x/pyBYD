"""High-level async client for the BYD vehicle API."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import aiohttp

from pybyd._api.charging import fetch_charging_status
from pybyd._api.control import poll_remote_control
from pybyd._api.energy import fetch_energy_consumption
from pybyd._api.gps import poll_gps_info
from pybyd._api.hvac import fetch_hvac_status
from pybyd._api.login import build_login_request, parse_login_response
from pybyd._crypto.hashing import md5_hex
from pybyd._api.realtime import poll_vehicle_realtime
from pybyd._api.vehicles import build_list_request, parse_vehicle_list
from pybyd._cache import VehicleDataCache
from pybyd._crypto.bangcle import BangcleCodec
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError, BydAuthenticationError, BydError
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

#: API error codes that indicate the session token is no longer valid.
#: When one of these is encountered the client will transparently
#: re-authenticate and retry the request once.
_SESSION_EXPIRED_CODES: frozenset[str] = frozenset({"1005", "1010"})


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
        self._debug_recorder = debug_recorder

    async def __aenter__(self) -> BydClient:
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        self._transport = SecureTransport(self._config, self._codec, self._http_session)
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
            if exc.code not in _SESSION_EXPIRED_CODES:
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
            if exc.code not in _SESSION_EXPIRED_CODES:
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
            if exc.code not in _SESSION_EXPIRED_CODES:
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
            If the API returns an error.
        BydError
            If not logged in.
        """
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
        except BydApiError as exc:
            if exc.code not in _SESSION_EXPIRED_CODES:
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

        If *command_pwd* is provided it is used as-is (caller is
        responsible for hashing).  Otherwise the PIN from
        ``config.control_pin`` is MD5-hashed automatically.

        Returns
        -------
        str
            MD5 uppercase hex of the control PIN, or empty string
            if no PIN is configured.
        """
        if command_pwd is not None:
            return command_pwd
        if self._config.control_pin:
            return md5_hex(self._config.control_pin)
        return ""

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
        session = await self.ensure_session()
        transport = self._require_transport()
        resolved_pwd = self._resolve_command_pwd(command_pwd)
        try:
            return await poll_remote_control(
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
        except BydApiError as exc:
            if exc.code not in _SESSION_EXPIRED_CODES:
                raise
            _logger.debug("Session rejected (code %s) — re-authenticating", exc.code)
            self.invalidate_session()
            session = await self.ensure_session()
            return await poll_remote_control(
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
        params = {"batteryHeat": 1 if on else 0}
        return await self.remote_control(
            vin,
            RemoteCommand.BATTERY_HEAT,
            control_params=params,
            command_pwd=command_pwd,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    # ── Read-only status endpoints ───────────────────────────

    async def get_hvac_status(self, vin: str) -> HvacStatus:
        """Fetch current HVAC / climate control status.

        Uses ``/control/getStatusNow``.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.

        Returns
        -------
        HvacStatus
            Current climate control state.
        """
        session = await self.ensure_session()
        transport = self._require_transport()
        try:
            return await fetch_hvac_status(self._config, session, transport, vin, cache=self._cache)
        except BydApiError as exc:
            if exc.code not in _SESSION_EXPIRED_CODES:
                raise
            _logger.debug("Session rejected (code %s) — re-authenticating", exc.code)
            self.invalidate_session()
            session = await self.ensure_session()
            return await fetch_hvac_status(self._config, session, transport, vin, cache=self._cache)

    async def get_charging_status(self, vin: str) -> ChargingStatus:
        """Fetch smart charging status (SOC, charge state, time-to-full).

        Uses ``/control/smartCharge/homePage``.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.

        Returns
        -------
        ChargingStatus
            Battery and charging state.
        """
        session = await self.ensure_session()
        transport = self._require_transport()
        try:
            return await fetch_charging_status(self._config, session, transport, vin, cache=self._cache)
        except BydApiError as exc:
            if exc.code not in _SESSION_EXPIRED_CODES:
                raise
            _logger.debug("Session rejected (code %s) — re-authenticating", exc.code)
            self.invalidate_session()
            session = await self.ensure_session()
            return await fetch_charging_status(self._config, session, transport, vin, cache=self._cache)
