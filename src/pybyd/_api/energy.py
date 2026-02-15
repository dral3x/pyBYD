"""Energy consumption endpoint.

Endpoint:
  - /vehicleInfo/vehicle/getEnergyConsumption (single request)
"""

from __future__ import annotations

import logging

from pybyd._api._common import build_inner_base, post_token_json
from pybyd._transport import Transport
from pybyd.config import BydConfig
from pybyd.models.energy import EnergyConsumption
from pybyd.session import Session

_logger = logging.getLogger(__name__)

_ENDPOINT = "/vehicleInfo/vehicle/getEnergyConsumption"

#: API error codes indicating the endpoint is not supported for this vehicle.
_NOT_SUPPORTED_CODES: frozenset[str] = frozenset({"1001"})


async def fetch_energy_consumption(
    config: BydConfig,
    session: Session,
    transport: Transport,
    vin: str,
) -> EnergyConsumption:
    """Fetch energy consumption data for a vehicle.

    Parameters
    ----------
    config : BydConfig
        Client configuration.
    session : Session
        Authenticated session.
    transport : Transport
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
    inner = build_inner_base(config, vin=vin)
    decoded = await post_token_json(
        endpoint=_ENDPOINT,
        config=config,
        session=session,
        transport=transport,
        inner=inner,
        vin=vin,
        not_supported_codes=_NOT_SUPPORTED_CODES,
    )
    _logger.debug(
        "Energy response decoded vin=%s keys=%s",
        vin,
        list(decoded.keys()) if isinstance(decoded, dict) else [],
    )
    return EnergyConsumption.model_validate(decoded)
