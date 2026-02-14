"""Normalization helpers.

Centralizes defensive parsing and placeholder handling.
"""

from __future__ import annotations

import math
from enum import IntEnum
from typing import Any, TypeVar

TEnum = TypeVar("TEnum", bound=IntEnum)


def safe_float(value: Any) -> float | None:
    if value is None or value == "" or value == "--":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def safe_int(value: Any) -> int | None:
    parsed = safe_float(value)
    if parsed is None:
        return None
    return int(parsed)


def safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def non_negative_or_zero(value: Any) -> int | None:
    parsed = safe_int(value)
    if parsed is None:
        return None
    return 0 if parsed < 0 else parsed


def to_enum(enum_cls: type[TEnum], value: Any, default: TEnum | None = None) -> TEnum | int | None:
    parsed = safe_int(value)
    if parsed is None:
        return default
    try:
        return enum_cls(parsed)
    except ValueError:
        return parsed


def is_meaningful(value: Any) -> bool:
    """Return True if the value should be included in a state patch.

    This is intentionally opinionated and exists to keep the state/store layer
    free of placeholder/sentinel filtering.
    """

    if value is None:
        return False
    if value == "":
        return False
    if value == "--":
        return False
    if value == {}:
        return False
    return bool(value != [])


def prune_patch(data: Any) -> Any:
    """Recursively drop non-meaningful values from a patch structure.

    - Dicts: remove keys with non-meaningful values; recurse into nested dicts/lists.
    - Lists: prune elements and drop non-meaningful items.
    - Scalars: returned as-is.

    State merging assumes incoming patches are already pruned.
    """

    if isinstance(data, dict):
        pruned: dict[str, Any] = {}
        for key, value in data.items():
            cleaned = prune_patch(value)
            if is_meaningful(cleaned):
                pruned[key] = cleaned
        return pruned

    if isinstance(data, list):
        items: list[Any] = []
        for item in data:
            cleaned = prune_patch(item)
            if is_meaningful(cleaned):
                items.append(cleaned)
        return items

    return data


def normalize_timestamp_seconds(value: Any) -> float | None:
    """Normalize API timestamps to epoch seconds.

    - Empty/missing -> None
    - <= 0 -> None
    - Milliseconds (> 1e11) -> seconds
    """

    if value is None or value == "":
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    if ts > 1e11:
        ts /= 1000.0
    return ts


def extract_payload_timestamp(section: Any, data: dict[str, Any]) -> float | None:
    """Best-effort extraction of a payload timestamp for a section.

    Kept in ingestion utils so state/store doesn't need to interpret raw payloads.
    """

    # Import lazily to avoid coupling ingestion helpers back into state.
    from pybyd.state.events import StateSection

    if section == StateSection.REALTIME:
        return normalize_timestamp_seconds(data.get("timestamp") or data.get("time"))
    if section == StateSection.GPS:
        # Normalized model uses `gps_timestamp`. Raw payload may contain multiple aliases.
        ts_value = data.get("gps_timestamp")
        if ts_value is not None:
            return normalize_timestamp_seconds(ts_value)
        nested = data.get("data")
        candidate: dict[str, Any] = nested if isinstance(nested, dict) else data
        return normalize_timestamp_seconds(
            candidate.get("gpsTimeStamp")
            or candidate.get("gpsTimestamp")
            or candidate.get("gpsTime")
            or candidate.get("time")
            or candidate.get("uploadTime")
        )
    if section == StateSection.CHARGING:
        return normalize_timestamp_seconds(data.get("update_time") or data.get("updateTime") or data.get("time"))
    if section == StateSection.HVAC:
        return normalize_timestamp_seconds(data.get("time"))
    if section == StateSection.ENERGY:
        return normalize_timestamp_seconds(data.get("time"))
    if section == StateSection.VEHICLE:
        return normalize_timestamp_seconds(data.get("time"))
    return None
