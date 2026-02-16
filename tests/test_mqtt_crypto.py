from __future__ import annotations

import json

from pybyd._crypto.aes import aes_encrypt_hex
from pybyd._mqtt import decode_mqtt_payload
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
