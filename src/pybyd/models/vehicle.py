"""Vehicle model."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class EmpowerRange:
    """A permission scope granted to a shared user."""

    code: str
    """Category code (e.g. ``"2"`` = Keys and control)."""
    name: str
    """Human-readable category name."""
    children: list[EmpowerRange]
    """Child permission items."""


@dataclasses.dataclass(frozen=True)
class Vehicle:
    """A vehicle associated with the user's account.

    Fields are mapped from the ``/app/account/getAllListByUserId``
    response documented in PROTOCOL.md.
    """

    vin: str
    """Vehicle Identification Number."""
    model_name: str
    """Model name (e.g. ``"Tang EV"``)."""
    brand_name: str
    """Brand name (e.g. ``"BYD"``)."""
    energy_type: str
    """Energy type identifier (``"0"`` for EV)."""
    auto_alias: str
    """User-defined vehicle alias."""
    auto_plate: str
    """License plate."""
    pic_main_url: str
    """Primary image URL."""
    pic_set_url: str
    """Alternate image URL."""
    out_model_type: str
    """External model type label."""
    total_mileage: float | None
    """Odometer reading in km."""
    model_id: int | None
    """Internal model identifier."""
    car_type: int | None
    """Car type identifier."""
    default_car: bool
    """Whether this is the user's default vehicle."""
    empower_type: int | None
    """Sharing/empowerment type (``2`` = owner, ``-1`` = shared)."""
    permission_status: int | None
    """Permission status (``2`` = full)."""
    tbox_version: str
    """T-Box hardware version (e.g. ``"3"``)."""
    vehicle_state: str
    """Vehicle state string (e.g. ``"1"``)."""
    auto_bought_time: int | None
    """Vehicle purchase timestamp (epoch ms)."""
    yun_active_time: int | None
    """Cloud activation timestamp (epoch ms)."""
    empower_id: int | None
    """Empower relationship ID (present only for shared vehicles)."""
    range_detail_list: list[EmpowerRange]
    """Permission scopes granted to a shared user (empty for owners)."""

    raw: dict[str, Any]
    """Full API response dict for access to additional fields."""

    @property
    def is_shared(self) -> bool:
        """Whether this vehicle is shared (empowered) rather than owned."""
        return self.empower_type is not None and self.empower_type < 0
