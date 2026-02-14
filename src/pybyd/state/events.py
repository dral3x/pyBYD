"""Normalized ingestion events.

All ingestion paths (HTTP, MQTT, push) convert their inputs
into these events. Only the state/store layer is allowed to merge them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IngestionSource(StrEnum):
    HTTP = "http"
    MQTT = "mqtt"
    PUSH = "push"
    OPTIMISTIC = "optimistic"
    DERIVED = "derived"


class StateSection(StrEnum):
    REALTIME = "realtime"
    GPS = "gps"
    HVAC = "hvac"
    CHARGING = "charging"
    ENERGY = "energy"
    VEHICLE = "vehicle"
    CONTROL = "control"


class IngestionEvent(BaseModel):
    """A normalized update to apply to the state store."""

    model_config = ConfigDict(frozen=True)

    vin: str = Field(..., description="Vehicle VIN")
    section: StateSection
    source: IngestionSource
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload_timestamp: float | None = Field(
        default=None,
        description="Timestamp (epoch seconds) from the payload, if any.",
    )
    data: dict[str, Any] = Field(default_factory=dict, description="Normalized patch data")
    raw: dict[str, Any] = Field(default_factory=dict, description="Original payload (as received)")

    @field_validator("vin")
    @classmethod
    def _normalize_vin(cls, value: str) -> str:
        vin = value.strip()
        if not vin:
            raise ValueError("vin must be non-empty")
        return vin

    @field_validator("observed_at")
    @classmethod
    def _ensure_tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
