"""Internal MQTT bootstrap, parsing, and runtime helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import paho.mqtt.client as mqtt

from pybyd._api._envelope import build_token_outer_envelope
from pybyd._crypto.aes import aes_decrypt_utf8
from pybyd._crypto.hashing import md5_hex
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError, BydError
from pybyd.session import Session


@dataclass(frozen=True)
class MqttBootstrap:
    """Broker/session data required to connect to BYD MQTT."""

    user_id: str
    broker_host: str
    broker_port: int
    topic: str
    client_id: str
    username: str
    password: str


@dataclass(frozen=True)
class MqttEvent:
    """Normalized decrypted MQTT event envelope."""

    event: str
    vin: str | None
    topic: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class MqttPayloadLayers:
    """MQTT payload representation across encryption/decode layers."""

    raw_bytes: bytes
    raw_ascii: str
    plaintext: str
    parsed: dict[str, Any]


def _parse_broker(raw_broker: str) -> tuple[str, int]:
    value = raw_broker.strip()
    if not value:
        raise ValueError("Broker value is empty")

    if "://" in value:
        value = value.split("://", 1)[1]
    if "/" in value:
        value = value.split("/", 1)[0]

    host, _, maybe_port = value.rpartition(":")
    if host and maybe_port.isdigit():
        return host, int(maybe_port)
    return value, 8883


def _build_client_id(config: BydConfig) -> str:
    imei_md5 = (config.device.imei_md5 or "").strip().upper()
    if imei_md5 and set(imei_md5) != {"0"}:
        return f"oversea_{imei_md5}"
    return f"oversea_{md5_hex(config.device.imei)}"


def _build_mqtt_password(session: Session, client_id: str, ts_seconds: int) -> str:
    ts_text = str(ts_seconds)
    base = f"{session.sign_token}{client_id}{session.user_id}{ts_text}"
    return f"{ts_text}{md5_hex(base)}"


async def _fetch_emq_broker(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
) -> str:
    now_ms = int(time.time() * 1000)
    inner: dict[str, str] = {
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
    }
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)
    response = await transport.post_secure("/app/emqAuth/getEmqBrokerIp", outer)

    code = str(response.get("code", ""))
    if code != "0":
        raise BydApiError(
            f"Broker lookup failed: code={code} message={response.get('message', '')}",
            code=code,
            endpoint="/app/emqAuth/getEmqBrokerIp",
        )

    respond_data = response.get("respondData")
    if not isinstance(respond_data, str) or not respond_data:
        raise BydError("Broker lookup response missing respondData")

    decoded = json.loads(aes_decrypt_utf8(respond_data, content_key))
    if not isinstance(decoded, dict):
        raise BydError("Broker lookup response inner payload is not an object")

    broker = decoded.get("emqBorker") or decoded.get("emqBroker")
    if not isinstance(broker, str) or not broker.strip():
        raise BydError("Broker lookup response missing emqBorker/emqBroker")
    return broker.strip()


async def fetch_mqtt_bootstrap(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
) -> MqttBootstrap:
    """Build MQTT connection details from current authenticated session."""
    broker = await _fetch_emq_broker(config, session, transport)
    broker_host, broker_port = _parse_broker(broker)
    client_id = _build_client_id(config)
    now_seconds = int(time.time())
    return MqttBootstrap(
        user_id=session.user_id,
        broker_host=broker_host,
        broker_port=broker_port,
        topic=f"oversea/res/{session.user_id}",
        client_id=client_id,
        username=session.user_id,
        password=_build_mqtt_password(session, client_id, now_seconds),
    )


def decode_mqtt_payload_layers(payload: bytes, decrypt_key_hex: str) -> MqttPayloadLayers:
    """Decode MQTT payload into raw, plaintext, and parsed layers."""
    raw_text = payload.decode("ascii", errors="replace").strip()
    plain = aes_decrypt_utf8(raw_text, decrypt_key_hex)
    parsed = json.loads(plain)
    if not isinstance(parsed, dict):
        raise BydError("MQTT payload decrypted to non-object JSON")
    return MqttPayloadLayers(
        raw_bytes=payload,
        raw_ascii=raw_text,
        plaintext=plain,
        parsed=parsed,
    )


def decode_mqtt_payload(payload: bytes, decrypt_key_hex: str) -> dict[str, Any]:
    """Decrypt and parse MQTT payload bytes into a JSON object."""
    return decode_mqtt_payload_layers(payload, decrypt_key_hex).parsed


class BydMqttRuntime:
    """Threaded paho-mqtt runtime that emits parsed events onto an asyncio loop."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        decrypt_key_hex: str,
        on_event: Callable[[MqttEvent], None],
        keepalive: int = 120,
        logger: logging.Logger | None = None,
    ) -> None:
        self._loop = loop
        self._decrypt_key_hex = decrypt_key_hex
        self._on_event = on_event
        self._keepalive = keepalive
        self._logger = logger or logging.getLogger(__name__)
        self._client: mqtt.Client | None = None
        self._running = False
        self._topic: str | None = None

    @property
    def is_running(self) -> bool:
        """Whether the MQTT runtime is actively running."""
        return self._running

    def start(self, bootstrap: MqttBootstrap) -> None:
        """Connect and subscribe with provided broker details."""
        self.stop()
        self._logger.debug(
            "MQTT runtime start requested host=%s port=%s topic=%s client_id=%s",
            bootstrap.broker_host,
            bootstrap.broker_port,
            bootstrap.topic,
            bootstrap.client_id,
        )

        client = mqtt.Client(
            callback_api_version=cast(Any, mqtt).CallbackAPIVersion.VERSION2,
            client_id=bootstrap.client_id,
            protocol=mqtt.MQTTv5,
        )
        client.enable_logger(self._logger)
        client.username_pw_set(bootstrap.username, bootstrap.password)
        client.tls_set()

        self._topic = bootstrap.topic

        def on_connect(
            c: mqtt.Client,
            _userdata: Any,
            _flags: Any,
            reason_code: Any,
            _properties: Any,
        ) -> None:
            if reason_code.value != 0:
                self._logger.warning("MQTT connect failed: %s", reason_code)
                return
            self._logger.debug("MQTT connected successfully reason=%s", reason_code)
            if self._topic:
                self._logger.debug("MQTT subscribing topic=%s", self._topic)
                c.subscribe(self._topic, qos=0)

        def on_message(_c: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
            try:
                layers = decode_mqtt_payload_layers(msg.payload, self._decrypt_key_hex)
                self._logger.debug(
                    "Received PUBLISH topic=%s parsed=%s",
                    msg.topic,
                    layers.parsed,
                )

                event_name = str(layers.parsed.get("event") or "")
                vin_value = layers.parsed.get("vin")
                vin = vin_value if isinstance(vin_value, str) and vin_value else None
                self._logger.debug("MQTT payload decrypted event=%s vin=%s", event_name, vin)
                event = MqttEvent(
                    event=event_name,
                    vin=vin,
                    topic=msg.topic,
                    payload=layers.parsed,
                )
                self._loop.call_soon_threadsafe(self._on_event, event)
            except Exception:
                self._logger.debug("MQTT payload parse failure", exc_info=True)

        def on_disconnect(
            _client: mqtt.Client,
            _userdata: Any,
            _disconnect_flags: Any,
            reason_code: Any,
            _properties: Any,
        ) -> None:
            if self._running:
                self._logger.debug("MQTT disconnected: %s", reason_code)

        client.on_connect = on_connect
        client.on_message = on_message
        client.on_disconnect = on_disconnect

        client.connect(bootstrap.broker_host, bootstrap.broker_port, keepalive=self._keepalive)
        client.loop_start()

        self._client = client
        self._running = True
        self._logger.debug("MQTT network loop started")

    def stop(self) -> None:
        """Stop and disconnect current MQTT client if running."""
        client = self._client
        self._client = None
        was_running = self._running
        self._running = False
        self._topic = None

        if client is None:
            return
        try:
            if was_running:
                self._logger.debug("MQTT disconnect requested")
                client.disconnect()
        finally:
            client.loop_stop()
            self._logger.debug("MQTT network loop stopped")
