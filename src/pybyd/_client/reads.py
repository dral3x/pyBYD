"""Internal read operations for :class:`pybyd.client.BydClient`.

These functions keep `client.py` small without changing the public API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pybyd._api.charging import fetch_charging_status
from pybyd._api.energy import fetch_energy_consumption
from pybyd._api.gps import poll_gps_info
from pybyd._api.hvac import fetch_hvac_status
from pybyd._api.push_notifications import get_push_state as get_push_state_api
from pybyd._api.push_notifications import set_push_state as set_push_state_api
from pybyd.exceptions import BydSessionExpiredError
from pybyd.ingestion.apply import apply_model_to_store
from pybyd.ingestion.normalize import prune_patch
from pybyd.ingestion.realtime import poll_vehicle_realtime
from pybyd.ingestion.vehicles import fetch_vehicles
from pybyd.models.charging import ChargingStatus
from pybyd.models.command_responses import CommandAck
from pybyd.models.energy import EnergyConsumption
from pybyd.models.gps import GpsInfo
from pybyd.models.hvac import HvacStatus
from pybyd.models.push_notification import PushNotificationState
from pybyd.models.realtime import VehicleRealtimeData
from pybyd.models.requests import GpsInfoRequest, SetPushStateRequest, VehicleRealtimeRequest
from pybyd.models.vehicle import Vehicle
from pybyd.state.events import IngestionEvent, IngestionSource, StateSection

if TYPE_CHECKING:
    from pybyd.client import BydClient


async def get_vehicles(client: BydClient) -> list[Vehicle]:
    async def _fetch() -> list[Vehicle]:
        session = await client.ensure_session()
        transport = client._require_transport()
        return await fetch_vehicles(client._config, session, transport)

    vehicles: list[Vehicle] = await client._call_with_reauth(_fetch)
    for vehicle in vehicles:
        if vehicle.vin:
            raw = vehicle.raw if isinstance(vehicle.raw, dict) else {}
            apply_model_to_store(
                client.store.apply,
                vin=vehicle.vin,
                section=StateSection.VEHICLE,
                source=IngestionSource.HTTP,
                model=vehicle,
                raw=raw,
                timestamp_data=raw,
            )
    return vehicles


async def get_vehicle_realtime(
    client: BydClient,
    *,
    vin: str,
    poll_attempts: int = 10,
    poll_interval: float = 1.5,
    stale_after: float | None = None,
) -> VehicleRealtimeData:
    request = VehicleRealtimeRequest(
        vin=vin,
        poll_attempts=poll_attempts,
        poll_interval=poll_interval,
        stale_after=stale_after,
    )

    def _apply_http_snapshot(model: VehicleRealtimeData, raw: dict[str, Any]) -> None:
        apply_model_to_store(
            client.store.apply,
            vin=request.vin,
            section=StateSection.REALTIME,
            source=IngestionSource.HTTP,
            model=model,
            raw=raw,
        )

    async def _fetch() -> VehicleRealtimeData:
        session = await client.ensure_session()
        transport = client._require_transport()
        coordinator = client._mqtt

        return await poll_vehicle_realtime(
            config=client._config,
            session=session,
            transport=transport,
            vin=request.vin,
            poll_attempts=request.poll_attempts,
            poll_interval=request.poll_interval,
            mqtt_pre_waiter=coordinator.wait_for_realtime if coordinator else None,
            mqtt_pre_wait_seconds=5.0,
            mqtt_last_raw_getter=coordinator.last_realtime_raw if coordinator else None,
            on_http_snapshot=_apply_http_snapshot,
        )

    model: VehicleRealtimeData = await client._call_with_reauth(_fetch)

    # Final store apply for the returned model (idempotent).
    apply_model_to_store(
        client.store.apply,
        vin=request.vin,
        section=StateSection.REALTIME,
        source=IngestionSource.HTTP,
        model=model,
        raw=model.raw if isinstance(model.raw, dict) else {},
    )
    return model


async def get_gps_info(
    client: BydClient,
    *,
    vin: str,
    poll_attempts: int = 10,
    poll_interval: float = 1.5,
) -> GpsInfo:
    request = GpsInfoRequest(vin=vin, poll_attempts=poll_attempts, poll_interval=poll_interval)

    async def _fetch() -> GpsInfo:
        session = await client.ensure_session()
        transport = client._require_transport()
        return await poll_gps_info(
            client._config,
            session,
            transport,
            request.vin,
            poll_attempts=request.poll_attempts,
            poll_interval=request.poll_interval,
        )

    model: GpsInfo = await client._call_with_reauth(_fetch)
    apply_model_to_store(
        client.store.apply,
        vin=request.vin,
        section=StateSection.GPS,
        source=IngestionSource.HTTP,
        model=model,
        raw=model.raw if isinstance(model.raw, dict) else {},
    )
    return model


async def get_hvac_status(client: BydClient, *, vin: str) -> HvacStatus:
    async def _fetch() -> HvacStatus:
        session = await client.ensure_session()
        transport = client._require_transport()
        return await fetch_hvac_status(client._config, session, transport, vin)

    model: HvacStatus = await client._call_with_reauth(_fetch)
    raw = model.raw if isinstance(model.raw, dict) else {}
    apply_model_to_store(
        client.store.apply,
        vin=vin,
        section=StateSection.HVAC,
        source=IngestionSource.HTTP,
        model=model,
        raw=raw,
        timestamp_data=raw,
    )
    return model


async def get_charging_status(client: BydClient, *, vin: str) -> ChargingStatus:
    async def _fetch() -> ChargingStatus:
        session = await client.ensure_session()
        transport = client._require_transport()
        return await fetch_charging_status(client._config, session, transport, vin)

    model: ChargingStatus = await client._call_with_reauth(_fetch)
    apply_model_to_store(
        client.store.apply,
        vin=vin,
        section=StateSection.CHARGING,
        source=IngestionSource.HTTP,
        model=model,
        raw=model.raw if isinstance(model.raw, dict) else {},
    )
    return model


async def get_energy_consumption(client: BydClient, *, vin: str) -> EnergyConsumption:
    async def _fetch() -> EnergyConsumption:
        session = await client.ensure_session()
        transport = client._require_transport()
        return await fetch_energy_consumption(client._config, session, transport, vin)

    model: EnergyConsumption = await client._call_with_reauth(_fetch)
    raw = model.raw if isinstance(model.raw, dict) else {}
    apply_model_to_store(
        client.store.apply,
        vin=vin,
        section=StateSection.ENERGY,
        source=IngestionSource.HTTP,
        model=model,
        raw=raw,
        timestamp_data=raw,
    )
    return model


async def get_push_state(client: BydClient, *, vin: str) -> PushNotificationState:
    async def _fetch() -> PushNotificationState:
        session = await client.ensure_session()
        transport = client._require_transport()
        return await get_push_state_api(client._config, session, transport, vin)

    model: PushNotificationState = await client._call_with_reauth(_fetch)
    normalized = prune_patch(model.model_dump(exclude={"raw"}))
    client.store.apply(
        IngestionEvent(
            vin=vin,
            section=StateSection.VEHICLE,
            source=IngestionSource.HTTP,
            payload_timestamp=None,
            data={"push_state": normalized},
            raw=model.raw if isinstance(model.raw, dict) else {},
        )
    )
    return model


async def set_push_state(client: BydClient, *, vin: str, enable: bool) -> CommandAck:
    request = SetPushStateRequest(vin=vin, enable=enable)

    async def _call() -> CommandAck:
        session = await client.ensure_session()
        transport = client._require_transport()
        return await set_push_state_api(client._config, session, transport, request.vin, enable=request.enable)

    try:
        return await client._call_with_reauth(_call)
    except BydSessionExpiredError:
        # Should be handled by _call_with_reauth, but keep this as an explicit safety net.
        raise
