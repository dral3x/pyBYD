# Architecture

pyBYD is a thin async Python client for the BYD vehicle API.

## Two layers

1. **API** (`_api/`) — stateless endpoint functions.
   Each module owns one BYD endpoint group: `realtime`, `gps`, `hvac`,
   `charging`, `energy`, `push_notifications`, `smart_charging`,
   `vehicle_settings`, `control`, `login`.
   Functions accept `(config, session, transport, vin, ...)` and return
   a typed Pydantic model or raise.

2. **Client** (`client.py`) — thin async façade.
   `BydClient` manages lifecycle (aiohttp session, Bangcle codec,
   MQTT runtime) and delegates to the API layer.  It handles
   re-authentication on session expiry and optional MQTT command
   result waiting.

## Data flow

```
BydClient method
  → ensure_session() (re-auth if expired)
  → _api module function
      → SecureTransport.post_secure() (Bangcle encrypt → HTTP POST → decrypt)
      → Pydantic model_validate() on decrypted JSON
  ← typed model returned to caller
```

For commands, an MQTT fast-path is attempted first:

```
_remote_control()
  → _api.control.poll_remote_control()
      → trigger POST /control/remoteControl
      → mqtt_result_waiter (asyncio.Future with timeout)
      → fallback: poll POST /control/remoteControlResult
  ← RemoteControlResult
```

## Crypto

All HTTP payloads are double-encrypted:

- **Outer**: Bangcle white-box AES (proprietary S-box tables)
- **Inner**: AES-128-CBC with a per-request content key
- **Signing**: MD5/SHA1 based request signing

The `_crypto/` package is self-contained and not exposed publicly.

## Models

All models are frozen Pydantic v2 `BydBaseModel` subclasses (from
`models/_base.py`) with `extra="ignore"`, `populate_by_name=True`,
and `alias_generator=to_camel`.  BYD sentinel values (`""`, `"--"`,
NaN) are cleaned in the base model's `_clean_byd_values` validator.
State enums inherit from `BydEnum` which adds `UNKNOWN = -1` and a
`_missing_` hook so unmapped values fall back to `UNKNOWN`.

## Key files

| Path | Purpose |
|------|---------|
| `client.py` | Public async client |
| `_api/` | Stateless endpoint modules |
| `_transport.py` | Bangcle-wrapped HTTP POST |
| `_mqtt.py` | MQTT runtime + bootstrap |
| `_crypto/` | Bangcle AES, AES-CBC, hashing, signing |
| `models/_base.py` | `BydBaseModel` + `BydEnum` base classes |
| `models/` | Pydantic response models |
| `config.py` | Client configuration |
| `session.py` | Session token holder |
| `exceptions.py` | Exception hierarchy |
