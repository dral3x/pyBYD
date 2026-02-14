"""GPS information model."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from pybyd.ingestion.normalize import safe_float, safe_int, safe_str


class GpsInfo(BaseModel):
    """GPS location data for a vehicle.

    Numeric fields are ``None`` when the value is absent or
    unparseable from the API response.

    Parameters
    ----------
    latitude : float or None
        Latitude in degrees.
    longitude : float or None
        Longitude in degrees.
    speed : float or None
        GPS speed in km/h.
    direction : float or None
        Heading in degrees.
    gps_timestamp : int or None
        GPS data timestamp.
    request_serial : str or None
        Serial for follow-up polling.
    raw : dict
        Full API response dict.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=True,
    )

    latitude: float | None = Field(default=None, validation_alias=AliasChoices("latitude", "lat", "gpsLatitude"))
    longitude: float | None = Field(
        default=None,
        validation_alias=AliasChoices("longitude", "lng", "lon", "gpsLongitude"),
    )
    speed: float | None = Field(default=None, validation_alias=AliasChoices("speed", "gpsSpeed"))
    direction: float | None = Field(default=None, validation_alias=AliasChoices("direction", "heading", "course"))
    gps_timestamp: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "gpsTimeStamp",
            "gpsTimestamp",
            "gpsTime",
            "time",
            "uploadTime",
            "gps_timestamp",
        ),
    )
    request_serial: str | None = Field(default=None, validation_alias=AliasChoices("requestSerial", "request_serial"))
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _merge_nested_data(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        nested = values.get("data")
        if isinstance(nested, dict):
            merged = dict(values)
            merged.update(nested)
        else:
            merged = dict(values)
        merged.setdefault("raw", values)
        return merged

    @field_validator("latitude", "longitude", "speed", "direction", mode="before")
    @classmethod
    def _coerce_floats(cls, value: Any) -> float | None:
        return safe_float(value)

    @field_validator("gps_timestamp", mode="before")
    @classmethod
    def _coerce_timestamp(cls, value: Any) -> int | None:
        return safe_int(value)

    @field_validator("request_serial", mode="before")
    @classmethod
    def _coerce_request_serial(cls, value: Any) -> str | None:
        return safe_str(value)
