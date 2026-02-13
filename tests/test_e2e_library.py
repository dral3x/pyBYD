from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from pybyd._mqtt import MqttEvent
from pybyd.client import BydClient
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError, BydAuthenticationError


@dataclass
class FakeBydBackend:
    vin: str = "VIN-E2E-123"
    calls: dict[str, int] = field(default_factory=dict)
    login_should_fail: bool = False
    energy_error_code: str | None = None
    expire_once_endpoints: set[str] = field(default_factory=set)
    _expired_already: set[str] = field(default_factory=set)
    emit_mqtt_remote_result: bool = True
    mqtt_event_handler: Callable[[MqttEvent], None] | None = None

    def _record_call(self, endpoint: str) -> None:
        self.calls[endpoint] = self.calls.get(endpoint, 0) + 1

    def _code_zero(self, respond_data: Any) -> dict[str, Any]:
        return {"code": "0", "respondData": json.dumps(respond_data)}

    def _maybe_emit_remote_control_event(self) -> None:
        if not self.emit_mqtt_remote_result or self.mqtt_event_handler is None:
            return
        event = MqttEvent(
            event="remoteControl",
            vin=self.vin,
            topic="oversea/res/user-1",
            payload={"data": {"respondData": {"res": 2, "message": "ok", "requestSerial": "CMD-1"}}},
        )
        asyncio.get_running_loop().call_later(0.01, self.mqtt_event_handler, event)

    async def post_secure(self, endpoint: str, _outer_payload: dict[str, Any]) -> dict[str, Any]:
        self._record_call(endpoint)

        if endpoint in self.expire_once_endpoints and endpoint not in self._expired_already:
            self._expired_already.add(endpoint)
            return {"code": "1005", "message": "session expired"}

        if endpoint == "/app/account/login":
            if self.login_should_fail:
                return {"code": "5000", "message": "invalid credentials"}
            return self._code_zero(
                {
                    "token": {
                        "userId": "user-1",
                        "signToken": "sign-token-1",
                        "encryToken": "encrypt-token-1",
                    }
                }
            )

        if endpoint == "/app/account/getAllListByUserId":
            return self._code_zero(
                [
                    {
                        "vin": self.vin,
                        "modelName": "SEAL U",
                        "brandName": "BYD",
                        "energyType": "EV",
                        "autoAlias": "My BYD",
                        "rangeDetailList": [{"code": "2", "name": "Control", "childList": []}],
                    }
                ]
            )

        if endpoint == "/vehicleInfo/vehicle/vehicleRealTimeRequest":
            return self._code_zero({"requestSerial": "RT-1", "onlineState": 2})

        if endpoint == "/vehicleInfo/vehicle/vehicleRealTimeResult":
            return self._code_zero(
                {
                    "requestSerial": "RT-1",
                    "onlineState": 1,
                    "time": 1771000000,
                    "elecPercent": 84,
                    "speed": 0,
                    "leftFrontDoorLock": 2,
                    "rightFrontDoorLock": 2,
                }
            )

        if endpoint == "/control/getGpsInfo":
            return self._code_zero({"requestSerial": "GPS-1"})

        if endpoint == "/control/getGpsInfoResult":
            return self._code_zero(
                {
                    "requestSerial": "GPS-1",
                    "latitude": 52.3676,
                    "longitude": 4.9041,
                    "gpsTimeStamp": 1771000001,
                }
            )

        if endpoint == "/vehicleInfo/vehicle/getEnergyConsumption":
            if self.energy_error_code is not None:
                return {"code": self.energy_error_code, "message": "energy error"}
            return self._code_zero(
                {
                    "vin": self.vin,
                    "totalEnergy": "13.5",
                    "avgEnergyConsumption": "14.2",
                    "electricityConsumption": "11.8",
                    "fuelConsumption": "0",
                }
            )

        if endpoint == "/control/getStatusNow":
            return self._code_zero(
                {
                    "statusNow": {
                        "acSwitch": 1,
                        "status": 2,
                        "cycleChoice": 2,
                        "mainSettingTemp": 7,
                        "mainSettingTempNew": 21.0,
                    }
                }
            )

        if endpoint == "/control/smartCharge/homePage":
            return self._code_zero(
                {
                    "vin": self.vin,
                    "soc": 84,
                    "chargingState": 15,
                    "connectState": 1,
                    "waitStatus": 0,
                    "fullHour": 1,
                    "fullMinute": 20,
                    "updateTime": 1771000002,
                }
            )

        if endpoint == "/vehicle/vehicleswitch/verifyControlPassword":
            return self._code_zero({"ok": True})

        if endpoint == "/app/emqAuth/getEmqBrokerIp":
            return self._code_zero({"emqBorker": "mqtt.example.com:8883"})

        if endpoint == "/control/remoteControl":
            self._maybe_emit_remote_control_event()
            return self._code_zero({"controlState": 0, "requestSerial": "CMD-1"})

        if endpoint == "/control/remoteControlResult":
            return self._code_zero({"controlState": 1, "requestSerial": "CMD-1"})

        raise AssertionError(f"Unexpected endpoint in fake backend: {endpoint}")


@pytest.fixture
def config() -> BydConfig:
    return BydConfig(
        username="user@example.com",
        password="secret",
        control_pin="123456",
        mqtt_enabled=True,
        mqtt_command_timeout=0.2,
    )


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> FakeBydBackend:
    fake_backend = FakeBydBackend()

    async def fake_post_secure(_self: Any, endpoint: str, outer_payload: dict[str, Any]) -> dict[str, Any]:
        return await fake_backend.post_secure(endpoint, outer_payload)

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

    decrypt_targets = [
        "pybyd._api.login",
        "pybyd._api.vehicles",
        "pybyd._api.realtime",
        "pybyd._api.gps",
        "pybyd._api.energy",
        "pybyd._api.hvac",
        "pybyd._api.charging",
        "pybyd._api.control",
        "pybyd._mqtt",
    ]
    for target in decrypt_targets:
        monkeypatch.setattr(f"{target}.aes_decrypt_utf8", identity_decrypt)

    return fake_backend


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_client_happy_path_exercises_full_library(config: BydConfig, backend: FakeBydBackend) -> None:
    backend.expire_once_endpoints.add("/app/account/getAllListByUserId")

    async with BydClient(config) as client:
        backend.mqtt_event_handler = client._on_mqtt_event

        vehicles = await client.get_vehicles()
        assert len(vehicles) == 1
        vin = vehicles[0].vin
        assert vin == backend.vin

        realtime = await client.get_vehicle_realtime(vin, poll_attempts=1, poll_interval=0)
        assert realtime.elec_percent == 84

        gps = await client.get_gps_info(vin, poll_attempts=1, poll_interval=0)
        assert gps.latitude == pytest.approx(52.3676)

        energy = await client.get_energy_consumption(vin)
        assert energy.avg_energy_consumption == pytest.approx(14.2)

        hvac = await client.get_hvac_status(vin)
        assert hvac is not None
        assert hvac.main_setting_temp == 7

        charging = await client.get_charging_status(vin)
        assert charging is not None
        assert charging.soc == 84

        assert await client.verify_control_password(vin) is True

        lock_result = await client.lock(vin, poll_attempts=1, poll_interval=0)
        assert lock_result.success is True

        assert client._mqtt_runtime is not None
        assert client._mqtt_runtime.is_running is True

    assert backend.calls.get("/app/account/login", 0) == 2
    assert backend.calls.get("/app/emqAuth/getEmqBrokerIp", 0) >= 2
    assert backend.calls.get("/control/remoteControlResult", 0) == 0


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_login_error_raises_authentication(config: BydConfig, backend: FakeBydBackend) -> None:
    backend.login_should_fail = True

    async with BydClient(config) as client:
        with pytest.raises(BydAuthenticationError):
            await client.login()


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_api_error_raises_byd_api_error(config: BydConfig, backend: FakeBydBackend) -> None:
    backend.energy_error_code = "9999"

    async with BydClient(config) as client:
        vehicles = await client.get_vehicles()
        vin = vehicles[0].vin
        with pytest.raises(BydApiError, match="getEnergyConsumption"):
            await client.get_energy_consumption(vin)


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_e2e_remote_control_falls_back_to_poll_when_mqtt_times_out(
    config: BydConfig,
    backend: FakeBydBackend,
) -> None:
    backend.emit_mqtt_remote_result = False
    fallback_config = BydConfig(
        username=config.username,
        password=config.password,
        control_pin=config.control_pin,
        mqtt_enabled=True,
        mqtt_command_timeout=0.01,
    )

    async with BydClient(fallback_config) as client:
        vehicles = await client.get_vehicles()
        vin = vehicles[0].vin
        result = await client.lock(vin, poll_attempts=1, poll_interval=0)
        assert result.success is True

    assert backend.calls.get("/control/remoteControlResult", 0) == 1
