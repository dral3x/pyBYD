"""Data models for BYD API responses."""

from pybyd.models._base import BydBaseModel, BydEnum, BydTimestamp, parse_byd_timestamp
from pybyd.models.charging import ChargingStatus
from pybyd.models.control import (
    BatteryHeatParams,
    ClimateScheduleParams,
    ClimateStartParams,
    CommandAck,
    ControlState,
    RemoteCommand,
    RemoteControlResult,
    SeatClimateParams,
    VerifyControlPasswordResponse,
)
from pybyd.models.energy import EnergyConsumption
from pybyd.models.gps import GpsInfo
from pybyd.models.hvac import HvacStatus, celsius_to_scale
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
from pybyd.models.smart_charging import SmartChargingSchedule
from pybyd.models.token import AuthToken
from pybyd.models.vehicle import EmpowerRange, Vehicle

__all__ = [
    "AirCirculationMode",
    "AuthToken",
    "BydBaseModel",
    "BydEnum",
    "BydTimestamp",
    "ChargingState",
    "ChargingStatus",
    "CommandAck",
    "ConnectState",
    "ControlState",
    "BatteryHeatParams",
    "ClimateScheduleParams",
    "ClimateStartParams",
    "DoorOpenState",
    "EmpowerRange",
    "EnergyConsumption",
    "GpsInfo",
    "HvacStatus",
    "celsius_to_scale",
    "LockState",
    "OnlineState",
    "PowerGear",
    "PushNotificationState",
    "RemoteCommand",
    "RemoteControlResult",
    "SeatClimateParams",
    "SeatHeatVentState",
    "SmartChargingSchedule",
    "TirePressureUnit",
    "Vehicle",
    "VehicleRealtimeData",
    "VehicleState",
    "VerifyControlPasswordResponse",
    "WindowState",
    "parse_byd_timestamp",
]
