"""Session state management for authenticated API calls."""

from __future__ import annotations

import dataclasses
import functools
import time

from pybyd._crypto.hashing import md5_hex

#: Default session token time-to-live in seconds (12 hours).
#: The BYD API does not return an explicit expiry; this is a safe
#: conservative default derived from observed session lifetimes.
DEFAULT_SESSION_TTL: float = 12 * 3600


@dataclasses.dataclass
class Session:
    """Mutable session state after successful login.

    Parameters
    ----------
    user_id : str
        The authenticated user's ID.
    sign_token : str
        Token used for request signature derivation.
    encry_token : str
        Token used for content encryption key derivation.
    created_at : float
        Monotonic timestamp (``time.monotonic()``) when the session
        was created.  Defaults to *now* if not provided.
    ttl : float
        Time-to-live in seconds.  After this period the session is
        considered expired and should be refreshed via a new login.
    """

    user_id: str
    sign_token: str
    encry_token: str
    created_at: float = dataclasses.field(default_factory=time.monotonic)
    ttl: float = DEFAULT_SESSION_TTL

    @functools.cached_property
    def content_key(self) -> str:
        """AES key for encrypting/decrypting inner payload data.

        Derived as ``MD5(encry_token)`` in uppercase hex.
        """
        return md5_hex(self.encry_token)

    @functools.cached_property
    def sign_key(self) -> str:
        """Key used in request signature computation.

        Derived as ``MD5(sign_token)`` in uppercase hex.
        """
        return md5_hex(self.sign_token)

    @property
    def is_expired(self) -> bool:
        """Whether the session has exceeded its TTL."""
        return (time.monotonic() - self.created_at) >= self.ttl

    @property
    def age(self) -> float:
        """Seconds since the session was created."""
        return time.monotonic() - self.created_at
