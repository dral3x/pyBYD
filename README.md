# pybyd

Async Python client for the BYD vehicle API. Provides typed access to
vehicle telemetry, GPS location, energy consumption, and remote control
commands (lock, unlock, climate, horn, flash).

Built on top of the protocol research from
[Niek/BYD-re](https://github.com/Niek/BYD-re) and the endpoint
definitions found in [TA2k/ioBroker.byd](https://github.com/TA2k/ioBroker.byd).

**Status:** Alpha. The API surface may change before 1.0.

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

## Test client

A standalone script exercises all endpoints and prints the results:

```bash
export BYD_USERNAME="you@example.com"
export BYD_PASSWORD="your-password"
python scripts/test_client.py
python scripts/test_client.py --skip-control   # skip remote commands
python scripts/test_client.py --vin LNBX...    # specific vehicle
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
