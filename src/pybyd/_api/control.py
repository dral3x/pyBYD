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
from collections.abc import Awaitable, Callable
from typing import Any

from pybyd._api._envelope import build_token_outer_envelope
from pybyd._constants import SESSION_EXPIRED_CODES
from pybyd._crypto.aes import aes_decrypt_utf8
from pybyd._transport import Transport
from pybyd.config import BydConfig
from pybyd.exceptions import (
    BydApiError,
    BydControlPasswordError,
    BydEndpointNotSupportedError,
    BydRateLimitError,
    BydRemoteControlError,
    BydSessionExpiredError,
)
from pybyd.models.control import RemoteCommand, RemoteControlResult, VerifyControlPasswordResponse
from pybyd.session import Session

_logger = logging.getLogger(__name__)

CONTROL_PASSWORD_ERROR_CODES: frozenset[str] = frozenset({"5005", "5006"})
ENDPOINT_NOT_SUPPORTED_CODES: frozenset[str] = frozenset({"1001"})
REMOTE_CONTROL_SERVICE_ERROR_CODES: frozenset[str] = frozenset({"1009"})
REMOTE_CONTROL_ENDPOINTS: frozenset[str] = frozenset({"/control/remoteControl", "/control/remoteControlResult"})
VERIFY_CONTROL_PASSWORD_ENDPOINT = "/vehicle/vehicleswitch/verifyControlPassword"


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


def _build_verify_control_password_inner(
    config: BydConfig,
    vin: str,
    command_pwd: str,
    now_ms: int,
) -> dict[str, Any]:
    """Build inner payload for control password verification endpoint."""
    return {
        "commandPwd": command_pwd,
        "deviceType": config.device.device_type,
        "functionType": "remoteControl",
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }


async def verify_control_password(
    config: BydConfig,
    session: Session,
    transport: Transport,
    vin: str,
    command_pwd: str,
) -> VerifyControlPasswordResponse:
    """Verify remote control password for a vehicle.

    Calls ``/vehicle/vehicleswitch/verifyControlPassword`` and returns the
    decrypted inner response payload.
    """
    now_ms = int(time.time() * 1000)
    inner = _build_verify_control_password_inner(config, vin, command_pwd, now_ms)
    outer, content_key = build_token_outer_envelope(
        config,
        session,
        inner,
        now_ms,
        user_type="1",
    )

    response = await transport.post_secure(VERIFY_CONTROL_PASSWORD_ENDPOINT, outer)
    resp_code = str(response.get("code", ""))
    if resp_code != "0":
        if resp_code in SESSION_EXPIRED_CODES:
            raise BydSessionExpiredError(
                f"{VERIFY_CONTROL_PASSWORD_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=VERIFY_CONTROL_PASSWORD_ENDPOINT,
            )
        if resp_code in CONTROL_PASSWORD_ERROR_CODES:
            raise BydControlPasswordError(
                f"{VERIFY_CONTROL_PASSWORD_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=VERIFY_CONTROL_PASSWORD_ENDPOINT,
            )
        if resp_code in ENDPOINT_NOT_SUPPORTED_CODES:
            raise BydEndpointNotSupportedError(
                f"{VERIFY_CONTROL_PASSWORD_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=VERIFY_CONTROL_PASSWORD_ENDPOINT,
            )
        raise BydApiError(
            f"{VERIFY_CONTROL_PASSWORD_ENDPOINT} failed: code={resp_code} message={response.get('message', '')}",
            code=resp_code,
            endpoint=VERIFY_CONTROL_PASSWORD_ENDPOINT,
        )

    encrypted_inner = response.get("respondData")
    if not encrypted_inner:
        return VerifyControlPasswordResponse(vin=vin, ok=None, raw={})
    decrypted_inner = aes_decrypt_utf8(encrypted_inner, content_key)
    if not decrypted_inner or not decrypted_inner.strip():
        return VerifyControlPasswordResponse(vin=vin, ok=None, raw={})

    try:
        parsed = json.loads(decrypted_inner)
        if not isinstance(parsed, dict):
            raise BydControlPasswordError(
                (
                    f"{VERIFY_CONTROL_PASSWORD_ENDPOINT} failed: "
                    "unexpected decrypted payload shape (invalid control PIN or cloud control locked)"
                ),
                code="5005",
                endpoint=VERIFY_CONTROL_PASSWORD_ENDPOINT,
            )

        raw: dict[str, Any] = parsed
        ok_value = raw.get("ok")
        ok = ok_value if isinstance(ok_value, bool) else None
        return VerifyControlPasswordResponse(vin=vin, ok=ok, raw=raw)
    except json.JSONDecodeError as exc:
        raise BydControlPasswordError(
            (
                f"{VERIFY_CONTROL_PASSWORD_ENDPOINT} failed: "
                "invalid decrypted payload (invalid control PIN or cloud control locked)"
            ),
            code="5005",
            endpoint=VERIFY_CONTROL_PASSWORD_ENDPOINT,
        ) from exc


def _is_remote_control_ready(data: dict[str, Any]) -> bool:
    """Check if remote control result has a terminal state.

    Returns ``True`` when ``controlState`` is defined and not 0
    (pending), when a ``res`` field is present (immediate result),
    or when a ``result`` field is present.
    """
    if not data:
        return False
    control_state = data.get("controlState")
    if control_state is not None and int(control_state) != 0:
        return True
    if "res" in data:
        return True
    return "result" in data


def _parse_control_result(data: dict[str, Any]) -> RemoteControlResult:
    """Parse raw remote control dict into a typed model."""

    return RemoteControlResult.model_validate(data)


def parse_remote_control_result_data(data: dict[str, Any]) -> RemoteControlResult:
    """Parse raw remote-control result payload into a typed model."""
    return _parse_control_result(data)


async def _fetch_control_endpoint(
    endpoint: str,
    config: BydConfig,
    session: Session,
    transport: Transport,
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
        config,
        vin,
        command,
        now_ms,
        control_params=control_params,
        command_pwd=command_pwd,
        request_serial=request_serial,
    )
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(endpoint, outer)

    resp_code = str(response.get("code", ""))
    if resp_code != "0":
        if resp_code in SESSION_EXPIRED_CODES:
            raise BydSessionExpiredError(
                f"{endpoint} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=endpoint,
            )
        if resp_code in CONTROL_PASSWORD_ERROR_CODES:
            raise BydControlPasswordError(
                f"{endpoint} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=endpoint,
            )
        if resp_code in ENDPOINT_NOT_SUPPORTED_CODES:
            raise BydEndpointNotSupportedError(
                f"{endpoint} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=endpoint,
            )
        if endpoint in REMOTE_CONTROL_ENDPOINTS and resp_code in REMOTE_CONTROL_SERVICE_ERROR_CODES:
            raise BydRemoteControlError(
                f"{endpoint} failed: code={resp_code} message={response.get('message', '')}",
                code=resp_code,
                endpoint=endpoint,
            )
        raise BydApiError(
            f"{endpoint} failed: code={resp_code} message={response.get('message', '')}",
            code=resp_code,
            endpoint=endpoint,
        )

    result = json.loads(aes_decrypt_utf8(response["respondData"], content_key))
    next_serial = (result.get("requestSerial") if isinstance(result, dict) else None) or request_serial

    return result, next_serial


async def poll_remote_control(
    config: BydConfig,
    session: Session,
    transport: Transport,
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
    mqtt_result_waiter: Callable[[str | None], Awaitable[RemoteControlResult | None]] | None = None,
) -> RemoteControlResult:
    """Send a remote control command and poll until completion.

    Parameters
    ----------
    config : BydConfig
        Client configuration.
    session : Session
        Authenticated session.
    transport : Transport
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
                mqtt_result_waiter=mqtt_result_waiter,
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
    transport: Transport,
    vin: str,
    command: RemoteCommand,
    *,
    control_params: dict[str, Any] | None = None,
    command_pwd: str | None = None,
    poll_attempts: int = 10,
    poll_interval: float = 1.5,
    rate_limit_retries: int = 3,
    rate_limit_delay: float = 5.0,
    mqtt_result_waiter: Callable[[str | None], Awaitable[RemoteControlResult | None]] | None = None,
) -> RemoteControlResult:
    """Single attempt: trigger + poll.  Raises on failure."""
    # Phase 1: Trigger request (with control params) — retry on 6024
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
            )
            break
        except BydApiError as exc:
            if exc.code == "6024":
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
            f"Remote control {command.name} rate-limited after {rate_limit_retries} retries (code 6024)",
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
        _logger.debug("Remote control %s request returned without serial; using immediate result", command.name)
        return _parse_control_result(result if isinstance(result, dict) else {})

    if mqtt_result_waiter is not None:
        try:
            mqtt_result = await mqtt_result_waiter(serial)
            if mqtt_result is not None:
                _logger.debug(
                    "Remote control %s resolved via MQTT success=%s state=%s",
                    command.name,
                    mqtt_result.success,
                    mqtt_result.control_state,
                )
                return mqtt_result
            _logger.debug("Remote control %s mqtt_wait returned no result; falling back to polling", command.name)
        except Exception:
            _logger.debug("Remote control %s mqtt_wait failed; falling back to polling", command.name, exc_info=True)

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
        except BydSessionExpiredError:
            raise
        except BydApiError:
            _logger.debug(
                "Remote control %s poll attempt=%d failed",
                command.name,
                attempt,
                exc_info=True,
            )

    parsed = _parse_control_result(latest if isinstance(latest, dict) else {})
    _logger.debug(
        "Remote control %s final parsed result success=%s state=%s",
        command.name,
        parsed.success,
        parsed.control_state,
    )
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
