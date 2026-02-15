# Client API Reference

## Quick start

```python
from pybyd import BydClient, BydConfig

config = BydConfig.from_env()  # reads BYD_USERNAME, BYD_PASSWORD, ...

async with BydClient(config) as client:
    await client.login()
    vehicles = await client.get_vehicles()
    realtime = await client.get_vehicle_realtime(vehicles[0].vin)
```

## BydClient

### Lifecycle

| Method | Description |
|--------|-------------|
| `async with BydClient(config) as client:` | Initialize transport, codec, HTTP session |
| `await client.login()` | Authenticate and start MQTT listener |
| `await client.ensure_session()` | Re-authenticate if session expired |
| `client.invalidate_session()` | Force next call to re-authenticate |

### Read endpoints

| Method | Returns | Description |
|--------|---------|-------------|
| `get_vehicles()` | `list[Vehicle]` | All vehicles on the account |
| `get_vehicle_realtime(vin)` | `VehicleRealtimeData` | Trigger + poll realtime telemetry |
| `get_gps_info(vin)` | `GpsInfo` | Trigger + poll GPS location |
| `get_hvac_status(vin)` | `HvacStatus` | Climate / HVAC status |
| `get_charging_status(vin)` | `ChargingStatus` | Charging status |
| `get_energy_consumption(vin)` | `EnergyConsumption` | Energy consumption data |
| `get_push_state(vin)` | `PushNotificationState` | Push notification state |
| `set_push_state(vin, enable=)` | `CommandAck` | Toggle push notifications |

Polling endpoints (`get_vehicle_realtime`, `get_gps_info`) accept optional `poll_attempts` (default 10) and `poll_interval` (default 1.5s).

### Control commands

All control commands require a control PIN (configured via `config.control_pin` or passed as `command_pwd`).

| Method | Parameters | Returns |
|--------|-----------|---------|
| `lock(vin)` | — | `RemoteControlResult` |
| `unlock(vin)` | — | `RemoteControlResult` |
| `start_climate(vin, params=)` | `ClimateStartParams` | `RemoteControlResult` |
| `stop_climate(vin)` | — | `RemoteControlResult` |
| `flash_lights(vin)` | — | `RemoteControlResult` |
| `close_windows(vin)` | — | `RemoteControlResult` |
| `find_car(vin)` | — | `RemoteControlResult` |
| `schedule_climate(vin, params=)` | `ClimateScheduleParams` | `RemoteControlResult` |
| `set_seat_climate(vin, params=)` | `SeatClimateParams` | `RemoteControlResult` |
| `set_battery_heat(vin, params=)` | `BatteryHeatParams` | `RemoteControlResult` |
| `verify_control_password(vin)` | — | `VerifyControlPasswordResponse` |

### Settings commands

| Method | Parameters | Returns |
|--------|-----------|---------|
| `save_charging_schedule(vin, schedule)` | `SmartChargingSchedule` | `CommandAck` |
| `toggle_smart_charging(vin, enable=)` | `bool` | `CommandAck` |
| `rename_vehicle(vin, name=)` | `str` | `CommandAck` |

## Configuration

```python
config = BydConfig(
    username="user@example.com",
    password="password",
    control_pin="123456",          # 6-digit PIN from BYD app
    mqtt_enabled=True,             # MQTT for fast command results
    mqtt_timeout=10.0,             # seconds before HTTP poll fallback
    session_ttl=43200,             # 12 hours
)
```

Or from environment variables:

```python
config = BydConfig.from_env()
```

Environment variables: `BYD_USERNAME`, `BYD_PASSWORD`, `BYD_CONTROL_PIN`, `BYD_MQTT_ENABLED`, `BYD_MQTT_TIMEOUT`, `BYD_SESSION_TTL`, etc.

## Control parameter models

### ClimateStartParams

```python
from pybyd import ClimateStartParams

params = ClimateStartParams(
    temperature=240,          # BYD unit (÷10 = 24.0°C)
    copilot_temperature=240,
    time_span=30,             # minutes (clamped to 1–60)
)
```

### SeatClimateParams

```python
from pybyd import SeatClimateParams

params = SeatClimateParams(
    main_heat=3,              # 0=off, 1–3=level
    copilot_ventilation=2,
)
```

### BatteryHeatParams

```python
from pybyd import BatteryHeatParams

params = BatteryHeatParams(on=True)
```

### ClimateScheduleParams

```python
from pybyd import ClimateScheduleParams

params = ClimateScheduleParams(
    booking_id=1,
    booking_time=1800,  # epoch seconds or BYD booking time
)
```

## Error handling

All errors inherit from `BydError`:

- `BydSessionExpiredError` — auto-handled by `_call_with_reauth`
- `BydApiError` — general API error with `code` and `endpoint`
- `BydControlPasswordError` — wrong PIN
- `BydRemoteControlError` — command failed (controlState=2)
- `BydRateLimitError` — server rate limiting (code 6024)
- `BydEndpointNotSupportedError` — endpoint not available for vehicle
