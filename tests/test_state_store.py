from __future__ import annotations

from datetime import UTC, datetime

from pybyd.state.events import IngestionEvent, IngestionSource, StateSection
from pybyd.state.store import StateStore


def _dt() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def test_partial_update_does_not_overwrite_with_none() -> None:
    store = StateStore(skew_allowance_seconds=0.0)
    vin = "VIN123"

    store.apply(
        IngestionEvent(
            vin=vin,
            section=StateSection.REALTIME,
            source=IngestionSource.MQTT,
            observed_at=_dt(),
            payload_timestamp=100.0,
            data={"x": 5},
        )
    )
    store.apply(
        IngestionEvent(
            vin=vin,
            section=StateSection.REALTIME,
            source=IngestionSource.MQTT,
            observed_at=_dt(),
            payload_timestamp=101.0,
            # Patches are pruned at the ingestion boundary; missing keys mean "no update".
            data={},
        )
    )

    assert store.get_section(vin, StateSection.REALTIME)["x"] == 5


def test_stale_update_rejected_outside_skew_allowance() -> None:
    store = StateStore(skew_allowance_seconds=60.0)
    vin = "VIN123"

    store.apply(
        IngestionEvent(
            vin=vin,
            section=StateSection.REALTIME,
            source=IngestionSource.HTTP,
            observed_at=_dt(),
            payload_timestamp=100.0,
            data={"a": 1},
        )
    )

    # Too old (100 - 60 = 40). 10 should be rejected.
    store.apply(
        IngestionEvent(
            vin=vin,
            section=StateSection.REALTIME,
            source=IngestionSource.MQTT,
            observed_at=_dt(),
            payload_timestamp=10.0,
            data={"b": 2},
        )
    )

    assert "b" not in store.get_section(vin, StateSection.REALTIME)


def test_payload_timestamp_never_decreases_when_older_update_accepted_within_skew() -> None:
    store = StateStore(skew_allowance_seconds=60.0)
    vin = "VIN123"

    store.apply(
        IngestionEvent(
            vin=vin,
            section=StateSection.REALTIME,
            source=IngestionSource.HTTP,
            observed_at=_dt(),
            payload_timestamp=100.0,
            data={"a": 1},
        )
    )

    # Slightly older but within skew (>= 40), accepted.
    store.apply(
        IngestionEvent(
            vin=vin,
            section=StateSection.REALTIME,
            source=IngestionSource.MQTT,
            observed_at=_dt(),
            payload_timestamp=50.0,
            data={"b": 2},
        )
    )

    state = store._vehicles[vin].sections[StateSection.REALTIME]  # noqa: SLF001
    assert state.payload_timestamp == 100.0
    assert store.get_section(vin, StateSection.REALTIME)["b"] == 2


def test_source_priority_used_when_timestamps_missing() -> None:
    store = StateStore(skew_allowance_seconds=0.0)
    vin = "VIN123"

    store.apply(
        IngestionEvent(
            vin=vin,
            section=StateSection.HVAC,
            source=IngestionSource.MQTT,
            observed_at=_dt(),
            payload_timestamp=None,
            data={"status": 1},
        )
    )

    # HTTP should win and then block lower-priority timestamp-less MQTT updates.
    store.apply(
        IngestionEvent(
            vin=vin,
            section=StateSection.HVAC,
            source=IngestionSource.HTTP,
            observed_at=_dt(),
            payload_timestamp=None,
            data={"ac_switch": 1},
        )
    )
    store.apply(
        IngestionEvent(
            vin=vin,
            section=StateSection.HVAC,
            source=IngestionSource.MQTT,
            observed_at=_dt(),
            payload_timestamp=None,
            data={"pm": 5},
        )
    )

    section = store.get_section(vin, StateSection.HVAC)
    assert section.get("ac_switch") == 1
    assert section.get("pm") is None
