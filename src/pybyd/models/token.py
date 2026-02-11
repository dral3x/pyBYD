"""Authentication token model."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class AuthToken:
    """Token returned after successful login.

    Parameters
    ----------
    user_id : str
        The authenticated user's ID.
    sign_token : str
        Token for signature key derivation.
    encry_token : str
        Token for encryption key derivation.
    raw : dict
        Full decoded token dict for access to additional fields.
    """

    user_id: str
    sign_token: str
    encry_token: str
    raw: dict[str, Any]
