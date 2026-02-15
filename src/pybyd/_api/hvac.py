"""HVAC status endpoint.

Endpoint:
  - /control/getStatusNow
"""

from __future__ import annotations

import logging

from pybyd._api._common import build_inner_base, post_token_json
from pybyd._transport import Transport
from pybyd.config import BydConfig
from pybyd.models.hvac import HvacStatus
from pybyd.session import Session

_logger = logging.getLogger(__name__)

_ENDPOINT = "/control/getStatusNow"

#: API error codes indicating the endpoint is not supported for this vehicle.
_NOT_SUPPORTED_CODES: frozenset[str] = frozenset({"1001"})


async def fetch_hvac_status(
    config: BydConfig,
    session: Session,
    transport: Transport,
    vin: str,
) -> HvacStatus:
    """Fetch current HVAC/climate control status for a vehicle."""
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
        "HVAC response decoded vin=%s keys=%s",
        vin,
        list(decoded.keys()) if isinstance(decoded, dict) else [],
    )
    return HvacStatus.model_validate(decoded)
