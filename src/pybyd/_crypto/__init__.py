"""Cryptographic primitives for BYD API communication."""

from __future__ import annotations

from typing import Protocol

from pybyd._crypto.aes import aes_decrypt_utf8, aes_encrypt_hex
from pybyd._crypto.bangcle import BangcleCodec
from pybyd._crypto.hashing import compute_checkcode, md5_hex, sha1_mixed
from pybyd._crypto.signing import build_sign_string


class EnvelopeCodec(Protocol):
    """Protocol for Bangcle envelope encoding/decoding."""

    def encode_envelope(self, plaintext: str | bytes) -> str: ...

    def decode_envelope(self, envelope: str) -> bytes: ...


__all__ = [
    "BangcleCodec",
    "EnvelopeCodec",
    "aes_decrypt_utf8",
    "aes_encrypt_hex",
    "build_sign_string",
    "compute_checkcode",
    "md5_hex",
    "sha1_mixed",
]
