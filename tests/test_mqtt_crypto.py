from __future__ import annotations

import json

import pytest

from pybyd._crypto.aes import aes_encrypt_hex
from pybyd._mqtt import decode_mqtt_payload
from pybyd.exceptions import BydCryptoError
from pybyd.session import Session


def test_decode_mqtt_payload_uses_content_key_shape() -> None:
    # encry_token itself is not necessarily hex; the AES key is MD5(encry_token)
    session = Session(user_id="1", sign_token="sign", encry_token="not-hex-token")
    key_hex = session.content_key()

    plaintext = json.dumps({"event": "vehicleInfo", "vin": "TESTVIN"}, separators=(",", ":"))
    cipher_hex = aes_encrypt_hex(plaintext, key_hex)

    spaced = f"  {cipher_hex[:10]}\n{cipher_hex[10:]}  "
    parsed, _plaintext = decode_mqtt_payload(spaced.encode("ascii"), key_hex)
    assert parsed["event"] == "vehicleInfo"
    assert parsed["vin"] == "TESTVIN"


def test_decode_mqtt_payload_wrong_key_raises_crypto_error() -> None:
    """Decrypting with the wrong key must raise BydCryptoError (not a generic Exception)."""
    session = Session(user_id="1", sign_token="sign", encry_token="correct-token")
    correct_key = session.content_key()

    plaintext = json.dumps({"event": "vehicleInfo", "vin": "V"}, separators=(",", ":"))
    cipher_hex = aes_encrypt_hex(plaintext, correct_key)

    wrong_session = Session(user_id="1", sign_token="sign", encry_token="wrong-token")
    wrong_key = wrong_session.content_key()

    with pytest.raises(BydCryptoError, match="AES decryption failed"):
        decode_mqtt_payload(cipher_hex.encode("ascii"), wrong_key)
