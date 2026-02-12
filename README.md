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

## Requirements

- Python 3.11+
- aiohttp
- cryptography

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

On successful command completion, pyBYD applies an optimistic update to
cached command-related fields (for example lock/window/climate/seat/battery-heat
state). This allows integrations to reflect the desired target state
immediately while waiting for the next backend telemetry refresh.

If `control_pin` is configured, the client verifies it once via
`/vehicle/vehicleswitch/verifyControlPassword` during initialization
(`get_vehicles`). If verification fails, remote commands are disabled
for that client instance to avoid hammering the API.

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

## Credits

- [Niek/BYD-re](https://github.com/Niek/BYD-re) -- initial reverse
  engineering of the BYD app HTTP crypto path, Bangcle envelope codec,
  and Node.js reference client.
- [TA2k/ioBroker.byd](https://github.com/TA2k/ioBroker.byd) -- ioBroker
  adapter that provided additional endpoint definitions (energy
  consumption, remote control).

## License

MIT
