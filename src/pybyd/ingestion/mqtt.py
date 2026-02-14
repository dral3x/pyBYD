"""MQTT ingestion helpers.

This module translates decrypted MQTT events into normalized state-store events.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pybyd.ingestion.apply import build_event_from_model
from pybyd.ingestion.normalize import extract_payload_timestamp, prune_patch
from pybyd.models.charging import ChargingStatus
from pybyd.models.energy import EnergyConsumption
from pybyd.models.hvac import HvacStatus
from pybyd.models.realtime import VehicleRealtimeData
from pybyd.state.events import IngestionEvent, IngestionSource, StateSection


class _MqttVehicleInfoEnvelope(BaseModel):
    """Minimal Pydantic envelope for MQTT `vehicleInfo` messages."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    data: _MqttVehicleInfoData = Field(...)


class _MqttVehicleInfoData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    respondData: dict[str, Any] = Field(...)


def _extract_respond_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        envelope = _MqttVehicleInfoEnvelope.model_validate(payload)
    except ValidationError:
        return None
    return envelope.data.respondData


def build_events_from_vehicle_info(
    *,
    vin: str,
    payload: dict[str, Any],
) -> tuple[list[IngestionEvent], dict[str, Any] | None]:
    """Build state-store events from a `vehicleInfo` MQTT payload.

    Returns a tuple of:
    - list of events to apply
    - the raw realtime dict (respondData), for use by MQTT-first HTTP short-circuiting
    """
    respond_data = _extract_respond_data(payload)
    if respond_data is None:
        return [], None

    events: list[IngestionEvent] = []

    # Realtime section (authoritative for most fields)
    realtime_model = VehicleRealtimeData.from_api(respond_data)
    events.append(
        build_event_from_model(
            vin=vin,
            section=StateSection.REALTIME,
            source=IngestionSource.MQTT,
            model=realtime_model,
            raw=respond_data,
        )
    )

    # Derived section projections (best-effort; only apply if we get meaningful keys)
    hvac = HvacStatus.model_validate(respond_data)
    hvac_patch = prune_patch(hvac.model_dump(exclude={"raw"}, exclude_none=True))
    if hvac_patch:
        events.append(
            IngestionEvent(
                vin=vin,
                section=StateSection.HVAC,
                source=IngestionSource.MQTT,
                # The HVAC model does not currently expose the payload `time` field,
                # so the normalized patch may not include a timestamp. Use raw respond_data.
                payload_timestamp=extract_payload_timestamp(StateSection.HVAC, respond_data),
                data=hvac_patch,
                raw=respond_data,
            )
        )

    charging = ChargingStatus.model_validate({"vin": vin, **respond_data})
    charging_patch = prune_patch(charging.model_dump(exclude={"raw"}, exclude_none=True))
    if charging_patch:
        # Charging model commonly includes updateTime derived fields; timestamp from patch.
        events.append(
            IngestionEvent(
                vin=vin,
                section=StateSection.CHARGING,
                source=IngestionSource.MQTT,
                payload_timestamp=extract_payload_timestamp(StateSection.CHARGING, charging_patch),
                data=charging_patch,
                raw=respond_data,
            )
        )

    energy = EnergyConsumption.model_validate({"vin": vin, **respond_data})
    energy_patch = prune_patch(energy.model_dump(exclude={"raw"}, exclude_none=True))
    if energy_patch:
        events.append(
            IngestionEvent(
                vin=vin,
                section=StateSection.ENERGY,
                source=IngestionSource.MQTT,
                # Energy model patch typically does not include a `time` field; use raw realtime respond_data.
                payload_timestamp=extract_payload_timestamp(StateSection.ENERGY, respond_data),
                data=energy_patch,
                raw=respond_data,
            )
        )

    return events, respond_data
