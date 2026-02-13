#!/usr/bin/env python3
"""Passive MQTT probe for BYD real-time payload observation.

This script reuses pyBYD login/session crypto to:
1) authenticate against BYD,
2) resolve MQTT broker via /app/emqAuth/getEmqBrokerIp,
3) subscribe to oversea/res/<userId>,
4) decrypt inbound payloads (AES-128-CBC, key=MD5(encryToken)).

Use this to verify whether messages are periodic or only reactive.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Allow running from repo root without installing the package.
_repo = Path(__file__).resolve().parent.parent
_src = _repo / "src"
if _src.is_dir():
    sys.path.insert(0, str(_src))


def _maybe_reexec_with_project_venv() -> None:
    candidate_env = (_repo / ".venv").resolve()
    candidate_python = candidate_env / "bin" / "python"
    if not candidate_python.exists():
        return

    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == candidate_env:
        return
    if os.environ.get("PYBYD_MQTT_PROBE_REEXEC") == "1":
        return

    env = dict(os.environ)
    env["PYBYD_MQTT_PROBE_REEXEC"] = "1"
    os.execve(str(candidate_python), [str(candidate_python), *sys.argv], env)


_maybe_reexec_with_project_venv()

from pybyd import BydClient, BydConfig  # noqa: E402
from pybyd._mqtt import decode_mqtt_payload  # noqa: E402

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:  # pragma: no cover - environment/setup issue
    raise SystemExit(
        "Missing dependency 'paho-mqtt'. Install with: pip install paho-mqtt",
    ) from exc

_LOG = logging.getLogger("mqtt_probe")


@dataclass(frozen=True)
class ProbeBootstrap:
    user_id: str
    broker_host: str
    broker_port: int
    topic: str
    client_id: str
    username: str
    password: str
    decrypt_key_hex: str


@dataclass
class ProbeStats:
    started_at: float
    total_messages: int = 0
    decrypt_ok: int = 0
    decrypt_failed: int = 0
    first_message_at: float | None = None
    last_message_at: float | None = None
    last_idle_report_at: float | None = None

    def on_message(self, now: float) -> float | None:
        previous = self.last_message_at
        self.total_messages += 1
        if self.first_message_at is None:
            self.first_message_at = now
        self.last_message_at = now
        return None if previous is None else now - previous


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Passive MQTT probe for BYD realtime topic.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="Maximum runtime in seconds (0 = run until Ctrl+C).",
    )
    parser.add_argument(
        "--idle-report-seconds",
        type=int,
        default=60,
        help="Print idle notice each N seconds without messages.",
    )
    parser.add_argument(
        "--keepalive",
        type=int,
        default=120,
        help="MQTT keepalive in seconds.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print raw MQTT payload (ASCII hex).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Pretty-print decrypted JSON payload.",
    )
    parser.add_argument(
        "--no-decrypt",
        action="store_true",
        help="Disable payload decryption and print metadata only.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logs.",
    )
    return parser.parse_args()


async def _bootstrap(config: BydConfig) -> ProbeBootstrap:
    async with BydClient(config) as client:
        await client.login()
        session = await client.ensure_session()
        mqtt_bootstrap = await client.get_mqtt_bootstrap()

        return ProbeBootstrap(
            user_id=mqtt_bootstrap.user_id,
            broker_host=mqtt_bootstrap.broker_host,
            broker_port=mqtt_bootstrap.broker_port,
            topic=mqtt_bootstrap.topic,
            client_id=mqtt_bootstrap.client_id,
            username=mqtt_bootstrap.username,
            password=mqtt_bootstrap.password,
            decrypt_key_hex=session.content_key,
        )


def _print_bootstrap(data: ProbeBootstrap) -> None:
    print("[probe] MQTT bootstrap")
    print(f"[probe]   broker   : {data.broker_host}:{data.broker_port}")
    print(f"[probe]   topic    : {data.topic}")
    print(f"[probe]   clientId : {data.client_id}")
    print(f"[probe]   username : {data.username}")


def _print_summary(stats: ProbeStats) -> None:
    runtime = time.time() - stats.started_at
    print("[probe] Summary")
    print(f"[probe]   runtime_s      : {runtime:.1f}")
    print(f"[probe]   total_messages : {stats.total_messages}")
    print(f"[probe]   decrypt_ok     : {stats.decrypt_ok}")
    print(f"[probe]   decrypt_failed : {stats.decrypt_failed}")
    if stats.first_message_at is not None:
        first_message = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stats.first_message_at))
        print(f"[probe]   first_message  : {first_message}")
    if stats.last_message_at is not None:
        last_message = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stats.last_message_at))
        print(f"[probe]   last_message   : {last_message}")


def _main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config = BydConfig.from_env()
    try:
        bootstrap = asyncio.run(_bootstrap(config))
    except Exception as exc:  # pragma: no cover - network/system interaction
        print(f"[probe] Bootstrap failed: {exc}", file=sys.stderr)
        return 2

    _print_bootstrap(bootstrap)

    stats = ProbeStats(started_at=time.time())
    should_stop = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal should_stop
        should_stop = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    mqtt_client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=bootstrap.client_id,
        protocol=mqtt.MQTTv5,
    )
    mqtt_client.enable_logger(_LOG)
    mqtt_client.username_pw_set(bootstrap.username, bootstrap.password)
    mqtt_client.tls_set()

    def on_connect(
        client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.value != 0:
            print(f"[probe] MQTT connect failed: {reason_code}", file=sys.stderr)
            client.disconnect()
            return
        print(f"[probe] Connected. Subscribing to {bootstrap.topic}")
        client.subscribe(bootstrap.topic, qos=0)

    def on_disconnect(
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if not should_stop:
            print(f"[probe] Disconnected: {reason_code}")

    def on_message(_client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        now = time.time()
        delta = stats.on_message(now)
        ts_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        gap_text = "first" if delta is None else f"{delta:.1f}s"

        raw_text = msg.payload.decode("ascii", errors="replace").strip()
        print(
            f"[probe] msg#{stats.total_messages} at {ts_text} gap={gap_text} "
            f"topic={msg.topic} bytes={len(msg.payload)} hexchars={len(raw_text)}",
        )

        if args.raw:
            print(f"[probe] raw={raw_text}")

        if args.no_decrypt:
            return

        try:
            parsed_payload = decode_mqtt_payload(msg.payload, bootstrap.decrypt_key_hex)
            stats.decrypt_ok += 1
            if args.json:
                print(json.dumps(parsed_payload, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(json.dumps(parsed_payload, ensure_ascii=False, sort_keys=True))
        except Exception as exc:  # pragma: no cover - depends on live payloads
            stats.decrypt_failed += 1
            print(f"[probe] decrypt_failed: {exc}")

    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message

    print("[probe] Connecting...")
    try:
        mqtt_client.connect(bootstrap.broker_host, bootstrap.broker_port, keepalive=args.keepalive)
        mqtt_client.loop_start()

        while not should_stop:
            now = time.time()

            if args.duration > 0 and (now - stats.started_at) >= args.duration:
                print(f"[probe] Reached --duration={args.duration}s, stopping.")
                break

            if args.idle_report_seconds > 0:
                last_activity = stats.last_message_at or stats.started_at
                idle_seconds = now - last_activity
                last_report = stats.last_idle_report_at or stats.started_at
                should_report = (
                    idle_seconds >= args.idle_report_seconds and (now - last_report) >= args.idle_report_seconds
                )
                if should_report:
                    print(f"[probe] idle_for={idle_seconds:.1f}s without inbound messages")
                    stats.last_idle_report_at = now

            time.sleep(1.0)

    except KeyboardInterrupt:
        pass
    finally:
        should_stop = True
        try:
            mqtt_client.disconnect()
        finally:
            mqtt_client.loop_stop()

    _print_summary(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
