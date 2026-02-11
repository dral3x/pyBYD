"""High-level async client for the BYD vehicle API."""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from pybyd._api.charging import fetch_charging_status
from pybyd._api.control import poll_remote_control
from pybyd._api.energy import fetch_energy_consumption
from pybyd._api.gps import poll_gps_info
from pybyd._api.hvac import fetch_hvac_status
from pybyd._api.login import build_login_request, parse_login_response
from pybyd._api.realtime import poll_vehicle_realtime
from pybyd._api.vehicles import build_list_request, parse_vehicle_list
from pybyd._crypto.bangcle import BangcleCodec
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydError
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
    """

    def __init__(
        self,
        config: BydConfig,
        *,
        session: aiohttp.ClientSession | None = None,
        codec: BangcleCodec | None = None,
    ) -> None:
        self._config = config
        self._external_session = session is not None
        self._http_session = session
        self._codec = codec or BangcleCodec()
        self._transport: SecureTransport | None = None
        self._session: Session | None = None

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

    def _require_session(self) -> Session:
        """Return the current session or raise if not logged in."""
        if self._session is None:
            raise BydError("Not logged in. Call login() first.")
        return self._session

    def _require_transport(self) -> SecureTransport:
        """Return the transport or raise if not initialized."""
        if self._transport is None:
            raise BydError("Client not initialized. Use 'async with BydClient(...) as client:'")
        return self._transport

    @property
    def is_logged_in(self) -> bool:
        """Whether the client has an active session."""
        return self._session is not None

    async def login(self) -> AuthToken:
        """Authenticate with the BYD API.

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

        self._session = Session(
            user_id=token.user_id,
            sign_token=token.sign_token,
            encry_token=token.encry_token,
        )
        _logger.info("Login succeeded for user_id=%s", token.user_id)
        return token

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
        session = self._require_session()
        transport = self._require_transport()
        now_ms = int(time.time() * 1000)
        outer, content_key = build_list_request(self._config, session, now_ms)
        response = await transport.post_secure("/app/account/getAllListByUserId", outer)
        return parse_vehicle_list(response, content_key)

    async def get_vehicle_realtime(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
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
        session = self._require_session()
        transport = self._require_transport()
        return await poll_vehicle_realtime(
            self._config,
            session,
            transport,
            vin,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def get_gps_info(
        self,
        vin: str,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
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
        session = self._require_session()
        transport = self._require_transport()
        return await poll_gps_info(
            self._config,
            session,
            transport,
            vin,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
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
        session = self._require_session()
        transport = self._require_transport()
        return await fetch_energy_consumption(
            self._config,
            session,
            transport,
            vin,
        )

    async def remote_control(
        self,
        vin: str,
        command: RemoteCommand,
        *,
        poll_attempts: int = 10,
        poll_interval: float = 1.5,
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
        poll_attempts : int
            Maximum number of result poll attempts (default 10).
        poll_interval : float
            Seconds between poll attempts (default 1.5).

        Returns
        -------
        RemoteControlResult
            The command result.

        Raises
        ------
        BydRemoteControlError
            If the command fails (controlState=2).
        BydApiError
            If the API returns an error.
        BydError
            If not logged in.
        """
        session = self._require_session()
        transport = self._require_transport()
        return await poll_remote_control(
            self._config,
            session,
            transport,
            vin,
            command,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
        )

    async def lock(self, vin: str, **kwargs: Any) -> RemoteControlResult:
        """Lock the vehicle doors.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        **kwargs
            Forwarded to :meth:`remote_control`.
        """
        return await self.remote_control(vin, RemoteCommand.LOCK, **kwargs)

    async def unlock(self, vin: str, **kwargs: Any) -> RemoteControlResult:
        """Unlock the vehicle doors.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        **kwargs
            Forwarded to :meth:`remote_control`.
        """
        return await self.remote_control(vin, RemoteCommand.UNLOCK, **kwargs)

    async def flash_lights(self, vin: str, **kwargs: Any) -> RemoteControlResult:
        """Flash the vehicle lights.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        **kwargs
            Forwarded to :meth:`remote_control`.
        """
        return await self.remote_control(vin, RemoteCommand.FLASH_LIGHTS, **kwargs)

    async def honk_horn(self, vin: str, **kwargs: Any) -> RemoteControlResult:
        """Honk the vehicle horn.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        **kwargs
            Forwarded to :meth:`remote_control`.
        """
        return await self.remote_control(vin, RemoteCommand.HORN, **kwargs)

    async def start_climate(self, vin: str, **kwargs: Any) -> RemoteControlResult:
        """Start climate control.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        **kwargs
            Forwarded to :meth:`remote_control`.
        """
        return await self.remote_control(vin, RemoteCommand.START_CLIMATE, **kwargs)

    async def stop_climate(self, vin: str, **kwargs: Any) -> RemoteControlResult:
        """Stop climate control.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        **kwargs
            Forwarded to :meth:`remote_control`.
        """
        return await self.remote_control(vin, RemoteCommand.STOP_CLIMATE, **kwargs)

    async def open_trunk(self, vin: str, **kwargs: Any) -> RemoteControlResult:
        """Open the trunk.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        **kwargs
            Forwarded to :meth:`remote_control`.
        """
        return await self.remote_control(vin, RemoteCommand.OPEN_TRUNK, **kwargs)

    async def close_windows(self, vin: str, **kwargs: Any) -> RemoteControlResult:
        """Close all windows.

        Parameters
        ----------
        vin : str
            Vehicle Identification Number.
        **kwargs
            Forwarded to :meth:`remote_control`.
        """
        return await self.remote_control(vin, RemoteCommand.CLOSE_WINDOWS, **kwargs)

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
        session = self._require_session()
        transport = self._require_transport()
        return await fetch_hvac_status(self._config, session, transport, vin)

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
        session = self._require_session()
        transport = self._require_transport()
        return await fetch_charging_status(self._config, session, transport, vin)
