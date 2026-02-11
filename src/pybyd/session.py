"""Session state management for authenticated API calls."""

from __future__ import annotations

import dataclasses
import functools

from pybyd._crypto.hashing import md5_hex


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
    """

    user_id: str
    sign_token: str
    encry_token: str

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
