"""Remote control endpoints.

.. warning::
    Remote control is **unverified / non-functional** as of 2025-07.
    The ``/control/remoteControl`` endpoint returns error code 1007
    ("Service error") for every tested command and account.  The
    payload structure here matches TA2k's ioBroker.byd adapter, but
    the server rejects all requests.  This module is retained so the
    wire format is ready once the root cause is identified.

Endpoints:
  - /control/remoteControl (trigger)
  - /control/remoteControlResult (poll)
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any

from pybyd._api._envelope import build_token_outer_envelope
from pybyd._crypto.aes import aes_decrypt_utf8
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError, BydRemoteControlError
from pybyd.models.control import ControlState, RemoteCommand, RemoteControlResult
from pybyd.session import Session

_logger = logging.getLogger(__name__)


def _safe_int(value: Any) -> int | None:
    """Convert a value to int, returning None on failure."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
        if result != result:  # NaN check
            return None
        return int(result)
    except (ValueError, TypeError):
        return None


def _build_control_inner(
    config: BydConfig,
    vin: str,
    command: RemoteCommand,
    now_ms: int,
    *,
    control_params: dict[str, Any] | None = None,
    command_pwd: str | None = None,
    request_serial: str | None = None,
) -> dict[str, Any]:
    """Build the inner payload for remote control endpoints.

    Parameters
    ----------
    control_params
        Optional command parameters. Serialised to a JSON string as
        ``controlParamsMap`` in the payload.
    command_pwd
        Optional control password (PIN) sent as ``commandPwd``.
    """
    inner: dict[str, Any] = {
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "instructionCode": None,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }
    # commandType is added alongside instructionCode (which stays null)
    inner["commandType"] = command.value
    if control_params is not None:
        inner["controlParamsMap"] = json.dumps(
            control_params, separators=(",", ":"),
        )
    if command_pwd is not None:
        inner["commandPwd"] = command_pwd
    if request_serial:
        inner["requestSerial"] = request_serial
    return inner


def _is_remote_control_ready(data: dict[str, Any]) -> bool:
    """Check if remote control result has a terminal state.

    Returns ``True`` when ``controlState`` is defined and not 0
    (pending), or when a ``result`` field is present.
    """
    if not data:
        return False
    control_state = _safe_int(data.get("controlState"))
    if control_state is not None and control_state != 0:
        return True
    return "result" in data


def _parse_control_result(data: dict[str, Any]) -> RemoteControlResult:
    """Parse raw remote control dict into a typed dataclass."""
    raw_state = _safe_int(data.get("controlState")) or 0
    try:
        control_state = ControlState(raw_state)
    except ValueError:
        control_state = ControlState.PENDING
    return RemoteControlResult(
        control_state=control_state,
        success=control_state == ControlState.SUCCESS,
        request_serial=data.get("requestSerial"),
        raw=data,
    )


async def _fetch_control_endpoint(
    endpoint: str,
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    command: RemoteCommand,
    *,
    control_params: dict[str, Any] | None = None,
    command_pwd: str | None = None,
    request_serial: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Fetch a single control endpoint, returning (result_dict, next_serial)."""
    now_ms = int(time.time() * 1000)
    inner = _build_control_inner(
        config, vin, command, now_ms,
        control_params=control_params,
        command_pwd=command_pwd,
        request_serial=request_serial,
    )
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(endpoint, outer)
    if str(response.get("code")) != "0":
        raise BydApiError(
            f"{endpoint} failed: code={response.get('code')} message={response.get('message', '')}",
            code=str(response.get("code", "")),
            endpoint=endpoint,
        )

    result = json.loads(aes_decrypt_utf8(response["respondData"], content_key))
    next_serial = (result.get("requestSerial") if isinstance(result, dict) else None) or request_serial

    return result, next_serial


async def poll_remote_control(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    command: RemoteCommand,
    *,
    control_params: dict[str, Any] | None = None,
    command_pwd: str | None = None,
    poll_attempts: int = 10,
    poll_interval: float = 1.5,
) -> RemoteControlResult:
    """Send a remote control command and poll until completion.

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
    command : RemoteCommand
        The remote command to send.
    control_params : dict or None
        Command-specific parameters (serialised as ``controlParamsMap``).
    command_pwd : str or None
        Optional control password (PIN).
    poll_attempts : int
        Maximum number of result poll attempts.
    poll_interval : float
        Seconds between poll attempts.

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
    """
    # Phase 1: Trigger request (with control params)
    result, serial = await _fetch_control_endpoint(
        "/control/remoteControl",
        config,
        session,
        transport,
        vin,
        command,
        control_params=control_params,
        command_pwd=command_pwd,
    )
    _logger.debug(
        "Remote control %s: controlState=%s serial=%s",
        command.name,
        result.get("controlState") if isinstance(result, dict) else None,
        serial,
    )

    if isinstance(result, dict) and _is_remote_control_ready(result):
        parsed = _parse_control_result(result)
        if parsed.control_state == 2:
            raise BydRemoteControlError(
                f"Remote control {command.name} failed (controlState=2)",
                code="2",
                endpoint="/control/remoteControl",
            )
        return parsed

    if not serial:
        return _parse_control_result(result if isinstance(result, dict) else {})

    # Phase 2: Poll for results
    latest = result
    for attempt in range(1, poll_attempts + 1):
        if poll_interval > 0:
            await asyncio.sleep(poll_interval)

        try:
            latest, serial = await _fetch_control_endpoint(
                "/control/remoteControlResult",
                config,
                session,
                transport,
                vin,
                command,
                request_serial=serial,
            )
            _logger.debug(
                "Remote control %s poll attempt=%d controlState=%s serial=%s",
                command.name,
                attempt,
                latest.get("controlState") if isinstance(latest, dict) else None,
                serial,
            )
            if isinstance(latest, dict) and _is_remote_control_ready(latest):
                break
        except BydApiError:
            _logger.debug(
                "Remote control %s poll attempt=%d failed",
                command.name,
                attempt,
                exc_info=True,
            )

    parsed = _parse_control_result(latest if isinstance(latest, dict) else {})
    if parsed.control_state == 2:
        raise BydRemoteControlError(
            f"Remote control {command.name} failed (controlState=2)",
            code="2",
            endpoint="/control/remoteControlResult",
        )
    return parsed
