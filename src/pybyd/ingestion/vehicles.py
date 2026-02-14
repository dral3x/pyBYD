"""Vehicle list ingestion + parsing."""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

from pybyd._api._common import build_inner_base, post_token_json
from pybyd._transport import SecureTransport
from pybyd.config import BydConfig
from pybyd.models.vehicle import Vehicle
from pybyd.session import Session


async def fetch_vehicles(config: BydConfig, session: Session, transport: SecureTransport) -> list[Vehicle]:
    """Fetch and parse the vehicle list."""
    endpoint = "/app/account/getAllListByUserId"
    inner = build_inner_base(config)
    decoded = await post_token_json(
        endpoint=endpoint,
        config=config,
        session=session,
        transport=transport,
        inner=inner,
    )

    try:
        return TypeAdapter(list[Vehicle]).validate_python(decoded)
    except ValidationError:
        return []
