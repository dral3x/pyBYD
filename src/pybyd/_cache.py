"""Internal vehicle data cache for merging partial endpoint responses."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


def _is_meaningful(value: Any) -> bool:
    """Return True if the value should overwrite cached data."""
    if value is None:
        return False
    if value == "":
        return False
    if value == "--":
        return False
    if value == []:
        return False
    return bool(value != {})


def _merge_dict(target: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge incoming into target, keeping cached values for empty fields."""
    for key, value in incoming.items():
        if isinstance(value, dict):
            if not value:
                continue
            existing = target.get(key)
            if isinstance(existing, dict):
                _merge_dict(existing, value)
            else:
                target[key] = copy.deepcopy(value)
        else:
            if _is_meaningful(value):
                target[key] = value
    return target


def _normalize_timestamp_seconds(value: Any) -> float | None:
    """Normalize timestamps to seconds since epoch."""
    if value is None or value == "":
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    # Treat values above 1e11 as milliseconds.
    if ts > 1e11:
        ts /= 1000.0
    return ts


def _age_seconds(now_ms: int, timestamp_seconds: float | None) -> float | None:
    if timestamp_seconds is None:
        return None
    return (now_ms / 1000.0) - timestamp_seconds


@dataclass
class VehicleCacheEntry:
    """Merged telemetry cache for a single vehicle."""

    realtime: dict[str, Any] = field(default_factory=dict)
    gps: dict[str, Any] = field(default_factory=dict)
    hvac: dict[str, Any] = field(default_factory=dict)
    charging: dict[str, Any] = field(default_factory=dict)
    energy: dict[str, Any] = field(default_factory=dict)
    vehicle: dict[str, Any] = field(default_factory=dict)


class VehicleDataCache:
    """Merge partial endpoint responses into per-vehicle snapshots."""

    def __init__(self) -> None:
        self._vehicles: dict[str, VehicleCacheEntry] = {}

    def _entry(self, vin: str) -> VehicleCacheEntry:
        entry = self._vehicles.get(vin)
        if entry is None:
            entry = VehicleCacheEntry()
            self._vehicles[vin] = entry
        return entry

    def merge_realtime(self, vin: str, data: dict[str, Any]) -> dict[str, Any]:
        entry = self._entry(vin)
        _merge_dict(entry.realtime, data)
        return copy.deepcopy(entry.realtime)

    def merge_gps(self, vin: str, data: dict[str, Any]) -> dict[str, Any]:
        entry = self._entry(vin)
        _merge_dict(entry.gps, data)
        return copy.deepcopy(entry.gps)

    def merge_hvac(self, vin: str, data: dict[str, Any]) -> dict[str, Any]:
        entry = self._entry(vin)
        _merge_dict(entry.hvac, data)
        return copy.deepcopy(entry.hvac)

    def merge_charging(self, vin: str, data: dict[str, Any]) -> dict[str, Any]:
        entry = self._entry(vin)
        _merge_dict(entry.charging, data)
        return copy.deepcopy(entry.charging)

    def merge_energy(self, vin: str, data: dict[str, Any]) -> dict[str, Any]:
        entry = self._entry(vin)
        _merge_dict(entry.energy, data)
        return copy.deepcopy(entry.energy)

    def merge_vehicle(self, vin: str, data: dict[str, Any]) -> dict[str, Any]:
        entry = self._entry(vin)
        _merge_dict(entry.vehicle, data)
        return copy.deepcopy(entry.vehicle)

    def get_realtime(self, vin: str) -> dict[str, Any]:
        entry = self._vehicles.get(vin)
        if entry is None:
            return {}
        return copy.deepcopy(entry.realtime)

    def get_gps(self, vin: str) -> dict[str, Any]:
        entry = self._vehicles.get(vin)
        if entry is None:
            return {}
        return copy.deepcopy(entry.gps)

    def get_realtime_age_seconds(self, vin: str, now_ms: int) -> float | None:
        entry = self._vehicles.get(vin)
        if entry is None or not entry.realtime:
            return None
        ts = _normalize_timestamp_seconds(entry.realtime.get("time"))
        return _age_seconds(now_ms, ts)

    def get_gps_age_seconds(self, vin: str, now_ms: int) -> float | None:
        entry = self._vehicles.get(vin)
        if entry is None or not entry.gps:
            return None
        gps_data: dict[str, Any] = entry.gps
        nested = gps_data.get("data")
        if isinstance(nested, dict):
            gps_data = nested
        ts = _normalize_timestamp_seconds(
            gps_data.get("gpsTimeStamp")
            or gps_data.get("gpsTimestamp")
            or gps_data.get("gpsTime")
            or gps_data.get("time")
            or gps_data.get("uploadTime")
        )
        return _age_seconds(now_ms, ts)
