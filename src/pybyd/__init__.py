"""pybyd - Async Python client for BYD vehicle telemetry API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pybyd")
except PackageNotFoundError:
    __version__ = "0+local"
from pybyd.client import BydClient
from pybyd.config import BydConfig, DeviceProfile
from pybyd.exceptions import (
    BangcleError,
    BydApiError,
    BydAuthenticationError,
    BydConfigError,
    BydControlPasswordError,
    BydCryptoError,
    BydEndpointNotSupportedError,
    BydError,
    BydRateLimitError,
    BydRemoteControlError,
    BydSessionExpiredError,
    BydTransportError,
)
from pybyd.models import (
    AirCirculationMode,
    AuthToken,
    ChargingState,
    ChargingStatus,
    ConnectState,
    ControlState,
    DoorOpenState,
    EnergyConsumption,
    GpsInfo,
    HvacStatus,
    LockState,
    OnlineState,
    PowerGear,
    RemoteCommand,
    RemoteControlResult,
    SeatHeatVentState,
    TirePressureUnit,
    Vehicle,
    VehicleRealtimeData,
    VehicleState,
    WindowState,
)

__all__ = [
    "__version__",
    "AirCirculationMode",
    "AuthToken",
    "BangcleError",
    "BydApiError",
    "BydAuthenticationError",
    "BydClient",
    "BydConfig",
    "BydConfigError",
    "BydControlPasswordError",
    "BydCryptoError",
    "BydEndpointNotSupportedError",
    "BydError",
    "BydRateLimitError",
    "BydRemoteControlError",
    "BydSessionExpiredError",
    "BydTransportError",
    "ChargingState",
    "ChargingStatus",
    "ConnectState",
    "ControlState",
    "DeviceProfile",
    "DoorOpenState",
    "EnergyConsumption",
    "GpsInfo",
    "HvacStatus",
    "LockState",
    "OnlineState",
    "PowerGear",
    "RemoteCommand",
    "RemoteControlResult",
    "SeatHeatVentState",
    "TirePressureUnit",
    "Vehicle",
    "VehicleRealtimeData",
    "VehicleState",
    "WindowState",
]
