"""Tests for Pydantic model parsing with BydBaseModel + BydEnum."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pybyd.models.charging import ChargingStatus
from pybyd.models.energy import EnergyConsumption
from pybyd.models.gps import GpsInfo
from pybyd.models.hvac import HvacStatus
from pybyd.models.push_notification import PushNotificationState
from pybyd.models.realtime import (
    AirCirculationMode,
    ChargingState,
    ConnectState,
    DoorOpenState,
    LockState,
    OnlineState,
    PowerGear,
    SeatHeatVentState,
    TirePressureUnit,
    VehicleRealtimeData,
    VehicleState,
    WindowState,
)
from pybyd.models.vehicle import Vehicle

# ------------------------------------------------------------------
# BydEnum
# ------------------------------------------------------------------


class TestBydEnum:
    def test_unknown_value_falls_back(self) -> None:
        assert PowerGear(99) == PowerGear.UNKNOWN

    def test_known_value(self) -> None:
        assert PowerGear(3) == PowerGear.DRIVE

    def test_all_enums_have_unknown(self) -> None:
        for cls in (
            OnlineState,
            ConnectState,
            VehicleState,
            ChargingState,
            TirePressureUnit,
            DoorOpenState,
            LockState,
            WindowState,
            PowerGear,
            SeatHeatVentState,
            AirCirculationMode,
        ):
            assert hasattr(cls, "UNKNOWN"), f"{cls.__name__} missing UNKNOWN"
            assert cls.UNKNOWN == -1, f"{cls.__name__}.UNKNOWN != -1"


# ------------------------------------------------------------------
# VehicleRealtimeData
# ------------------------------------------------------------------


class TestVehicleRealtimeData:
    SAMPLE_PAYLOAD: dict = {
        "onlineState": 1,
        "connectState": -1,
        "vehicleState": 0,
        "requestSerial": "abc123",
        "elecPercent": "85.5",
        "powerBattery": "85.0",
        "enduranceMileage": "320.5",
        "totalMileage": "12345.6",
        "speed": "22.0",
        "powerGear": 3,
        "tempInCar": "21.5",
        "mainSettingTemp": "7",
        "mainSettingTempNew": "21.0",
        "airRunState": 1,
        "mainSeatHeatState": 3,
        "chargingState": -1,
        "chargeState": 15,
        "waitStatus": "0",
        "fullHour": -1,
        "fullMinute": -1,
        "remainingHours": "2",
        "remainingMinutes": "30",
        "bookingChargeState": "0",
        "leftFrontDoor": 0,
        "rightFrontDoor": 0,
        "trunkLid": 0,
        "leftFrontDoorLock": 2,
        "rightFrontDoorLock": 2,
        "leftRearDoorLock": 2,
        "rightRearDoorLock": 2,
        "leftFrontWindow": 1,
        "rightFrontWindow": 1,
        "leftRearWindow": 1,
        "rightRearWindow": 1,
        "leftFrontTirepressure": "2.4",
        "rightFrontTirepressure": "2.4",
        "leftRearTirepressure": "2.5",
        "rightRearTirepressure": "2.5",
        "tirePressUnit": 1,
        "abs": "0",
        "time": 1700000000,
    }

    def test_basic_parsing(self) -> None:
        data = VehicleRealtimeData.model_validate(self.SAMPLE_PAYLOAD)
        assert data.online_state == OnlineState.ONLINE
        assert data.connect_state == ConnectState.UNKNOWN
        assert data.vehicle_state == VehicleState.ON
        assert data.request_serial == "abc123"

    def test_float_from_strings(self) -> None:
        data = VehicleRealtimeData.model_validate(self.SAMPLE_PAYLOAD)
        assert data.elec_percent == 85.5
        assert data.endurance_mileage == 320.5
        assert data.total_mileage == 12345.6
        assert data.speed == 22.0
        assert data.temp_in_car == 21.5

    def test_int_from_strings(self) -> None:
        data = VehicleRealtimeData.model_validate(self.SAMPLE_PAYLOAD)
        assert data.main_setting_temp == 7
        assert data.wait_status == 0
        assert data.booking_charge_state == 0
        assert data.abs_warning == 0
        assert data.timestamp == datetime.fromtimestamp(1700000000, tz=UTC)

    def test_negative_values_kept_as_is(self) -> None:
        """BYD -1 is NOT stripped; it's a valid API value."""
        data = VehicleRealtimeData.model_validate(self.SAMPLE_PAYLOAD)
        assert data.full_hour == -1
        assert data.full_minute == -1

    def test_remaining_hours(self) -> None:
        data = VehicleRealtimeData.model_validate(self.SAMPLE_PAYLOAD)
        assert data.remaining_hours == 2
        assert data.remaining_minutes == 30

    def test_enum_fields(self) -> None:
        data = VehicleRealtimeData.model_validate(self.SAMPLE_PAYLOAD)
        assert data.power_gear == PowerGear.DRIVE
        assert data.air_run_state == AirCirculationMode.INTERNAL
        assert data.main_seat_heat_state == SeatHeatVentState.HIGH
        assert data.charging_state == ChargingState.UNKNOWN
        assert data.charge_state == ChargingState.GUN_CONNECTED

    def test_door_lock_window_enums(self) -> None:
        data = VehicleRealtimeData.model_validate(self.SAMPLE_PAYLOAD)
        assert data.left_front_door == DoorOpenState.CLOSED
        assert data.trunk_lid == DoorOpenState.CLOSED
        assert data.left_front_door_lock == LockState.LOCKED
        assert data.left_front_window == WindowState.CLOSED

    def test_tire_pressure_key_alias(self) -> None:
        """BYD sends lowercase 'p' in tirepressure — normalised by _KEY_ALIASES."""
        data = VehicleRealtimeData.model_validate(self.SAMPLE_PAYLOAD)
        assert data.left_front_tire_pressure == 2.4
        assert data.right_rear_tire_pressure == 2.5
        assert data.tire_press_unit == TirePressureUnit.BAR

    def test_abs_alias(self) -> None:
        data = VehicleRealtimeData.model_validate(self.SAMPLE_PAYLOAD)
        assert data.abs_warning == 0

    def test_timestamp_alias(self) -> None:
        data = VehicleRealtimeData.model_validate(self.SAMPLE_PAYLOAD)
        assert data.timestamp == datetime.fromtimestamp(1700000000, tz=UTC)

    def test_back_cover_alias(self) -> None:
        """backCover normalised to trunkLid by _KEY_ALIASES."""
        data = VehicleRealtimeData.model_validate({"backCover": 1})
        assert data.trunk_lid == DoorOpenState.OPEN

    def test_sentinels_become_none(self) -> None:
        data = VehicleRealtimeData.model_validate({"elecPercent": "", "totalMileage": "--"})
        assert data.elec_percent is None
        assert data.total_mileage is None

    def test_unknown_enum_falls_back(self) -> None:
        data = VehicleRealtimeData.model_validate({"powerGear": 99})
        assert data.power_gear == PowerGear.UNKNOWN

    def test_defaults_are_unknown(self) -> None:
        data = VehicleRealtimeData.model_validate({})
        assert data.online_state == OnlineState.UNKNOWN
        assert data.vehicle_state == VehicleState.UNKNOWN
        assert data.power_gear is None
        assert data.charging_state == ChargingState.UNKNOWN

    def test_populate_by_name(self) -> None:
        data = VehicleRealtimeData(elec_percent=50.0, speed=100.0)
        assert data.elec_percent == 50.0
        assert data.speed == 100.0

    def test_raw_stashed(self) -> None:
        data = VehicleRealtimeData.model_validate({"onlineState": 1})
        assert data.raw == {"onlineState": 1}

    def test_is_locked(self) -> None:
        data = VehicleRealtimeData.model_validate(self.SAMPLE_PAYLOAD)
        assert data.is_locked is True

    def test_recent_50km_energy_alias(self) -> None:
        data = VehicleRealtimeData.model_validate({"recent50kmEnergy": "15.2"})
        assert data.recent_50km_energy == "15.2"


# ------------------------------------------------------------------
# HvacStatus
# ------------------------------------------------------------------


class TestHvacStatus:
    def test_camel_case_parsing(self) -> None:
        data = HvacStatus.model_validate(
            {
                "statusNow": {
                    "acSwitch": "1",
                    "status": "2",
                    "mainSettingTempNew": "21.5",
                    "tempInCar": "20.0",
                    "mainSeatHeatState": 3,
                    "pm25StateOutCar": "0",
                }
            }
        )
        assert data.ac_switch == 1
        assert data.status == 2
        assert data.main_setting_temp_new == 21.5
        assert data.temp_in_car == 20.0
        assert data.main_seat_heat_state == SeatHeatVentState.HIGH
        assert data.pm25_state_out_car == 0

    def test_is_ac_on(self) -> None:
        data = HvacStatus.model_validate({"statusNow": {"acSwitch": 1}})
        assert data.is_ac_on is True


# ------------------------------------------------------------------
# ChargingStatus
# ------------------------------------------------------------------


class TestChargingStatus:
    def test_camel_case_parsing(self) -> None:
        data = ChargingStatus.model_validate(
            {
                "vin": "TEST123",
                "soc": "85",
                "chargingState": "1",
                "connectState": "1",
                "fullHour": "2",
                "fullMinute": "30",
                "updateTime": "1700000000",
            }
        )
        assert data.vin == "TEST123"
        assert data.soc == 85
        assert data.charging_state == 1
        assert data.is_charging is True
        assert data.full_hour == 2
        assert data.full_minute == 30
        assert data.update_time == datetime.fromtimestamp(1700000000, tz=UTC)

    def test_soc_key_alias(self) -> None:
        """elecPercent normalised to soc."""
        data = ChargingStatus.model_validate({"elecPercent": "90"})
        assert data.soc == 90

    def test_update_time_key_alias(self) -> None:
        """time normalised to updateTime."""
        data = ChargingStatus.model_validate({"time": "1700000000"})
        assert data.update_time == datetime.fromtimestamp(1700000000, tz=UTC)


# ------------------------------------------------------------------
# EnergyConsumption
# ------------------------------------------------------------------


class TestEnergyConsumption:
    def test_camel_case_parsing(self) -> None:
        data = EnergyConsumption.model_validate(
            {
                "vin": "TEST123",
                "totalEnergy": "15.2",
                "avgEnergyConsumption": "--",
                "fuelConsumption": "",
            }
        )
        assert data.vin == "TEST123"
        assert data.total_energy == 15.2
        assert data.avg_energy_consumption is None
        assert data.fuel_consumption is None


# ------------------------------------------------------------------
# GpsInfo
# ------------------------------------------------------------------


class TestGpsInfo:
    def test_confirmed_mqtt_payload(self) -> None:
        """GPS model parses the confirmed MQTT payload keys."""
        data = GpsInfo.model_validate(
            {
                "gpsTimeStamp": 1771146108,
                "latitude": 63.397917,
                "direction": 77.9,
                "longitude": 10.410188,
            }
        )
        assert data.latitude == pytest.approx(63.397917)
        assert data.longitude == pytest.approx(10.410188)
        assert data.direction == pytest.approx(77.9)
        assert data.gps_timestamp == datetime.fromtimestamp(1771146108, tz=UTC)

    def test_nested_data_flattened(self) -> None:
        """GPS response wraps values in a nested 'data' dict."""
        data = GpsInfo.model_validate(
            {
                "data": {
                    "gpsTimeStamp": 1771146108,
                    "latitude": 63.4,
                    "longitude": 10.4,
                    "direction": 77.9,
                },
                "requestSerial": "GPS-1",
            }
        )
        assert data.latitude == pytest.approx(63.4)
        assert data.request_serial == "GPS-1"


# ------------------------------------------------------------------
# Vehicle
# ------------------------------------------------------------------


class TestVehicle:
    def test_camel_case_parsing(self) -> None:
        data = Vehicle.model_validate(
            {
                "vin": "TESTVIN",
                "modelName": "Seal",
                "brandName": "BYD",
                "energyType": "0",
                "totalMileage": "12345.6",
                "defaultCar": 1,
                "empowerType": "2",
            }
        )
        assert data.vin == "TESTVIN"
        assert data.model_name == "Seal"
        assert data.brand_name == "BYD"
        assert data.total_mileage == 12345.6
        assert data.default_car is True
        assert data.empower_type == 2

    def test_children_key_alias(self) -> None:
        from pybyd.models.vehicle import EmpowerRange

        data = EmpowerRange.model_validate(
            {
                "code": "2",
                "name": "Keys and control",
                "childList": [{"code": "21", "name": "Basic control"}],
            }
        )
        assert len(data.children) == 1
        assert data.children[0].code == "21"


# ------------------------------------------------------------------
# PushNotificationState
# ------------------------------------------------------------------


class TestPushNotificationState:
    def test_camel_case_parsing(self) -> None:
        data = PushNotificationState.model_validate({"vin": "TEST", "pushSwitch": "1"})
        assert data.push_switch == 1
        assert data.is_enabled is True
