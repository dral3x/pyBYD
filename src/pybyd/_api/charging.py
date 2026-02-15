"""Smart charging status endpoint.

Endpoint:
  - /control/smartCharge/homePage
"""

from __future__ import annotations

import logging

from pybyd._api._common import ENDPOINT_NOT_SUPPORTED_CODES, build_inner_base, post_token_json
from pybyd._transport import Transport
from pybyd.config import BydConfig
from pybyd.models.charging import ChargingStatus
from pybyd.session import Session

_logger = logging.getLogger(__name__)

_ENDPOINT = "/control/smartCharge/homePage"


async def fetch_charging_status(
    config: BydConfig,
    session: Session,
    transport: Transport,
    vin: str,
) -> ChargingStatus:
    """Fetch smart charging status (SOC, charge state, time-to-full)."""
    inner = build_inner_base(config, vin=vin)
    decoded = await post_token_json(
        endpoint=_ENDPOINT,
        config=config,
        session=session,
        transport=transport,
        inner=inner,
        vin=vin,
        not_supported_codes=ENDPOINT_NOT_SUPPORTED_CODES,
    )
    _logger.debug(
        "Charging response decoded vin=%s keys=%s",
        vin,
        list(decoded.keys()) if isinstance(decoded, dict) else [],
    )
    return ChargingStatus.model_validate(decoded)
