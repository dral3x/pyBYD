from __future__ import annotations

import pytest

from pybyd._api.control import _fetch_control_endpoint
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError, BydRemoteControlError
from pybyd.models.control import RemoteCommand
from pybyd.session import Session


class _ErrorTransport:
    def __init__(self, code: str, message: str = "") -> None:
        self._code = code
        self._message = message

    async def post_secure(self, _endpoint: str, _payload: dict[str, object]) -> dict[str, object]:
        return {"code": self._code, "message": self._message}


def _make_session() -> Session:
    return Session(
        user_id="user-1",
        sign_token="sign-token-1",
        encry_token="encry-token-1",
        ttl=3600,
    )


@pytest.mark.asyncio
async def test_remote_control_1009_raises_remote_control_error(monkeypatch: pytest.MonkeyPatch) -> None:
    config = BydConfig(username="user@example.com", password="secret")
    session = _make_session()

    monkeypatch.setattr(
        "pybyd._api.control.build_token_outer_envelope",
        lambda *_args, **_kwargs: ({"encryData": "ignored"}, "dummy-key"),
    )

    with pytest.raises(BydRemoteControlError) as exc_info:
        await _fetch_control_endpoint(
            "/control/remoteControl",
            config,
            session,
            _ErrorTransport("1009", "Dienstfehler(1009)"),
            "VIN-E2E-123",
            RemoteCommand.LOCK,
        )

    exc = exc_info.value
    assert exc.code == "1009"
    assert exc.endpoint == "/control/remoteControl"


@pytest.mark.asyncio
async def test_non_remote_endpoint_1009_stays_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    config = BydConfig(username="user@example.com", password="secret")
    session = _make_session()

    monkeypatch.setattr(
        "pybyd._api.control.build_token_outer_envelope",
        lambda *_args, **_kwargs: ({"encryData": "ignored"}, "dummy-key"),
    )

    with pytest.raises(BydApiError) as exc_info:
        await _fetch_control_endpoint(
            "/vehicle/someOtherEndpoint",
            config,
            session,
            _ErrorTransport("1009", "Dienstfehler(1009)"),
            "VIN-E2E-123",
            RemoteCommand.LOCK,
        )

    exc = exc_info.value
    assert not isinstance(exc, BydRemoteControlError)
    assert exc.code == "1009"
    assert exc.endpoint == "/vehicle/someOtherEndpoint"
