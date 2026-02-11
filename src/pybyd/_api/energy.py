"""Energy consumption endpoint.

Endpoint:
  - /vehicleInfo/vehicle/getEnergyConsumption (single request)
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

from pybyd._api._envelope import build_token_outer_envelope
from pybyd._cache import VehicleDataCache
from pybyd._crypto.aes import aes_decrypt_utf8
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.exceptions import BydApiError
from pybyd.models.energy import EnergyConsumption
from pybyd.session import Session

_logger = logging.getLogger(__name__)

_ENDPOINT = "/vehicleInfo/vehicle/getEnergyConsumption"


def _safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None on failure."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
        if result != result:  # NaN check
            return None
        return result
    except (ValueError, TypeError):
        return None


def _build_energy_inner(
    config: BydConfig,
    vin: str,
    now_ms: int,
) -> dict[str, str]:
    """Build the inner payload for the energy consumption endpoint."""
    return {
        "deviceType": config.device.device_type,
        "imeiMD5": config.device.imei_md5,
        "networkType": config.device.network_type,
        "random": secrets.token_hex(16).upper(),
        "timeStamp": str(now_ms),
        "version": config.app_inner_version,
        "vin": vin,
    }


def _parse_energy_consumption(data: dict[str, Any]) -> EnergyConsumption:
    """Parse raw energy dict into a typed dataclass."""
    return EnergyConsumption(
        vin=str(data.get("vin", "")),
        total_energy=_safe_float(data.get("totalEnergy")),
        avg_energy_consumption=_safe_float(data.get("avgEnergyConsumption")),
        electricity_consumption=_safe_float(data.get("electricityConsumption")),
        fuel_consumption=_safe_float(data.get("fuelConsumption")),
        raw=data,
    )


async def fetch_energy_consumption(
    config: BydConfig,
    session: Session,
    transport: SecureTransport,
    vin: str,
    cache: VehicleDataCache | None = None,
) -> EnergyConsumption:
    """Fetch energy consumption data for a vehicle.

    Parameters
    ----------
    config : BydConfig
        Client configuration.
    session : Session
        Authenticated session.
    transport : SecureTransport
        HTTP transport.
    vin : str
        Vehicle Identification Number.

    Returns
    -------
    EnergyConsumption
        Energy consumption data.

    Raises
    ------
    BydApiError
        If the API returns an error.
    """
    now_ms = int(time.time() * 1000)
    inner = _build_energy_inner(config, vin, now_ms)
    outer, content_key = build_token_outer_envelope(config, session, inner, now_ms)

    response = await transport.post_secure(_ENDPOINT, outer)
    if str(response.get("code")) != "0":
        raise BydApiError(
            f"{_ENDPOINT} failed: code={response.get('code')} message={response.get('message', '')}",
            code=str(response.get("code", "")),
            endpoint=_ENDPOINT,
        )

    data = json.loads(aes_decrypt_utf8(response["respondData"], content_key))
    _logger.debug("Energy consumption response keys=%s", list(data.keys()) if isinstance(data, dict) else [])
    if cache is not None and isinstance(data, dict):
        data = cache.merge_energy(vin, data)
    return _parse_energy_consumption(data if isinstance(data, dict) else {})
