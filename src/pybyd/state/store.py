"""Deterministic in-memory state store.

This is the only component allowed to merge incoming ingestion updates.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pybyd.state.events import IngestionEvent, IngestionSource, StateSection
from pybyd.state.policy import is_expired, should_accept_update, source_priority

_OPTIMISTIC_TTL_SECONDS_KEY = "__pybyd_optimistic_ttl_s"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _merge_patch(target: dict[str, Any], patch: dict[str, Any]) -> None:
    """Apply a normalized patch.

    The ingestion/Pydantic boundary is responsible for:
    - pruning placeholders/sentinels
    - excluding unset/None fields

    State-store merge semantics are therefore simple: keys in the patch overwrite.
    """

    if not patch:
        return
    target.update(copy.deepcopy(patch))


def _merge_patch_fill_missing(target: dict[str, Any], patch: dict[str, Any]) -> None:
    """Apply a patch without overwriting existing keys.

    Used for older/out-of-order updates: they may carry additional fields we
    haven't seen yet, but shouldn't be able to revert already-known values.
    """

    if not patch:
        return
    for key, value in patch.items():
        if key not in target:
            target[key] = copy.deepcopy(value)


class SectionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict[str, Any] = Field(default_factory=dict)
    payload_timestamp: float | None = None
    observed_at: datetime | None = None
    source: IngestionSource | None = None
    populated_keys: int = 0


class OptimisticOverlay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict[str, Any]
    applied_at: datetime
    expires_at: datetime


class VehicleState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: dict[StateSection, SectionSnapshot] = Field(default_factory=dict)
    optimistic: dict[StateSection, OptimisticOverlay] = Field(default_factory=dict)


class StateStore:
    """In-memory store for merged vehicle state.

    This store is designed to be deterministic: given the same sequence of
    `IngestionEvent`s, it will produce the same snapshots.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _utcnow,
        optimistic_ttl: timedelta = timedelta(seconds=60),
        skew_allowance_seconds: float = 60.0,
    ) -> None:
        self._clock = clock
        self._optimistic_ttl = optimistic_ttl
        self._skew_allowance_seconds = skew_allowance_seconds
        self._vehicles: dict[str, VehicleState] = {}

    def _vehicle(self, vin: str) -> VehicleState:
        state = self._vehicles.get(vin)
        if state is None:
            state = VehicleState()
            self._vehicles[vin] = state
        return state

    def apply(self, event: IngestionEvent) -> None:
        """Apply a normalized ingestion event."""
        state = self._vehicle(event.vin)
        now = self._clock()

        if event.source == IngestionSource.OPTIMISTIC:
            ttl_seconds: float | None = None
            if isinstance(event.raw, dict) and _OPTIMISTIC_TTL_SECONDS_KEY in event.raw:
                value = event.raw.get(_OPTIMISTIC_TTL_SECONDS_KEY)
                if isinstance(value, (int, float)):
                    ttl_seconds = float(value)

            if ttl_seconds is None:
                expires_at = now + self._optimistic_ttl
            elif ttl_seconds <= 0:
                # "Sticky" optimistic overlay: does not expire on its own.
                # It is still cleared by any non-optimistic update for the section.
                expires_at = datetime.max.replace(tzinfo=UTC)
            else:
                expires_at = now + timedelta(seconds=ttl_seconds)
            state.optimistic[event.section] = OptimisticOverlay(
                data=copy.deepcopy(event.data),
                applied_at=event.observed_at,
                expires_at=expires_at,
            )
            return

        # Any server/derived update clears optimistic overlay for that section.
        state.optimistic.pop(event.section, None)

        snapshot = state.sections.get(event.section)
        if snapshot is None:
            snapshot = SectionSnapshot()
            state.sections[event.section] = snapshot

        incoming_ts = event.payload_timestamp

        if not should_accept_update(
            cached_payload_ts=snapshot.payload_timestamp,
            incoming_payload_ts=incoming_ts,
            cached_source=snapshot.source,
            incoming_source=event.source,
            skew_allowance_seconds=self._skew_allowance_seconds,
        ):
            return

        # If an update is older than what we already have, it can still be useful
        # (late-arriving partial fields), but it must not overwrite known values
        # unless it comes from a strictly higher-priority source.
        merge_overwrite = True
        if incoming_ts is not None and snapshot.payload_timestamp is not None and incoming_ts < snapshot.payload_timestamp:
            cached_prio = source_priority(snapshot.source) if snapshot.source is not None else 0
            incoming_prio = source_priority(event.source)
            merge_overwrite = incoming_prio > cached_prio

        # Merge patch into snapshot.
        if merge_overwrite:
            _merge_patch(snapshot.data, event.data)
        else:
            _merge_patch_fill_missing(snapshot.data, event.data)
        snapshot.observed_at = event.observed_at
        snapshot.source = event.source
        # Never move payload_timestamp backwards; this preserves stale-rejection strength
        # even when slightly older updates are accepted due to clock-skew allowance.
        if incoming_ts is not None:
            if snapshot.payload_timestamp is None:
                snapshot.payload_timestamp = incoming_ts
            else:
                snapshot.payload_timestamp = max(snapshot.payload_timestamp, incoming_ts)
        snapshot.populated_keys = len(snapshot.data)

    def get_section(self, vin: str, section: StateSection) -> dict[str, Any]:
        """Get the merged view of a section (including optimistic overlay)."""
        state = self._vehicles.get(vin)
        if state is None:
            return {}

        base = state.sections.get(section)
        result: dict[str, Any] = copy.deepcopy(base.data) if base is not None else {}

        overlay = state.optimistic.get(section)
        if overlay is None:
            return result

        now = self._clock()
        if is_expired(now, overlay.expires_at):
            state.optimistic.pop(section, None)
            return result

        # Overlay always wins for keys it supplies.
        _merge_patch(result, overlay.data)
        return result

    def get_vehicle_snapshot(self, vin: str) -> dict[StateSection, dict[str, Any]]:
        """Get merged state for all sections."""
        state = self._vehicles.get(vin)
        if state is None:
            return {}

        sections = set(state.sections.keys()) | set(state.optimistic.keys())
        return {section: self.get_section(vin, section) for section in sections}
