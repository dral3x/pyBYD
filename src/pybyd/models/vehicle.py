"""Vehicle model."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class Vehicle:
    """A vehicle associated with the user's account.

    Parameters
    ----------
    vin : str
        Vehicle Identification Number.
    model_name : str
        Model name (e.g. ``"BYD ATTO 3"``).
    brand_name : str
        Brand name.
    energy_type : str
        Energy type identifier.
    auto_alias : str
        User-defined vehicle alias.
    auto_plate : str
        License plate.
    raw : dict
        Full API response dict for access to additional fields.
    """

    vin: str
    model_name: str
    brand_name: str
    energy_type: str
    auto_alias: str
    auto_plate: str
    raw: dict[str, Any]
