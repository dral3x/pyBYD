"""Vehicle list endpoint.

Endpoint:
  - /app/account/getAllListByUserId
"""

from __future__ import annotations

import logging

from pybyd._api._common import build_inner_base, post_token_json
from pybyd._transport import Transport
from pybyd.config import BydConfig
from pybyd.models.vehicle import Vehicle
from pybyd.session import Session

_logger = logging.getLogger(__name__)

_ENDPOINT = "/app/account/getAllListByUserId"


async def fetch_vehicle_list(
    config: BydConfig,
    session: Session,
    transport: Transport,
) -> list[Vehicle]:
    """Fetch all vehicles associated with the authenticated user."""
    inner = build_inner_base(config)
    decoded = await post_token_json(
        endpoint=_ENDPOINT,
        config=config,
        session=session,
        transport=transport,
        inner=inner,
    )
    _logger.debug(
        "Vehicle list response decoded count=%d",
        len(decoded) if isinstance(decoded, list) else 0,
    )
    items = decoded if isinstance(decoded, list) else []
    return [Vehicle.model_validate(item) for item in items]
