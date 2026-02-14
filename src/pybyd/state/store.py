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
from pybyd.state.policy import is_expired, should_accept_update


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
            expires_at = now + self._optimistic_ttl
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

        # Merge patch into snapshot.
        _merge_patch(snapshot.data, event.data)
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
