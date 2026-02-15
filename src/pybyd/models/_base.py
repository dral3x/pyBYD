"""Base model and enum for BYD API responses.

Every BYD response model inherits from :class:`BydBaseModel` which
provides:

* ``alias_generator=to_camel`` so camelCase API keys map
  automatically to snake_case fields.
* A ``model_validator(mode="before")`` that strips BYD sentinel
  values (``""``, ``"--"``, NaN) so the field default is used.
* A ``raw`` dict that captures the original payload.

State enums inherit from :class:`BydEnum` which adds an ``UNKNOWN``
member at ``-1`` and a ``_missing_`` hook that returns ``UNKNOWN``
for any value without a mapped member.
"""

from __future__ import annotations

import enum
import math
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

# Sentinel strings the BYD API uses for "not available".
_SENTINELS = frozenset({"", "--", "NaN", "nan"})

# Threshold to distinguish seconds from milliseconds.
_MS_THRESHOLD = 1_000_000_000_000


def parse_byd_timestamp(value: Any) -> datetime | None:
    """Convert a BYD epoch timestamp (seconds **or** milliseconds) to a UTC datetime.

    Returns ``None`` when the value is ``None`` or not numeric.
    """
    if value is None:
        return value
    if isinstance(value, datetime):
        return value
    ts = int(value)
    if ts >= _MS_THRESHOLD:
        ts = ts // 1000
    return datetime.fromtimestamp(ts, tz=UTC)


BydTimestamp = Annotated[datetime | None, BeforeValidator(parse_byd_timestamp)]
"""Annotated type that coerces BYD epoch ints (seconds or ms) to UTC datetimes."""


class BydEnum(enum.IntEnum):
    """Base for BYD API state enums.

    Every subclass **must** define ``UNKNOWN = -1``.
    Values the API sends that have no mapped member automatically
    resolve to ``UNKNOWN`` instead of raising ``ValueError``.
    """

    @classmethod
    def _missing_(cls, value: object) -> BydEnum:
        # noinspection PyUnresolvedReferences
        return cls.UNKNOWN  # type: ignore[attr-defined]


class BydBaseModel(BaseModel):
    """Base for BYD API response models.

    Handles:
    * camelCase → snake_case via ``alias_generator=to_camel``
    * BYD sentinel values (``""``, ``"--"``, NaN) → dropped so
      the field default is used instead
    * Stashes the original API dict in ``raw``
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=True,
        alias_generator=to_camel,
    )

    raw: dict[str, Any] = Field(default_factory=dict)
    """Original API response dict."""

    @model_validator(mode="before")
    @classmethod
    def _clean_byd_values(cls, values: Any) -> Any:
        """Strip BYD sentinel values, apply key aliases, and stash the raw payload."""
        if not isinstance(values, dict):
            return values
        original = dict(values)

        # Apply per-model key aliases (old API key → canonical camelCase key).
        aliases: dict[str, str] = getattr(cls, "_KEY_ALIASES", {})
        working = dict(original)
        for old_key, new_key in aliases.items():
            if old_key in working and new_key not in working:
                working[new_key] = working.pop(old_key)

        cleaned: dict[str, Any] = {}
        for key, value in working.items():
            if value is None:
                continue
            if isinstance(value, str) and value.strip() in _SENTINELS:
                continue
            if isinstance(value, float) and math.isnan(value):
                continue
            cleaned[key] = value

        # Only auto-stash raw when not explicitly provided (i.e. model_validate
        # from an API dict).  When constructing with kwargs that include raw=,
        # keep the caller's value.
        if "raw" not in values:
            cleaned["raw"] = original
        return cleaned
