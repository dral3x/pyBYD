from __future__ import annotations

from pybyd._redact import redact_for_log


def test_redact_for_log_redacts_sensitive_keys() -> None:
    payload = {
        "code": "0",
        "respondData": "ABCDEF",
        "token": {"userId": "123", "signToken": "SIG", "encryToken": "ENC"},
        "password": "pw",
        "nested": {"encryData": "deadbeef"},
    }

    redacted = redact_for_log(payload)
    assert redacted["respondData"] == "<redacted>"
    assert redacted["password"] == "<redacted>"
    assert redacted["token"] == "<redacted>"
    assert redacted["nested"]["encryData"] == "<redacted>"


def test_redact_for_log_truncates_long_strings() -> None:
    long_value = "x" * 600
    redacted = redact_for_log({"value": long_value}, max_string=10)
    assert redacted["value"].startswith("x" * 10)
    assert "<truncated>" in redacted["value"]
