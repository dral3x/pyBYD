# Architecture

pyBYD is a fully async Python client for the BYD vehicle API.

The library is structured as three layers:

1. **Ingestion** (how data enters)
   - **REST**: Signed/encrypted POST requests via `SecureTransport`.
   - **MQTT**: Background listener decrypts events and emits normalized updates.
   - **Push (future)**: Intended to feed the same update pipeline once implemented.

2. **State / Data layer** (single source of truth)
   - `StateStore` is the only component allowed to merge updates.
   - It applies deterministic rules so the same input sequence yields the same state.
   - It supports temporary **optimistic overlays** for commands (cleared by server updates or expiry).

3. **Public API**
   - `BydClient` exposes typed methods like `get_vehicle_realtime()`, `get_gps_info()`, `lock()`.
   - Methods return typed models (Pydantic v2) and also enrich the `StateStore`.

## Data flow

- REST endpoint → decrypt/parse → typed model → normalized dict → `StateStore.apply(IngestionEvent)`
- MQTT message → decrypt/parse → typed model → normalized dict → `StateStore.apply(IngestionEvent)`

Consumers can either:

- call `BydClient` methods to fetch data/issue commands, or
- read the latest merged snapshots via `client.store.get_section(vin, section)`.

## Key files

- Public API: `src/pybyd/client.py`
- Ingestion primitives: `src/pybyd/ingestion/`
- State store + merge policy: `src/pybyd/state/`
- Transport/crypto: `src/pybyd/_transport.py`, `src/pybyd/_crypto/`
