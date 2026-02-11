"""Custom exception hierarchy for pybyd."""

from __future__ import annotations


class BydError(Exception):
    """Base exception for all pybyd errors."""


class BydConfigError(BydError):
    """Invalid or missing configuration."""


class BydCryptoError(BydError):
    """Encryption or decryption failure."""


class BangcleError(BydCryptoError):
    """Bangcle envelope encode/decode failure."""


class BangcleTableLoadError(BangcleError):
    """Could not load Bangcle lookup tables."""


class BydTransportError(BydError):
    """HTTP-level failure (network, non-200, invalid JSON)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        endpoint: str = "",
    ) -> None:
        self.status_code = status_code
        self.endpoint = endpoint
        super().__init__(message)


class BydApiError(BydError):
    """API returned a non-zero code (application-level error)."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        endpoint: str = "",
    ) -> None:
        self.code = code
        self.endpoint = endpoint
        super().__init__(message)


class BydAuthenticationError(BydApiError):
    """Login failed or session expired."""


class BydRemoteControlError(BydApiError):
    """Remote control command failed (controlState=2)."""
