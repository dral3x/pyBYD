from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from pybyd.client import BydClient
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError


@dataclass
class FakeSmartChargingBackend:
    vin: str = "VIN-SC-TEST"
    calls: dict[str, int] = field(default_factory=dict)
    toggle_error_code: str | None = None
    save_error_code: str | None = None

    def _record_call(self, endpoint: str) -> None:
        self.calls[endpoint] = self.calls.get(endpoint, 0) + 1

    def _code_zero(self, respond_data: Any) -> dict[str, Any]:
        return {"code": "0", "respondData": json.dumps(respond_data)}

    async def post_secure(self, endpoint: str, _outer_payload: dict[str, Any]) -> dict[str, Any]:
        self._record_call(endpoint)

        if endpoint == "/app/account/login":
            return self._code_zero(
                {
                    "token": {
                        "userId": "user-1",
                        "signToken": "sign-token-1",
                        "encryToken": "encrypt-token-1",
                    }
                }
            )

        if endpoint == "/app/emqAuth/getEmqBrokerIp":
            return self._code_zero({"emqBorker": "mqtt.example.com:8883"})

        if endpoint == "/control/smartCharge/changeChargeStatue":
            if self.toggle_error_code is not None:
                return {"code": self.toggle_error_code, "message": "error"}
            return self._code_zero({"result": "ok"})

        if endpoint == "/control/smartCharge/saveOrUpdate":
            if self.save_error_code is not None:
                return {"code": self.save_error_code, "message": "error"}
            return self._code_zero({"result": "ok"})

        raise AssertionError(f"Unexpected endpoint: {endpoint}")


@pytest.fixture
def config() -> BydConfig:
    return BydConfig(
        username="user@example.com",
        password="secret",
        mqtt_enabled=True,
        mqtt_command_timeout=0.2,
    )


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> FakeSmartChargingBackend:
    fake = FakeSmartChargingBackend()

    async def fake_post_secure(_self: Any, endpoint: str, outer_payload: dict[str, Any]) -> dict[str, Any]:
        return await fake.post_secure(endpoint, outer_payload)

    async def fake_async_load_tables(_self: Any) -> None:
        return None

    def fake_mqtt_start(self: Any, _bootstrap: Any) -> None:
        self._running = True

    def fake_mqtt_stop(self: Any) -> None:
        self._running = False

    def identity_decrypt(payload: str, _key: str) -> str:
        return payload

    monkeypatch.setattr("pybyd._transport.SecureTransport.post_secure", fake_post_secure)
    monkeypatch.setattr("pybyd._crypto.bangcle.BangcleCodec.async_load_tables", fake_async_load_tables)
    monkeypatch.setattr("pybyd._mqtt.BydMqttRuntime.start", fake_mqtt_start)
    monkeypatch.setattr("pybyd._mqtt.BydMqttRuntime.stop", fake_mqtt_stop)

    for target in [
        "pybyd._api.login",
        "pybyd._api.smart_charging",
        "pybyd._mqtt",
    ]:
        monkeypatch.setattr(f"{target}.aes_decrypt_utf8", identity_decrypt)

    return fake


@pytest.mark.asyncio
async def test_toggle_smart_charging_enable(config: BydConfig, backend: FakeSmartChargingBackend) -> None:
    async with BydClient(config) as client:
        result = await client.toggle_smart_charging(backend.vin, enable=True)
        assert result == {"result": "ok"}
    assert backend.calls.get("/control/smartCharge/changeChargeStatue", 0) == 1


@pytest.mark.asyncio
async def test_toggle_smart_charging_disable(config: BydConfig, backend: FakeSmartChargingBackend) -> None:
    async with BydClient(config) as client:
        result = await client.toggle_smart_charging(backend.vin, enable=False)
        assert result == {"result": "ok"}


@pytest.mark.asyncio
async def test_toggle_smart_charging_api_error(config: BydConfig, backend: FakeSmartChargingBackend) -> None:
    backend.toggle_error_code = "9999"
    async with BydClient(config) as client:
        with pytest.raises(BydApiError, match="changeChargeStatue"):
            await client.toggle_smart_charging(backend.vin, enable=True)


@pytest.mark.asyncio
async def test_save_charging_schedule(config: BydConfig, backend: FakeSmartChargingBackend) -> None:
    async with BydClient(config) as client:
        result = await client.save_charging_schedule(
            backend.vin,
            target_soc=80,
            start_hour=22,
            start_minute=0,
            end_hour=6,
            end_minute=0,
        )
        assert result == {"result": "ok"}
    assert backend.calls.get("/control/smartCharge/saveOrUpdate", 0) == 1


@pytest.mark.asyncio
async def test_save_charging_schedule_api_error(config: BydConfig, backend: FakeSmartChargingBackend) -> None:
    backend.save_error_code = "9999"
    async with BydClient(config) as client:
        with pytest.raises(BydApiError, match="saveOrUpdate"):
            await client.save_charging_schedule(
                backend.vin,
                target_soc=80,
                start_hour=22,
                start_minute=0,
                end_hour=6,
                end_minute=0,
            )
