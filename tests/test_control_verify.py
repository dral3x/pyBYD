from __future__ import annotations

import pytest

from pybyd._api.control import verify_control_password
from pybyd.config import BydConfig
from pybyd.session import Session


class _FakeTransport:
    async def post_secure(self, endpoint: str, _outer_payload: dict[str, object]) -> dict[str, object]:
        assert endpoint == "/vehicle/vehicleswitch/verifyControlPassword"
        return {"code": "0", "respondData": "ciphertext"}


@pytest.mark.asyncio
async def test_verify_control_password_accepts_empty_decrypted_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    config = BydConfig(username="user@example.com", password="secret", control_pin="123456")
    session = Session(
        user_id="user-1",
        sign_token="sign-token-1",
        encry_token="encry-token-1",
        ttl=3600,
    )

    monkeypatch.setattr("pybyd._api.control.aes_decrypt_utf8", lambda _value, _key: "")

    result = await verify_control_password(
        config,
        session,
        _FakeTransport(),
        "VIN-E2E-123",
        "E10ADC3949BA59ABBE56E057F20F883E",
    )

    assert result == {}
