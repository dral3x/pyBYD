"""Ingestion application helpers.

This module centralizes the common pattern used across ingestion paths:

- parse raw payload into a typed Pydantic model
- dump a normalized patch from the model
- compute a best-effort payload timestamp
- create/apply a :class:`pybyd.state.events.IngestionEvent`

Keeping this logic in one place reduces duplication between HTTP reads and
MQTT ingestion while preserving the existing state-store semantics.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pybyd.ingestion.normalize import extract_payload_timestamp, prune_patch
from pybyd.state.events import IngestionEvent, IngestionSource, StateSection


class _ModelWithDump(Protocol):
    raw: Any

    def model_dump(self, *, exclude: set[str] | None = None, exclude_none: bool = False) -> dict[str, Any]: ...


def build_event_from_model(
    *,
    vin: str,
    section: StateSection,
    source: IngestionSource,
    model: _ModelWithDump,
    raw: dict[str, Any] | None = None,
    exclude_none: bool = False,
    timestamp_data: dict[str, Any] | None = None,
    payload_timestamp: float | None = None,
    data_wrapper: tuple[str, ...] | None = None,
) -> IngestionEvent:
    """Build an ingestion event from a model.

    Parameters
    ----------
    raw
        Raw payload to attach to the event. Defaults to ``model.raw`` if that is a dict.
    exclude_none
        Whether to exclude ``None`` fields from the dumped model before pruning.
    timestamp_data
        Dict used to extract the best-effort payload timestamp. When omitted, the
        pruned patch is used if it is a dict.
    payload_timestamp
        Explicit timestamp override.
    data_wrapper
        Optional wrapper path used to nest the dumped patch under one or more keys.
        For example, ``("push_state",)`` yields ``{"push_state": <patch>}``.
    """

    dumped = model.model_dump(exclude={"raw"}, exclude_none=exclude_none)
    patch = prune_patch(dumped)

    data: Any = patch
    if data_wrapper:
        for key in reversed(data_wrapper):
            data = {key: data}

    raw_payload: dict[str, Any] = {}
    if raw is not None:
        raw_payload = raw
    else:
        candidate = getattr(model, "raw", None)
        raw_payload = candidate if isinstance(candidate, dict) else {}

    if payload_timestamp is None:
        ts_source = timestamp_data
        if ts_source is None and isinstance(patch, dict):
            ts_source = patch
        payload_timestamp = extract_payload_timestamp(section, ts_source or {})

    return IngestionEvent(
        vin=vin,
        section=section,
        source=source,
        payload_timestamp=payload_timestamp,
        data=data if isinstance(data, dict) else {},
        raw=raw_payload,
    )


def apply_model_to_store(
    store_apply: Callable[[IngestionEvent], None],
    *,
    vin: str,
    section: StateSection,
    source: IngestionSource,
    model: _ModelWithDump,
    raw: dict[str, Any] | None = None,
    exclude_none: bool = False,
    timestamp_data: dict[str, Any] | None = None,
    payload_timestamp: float | None = None,
    data_wrapper: tuple[str, ...] | None = None,
) -> IngestionEvent:
    """Build and apply an ingestion event to a store."""

    event = build_event_from_model(
        vin=vin,
        section=section,
        source=source,
        model=model,
        raw=raw,
        exclude_none=exclude_none,
        timestamp_data=timestamp_data,
        payload_timestamp=payload_timestamp,
        data_wrapper=data_wrapper,
    )
    store_apply(event)
    return event
