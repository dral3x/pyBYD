from __future__ import annotations

import json

import pytest

from pybyd._api.control import _build_control_inner
from pybyd.config import BydConfig
from pybyd.models.control import RemoteCommand
from pybyd.models.control_params import ClimateScheduleParams, ClimateStartParams, SeatClimateParams


def test_climate_start_params_celsius_conversion() -> None:
    params = ClimateStartParams(temperature_c=21.0, time_span=10)
    payload = params.to_control_params_map()
    assert payload["mainSettingTemp"] == 7
    assert payload["timeSpan"] == 1


def test_climate_start_params_rejects_double_temp_inputs() -> None:
    with pytest.raises(ValueError):
        ClimateStartParams(temperature=7, temperature_c=21.0)


def test_climate_schedule_params_includes_booking_fields() -> None:
    params = ClimateScheduleParams(booking_id=123, booking_time=1700000000, temperature=7, time_span=5)
    payload = params.to_control_params_map()
    assert payload["bookingId"] == 123
    assert payload["bookingTime"] == 1700000000
    assert payload["mainSettingTemp"] == 7
    assert payload["timeSpan"] == 5


def test_seat_climate_params_key_encoding() -> None:
    params = SeatClimateParams(main_heat=1, copilot_ventilation=3, steering_wheel_heat=1)
    payload = params.to_control_params_map()
    assert payload["mainHeat"] == 1
    assert payload["copilotVentilation"] == 3
    assert payload["steeringWheelHeat"] == 1


def test_build_control_inner_serializes_control_params_map_as_json_string() -> None:
    config = BydConfig(username="user@example.com", password="secret", country_code="NL")
    inner = _build_control_inner(
        config,
        vin="TESTVIN",
        command=RemoteCommand.START_CLIMATE,
        now_ms=1700000000000,
        control_params={"mainSettingTemp": 7, "timeSpan": 1},
        command_pwd="ABCDEF",
    )
    assert inner["commandType"] == RemoteCommand.START_CLIMATE.value
    assert inner["commandPwd"] == "ABCDEF"
    assert isinstance(inner["controlParamsMap"], str)
    assert json.loads(inner["controlParamsMap"]) == {"mainSettingTemp": 7, "timeSpan": 1}
