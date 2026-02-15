from __future__ import annotations

from pybyd._tools.field_mapper import RedactionConfig, diff_flatmaps, flatten_json, redact


def test_flatten_json_paths() -> None:
    data = {"a": {"b": 1, "c": [10, {"d": 20}]}, "e": []}
    flat = flatten_json(data)
    assert flat["a.b"] == 1
    assert flat["a.c[0]"] == 10
    assert flat["a.c[1].d"] == 20
    assert flat["e"] == []


def test_diff_flatmaps_ignored() -> None:
    before = {"x": 1, "y": 2}
    after = {"x": 1, "y": 3}
    diffs = diff_flatmaps(before, after, ignored_paths={"y"})
    assert not diffs


def test_redaction_basic() -> None:
    cfg = RedactionConfig(enabled=True)
    obj = {
        "vin": "LNBX1234567890123",
        "user_id": "12345",
        "latitude": 52.0,
        "longitude": 4.0,
        "signToken": "abc",
        "nested": {"password": "secret"},
    }
    red = redact(obj, cfg)
    assert red["vin"] == cfg.placeholder
    assert red["user_id"] == cfg.placeholder
    assert red["latitude"] == cfg.placeholder
    assert red["longitude"] == cfg.placeholder
    assert red["signToken"] == cfg.placeholder
    assert red["nested"]["password"] == cfg.placeholder
