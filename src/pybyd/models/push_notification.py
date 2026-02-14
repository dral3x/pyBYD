"""Push notification state model."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from pybyd.ingestion.normalize import safe_int


class PushNotificationState(BaseModel):
    """Push notification switch state for a vehicle."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=True,
    )

    vin: str = Field(default="", validation_alias=AliasChoices("vin"))
    """Vehicle Identification Number."""

    push_switch: int | None = Field(default=None, validation_alias=AliasChoices("pushSwitch", "push_switch"))
    """Push notification toggle (0=off, 1=on)."""

    raw: dict[str, Any] = Field(default_factory=dict)
    """Full API response dict."""

    @property
    def is_enabled(self) -> bool:
        """Whether push notifications are currently enabled."""
        return self.push_switch is not None and self.push_switch == 1

    @model_validator(mode="before")
    @classmethod
    def _ensure_raw(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        merged = dict(values)
        merged.setdefault("raw", values)
        return merged

    @field_validator("push_switch", mode="before")
    @classmethod
    def _coerce_int(cls, value: Any) -> int | None:
        return safe_int(value)
