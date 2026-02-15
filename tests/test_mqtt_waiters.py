from __future__ import annotations

import asyncio

import pytest

from pybyd._mqtt import MqttEvent
from pybyd.client import BydClient
from pybyd.config import BydConfig


class _DummyRuntime:
    @property
    def is_running(self) -> bool:  # pragma: no cover
        return True


@pytest.mark.asyncio
async def test_remote_control_waiter_matches_uuid_serial() -> None:
    config = BydConfig(username="user@example.com", password="secret", country_code="NL")
    client = BydClient(config)

    vin = "LC0CF4CD7N1000375"
    serial = "C97B51D8E15D46E589675474BA8A207A"

    # Bypass full startup; _mqtt_wait only requires a running runtime + loop.
    client._loop = asyncio.get_running_loop()  # type: ignore[attr-defined]
    client._mqtt_runtime = _DummyRuntime()  # type: ignore[attr-defined]

    waiter_task = asyncio.create_task(
        client._mqtt_wait(vin, event_type="remoteControl", serial=serial, timeout=1.0)  # type: ignore[attr-defined]
    )
    await asyncio.sleep(0)

    event = MqttEvent(
        event="remoteControl",
        vin=vin,
        topic="oversea/res/347678",
        payload={
            "event": "remoteControl",
            "vin": vin,
            "data": {
                "uuid": serial,
                "identifier": "347678",
                "respondData": {"res": 2, "message": "Unlocking successful."},
            },
        },
    )

    client._on_mqtt_event(event)  # type: ignore[attr-defined]

    raw = await waiter_task
    assert raw is not None
    assert raw["res"] == 2
    # ensure correlation id is normalised
    assert raw["requestSerial"] == serial


@pytest.mark.asyncio
async def test_remote_control_opportunistic_match_without_serial_resolves_oldest_only() -> None:
    config = BydConfig(username="user@example.com", password="secret", country_code="NL")
    client = BydClient(config)

    vin = "LC0CF4CD7N1000375"
    serial_1 = "SERIAL-ONE"
    serial_2 = "SERIAL-TWO"

    client._loop = asyncio.get_running_loop()  # type: ignore[attr-defined]
    client._mqtt_runtime = _DummyRuntime()  # type: ignore[attr-defined]

    task1 = asyncio.create_task(
        client._mqtt_wait(vin, event_type="remoteControl", serial=serial_1, timeout=1.0)  # type: ignore[attr-defined]
    )
    task2 = asyncio.create_task(
        client._mqtt_wait(vin, event_type="remoteControl", serial=serial_2, timeout=0.2)  # type: ignore[attr-defined]
    )
    await asyncio.sleep(0)

    # Payload shape observed in the wild: respondData has result, but no requestSerial/uuid.
    event = MqttEvent(
        event="remoteControl",
        vin=vin,
        topic="oversea/res/347678",
        payload={
            "event": "remoteControl",
            "vin": vin,
            "data": {"respondData": {"res": 2, "message": "OK"}},
        },
    )

    client._on_mqtt_event(event)  # type: ignore[attr-defined]

    raw1 = await task1
    assert raw1 is not None
    assert raw1["res"] == 2

    # Only one waiter should be opportunistically satisfied.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(task2, timeout=0.05)
    task2.cancel()
