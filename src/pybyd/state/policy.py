"""Deterministic state merge policy.

This module intentionally contains *no* payload parsing or placeholder filtering.
The ingestion/Pydantic boundary is responsible for producing normalized patches
and timestamps.
"""

from __future__ import annotations

from datetime import datetime

from pybyd.state.events import IngestionSource


def source_priority(source: IngestionSource) -> int:
    """Higher wins for deterministic tie-breaking."""
    # Server-sourced beats derived; optimistic is lowest.
    priorities: dict[IngestionSource, int] = {
        IngestionSource.HTTP: 50,
        IngestionSource.MQTT: 40,
        IngestionSource.PUSH: 40,
        IngestionSource.DERIVED: 10,
        IngestionSource.OPTIMISTIC: 0,
    }
    return priorities.get(source, 0)


def should_accept_update(
    *,
    cached_payload_ts: float | None,
    incoming_payload_ts: float | None,
    cached_source: IngestionSource | None,
    incoming_source: IngestionSource,
    skew_allowance_seconds: float,
) -> bool:
    """Decide whether an incoming event should be applied.

    Policy:
    - If both timestamps exist: accept if incoming is newer (or within skew allowance).
    - If timestamps missing: prefer HTTP over MQTT by source priority.
    """
    if incoming_payload_ts is not None and cached_payload_ts is not None:
        return incoming_payload_ts >= (cached_payload_ts - skew_allowance_seconds)

    # If we have no timestamp signal, fall back to source priority.
    if cached_source is None:
        return True
    return source_priority(incoming_source) >= source_priority(cached_source)


def is_expired(now: datetime, expires_at: datetime) -> bool:
    return now >= expires_at
