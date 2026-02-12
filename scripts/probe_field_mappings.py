#!/usr/bin/env python3
"""Probe BYD API field mappings via controlled remote commands.

This script performs live, non-destructive probing where possible:
1) Capture baseline snapshots across supported read endpoints.
2) Execute a command with conservative retry behavior.
3) Capture post-command snapshots and detect changed fields.
4) Attempt rollback for reversible commands and verify restoration.
5) Produce JSON + Markdown reports with field-level evidence.

The script intentionally spaces API requests to avoid overloading the BYD API.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import enum
import json
import logging
import os
import sys
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_repo = Path(__file__).resolve().parent.parent
_src = _repo / "src"
if _src.is_dir():
    sys.path.insert(0, str(_src))

from pybyd import BydClient, BydConfig  # noqa: E402
from pybyd.exceptions import BydApiError  # noqa: E402

LOG = logging.getLogger("probe_field_mappings")

NON_RETRYABLE_CONTROL_CODES: frozenset[str] = frozenset({"5005", "5006"})


VOLATILE_PARSED_FIELDS: dict[str, set[str]] = {
    "realtime": {"timestamp", "request_serial", "speed", "total_mileage", "total_mileage_v2"},
    "gps": {"gps_timestamp", "request_serial", "speed", "direction", "latitude", "longitude"},
    "charging": {"update_time", "full_hour", "full_minute"},
    "hvac": set(),
    "energy": set(),
}

VOLATILE_RAW_FIELDS: dict[str, set[str]] = {
    "realtime": {"time", "requestSerial", "speed", "totalMileage", "totalMileageV2"},
    "gps": {
        "requestSerial",
        "gpsTimeStamp",
        "gpsTimestamp",
        "gpsTime",
        "time",
        "uploadTime",
        "speed",
        "gpsSpeed",
        "direction",
        "heading",
        "course",
        "latitude",
        "lat",
        "gpsLatitude",
        "longitude",
        "lng",
        "lon",
        "gpsLongitude",
    },
    "charging": {"updateTime", "fullHour", "fullMinute"},
    "hvac": set(),
    "energy": set(),
}

READ_ENDPOINTS: tuple[str, ...] = ("realtime", "hvac", "charging", "gps", "energy")


@dataclass(frozen=True)
class ProbeCommand:
    name: str
    apply_label: str
    rollback_label: str | None
    one_way: bool
    apply: Callable[[BydClient, str, str | None, int, float], Awaitable[Any]]
    rollback: Callable[[BydClient, str, str | None, int, float], Awaitable[Any]] | None


@dataclass
class ProbeOptions:
    vin: str
    command_pwd: str | None
    between_commands_delay: float
    between_reads_delay: float
    settle_delay: float
    verify_polls: int
    verify_poll_interval: float
    command_retries: int
    poll_attempts: int
    poll_interval: float
    output_dir: Path


@dataclass
class FieldEvidence:
    endpoint: str
    parsed_field: str
    raw_keys: list[str]
    command: str
    direction: str
    before: Any
    after: Any
    reverted: bool | None


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return {"name": value.name, "value": value.value}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _safe_json_value(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _safe_json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json_value(v) for v in value]
    if isinstance(value, tuple):
        return [_safe_json_value(v) for v in value]
    return value


def _parsed_dataclass_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if not dataclasses.is_dataclass(obj) or isinstance(obj, type):
        return {"__repr__": repr(obj)}
    out: dict[str, Any] = {}
    for f in dataclasses.fields(obj):
        if f.name == "raw":
            continue
        val = getattr(obj, f.name)
        if isinstance(val, enum.Enum):
            out[f.name] = val.value
        else:
            out[f.name] = val
    return out


def _obj_raw_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw
    return {}


def _normalize_for_compare(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, list):
        return [_normalize_for_compare(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize_for_compare(v) for k, v in sorted(value.items())}
    return value


def _diff_keys(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    ignored: set[str],
) -> dict[str, tuple[Any, Any]]:
    keys = set(before) | set(after)
    changes: dict[str, tuple[Any, Any]] = {}
    for key in sorted(keys):
        if key in ignored:
            continue
        b = _normalize_for_compare(before.get(key))
        a = _normalize_for_compare(after.get(key))
        if b != a:
            changes[key] = (before.get(key), after.get(key))
    return changes


async def _safe_read_endpoint(
    client: BydClient,
    endpoint: str,
    vin: str,
) -> tuple[str, Any, str | None]:
    try:
        if endpoint == "realtime":
            return endpoint, await client.get_vehicle_realtime(vin, stale_after=0), None
        if endpoint == "hvac":
            return endpoint, await client.get_hvac_status(vin), None
        if endpoint == "charging":
            return endpoint, await client.get_charging_status(vin), None
        if endpoint == "gps":
            return endpoint, await client.get_gps_info(vin, stale_after=0), None
        if endpoint == "energy":
            return endpoint, await client.get_energy_consumption(vin), None
        return endpoint, None, f"Unsupported endpoint {endpoint}"
    except Exception as exc:  # noqa: BLE001
        return endpoint, None, f"{type(exc).__name__}: {exc}"


async def capture_snapshot(
    client: BydClient,
    vin: str,
    *,
    between_reads_delay: float,
) -> dict[str, Any]:
    data: dict[str, Any] = {"captured_at": datetime.now(UTC).isoformat(), "endpoints": {}}
    for index, endpoint in enumerate(READ_ENDPOINTS):
        name, obj, err = await _safe_read_endpoint(client, endpoint, vin)
        data["endpoints"][name] = {
            "error": err,
            "parsed": _safe_json_value(_parsed_dataclass_dict(obj)) if obj is not None else None,
            "raw": _safe_json_value(_obj_raw_dict(obj)) if obj is not None else None,
        }
        if index < len(READ_ENDPOINTS) - 1 and between_reads_delay > 0:
            await asyncio.sleep(between_reads_delay)
    return data


def _snapshot_endpoint(snapshot: dict[str, Any], endpoint: str) -> dict[str, Any]:
    return snapshot.get("endpoints", {}).get(endpoint, {})


def _flatten_diffs(
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
) -> dict[str, Any]:
    by_endpoint: dict[str, Any] = {}
    for endpoint in READ_ENDPOINTS:
        before_ep = _snapshot_endpoint(before_snapshot, endpoint)
        after_ep = _snapshot_endpoint(after_snapshot, endpoint)

        before_parsed = before_ep.get("parsed") if isinstance(before_ep, dict) else None
        after_parsed = after_ep.get("parsed") if isinstance(after_ep, dict) else None
        before_raw = before_ep.get("raw") if isinstance(before_ep, dict) else None
        after_raw = after_ep.get("raw") if isinstance(after_ep, dict) else None

        parsed_changes = _diff_keys(
            before_parsed or {},
            after_parsed or {},
            ignored=VOLATILE_PARSED_FIELDS.get(endpoint, set()),
        )
        raw_changes = _diff_keys(
            before_raw or {},
            after_raw or {},
            ignored=VOLATILE_RAW_FIELDS.get(endpoint, set()),
        )

        by_endpoint[endpoint] = {
            "parsed_changes": {
                k: {"before": _safe_json_value(v[0]), "after": _safe_json_value(v[1])}
                for k, v in parsed_changes.items()
            },
            "raw_changes": {
                k: {"before": _safe_json_value(v[0]), "after": _safe_json_value(v[1])} for k, v in raw_changes.items()
            },
            "parsed_change_count": len(parsed_changes),
            "raw_change_count": len(raw_changes),
        }
    return by_endpoint


def _has_material_changes(diffs: dict[str, Any], *, include_raw: bool = False) -> bool:
    if include_raw:
        return any(
            (entry.get("parsed_change_count", 0) + entry.get("raw_change_count", 0)) > 0 for entry in diffs.values()
        )
    return any(entry.get("parsed_change_count", 0) > 0 for entry in diffs.values())


def _summarize_attempt_errors(commands: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, int] = {}
    total = 0

    def add_error(message: str) -> None:
        nonlocal total
        total += 1
        grouped[message] = grouped.get(message, 0) + 1

    for command in commands:
        for attempt in command.get("apply", {}).get("attempts", []):
            if not attempt.get("ok"):
                error = attempt.get("error", {})
                add_error(str(error.get("message", "unknown error")))
        rollback = command.get("rollback")
        if isinstance(rollback, dict):
            for attempt in rollback.get("attempts", []):
                if not attempt.get("ok"):
                    error = attempt.get("error", {})
                    add_error(str(error.get("message", "unknown error")))

    return {
        "total_errors": total,
        "by_message": sorted(
            ({"message": msg, "count": count} for msg, count in grouped.items()),
            key=lambda item: item["count"],
            reverse=True,
        ),
    }


async def _execute_with_retry(
    fn: Callable[[], Awaitable[Any]],
    *,
    retries: int,
    delay: float,
) -> tuple[Any | None, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for idx in range(1, retries + 1):
        started = datetime.now(UTC).isoformat()
        try:
            result = await fn()
            attempts.append(
                {
                    "attempt": idx,
                    "started_at": started,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "ok": True,
                    "result": _safe_json_value(result),
                }
            )
            return result, attempts
        except Exception as exc:  # noqa: BLE001
            code = None
            non_retryable = False
            if isinstance(exc, BydApiError):
                code = exc.code
                non_retryable = code in NON_RETRYABLE_CONTROL_CODES
            attempts.append(
                {
                    "attempt": idx,
                    "started_at": started,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "ok": False,
                    "error": {
                        "type": type(exc).__name__,
                        "code": code,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                    "non_retryable": non_retryable,
                }
            )
            if non_retryable:
                break
            if idx < retries:
                await asyncio.sleep(delay)
    return None, attempts


async def _capture_verified_after(
    client: BydClient,
    vin: str,
    *,
    settle_delay: float,
    verify_polls: int,
    verify_poll_interval: float,
    between_reads_delay: float,
) -> dict[str, Any]:
    if settle_delay > 0:
        await asyncio.sleep(settle_delay)

    snapshots: list[dict[str, Any]] = []
    for idx in range(verify_polls):
        snap = await capture_snapshot(client, vin, between_reads_delay=between_reads_delay)
        snapshots.append(snap)
        if idx < verify_polls - 1 and verify_poll_interval > 0:
            await asyncio.sleep(verify_poll_interval)

    if len(snapshots) == 1:
        return snapshots[0]

    last = snapshots[-1]
    prev = snapshots[-2]
    stabilize_diffs = _flatten_diffs(prev, last)
    return {
        **last,
        "stability_check": {
            "snapshots_considered": len(snapshots),
            "last_interval_changes": stabilize_diffs,
            "appears_stable": not _has_material_changes(stabilize_diffs),
        },
    }


def _build_probe_commands() -> list[ProbeCommand]:
    async def do_lock(client: BydClient, vin: str, pwd: str | None, attempts: int, interval: float) -> Any:
        return await client.lock(vin, command_pwd=pwd, poll_attempts=attempts, poll_interval=interval)

    async def do_unlock(client: BydClient, vin: str, pwd: str | None, attempts: int, interval: float) -> Any:
        return await client.unlock(vin, command_pwd=pwd, poll_attempts=attempts, poll_interval=interval)

    async def do_start_climate(client: BydClient, vin: str, pwd: str | None, attempts: int, interval: float) -> Any:
        return await client.start_climate(
            vin,
            temperature=7,
            copilot_temperature=7,
            cycle_mode=2,
            time_span=1,
            command_pwd=pwd,
            poll_attempts=attempts,
            poll_interval=interval,
        )

    async def do_stop_climate(client: BydClient, vin: str, pwd: str | None, attempts: int, interval: float) -> Any:
        return await client.stop_climate(vin, command_pwd=pwd, poll_attempts=attempts, poll_interval=interval)

    async def do_seat_on(client: BydClient, vin: str, pwd: str | None, attempts: int, interval: float) -> Any:
        return await client.set_seat_climate(
            vin,
            main_heat=1,
            poll_attempts=attempts,
            poll_interval=interval,
            command_pwd=pwd,
        )

    async def do_seat_off(client: BydClient, vin: str, pwd: str | None, attempts: int, interval: float) -> Any:
        return await client.set_seat_climate(vin, poll_attempts=attempts, poll_interval=interval, command_pwd=pwd)

    async def do_battery_heat_on(client: BydClient, vin: str, pwd: str | None, attempts: int, interval: float) -> Any:
        return await client.set_battery_heat(
            vin, on=True, command_pwd=pwd, poll_attempts=attempts, poll_interval=interval
        )

    async def do_battery_heat_off(client: BydClient, vin: str, pwd: str | None, attempts: int, interval: float) -> Any:
        return await client.set_battery_heat(
            vin, on=False, command_pwd=pwd, poll_attempts=attempts, poll_interval=interval
        )

    async def do_flash_lights(client: BydClient, vin: str, _pwd: str | None, attempts: int, interval: float) -> Any:
        return await client.flash_lights(vin, poll_attempts=attempts, poll_interval=interval)

    async def do_find_car(client: BydClient, vin: str, _pwd: str | None, attempts: int, interval: float) -> Any:
        return await client.find_car(vin, poll_attempts=attempts, poll_interval=interval)

    async def do_close_windows(client: BydClient, vin: str, _pwd: str | None, attempts: int, interval: float) -> Any:
        return await client.close_windows(vin, poll_attempts=attempts, poll_interval=interval)

    return [
        ProbeCommand("lock", "lock doors", "unlock doors", False, do_lock, do_unlock),
        ProbeCommand("unlock", "unlock doors", "lock doors", False, do_unlock, do_lock),
        ProbeCommand(
            "start_climate",
            "start climate",
            "stop climate",
            False,
            do_start_climate,
            do_stop_climate,
        ),
        ProbeCommand("stop_climate", "stop climate", "start climate", False, do_stop_climate, do_start_climate),
        ProbeCommand("seat_climate_on", "enable seat climate", "disable seat climate", False, do_seat_on, do_seat_off),
        ProbeCommand("seat_climate_off", "disable seat climate", "enable seat climate", False, do_seat_off, do_seat_on),
        ProbeCommand(
            "battery_heat_on",
            "enable battery heat",
            "disable battery heat",
            False,
            do_battery_heat_on,
            do_battery_heat_off,
        ),
        ProbeCommand(
            "battery_heat_off",
            "disable battery heat",
            "enable battery heat",
            False,
            do_battery_heat_off,
            do_battery_heat_on,
        ),
        ProbeCommand("flash_lights", "flash lights", None, True, do_flash_lights, None),
        ProbeCommand("find_car", "find car", None, True, do_find_car, None),
        ProbeCommand("close_windows", "close windows", None, True, do_close_windows, None),
    ]


def _build_field_evidence(
    command_name: str,
    apply_diffs: dict[str, Any],
    rollback_diffs: dict[str, Any] | None,
) -> list[FieldEvidence]:
    evidence: list[FieldEvidence] = []
    rollback_diffs = rollback_diffs or {}

    for endpoint, section in apply_diffs.items():
        parsed_changes = section.get("parsed_changes", {})
        raw_changes = section.get("raw_changes", {})

        raw_by_parsed_guess: dict[str, list[str]] = {}
        for rk in raw_changes:
            guess = rk[:1].lower() + "".join([c if c.islower() else f"_{c.lower()}" for c in rk[1:]])
            raw_by_parsed_guess.setdefault(guess, []).append(rk)

        rollback_section = rollback_diffs.get(endpoint, {})
        rollback_parsed_changes = rollback_section.get("parsed_changes", {})

        for field, values in parsed_changes.items():
            reverted = None
            if rollback_section:
                reverted = field in rollback_parsed_changes
            evidence.append(
                FieldEvidence(
                    endpoint=endpoint,
                    parsed_field=field,
                    raw_keys=raw_by_parsed_guess.get(field, []),
                    command=command_name,
                    direction=f"{values.get('before')} -> {values.get('after')}",
                    before=values.get("before"),
                    after=values.get("after"),
                    reverted=reverted,
                )
            )

    return evidence


def _confidence_label(total_hits: int, reversible_hits: int, reverted_hits: int) -> str:
    if total_hits == 0:
        return "none"
    if reverted_hits > 0:
        return "high"
    if reversible_hits > 0:
        return "medium"
    return "low"


def _compile_field_summary(evidence: list[FieldEvidence]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for ev in evidence:
        key = (ev.endpoint, ev.parsed_field)
        if key not in grouped:
            grouped[key] = {
                "endpoint": ev.endpoint,
                "parsed_field": ev.parsed_field,
                "commands": set(),
                "examples": [],
                "raw_keys": set(),
                "total_hits": 0,
                "reversible_hits": 0,
                "reverted_hits": 0,
            }
        cur = grouped[key]
        cur["commands"].add(ev.command)
        cur["examples"].append(ev.direction)
        cur["raw_keys"].update(ev.raw_keys)
        cur["total_hits"] += 1
        if ev.reverted is not None:
            cur["reversible_hits"] += 1
        if ev.reverted is True:
            cur["reverted_hits"] += 1

    rows: list[dict[str, Any]] = []
    for (_endpoint, _field), data in sorted(grouped.items()):
        rows.append(
            {
                "endpoint": data["endpoint"],
                "parsed_field": data["parsed_field"],
                "commands": sorted(data["commands"]),
                "raw_keys": sorted(data["raw_keys"]),
                "examples": data["examples"][:4],
                "total_hits": data["total_hits"],
                "reversible_hits": data["reversible_hits"],
                "reverted_hits": data["reverted_hits"],
                "confidence": _confidence_label(
                    data["total_hits"],
                    data["reversible_hits"],
                    data["reverted_hits"],
                ),
            }
        )
    return rows


def _md_for_run(run_data: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BYD field mapping probe report")
    lines.append("")
    lines.append(f"- Generated: {run_data['meta']['generated_at']}")
    lines.append(f"- VIN: {run_data['meta']['vin']}")
    lines.append(f"- Username: {run_data['meta']['username']}")
    lines.append(f"- Total commands: {len(run_data['commands'])}")
    lines.append(f"- Command failures: {run_data['meta']['command_failures']}")
    lines.append(f"- Rollback failures: {run_data['meta']['rollback_failures']}")
    lines.append(f"- Permission blocked (remote control): {run_data['meta']['permission_blocked']}")
    lines.append("")

    lines.append("## Error summary")
    lines.append("")
    if run_data["error_summary"]["total_errors"] == 0:
        lines.append("- No command/rollback execution errors.")
    else:
        for item in run_data["error_summary"]["by_message"][:8]:
            lines.append(f"- {item['count']}x {item['message']}")
    lines.append("")

    lines.append("## Field evidence summary")
    lines.append("")
    lines.append("| Endpoint | Parsed field | Confidence | Hits | Reverted hits | Commands | Raw keys |")
    lines.append("|---|---|---:|---:|---:|---|---|")
    for row in run_data["field_summary"]:
        lines.append(
            "| "
            + f"{row['endpoint']}"
            + " | "
            + f"{row['parsed_field']}"
            + " | "
            + f"{row['confidence']}"
            + " | "
            + f"{row['total_hits']}"
            + " | "
            + f"{row['reverted_hits']}"
            + " | "
            + f"{', '.join(row['commands'])}"
            + " | "
            + f"{', '.join(row['raw_keys']) if row['raw_keys'] else '-'}"
            + " |"
        )
    lines.append("")

    lines.append("## Command outcomes")
    lines.append("")
    for cmd in run_data["commands"]:
        lines.append(f"### {cmd['name']}")
        lines.append(f"- One-way: {cmd['one_way']}")
        lines.append(f"- Apply ok: {cmd['apply']['ok']}")
        lines.append(f"- Material parsed-field changes observed: {cmd['changes_after_apply']}")
        if cmd.get("rollback") is None:
            lines.append("- Rollback: n/a")
        else:
            lines.append(f"- Rollback ok: {cmd['rollback']['ok']}")
            lines.append(f"- Rollback restored state: {cmd['rollback'].get('restored_state')}")
        lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- Confidence high: field changed during a reversible command and changed back on rollback.")
    lines.append("- Confidence medium: field changed during reversible command but no verified rollback signal.")
    lines.append("- Confidence low: field changed only during one-way commands.")
    lines.append("- Volatile telemetry fields (timestamps/GPS movement/speed) are excluded from evidence counts.")
    return "\n".join(lines)


async def run_probe(config: BydConfig, options: ProbeOptions, *, username_for_report: str) -> dict[str, Any]:
    run_started = datetime.now(UTC).isoformat()
    evidence: list[FieldEvidence] = []
    commands_out: list[dict[str, Any]] = []
    command_failures = 0
    rollback_failures = 0
    cloud_control_locked = False

    async with BydClient(config) as client:
        await client.login()
        vehicles = await client.get_vehicles()
        target = next((v for v in vehicles if v.vin == options.vin), None)
        if target is None:
            known = ", ".join(v.vin for v in vehicles)
            raise ValueError(f"VIN {options.vin} not found. Available VINs: {known}")

        # Noise baseline
        baseline_1 = await capture_snapshot(client, options.vin, between_reads_delay=options.between_reads_delay)
        await asyncio.sleep(max(options.verify_poll_interval, 1.0))
        baseline_2 = await capture_snapshot(client, options.vin, between_reads_delay=options.between_reads_delay)
        baseline_noise = _flatten_diffs(baseline_1, baseline_2)

        for probe_cmd in _build_probe_commands():
            LOG.info("Running command probe: %s", probe_cmd.name)
            per_command: dict[str, Any] = {
                "name": probe_cmd.name,
                "apply_label": probe_cmd.apply_label,
                "rollback_label": probe_cmd.rollback_label,
                "one_way": probe_cmd.one_way,
                "started_at": datetime.now(UTC).isoformat(),
            }

            before = await capture_snapshot(client, options.vin, between_reads_delay=options.between_reads_delay)

            async def do_apply(command: ProbeCommand = probe_cmd) -> Any:
                return await command.apply(
                    client,
                    options.vin,
                    options.command_pwd,
                    options.poll_attempts,
                    options.poll_interval,
                )

            _res, apply_attempts = await _execute_with_retry(
                do_apply,
                retries=options.command_retries,
                delay=options.settle_delay,
            )
            apply_ok = any(a.get("ok") for a in apply_attempts)
            if not apply_ok:
                command_failures += 1
                cloud_control_locked = any(
                    a.get("error", {}).get("code") == "5006" for a in apply_attempts if not a.get("ok")
                )

            after_apply = await _capture_verified_after(
                client,
                options.vin,
                settle_delay=options.settle_delay,
                verify_polls=options.verify_polls,
                verify_poll_interval=options.verify_poll_interval,
                between_reads_delay=options.between_reads_delay,
            )
            apply_diffs = _flatten_diffs(before, after_apply)
            changed_after_apply = _has_material_changes(apply_diffs)

            per_command["before"] = before
            per_command["apply"] = {"ok": apply_ok, "attempts": apply_attempts}
            per_command["after_apply"] = after_apply
            per_command["diff_after_apply"] = apply_diffs
            per_command["changes_after_apply"] = changed_after_apply

            rollback_diffs: dict[str, Any] | None = None
            if probe_cmd.rollback is None:
                per_command["rollback"] = None
            elif not apply_ok:
                per_command["rollback"] = {
                    "ok": False,
                    "attempts": [],
                    "restored_state": None,
                    "skipped": True,
                    "reason": "apply_failed",
                }
            else:

                async def do_rollback(command: ProbeCommand = probe_cmd) -> Any:
                    assert command.rollback is not None  # noqa: S101
                    return await command.rollback(
                        client,
                        options.vin,
                        options.command_pwd,
                        options.poll_attempts,
                        options.poll_interval,
                    )

                _rollback_res, rollback_attempts = await _execute_with_retry(
                    do_rollback,
                    retries=options.command_retries,
                    delay=options.settle_delay,
                )
                rollback_ok = any(a.get("ok") for a in rollback_attempts)
                if not rollback_ok:
                    rollback_failures += 1

                after_rollback = await _capture_verified_after(
                    client,
                    options.vin,
                    settle_delay=options.settle_delay,
                    verify_polls=options.verify_polls,
                    verify_poll_interval=options.verify_poll_interval,
                    between_reads_delay=options.between_reads_delay,
                )
                rollback_diffs = _flatten_diffs(after_apply, after_rollback)
                restored_diffs = _flatten_diffs(before, after_rollback)
                restored_state = not _has_material_changes(restored_diffs)

                per_command["after_rollback"] = after_rollback
                per_command["diff_after_rollback"] = rollback_diffs
                per_command["diff_baseline_vs_after_rollback"] = restored_diffs
                per_command["rollback"] = {
                    "ok": rollback_ok,
                    "attempts": rollback_attempts,
                    "restored_state": restored_state,
                    "skipped": False,
                }

            evidence.extend(_build_field_evidence(probe_cmd.name, apply_diffs, rollback_diffs))
            per_command["finished_at"] = datetime.now(UTC).isoformat()
            commands_out.append(per_command)

            if cloud_control_locked:
                LOG.warning("Cloud control lock detected (5006); stopping remaining probes to prevent spam")
                break

            if options.between_commands_delay > 0:
                await asyncio.sleep(options.between_commands_delay)

    field_summary = _compile_field_summary(evidence)
    error_summary = _summarize_attempt_errors(commands_out)
    all_apply_failed = all(not c.get("apply", {}).get("ok", False) for c in commands_out)
    dominant_errors = {item["message"] for item in error_summary["by_message"][:3]}
    permission_blocked = all_apply_failed and any("code=1009" in msg for msg in dominant_errors)

    run_data = {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "run_started_at": run_started,
            "vin": options.vin,
            "username": username_for_report,
            "between_commands_delay": options.between_commands_delay,
            "between_reads_delay": options.between_reads_delay,
            "settle_delay": options.settle_delay,
            "verify_polls": options.verify_polls,
            "verify_poll_interval": options.verify_poll_interval,
            "command_retries": options.command_retries,
            "poll_attempts": options.poll_attempts,
            "poll_interval": options.poll_interval,
            "command_failures": command_failures,
            "rollback_failures": rollback_failures,
            "permission_blocked": permission_blocked,
            "cloud_control_locked": cloud_control_locked,
        },
        "baseline_noise": baseline_noise,
        "commands": commands_out,
        "field_summary": field_summary,
        "error_summary": error_summary,
    }
    return run_data


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe API field mappings by executing remote commands and "
            "recording endpoint deltas with rollback attempts."
        )
    )
    parser.add_argument("--vin", required=True, help="VIN to probe")
    parser.add_argument("--username", help="BYD username/email for this run")
    parser.add_argument("--password", help="BYD password for this run")
    parser.add_argument("--control-pin", help="Optional 6-digit control PIN")
    parser.add_argument(
        "--output-dir",
        default="src/pybyd/data/mapping_probes",
        help="Directory for JSON/Markdown reports",
    )
    parser.add_argument("--between-commands-delay", type=float, default=8.0)
    parser.add_argument("--between-reads-delay", type=float, default=1.2)
    parser.add_argument("--settle-delay", type=float, default=5.0)
    parser.add_argument("--verify-polls", type=int, default=2)
    parser.add_argument("--verify-poll-interval", type=float, default=2.5)
    parser.add_argument("--command-retries", type=int, default=2)
    parser.add_argument("--poll-attempts", type=int, default=10)
    parser.add_argument("--poll-interval", type=float, default=1.8)
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def _build_config(args: argparse.Namespace) -> BydConfig:
    username = args.username or os.environ.get("BYD_USERNAME")
    password = args.password or os.environ.get("BYD_PASSWORD")
    if not username or not password:
        raise ValueError("Missing credentials. Provide --username/--password or BYD_USERNAME/BYD_PASSWORD.")

    control_pin = args.control_pin or os.environ.get("BYD_CONTROL_PIN")
    return BydConfig.from_env(username=username, password=password, control_pin=control_pin)


async def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = _build_config(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    options = ProbeOptions(
        vin=args.vin,
        command_pwd=None,
        between_commands_delay=max(args.between_commands_delay, 0.0),
        between_reads_delay=max(args.between_reads_delay, 0.0),
        settle_delay=max(args.settle_delay, 0.0),
        verify_polls=max(args.verify_polls, 1),
        verify_poll_interval=max(args.verify_poll_interval, 0.0),
        command_retries=max(args.command_retries, 1),
        poll_attempts=max(args.poll_attempts, 1),
        poll_interval=max(args.poll_interval, 0.0),
        output_dir=output_dir,
    )

    run_data = await run_probe(config, options, username_for_report=config.username)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"probe_{options.vin}_{stamp}"
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"

    json_path.write_text(json.dumps(run_data, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_md_for_run(run_data), encoding="utf-8")

    print(f"Probe complete. JSON: {json_path}")
    print(f"Probe complete. Markdown: {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
