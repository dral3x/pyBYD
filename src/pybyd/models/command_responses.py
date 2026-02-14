"""Typed responses for BYD "command" style endpoints.

These endpoints typically return a small acknowledgement payload (often
`{"result": "ok"}`) or even an empty payload. Models here keep the
raw decrypted payload for forward compatibility.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class CommandAck(BaseModel):
    """Generic acknowledgement response for write/toggle endpoints."""

    model_config = ConfigDict(frozen=True)

    vin: str
    result: str | None
    raw: dict[str, Any]


class VerifyControlPasswordResponse(BaseModel):
    """Response from the control password verification endpoint."""

    model_config = ConfigDict(frozen=True)

    vin: str
    ok: bool | None
    raw: dict[str, Any]
