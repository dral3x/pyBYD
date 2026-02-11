"""Vehicle realtime data model."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class VehicleRealtimeData:
    """Realtime telemetry data for a vehicle.

    Numeric fields are ``None`` when the value is absent or
    unparseable from the API response. All original data is
    available in the ``raw`` dict.

    Parameters
    ----------
    online_state : int
        1 = online, 2 = offline, 0 = unknown.
    vehicle_state : str
        Vehicle state string.
    elec_percent : float or None
        Battery percentage.
    endurance_mileage : float or None
        Estimated remaining range in km.
    total_mileage : float or None
        Odometer reading in km.
    speed : float or None
        Current speed in km/h.
    temp_in_car : float or None
        Interior temperature in Celsius.
    charging_state : str
        Charging state string.
    left_front_door : str
        Door state.
    right_front_door : str
        Door state.
    left_rear_door : str
        Door state.
    right_rear_door : str
        Door state.
    trunk_lid : str
        Trunk lid state.
    left_front_tire_pressure : float or None
        Tire pressure.
    right_front_tire_pressure : float or None
        Tire pressure.
    left_rear_tire_pressure : float or None
        Tire pressure.
    right_rear_tire_pressure : float or None
        Tire pressure.
    timestamp : int or None
        Data timestamp (epoch ms or seconds).
    request_serial : str or None
        Serial for follow-up polling.
    raw : dict
        Full API response dict.
    """

    online_state: int
    vehicle_state: str
    elec_percent: float | None
    endurance_mileage: float | None
    total_mileage: float | None
    speed: float | None
    temp_in_car: float | None
    charging_state: str
    left_front_door: str
    right_front_door: str
    left_rear_door: str
    right_rear_door: str
    trunk_lid: str
    left_front_tire_pressure: float | None
    right_front_tire_pressure: float | None
    left_rear_tire_pressure: float | None
    right_rear_tire_pressure: float | None
    timestamp: int | None
    request_serial: str | None
    raw: dict[str, Any]
