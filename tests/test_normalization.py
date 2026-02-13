from __future__ import annotations

from datetime import UTC, datetime

from pybyd._api.realtime import _parse_vehicle_info
from pybyd._constants import SESSION_EXPIRED_CODES
from pybyd.config import BydConfig
from pybyd.models.charging import ChargingStatus
from pybyd.models.realtime import VehicleState


def test_session_expired_codes_include_1002() -> None:
    assert "1002" in SESSION_EXPIRED_CODES


def test_realtime_negative_charge_times_normalized_to_zero() -> None:
    realtime = _parse_vehicle_info(
        {
            "vin": "VIN123",
            "fullHour": -1,
            "fullMinute": -1,
            "remainingHours": -1,
            "remainingMinutes": -1,
        }
    )

    assert realtime.full_hour == 0
    assert realtime.full_minute == 0
    assert realtime.charge_remaining_hours == 0
    assert realtime.charge_remaining_minutes == 0


def test_realtime_vehicle_state_mapping_on_and_off() -> None:
    on_realtime = _parse_vehicle_info({"vehicleState": 0})
    off_realtime = _parse_vehicle_info({"vehicleState": 2})

    assert on_realtime.vehicle_state == VehicleState.ON
    assert off_realtime.vehicle_state == VehicleState.OFF


def test_charging_status_update_datetime_seconds() -> None:
    status = ChargingStatus(
        vin="VIN123",
        soc=None,
        charging_state=None,
        connect_state=None,
        wait_status=None,
        full_hour=None,
        full_minute=None,
        update_time=1_770_928_447,
        raw={},
    )

    assert status.update_datetime_utc == datetime.fromtimestamp(1_770_928_447, tz=UTC)


def test_charging_status_update_datetime_milliseconds() -> None:
    status = ChargingStatus(
        vin="VIN123",
        soc=None,
        charging_state=None,
        connect_state=None,
        wait_status=None,
        full_hour=None,
        full_minute=None,
        update_time=1_770_928_447_000,
        raw={},
    )

    assert status.update_datetime_utc == datetime.fromtimestamp(1_770_928_447, tz=UTC)


def test_config_api_trace_enabled_from_env(monkeypatch) -> None:
    monkeypatch.setenv("BYD_USERNAME", "user@example.com")
    monkeypatch.setenv("BYD_PASSWORD", "secret")
    monkeypatch.setenv("BYD_API_TRACE_ENABLED", "true")

    config = BydConfig.from_env()

    assert config.api_trace_enabled is True
