"""Remote control endpoints.

Endpoints:
  - /control/remoteControl (trigger)
  - /control/remoteControlResult (poll)

The inner payload requires ``commandPwd`` (MD5 of the 6-digit control
PIN set in the BYD app) and must **not** include ``instructionCode``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any, Callable

from pybyd._api._envelope import build_token_outer_envelope
from pybyd._crypto.aes import aes_decrypt_utf8
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError, BydRateLimitError, BydRemoteControlError
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
        "commandPwd": command_pwd or "",
        "commandType": command.value,
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }
    if control_params is not None:
        inner["controlParamsMap"] = json.dumps(
            control_params,
            separators=(",", ":"),
            sort_keys=True,
        )
    if request_serial:
        inner["requestSerial"] = request_serial
    return inner


def _is_remote_control_ready(data: dict[str, Any]) -> bool:
    """Check if remote control result has a terminal state.

    Returns ``True`` when ``controlState`` is defined and not 0
    (pending), when a ``res`` field is present (immediate result),
    or when a ``result`` field is present.
    """
    if not data:
        return False
    control_state = _safe_int(data.get("controlState"))
    if control_state is not None and control_state != 0:
        return True
    if "res" in data:
        return True
    return "result" in data


def _parse_control_result(data: dict[str, Any]) -> RemoteControlResult:
    """Parse raw remote control dict into a typed dataclass.

    The API may return results in two formats:
    - Polled result: ``{"controlState": 1, "requestSerial": "..."}``
    - Immediate result: ``{"res": 2, "message": "Closing windows successful"}``

    For immediate results, ``res == 2`` maps to SUCCESS.
    """
    # Check for immediate result format (res field)
    res_val = _safe_int(data.get("res"))
    if res_val is not None:
        # res=2 is observed as success in immediate responses
        control_state = ControlState.SUCCESS if res_val == 2 else ControlState.FAILURE
        return RemoteControlResult(
            control_state=control_state,
            success=control_state == ControlState.SUCCESS,
            request_serial=data.get("requestSerial"),
            raw=data,
        )

    # Standard polled result format (controlState field)
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
    debug_recorder: Callable[[dict[str, Any]], None] | None = None,
    phase: str = "request",
) -> tuple[dict[str, Any], str | None]:
    """Fetch a single control endpoint, returning (result_dict, next_serial)."""
    now_ms = int(time.time() * 1000)
    inner = _build_control_inner(
        config,
        vin,
        command,
        now_ms,
        control_params=control_params,
        command_pwd=command_pwd,
        request_serial=request_serial,
    )
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)
    debug_entry: dict[str, Any] = {
        "command": command.name,
        "vin": vin,
        "endpoint": endpoint,
        "phase": phase,
        "request_serial": request_serial,
        "request": {
            "inner": inner,
            "outer": outer,
            "encrypted_inner": outer.get("encryData"),
        },
    }

    try:
        response = await transport.post_secure(endpoint, outer)
    except Exception as exc:
        if debug_recorder is not None:
            debug_entry["error"] = {
                "stage": "transport",
                "message": str(exc),
            }
            debug_recorder(debug_entry)
        raise

    debug_entry["response"] = {
        "outer": response,
        "encrypted_inner": response.get("respondData"),
    }

    if str(response.get("code")) != "0":
        debug_entry["error"] = {
            "stage": "api",
            "code": response.get("code"),
            "message": response.get("message", ""),
        }
        if debug_recorder is not None:
            debug_recorder(debug_entry)
        raise BydApiError(
            f"{endpoint} failed: code={response.get('code')} message={response.get('message', '')}",
            code=str(response.get("code", "")),
            endpoint=endpoint,
        )

    try:
        result = json.loads(aes_decrypt_utf8(response["respondData"], content_key))
    except Exception as exc:
        debug_entry["error"] = {
            "stage": "decrypt",
            "message": str(exc),
        }
        if debug_recorder is not None:
            debug_recorder(debug_entry)
        raise

    debug_entry["response"]["decrypted_inner"] = result
    if debug_recorder is not None:
        debug_recorder(debug_entry)
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
    rate_limit_retries: int = 3,
    rate_limit_delay: float = 5.0,
    command_retries: int = 3,
    command_retry_delay: float = 3.0,
    debug_recorder: Callable[[dict[str, Any]], None] | None = None,
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
    rate_limit_retries : int
        How many times to retry the initial trigger when the server
        returns code 6024 ("previous command still in progress").
    rate_limit_delay : float
        Seconds to wait between rate-limit retries.
    command_retries : int
        How many times to retry the entire command when it fails
        (controlState=2).  Set to 1 for no retries.
    command_retry_delay : float
        Seconds to wait between command retries.

    Returns
    -------
    RemoteControlResult
        The command result.

    Raises
    ------
    BydRemoteControlError
        If the command fails (controlState=2) after all retries.
    BydRateLimitError
        If the server keeps returning code 6024 after all retries.
    BydApiError
        If the API returns an error.
    """
    last_exc: BydRemoteControlError | None = None

    for cmd_attempt in range(1, command_retries + 1):
        try:
            return await _poll_remote_control_once(
                config,
                session,
                transport,
                vin,
                command,
                control_params=control_params,
                command_pwd=command_pwd,
                poll_attempts=poll_attempts,
                poll_interval=poll_interval,
                rate_limit_retries=rate_limit_retries,
                rate_limit_delay=rate_limit_delay,
                debug_recorder=debug_recorder,
            )
        except BydRemoteControlError as exc:
            last_exc = exc
            if cmd_attempt < command_retries:
                _logger.info(
                    "Remote control %s failed (attempt %d/%d), retrying in %.1fs",
                    command.name,
                    cmd_attempt,
                    command_retries,
                    command_retry_delay,
                )
                await asyncio.sleep(command_retry_delay)

    # All retries exhausted – re-raise the last failure
    assert last_exc is not None  # noqa: S101
    raise last_exc


async def _poll_remote_control_once(
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
    rate_limit_retries: int = 3,
    rate_limit_delay: float = 5.0,
    debug_recorder: Callable[[dict[str, Any]], None] | None = None,
) -> RemoteControlResult:
    """Single attempt: trigger + poll.  Raises on failure."""
    # Phase 1: Trigger request (with control params) — retry on 6024
    last_rate_limit_exc: BydApiError | None = None
    for rate_attempt in range(1, rate_limit_retries + 1):
        try:
            result, serial = await _fetch_control_endpoint(
                "/control/remoteControl",
                config,
                session,
                transport,
                vin,
                command,
                control_params=control_params,
                command_pwd=command_pwd,
                debug_recorder=debug_recorder,
                phase="trigger",
            )
            last_rate_limit_exc = None
            break
        except BydApiError as exc:
            if exc.code == "6024":
                last_rate_limit_exc = exc
                _logger.info(
                    "Remote control %s rate-limited (6024), retry %d/%d in %.1fs",
                    command.name,
                    rate_attempt,
                    rate_limit_retries,
                    rate_limit_delay,
                )
                await asyncio.sleep(rate_limit_delay)
            else:
                raise
    else:
        # All rate-limit retries exhausted
        raise BydRateLimitError(
            f"Remote control {command.name} rate-limited after "
            f"{rate_limit_retries} retries (code 6024)",
            code="6024",
            endpoint="/control/remoteControl",
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
            msg = result.get("message") or result.get("msg") or "controlState=2"
            raise BydRemoteControlError(
                f"Remote control {command.name} failed: {msg}",
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
                debug_recorder=debug_recorder,
                phase="poll",
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
        msg = (
            (latest.get("message") or latest.get("msg") or "controlState=2")
            if isinstance(latest, dict)
            else "controlState=2"
        )
        raise BydRemoteControlError(
            f"Remote control {command.name} failed: {msg}",
            code="2",
            endpoint="/control/remoteControlResult",
        )
    return parsed
