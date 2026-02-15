from __future__ import annotations

import dataclasses
import enum
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class RedactionConfig:
    enabled: bool = True
    placeholder: str = "<redacted>"
    redact_vin: bool = True
    redact_user_ids: bool = True
    redact_gps: bool = True
    redact_tokens: bool = True


_VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")


def _is_probably_secret_key(key: str) -> bool:
    k = key.lower()
    return any(
        token in k
        for token in (
            "password",
            "passwd",
            "pin",
            "token",
            "sig",
            "sign",
            "encry",
            "secret",
            "cookie",
            "authorization",
            "bearer",
        )
    )


def _is_probably_gps_key(key: str) -> bool:
    k = key.lower()
    return k in {
        "lat",
        "latitude",
        "gpslatitude",
        "lng",
        "lon",
        "longitude",
        "gpslongitude",
        "address",
        "location",
    }


def safe_json_value(value: Any) -> Any:
    """Convert common model/container types into JSON-serialisable data."""
    if isinstance(value, enum.Enum):
        return {"name": value.name, "value": value.value}
    if isinstance(value, BaseModel):
        return safe_json_value(value.model_dump())
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: safe_json_value(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(k): safe_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json_value(v) for v in value]
    return value


def flatten_json(value: Any, *, prefix: str = "", max_depth: int = 12) -> dict[str, Any]:
    """Flatten a JSON-like value into a {path -> value} mapping.

    Paths use dot notation for dicts and [idx] for lists.
    """

    def rec(val: Any, path: str, depth: int, out: dict[str, Any]) -> None:
        if depth > max_depth:
            out[path] = "<max_depth_reached>"
            return
        if isinstance(val, Mapping):
            if not val:
                out[path] = {}
                return
            for k, v in val.items():
                key = str(k)
                child = f"{path}.{key}" if path else key
                rec(v, child, depth + 1, out)
            return
        if isinstance(val, list):
            if not val:
                out[path] = []
                return
            for i, item in enumerate(val):
                child = f"{path}[{i}]" if path else f"[{i}]"
                rec(item, child, depth + 1, out)
            return
        out[path] = val

    result: dict[str, Any] = {}
    rec(value, prefix, 0, result)
    if prefix and prefix not in result:
        # Ensure the prefix exists when caller expects a root key.
        result[prefix] = value
    return result


def normalize_for_compare(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, list):
        return [normalize_for_compare(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): normalize_for_compare(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    return value


def diff_flatmaps(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    ignored_paths: set[str] | None = None,
) -> dict[str, tuple[Any, Any]]:
    ignored = ignored_paths or set()
    keys = set(before) | set(after)
    out: dict[str, tuple[Any, Any]] = {}
    for key in sorted(keys):
        if key in ignored:
            continue
        b = normalize_for_compare(before.get(key))
        a = normalize_for_compare(after.get(key))
        if b != a:
            out[key] = (before.get(key), after.get(key))
    return out


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def redact(obj: Any, cfg: RedactionConfig) -> Any:
    if not cfg.enabled:
        return obj

    def rec(val: Any, key_hint: str | None = None) -> Any:
        if isinstance(val, str):
            if cfg.redact_vin and _VIN_RE.search(val):
                return _VIN_RE.sub(cfg.placeholder, val)
            return val
        if isinstance(val, Mapping):
            out: dict[str, Any] = {}
            for k, v in val.items():
                ks = str(k)
                if cfg.redact_tokens and _is_probably_secret_key(ks):
                    out[ks] = cfg.placeholder
                    continue
                if cfg.redact_user_ids and ks.lower() in {"userid", "user_id"}:
                    out[ks] = cfg.placeholder
                    continue
                if cfg.redact_vin and ks.lower() == "vin":
                    out[ks] = cfg.placeholder
                    continue
                if cfg.redact_gps and _is_probably_gps_key(ks):
                    out[ks] = cfg.placeholder
                    continue
                out[ks] = rec(v, ks)
            return out
        if isinstance(val, list):
            return [rec(v, key_hint) for v in val]
        return val

    return rec(obj)


@dataclass
class EvidenceHit:
    step_id: str
    step_title: str
    when: str
    endpoint: str
    section: str  # parsed|raw|mqtt
    path: str
    before: Any
    after: Any


class EvidenceCollector:
    def __init__(self) -> None:
        self._hits: list[EvidenceHit] = []

    def add_diff(
        self,
        *,
        step_id: str,
        step_title: str,
        endpoint: str,
        section: str,
        diffs: Mapping[str, tuple[Any, Any]],
        when: str | None = None,
    ) -> None:
        ts = when or utc_now_iso()
        for path, (b, a) in diffs.items():
            self._hits.append(
                EvidenceHit(
                    step_id=step_id,
                    step_title=step_title,
                    when=ts,
                    endpoint=endpoint,
                    section=section,
                    path=path,
                    before=b,
                    after=a,
                )
            )

    def to_field_index(self) -> dict[str, Any]:
        index: dict[str, Any] = {}
        for hit in self._hits:
            key = f"{hit.endpoint}:{hit.section}:{hit.path}"
            entry = index.setdefault(
                key,
                {
                    "endpoint": hit.endpoint,
                    "section": hit.section,
                    "path": hit.path,
                    "hits": [],
                    "count": 0,
                },
            )
            entry["count"] += 1
            entry["hits"].append(
                {
                    "step_id": hit.step_id,
                    "step_title": hit.step_title,
                    "when": hit.when,
                    "before": hit.before,
                    "after": hit.after,
                }
            )
        return index

    def to_markdown_summary(self, *, max_examples_per_field: int = 3) -> str:
        idx = self.to_field_index()
        lines: list[str] = []
        lines.append("# Field Evidence Summary")
        lines.append("")
        lines.append("Each row is a field path that changed during one or more steps.")
        lines.append("")
        lines.append("| Field | Count | Example steps |")
        lines.append("|---|---:|---|")
        for key in sorted(idx.keys()):
            entry = idx[key]
            field = f"{entry['endpoint']} / {entry['section']} / {entry['path']}"
            count = entry["count"]
            hits: list[dict[str, Any]] = entry["hits"]
            examples = ", ".join(
                f"{h['step_id']}:{h['step_title']}" for h in hits[:max_examples_per_field]
            )
            if len(hits) > max_examples_per_field:
                examples += f" (+{len(hits) - max_examples_per_field} more)"
            lines.append(f"| {field} | {count} | {examples} |")
        lines.append("")
        return "\n".join(lines)


def to_pretty_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
