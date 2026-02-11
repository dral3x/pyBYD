"""Energy consumption data model."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class EnergyConsumption:
    """Energy consumption data for a vehicle.

    Numeric fields are ``None`` when the value is absent or
    unparseable from the API response. All original data is
    available in the ``raw`` dict.

    Parameters
    ----------
    vin : str
        Vehicle Identification Number.
    total_energy : float or None
        Total energy consumption.
    avg_energy_consumption : float or None
        Average energy consumption.
    electricity_consumption : float or None
        Electricity portion of consumption.
    fuel_consumption : float or None
        Fuel portion of consumption.
    raw : dict
        Full API response dict.
    """

    vin: str
    total_energy: float | None
    avg_energy_consumption: float | None
    electricity_consumption: float | None
    fuel_consumption: float | None
    raw: dict[str, Any]
