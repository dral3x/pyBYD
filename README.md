# pybyd

Async Python client for the BYD vehicle API. Provides typed access to
vehicle telemetry, GPS location, energy consumption, and remote control
commands (lock, unlock, climate, horn, flash).

Built on top of the protocol research from
[Niek/BYD-re](https://github.com/Niek/BYD-re) and the endpoint
definitions found in [TA2k/ioBroker.byd](https://github.com/TA2k/ioBroker.byd).

**Status:** Alpha. The API surface may change before 1.0.

## PLEASE READ FIRST!

We are still working out the kinks, especially mapping states and setting up parsing. See [API_MAPPING.md](https://github.com/jkaberg/pyBYD/blob/main/API_MAPPING.md) for the current state.

Any help around this is grately appreciated, use the [test client](https://github.com/jkaberg/pyBYD#dump-all-data) to fetch the car values and send an PR. 

Thanks!

## Feature highlights

- Polling support for live vehicle metrics (realtime, GPS, energy, charging, HVAC).
- Remote command support for lock/unlock, horn/lights, and climate actions.
- Built-in per-vehicle cache layer that merges partial responses, reducing load on BYD's servers
- MQTT-assisted updates that feeds in to the cache layer

## Requirements

- Python 3.11+
- aiohttp
- cryptography
- paho-mqtt

## Installation

```bash
pip install pybyd
```

Or install from source:

```bash
cd lib
pip install -e ".[dev]"
```

## Quick start

```python
import asyncio
from pybyd import BydClient, BydConfig

async def main():
    config = BydConfig(
        username="you@example.com",
        password="your-password",
        country_code="NL",
    )

    async with BydClient(config) as client:
        token = await client.login()
        vehicles = await client.get_vehicles()

        vin = vehicles[0].vin
        print(f"VIN: {vin}")

        realtime = await client.get_vehicle_realtime(vin)
        print(f"Battery: {realtime.elec_percent}%")
        print(f"Range: {realtime.endurance_mileage} km")

        gps = await client.get_gps_info(vin)
        print(f"Location: {gps.latitude}, {gps.longitude}")

asyncio.run(main())
```

## Available endpoints

| Method | Description |
|--------|-------------|
| `login()` | Authenticate and obtain session tokens |
| `get_vehicles()` | List all vehicles on the account |
| `get_vehicle_realtime(vin)` | Battery, range, speed, doors, tire pressure |
| `get_gps_info(vin)` | GPS latitude, longitude, speed, heading |
| `get_energy_consumption(vin)` | Energy and fuel consumption stats |
| `verify_control_password(vin)` | Verify remote control PIN/password for a VIN |
| `remote_control(vin, command)` | Send a remote command (see below) |
| `lock(vin)` | Lock doors |
| `unlock(vin)` | Unlock doors |
| `flash_lights(vin)` | Flash lights |
| `honk_horn(vin)` | Honk horn |
| `start_climate(vin)` | Start climate control |
| `stop_climate(vin)` | Stop climate control |

## Configuration

Credentials can be passed directly or read from environment variables:

```python
# From environment: BYD_USERNAME, BYD_PASSWORD, BYD_COUNTRY_CODE, ...
config = BydConfig.from_env()

# With overrides
config = BydConfig.from_env(country_code="DE", language="de")
```

All `BYD_*` environment variables listed in `BydConfig.from_env` are
supported for CI and container deployments.

## Remote control

```python
from pybyd import RemoteCommand

result = await client.remote_control(vin, RemoteCommand.LOCK)
print(result.success)  # True / False
```

Remote commands use a two-phase trigger-and-poll pattern. The poll
parameters are configurable:

```python
result = await client.lock(vin, poll_attempts=15, poll_interval=2.0)
```

When MQTT is enabled (default), pyBYD uses MQTT-first completion:

1. trigger command via HTTP,
2. wait briefly for MQTT `remoteControl` response,
3. fall back to HTTP polling if no MQTT result arrives.

This preserves reliability while reducing command-result latency when
MQTT is available.

On successful command completion, pyBYD applies an optimistic update to
cached command-related fields (for example lock/window/climate/seat/battery-heat
state). This allows integrations to reflect the desired target state
immediately while waiting for the next backend telemetry refresh.

MQTT `vehicleInfo` payloads are also merged into the internal cache and
propagated across realtime/HVAC/charging/energy snapshots, keeping read
methods as up to date as possible between explicit API polls.

MQTT-related configuration:

- `mqtt_enabled` / `BYD_MQTT_ENABLED` (default: enabled)
- `mqtt_keepalive` / `BYD_MQTT_KEEPALIVE` (default: 120)
- `mqtt_command_timeout` / `BYD_MQTT_COMMAND_TIMEOUT` (default: 8.0)

`verify_control_password(...)` is available as an explicit helper call,
but remote commands are sent directly with `commandPwd` and rely on API
responses for success/failure.

## Error handling

```python
from pybyd import BydAuthenticationError, BydApiError, BydRemoteControlError

try:
    await client.login()
except BydAuthenticationError as e:
    print(f"Login failed: {e}")

try:
    await client.lock(vin)
except BydRemoteControlError as e:
    print(f"Command failed: {e}")
except BydApiError as e:
    print(f"API error: {e.code} at {e.endpoint}")
```

## Development

```bash
cd lib
pip install -e ".[dev]"
pytest                    # run tests
ruff check .              # lint
mypy src/pybyd            # type check
```

## Dump all data

A standalone script fetches every read-only endpoint and prints both
the parsed model fields and the raw API JSON — useful for discovering
unparsed fields or contributing new model coverage:

```bash
export BYD_USERNAME="you@example.com"
export BYD_PASSWORD="your-password"
# Human-readable output
python scripts/dump_all.py

# Only a specific vehicle
python scripts/dump_all.py --vin LNBX...

# Machine-readable JSON
python scripts/dump_all.py --json

# Save JSON to a file
python scripts/dump_all.py --json -o dump.json

# Skip specific endpoints
python scripts/dump_all.py --skip-gps --skip-energy

# Debug logging
python scripts/dump_all.py -v
```

## MQTT probe (passive watch)

`scripts/mqtt_probe.py` connects to the app MQTT broker and subscribes to:

- `oversea/res/<userId>`

It reuses pyBYD login/session logic, resolves broker via
`/app/emqAuth/getEmqBrokerIp` using the same core MQTT helpers as the
library client, and decrypts payloads using
`MD5(encryToken)` + AES-128-CBC (zero IV).

```bash
export BYD_USERNAME="you@example.com"
export BYD_PASSWORD="your-password"

# Watch indefinitely (Ctrl+C to stop)
python scripts/mqtt_probe.py

# Watch for 10 minutes and pretty-print decrypted JSON
python scripts/mqtt_probe.py --duration 600 --json

# Print idle notices every 30s if no messages arrive
python scripts/mqtt_probe.py --idle-report-seconds 30

# Print raw payloads (ASCII hex) too
python scripts/mqtt_probe.py --raw
```

## Credits

- [Niek/BYD-re](https://github.com/Niek/BYD-re) -- initial reverse
  engineering of the BYD app HTTP crypto path, Bangcle envelope codec,
  and Node.js reference client.
- [TA2k/ioBroker.byd](https://github.com/TA2k/ioBroker.byd) -- ioBroker
  adapter that provided additional endpoint definitions (energy
  consumption, remote control).

## License

MIT
