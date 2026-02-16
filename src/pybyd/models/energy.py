"""Energy consumption data model."""

# 16.02.2026 initial findings suggest this is locked behind specific car models - meaning its untested.

from __future__ import annotations

from pybyd.models._base import BydBaseModel


class EnergyConsumption(BydBaseModel):
    """Energy consumption data for a vehicle."""

    vin: str = ""
    total_energy: float | None = None
    avg_energy_consumption: float | None = None
    electricity_consumption: float | None = None
    fuel_consumption: float | None = None
