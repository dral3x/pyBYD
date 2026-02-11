"""GPS information model."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class GpsInfo:
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

    latitude: float | None
    longitude: float | None
    speed: float | None
    direction: float | None
    gps_timestamp: int | None
    request_serial: str | None
    raw: dict[str, Any]
