#!/usr/bin/env python3
"""Interactive field mapping harness for BYD API.

This script is designed for *manual* experimentation:

1) It takes a baseline snapshot across every readable endpoint.
2) For each step, it tells you exactly what to do in the mobile app/vehicle.
3) You press Enter when done.
4) It polls again and records what changed (parsed + raw + MQTT).

Outputs are written to a run directory with clear per-step separators so the
data can be analyzed later.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_repo = Path(__file__).resolve().parent.parent
_src = _repo / "src"
if _src.is_dir():
    sys.path.insert(0, str(_src))

# pylint: disable=wrong-import-position
from pybyd import BydClient, BydConfig  # noqa: E402
from pybyd._tools.field_mapper import (  # noqa: E402
    EvidenceCollector,
    RedactionConfig,
    diff_flatmaps,
    flatten_json,
    redact,
    safe_json_value,
    to_pretty_json,
    utc_now_iso,
)

LOG = logging.getLogger("interactive_field_mapper")


READ_ENDPOINTS: tuple[str, ...] = (
    "realtime",
    "gps",
    "hvac",
    "charging",
    "energy",
    "push",
)


VOLATILE_PATH_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "realtime": [
        re.compile(r"(^|\.)timestamp$"),
        re.compile(r"(^|\.)request_serial$"),
        re.compile(r"(^|\.)speed$"),
        re.compile(r"(^|\.)total_mileage"),
    ],
    "gps": [
        re.compile(r"(^|\.)gps_timestamp"),
        re.compile(r"(^|\.)request_serial$"),
        re.compile(r"(^|\.)speed$"),
        re.compile(r"(^|\.)direction$"),
        re.compile(r"(^|\.)latitude$"),
        re.compile(r"(^|\.)longitude$"),
    ],
    "charging": [
        re.compile(r"(^|\.)update_time"),
        re.compile(r"(^|\.)full_hour"),
        re.compile(r"(^|\.)full_minute"),
    ],
}


def _matches_volatile(endpoint: str, path: str) -> bool:
    return any(pat.search(path) for pat in VOLATILE_PATH_PATTERNS.get(endpoint, []))


def _section(title: str) -> str:
    line = "=" * 72
    return f"\n{line}\n{title}\n{line}\n"


def _slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "step"


def _model_to_parsed_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, BaseModel):
        d = obj.model_dump(exclude={"raw"})
        return safe_json_value(d)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        d = {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj) if f.name != "raw"}
        return safe_json_value(d)
    return {"__repr__": repr(obj)}


def _model_to_raw_dict(obj: Any) -> dict[str, Any]:
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return safe_json_value(raw)
    return {}


async def _safe_call(label: str, fn: Callable[[], Any]) -> tuple[str, Any, str | None]:
    try:
        res = await fn()
        return label, res, None
    except Exception as exc:  # noqa: BLE001
        return label, None, f"{type(exc).__name__}: {exc}"


async def capture_snapshot(
    client: BydClient,
    vin: str,
    *,
    between_reads_delay: float,
    include_vehicles: bool,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "captured_at": utc_now_iso(),
        "vin": vin,
        "endpoints": {},
    }

    if include_vehicles:
        name, obj, err = await _safe_call(
            "vehicles",
            client.get_vehicles,
        )
        snapshot["endpoints"][name] = {
            "error": err,
            "parsed": safe_json_value([v.model_dump(exclude={"raw"}) for v in obj]) if obj else None,
            "raw": safe_json_value([getattr(v, "raw", {}) for v in obj]) if obj else None,
        }
        if between_reads_delay > 0:
            await asyncio.sleep(between_reads_delay)

    for idx, endpoint in enumerate(READ_ENDPOINTS):
        if endpoint == "realtime":
            name, obj, err = await _safe_call(endpoint, lambda: client.get_vehicle_realtime(vin, stale_after=0))
        elif endpoint == "gps":
            name, obj, err = await _safe_call(endpoint, lambda: client.get_gps_info(vin, stale_after=0))
        elif endpoint == "hvac":
            name, obj, err = await _safe_call(endpoint, lambda: client.get_hvac_status(vin))
        elif endpoint == "charging":
            name, obj, err = await _safe_call(endpoint, lambda: client.get_charging_status(vin))
        elif endpoint == "energy":
            name, obj, err = await _safe_call(endpoint, lambda: client.get_energy_consumption(vin))
        elif endpoint == "push":
            name, obj, err = await _safe_call(endpoint, lambda: client.get_push_state(vin))
        else:
            name, obj, err = endpoint, None, f"Unsupported endpoint {endpoint}"

        parsed = _model_to_parsed_dict(obj) if obj is not None else None
        raw = _model_to_raw_dict(obj) if obj is not None else None

        snapshot["endpoints"][name] = {
            "error": err,
            "parsed": parsed,
            "raw": raw,
            "parsed_flat": flatten_json(parsed) if isinstance(parsed, dict) else None,
            "raw_flat": flatten_json(raw) if isinstance(raw, dict) else None,
        }

        if idx < len(READ_ENDPOINTS) - 1 and between_reads_delay > 0:
            await asyncio.sleep(between_reads_delay)

    return snapshot


def _ignored_paths_for_snapshot(snapshot: dict[str, Any], *, section: str) -> dict[str, set[str]]:
    ignored: dict[str, set[str]] = {}
    endpoints = snapshot.get("endpoints", {})
    if not isinstance(endpoints, dict):
        return ignored

    for endpoint, payload in endpoints.items():
        if not isinstance(payload, dict):
            continue
        flat = payload.get(f"{section}_flat")
        if not isinstance(flat, dict):
            continue
        ignore_set: set[str] = set()
        for path in flat:
            if _matches_volatile(str(endpoint), str(path)):
                ignore_set.add(str(path))
        ignored[str(endpoint)] = ignore_set
    return ignored


def diff_snapshots(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    ignore_by_endpoint_parsed: dict[str, set[str]] | None = None,
    ignore_by_endpoint_raw: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"by_endpoint": {}}
    before_eps = before.get("endpoints", {}) if isinstance(before.get("endpoints"), dict) else {}
    after_eps = after.get("endpoints", {}) if isinstance(after.get("endpoints"), dict) else {}

    for endpoint in sorted(set(before_eps) | set(after_eps)):
        b = before_eps.get(endpoint, {}) if isinstance(before_eps.get(endpoint), dict) else {}
        a = after_eps.get(endpoint, {}) if isinstance(after_eps.get(endpoint), dict) else {}
        b_parsed = b.get("parsed_flat") if isinstance(b.get("parsed_flat"), dict) else {}
        a_parsed = a.get("parsed_flat") if isinstance(a.get("parsed_flat"), dict) else {}
        b_raw = b.get("raw_flat") if isinstance(b.get("raw_flat"), dict) else {}
        a_raw = a.get("raw_flat") if isinstance(a.get("raw_flat"), dict) else {}

        ignored_parsed = (ignore_by_endpoint_parsed or {}).get(endpoint, set())
        ignored_raw = (ignore_by_endpoint_raw or {}).get(endpoint, set())

        parsed_changes = diff_flatmaps(b_parsed, a_parsed, ignored_paths=set(ignored_parsed))
        raw_changes = diff_flatmaps(b_raw, a_raw, ignored_paths=set(ignored_raw))
        out["by_endpoint"][endpoint] = {
            "parsed": {k: {"before": v[0], "after": v[1]} for k, v in parsed_changes.items()},
            "raw": {k: {"before": v[0], "after": v[1]} for k, v in raw_changes.items()},
            "counts": {"parsed": len(parsed_changes), "raw": len(raw_changes)},
        }
    return out


@dataclass(frozen=True)
class Step:
    step_id: str
    title: str
    instructions: str


def default_steps() -> list[Step]:
    # Keep steps explicit and human-driven. The goal is to test everything
    # observable; even if a vehicle doesn't support a feature, we still record
    # that nothing changed.
    titles: list[tuple[str, str]] = [
        (
            "hvac_ac_on",
            "Now we are going to see how A/C ON is detected.",
        ),
        (
            "hvac_ac_off",
            "Now we are going to see how A/C OFF is detected.",
        ),
        (
            "hvac_temp_up",
            "Now we are going to see how HVAC temperature changes are detected (increase by 1°C/°F).",
        ),
        (
            "hvac_temp_down",
            "Now we are going to see how HVAC temperature changes are detected (decrease by 1°C/°F).",
        ),
        (
            "hvac_defrost_toggle",
            "Now we are going to see how front defrost is detected.",
        ),
        (
            "hvac_recirculation_toggle",
            "Now we are going to see how air recirculation is detected.",
        ),
        (
            "lock_vehicle",
            "Now we are going to see how vehicle LOCK is detected.",
        ),
        (
            "unlock_vehicle",
            "Now we are going to see how vehicle UNLOCK is detected.",
        ),
        (
            "door_open_close",
            "Now we are going to see how DOOR OPEN/CLOSE is detected.",
        ),
        (
            "trunk_open_close",
            "Now we are going to see how TRUNK/BOOT OPEN/CLOSE is detected.",
        ),
        (
            "lights_flash",
            "Now we are going to see how lights/flash behaviour is detected.",
        ),
        (
            "horn_find",
            "Now we are going to see how find-vehicle/horn behaviour is detected (if available).",
        ),
        (
            "charging_plug_in",
            "Now we are going to see how PLUG-IN is detected.",
        ),
        (
            "charging_start",
            "Now we are going to see how CHARGING START is detected.",
        ),
        (
            "charging_stop",
            "Now we are going to see how CHARGING STOP is detected.",
        ),
        (
            "charging_plug_out",
            "Now we are going to see how PLUG-OUT is detected.",
        ),
        (
            "push_toggle",
            "Now we are going to see how PUSH NOTIFICATION SWITCH changes are detected.",
        ),
        (
            "vehicle_sleep_wake",
            "Now we are going to see how vehicle sleep/wake is reflected in the API.",
        ),
    ]
    steps: list[Step] = []
    for idx, (sid, headline) in enumerate(titles, start=1):
        step_id = f"{idx:04d}_{sid}"
        steps.append(
            Step(
                step_id=step_id,
                title=headline,
                instructions=(
                    f"{headline}\n\n"
                    "Do the action in the BYD mobile app (or in the vehicle), then come back here.\n"
                    "Press Enter when you have finished the action."
                ),
            )
        )
    return steps


def _install_transport_trace(client: BydClient, *, trace_path: Path, redaction_cfg: RedactionConfig) -> None:
    """Install a best-effort, redacted transport trace.

    This is intentionally *sanitized* to avoid leaking tokens/cookies/payloads.
    """
    transport = getattr(client, "_transport", None)
    if transport is None:
        raise RuntimeError("Client transport not initialized")
    orig = transport.post_secure

    async def wrapped(endpoint: str, outer: dict[str, Any]) -> dict[str, Any]:
        start = time.time()
        try:
            resp = await orig(endpoint, outer)
            ok = True
        except Exception as exc:  # noqa: BLE001
            ok = False
            resp = {"error": f"{type(exc).__name__}: {exc}"}

        item = {
            "ts": utc_now_iso(),
            "endpoint": endpoint,
            "ok": ok,
            "duration_ms": int((time.time() - start) * 1000),
            "outer_keys": sorted(list(outer.keys())),
            "response_keys": sorted(list(resp.keys())) if isinstance(resp, dict) else ["<non-dict>"],
            "code": str(resp.get("code")) if isinstance(resp, dict) else None,
            "message": resp.get("message") if isinstance(resp, dict) else None,
        }
        with trace_path.open("a", encoding="utf-8") as f:
            f.write(to_pretty_json(redact(item, redaction_cfg)))
            f.write("\n")
        if not ok:
            raise RuntimeError(resp["error"])
        return resp

    transport.post_secure = wrapped  # type: ignore[method-assign]


async def _ainput(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


async def run() -> None:
    parser = argparse.ArgumentParser(description="Interactive BYD API field mapping harness")
    parser.add_argument("--vin", help="VIN to use (default: first vehicle)")
    parser.add_argument("--out", default="field-mapper-runs", help="Output directory root")
    parser.add_argument("--between-reads", type=float, default=1.5, help="Delay between endpoint reads")
    parser.add_argument("--settle", type=float, default=2.0, help="Delay after you press Enter before polling")
    parser.add_argument("--baseline-snapshots", type=int, default=2, help="Noise calibration snapshots (no action)")
    parser.add_argument("--baseline-delay", type=float, default=4.0, help="Delay between baseline snapshots")
    parser.add_argument("--include-vehicles", action="store_true", help="Include vehicle list in snapshots")
    parser.add_argument("--no-mqtt", action="store_true", help="Disable MQTT capture even if config enables it")
    parser.add_argument("--trace-envelope", action="store_true", help="Write a redacted transport trace")
    parser.add_argument("--no-redact", action="store_true", help="Disable redaction (not recommended)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cfg = BydConfig.from_env()
    if args.no_mqtt:
        cfg = cfg.model_copy(update={"mqtt_enabled": False})

    redaction_cfg = RedactionConfig(enabled=not args.no_redact)

    out_root = Path(args.out).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    run_dir = out_root / f"run_{run_id}"
    steps_dir = run_dir / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)

    mqtt_events: list[dict[str, Any]] = []
    current_step_id: str | None = None

    def on_mqtt_event(event: str, vin: str, payload: dict[str, Any]) -> None:
        item = {
            "ts": utc_now_iso(),
            "step_id": current_step_id,
            "event": event,
            "vin": vin,
            "payload": payload,
        }
        mqtt_events.append(item)

    evidence = EvidenceCollector()

    header_lines: list[str] = []
    header_lines.append("# Interactive Field Mapping Run")
    header_lines.append("")
    header_lines.append(f"- Started: {utc_now_iso()}")
    header_lines.append(f"- Output: {run_dir}")
    header_lines.append(f"- Redaction: {'on' if redaction_cfg.enabled else 'off'}")
    header_lines.append(f"- MQTT enabled: {cfg.mqtt_enabled}")
    header_lines.append("")
    (run_dir / "report.md").write_text("\n".join(header_lines) + "\n", encoding="utf-8")

    # Write a config snapshot (redacted)
    (run_dir / "config.json").write_text(
        to_pretty_json(redact(safe_json_value(cfg.model_dump()), redaction_cfg)),
        encoding="utf-8",
    )

    # Transport trace
    trace_path = run_dir / "transport_trace.jsonl"

    async with BydClient(cfg, on_mqtt_event=on_mqtt_event) as client:
        await client.login()
        session = await client.ensure_session()

        # Store session metadata (redacted)
        (run_dir / "session.json").write_text(
            to_pretty_json(
                redact(
                    {
                        "user_id": session.user_id,
                        "started": utc_now_iso(),
                    },
                    redaction_cfg,
                )
            ),
            encoding="utf-8",
        )

        if args.trace_envelope:
            _install_transport_trace(client, trace_path=trace_path, redaction_cfg=redaction_cfg)

        vehicles = await client.get_vehicles()
        if not vehicles:
            raise RuntimeError("No vehicles returned by API")

        vin = args.vin or vehicles[0].vin
        (run_dir / "vin.txt").write_text(str(redact(vin, redaction_cfg)), encoding="utf-8")

        print(_section("Interactive field mapper"))
        print(f"Run dir: {run_dir}")
        print(f"VIN    : {redact(vin, redaction_cfg)}")
        print(f"MQTT   : {'enabled' if cfg.mqtt_enabled else 'disabled'}")
        print("")

        # Baseline/noise calibration
        baseline: list[dict[str, Any]] = []
        if args.baseline_snapshots > 0:
            print(_section("Baseline noise calibration"))
            print(
                "We will take a couple of snapshots WITHOUT you doing anything, "
                "so we can tell which fields are naturally noisy."
            )
            await _ainput("Press Enter to start baseline snapshots...")
            for i in range(args.baseline_snapshots):
                current_step_id = f"baseline_{i + 1}"
                snap = await capture_snapshot(
                    client,
                    vin,
                    between_reads_delay=args.between_reads,
                    include_vehicles=args.include_vehicles,
                )
                baseline.append(snap)
                (run_dir / f"baseline_{i + 1}.json").write_text(
                    to_pretty_json(redact(snap, redaction_cfg)), encoding="utf-8"
                )
                if i < args.baseline_snapshots - 1:
                    await asyncio.sleep(args.baseline_delay)
            current_step_id = None

        ignore_parsed = _ignored_paths_for_snapshot(baseline[0], section="parsed") if baseline else {}
        ignore_raw = _ignored_paths_for_snapshot(baseline[0], section="raw") if baseline else {}

        # Steps
        steps = default_steps()
        print(_section("Test steps"))
        print(f"Steps queued: {len(steps)}")
        print("You can abort at any time with Ctrl+C.\n")

        report_path = run_dir / "report.md"
        with report_path.open("a", encoding="utf-8") as rep:
            rep.write("\n## Steps\n")

        for step in steps:
            current_step_id = step.step_id
            step_dir = steps_dir / f"{step.step_id}_{_slug(step.title)}"
            step_dir.mkdir(parents=True, exist_ok=True)
            (step_dir / "instructions.txt").write_text(step.instructions + "\n", encoding="utf-8")

            print(_section(f"{step.step_id} - {step.title}"))
            print(step.instructions)
            print("")

            before = await capture_snapshot(
                client,
                vin,
                between_reads_delay=args.between_reads,
                include_vehicles=args.include_vehicles,
            )
            (step_dir / "before.json").write_text(to_pretty_json(redact(before, redaction_cfg)), encoding="utf-8")

            await _ainput("Action complete? Press Enter to continue...")
            if args.settle > 0:
                await asyncio.sleep(args.settle)

            after = await capture_snapshot(
                client,
                vin,
                between_reads_delay=args.between_reads,
                include_vehicles=args.include_vehicles,
            )
            (step_dir / "after.json").write_text(to_pretty_json(redact(after, redaction_cfg)), encoding="utf-8")

            diffs = diff_snapshots(
                before,
                after,
                ignore_by_endpoint_parsed=ignore_parsed,
                ignore_by_endpoint_raw=ignore_raw,
            )
            (step_dir / "diff.json").write_text(to_pretty_json(redact(diffs, redaction_cfg)), encoding="utf-8")

            # Step MQTT window capture
            step_mqtt = [e for e in mqtt_events if e.get("step_id") == step.step_id]
            (step_dir / "mqtt.json").write_text(to_pretty_json(redact(step_mqtt, redaction_cfg)), encoding="utf-8")

            # Evidence aggregation
            by_endpoint = diffs.get("by_endpoint", {})
            if isinstance(by_endpoint, dict):
                for endpoint, payload in by_endpoint.items():
                    if not isinstance(payload, dict):
                        continue
                    parsed = payload.get("parsed", {})
                    raw = payload.get("raw", {})
                    if isinstance(parsed, dict):
                        evidence.add_diff(
                            step_id=step.step_id,
                            step_title=step.title,
                            endpoint=str(endpoint),
                            section="parsed",
                            diffs={
                                k: (v.get("before"), v.get("after")) for k, v in parsed.items() if isinstance(v, dict)
                            },
                        )
                    if isinstance(raw, dict):
                        evidence.add_diff(
                            step_id=step.step_id,
                            step_title=step.title,
                            endpoint=str(endpoint),
                            section="raw",
                            diffs={k: (v.get("before"), v.get("after")) for k, v in raw.items() if isinstance(v, dict)},
                        )

            # Append to report
            with report_path.open("a", encoding="utf-8") as rep:
                rep.write(f"\n### {step.step_id} - {step.title}\n\n")
                rep.write("**Instructions**\n\n")
                rep.write(step.instructions.replace("\n", "  \n") + "\n\n")
                rep.write("**Diff counts**\n\n")
                rep.write("| Endpoint | Parsed changes | Raw changes |\n")
                rep.write("|---|---:|---:|\n")
                for endpoint, payload in sorted((by_endpoint or {}).items()):
                    if not isinstance(payload, dict):
                        continue
                    counts = payload.get("counts", {})
                    pc = counts.get("parsed", 0) if isinstance(counts, dict) else 0
                    rc = counts.get("raw", 0) if isinstance(counts, dict) else 0
                    rep.write(f"| {endpoint} | {pc} | {rc} |\n")
                rep.write("\n")
                rep.write(f"Artifacts: {step_dir.relative_to(run_dir)}\n")

        current_step_id = None

    # Persist full MQTT event log
    (run_dir / "mqtt_all.json").write_text(
        to_pretty_json(redact(mqtt_events, redaction_cfg)),
        encoding="utf-8",
    )

    # Evidence outputs
    (run_dir / "field_index.json").write_text(
        to_pretty_json(redact(evidence.to_field_index(), redaction_cfg)),
        encoding="utf-8",
    )
    with (run_dir / "report.md").open("a", encoding="utf-8") as rep:
        rep.write("\n\n")
        rep.write(evidence.to_markdown_summary())
        rep.write("\n")

    # Run summary
    summary = {
        "finished": utc_now_iso(),
        "run_dir": str(run_dir),
        "steps": len(default_steps()),
        "mqtt_events": len(mqtt_events),
    }
    (run_dir / "run_summary.json").write_text(to_pretty_json(redact(summary, redaction_cfg)), encoding="utf-8")

    print(_section("Run complete"))
    print(f"Report: {run_dir / 'report.md'}")
    print(f"Data  : {run_dir}")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nAborted.")


if __name__ == "__main__":
    main()
