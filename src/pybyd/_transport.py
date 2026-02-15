"""HTTP transport with Bangcle envelope wrapping and cookie management."""

from __future__ import annotations

import json
import logging
from http.cookies import SimpleCookie
from collections.abc import Mapping
from typing import Any, Protocol

import aiohttp

from pybyd._constants import USER_AGENT
from pybyd._crypto.bangcle import BangcleCodec
from pybyd.config import BydConfig
from pybyd.exceptions import BydTransportError

_logger = logging.getLogger(__name__)


class Transport(Protocol):
    """Structural transport interface used by endpoint modules.

    Having a protocol here makes it easy to pass test doubles/mocks while
    keeping the production implementation (`SecureTransport`) concrete.
    """

    async def post_secure(self, endpoint: str, outer_payload: Mapping[str, Any]) -> dict[str, Any]:
        ...


class SecureTransport:
    """HTTP transport that handles Bangcle envelope encoding and cookie persistence."""

    def __init__(
        self,
        config: BydConfig,
        codec: BangcleCodec,
        http_session: aiohttp.ClientSession,
    ) -> None:
        self._config = config
        self._codec = codec
        self._http = http_session
        self._cookies: dict[str, str] = {}
        self._cookie_header: str = ""

    def _update_cookies(self, headers: Any) -> None:
        """Extract Set-Cookie headers and store them."""
        raw_cookies = headers.getall("Set-Cookie", [])
        changed = False
        for raw in raw_cookies:
            cookie: SimpleCookie = SimpleCookie()
            cookie.load(raw)
            for key, morsel in cookie.items():
                value = morsel.value
                if self._cookies.get(key) != value:
                    self._cookies[key] = value
                    changed = True

        if changed:
            self._cookie_header = "; ".join(f"{k}={v}" for k, v in self._cookies.items())

    def _build_cookie_header(self) -> str:
        """Build a Cookie header string from stored cookies."""
        return self._cookie_header

    async def post_secure(self, endpoint: str, outer_payload: Mapping[str, Any]) -> dict[str, Any]:
        """Send a signed request through the Bangcle envelope layer.

        1. JSON-encode the outer payload
        2. Bangcle-encode it
        3. POST as ``{"request": "<encoded>"}``
        4. Bangcle-decode the ``{"response": "<encoded>"}`` reply
        5. Return the decoded JSON dict
        """
        encoded = self._codec.encode_envelope(json.dumps(outer_payload, separators=(",", ":")))

        headers: dict[str, str] = {
            "accept-encoding": "identity",
            "content-type": "application/json; charset=UTF-8",
            "user-agent": USER_AGENT,
        }

        cookie = self._build_cookie_header()
        if cookie:
            headers["cookie"] = cookie

        url = f"{self._config.base_url}{endpoint}"
        body = json.dumps({"request": encoded})

        _logger.debug("POST %s", url)

        try:
            async with self._http.post(url, data=body, headers=headers) as resp:
                self._update_cookies(resp.headers)
                text = await resp.text()
                if resp.status != 200:
                    raise BydTransportError(
                        f"HTTP {resp.status} from {endpoint}: {text[:200]}",
                        status_code=resp.status,
                        endpoint=endpoint,
                    )
        except BydTransportError:
            raise
        except aiohttp.ClientError as exc:
            raise BydTransportError(
                f"Request to {endpoint} failed: {exc}",
                endpoint=endpoint,
            ) from exc

        try:
            body_json = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BydTransportError(
                f"Invalid JSON from {endpoint}: {text[:200]}",
                endpoint=endpoint,
            ) from exc

        if not isinstance(body_json, dict) or "response" not in body_json:
            raise BydTransportError(
                f"Missing 'response' field from {endpoint}",
                endpoint=endpoint,
            )

        response_str = body_json["response"]
        if not isinstance(response_str, str) or not response_str.strip():
            raise BydTransportError(
                f"Empty response payload from {endpoint}",
                endpoint=endpoint,
            )

        decoded_text = self._codec.decode_envelope(response_str).decode("utf-8").strip()

        # Handle stray F prefix on decoded JSON (observed in some responses)
        if decoded_text.startswith("F{") or decoded_text.startswith("F["):
            decoded_text = decoded_text[1:]

        try:
            result: dict[str, Any] = json.loads(decoded_text)
        except json.JSONDecodeError as exc:
            raise BydTransportError(
                f"Bangcle response from {endpoint} is not JSON: {decoded_text[:64]}",
                endpoint=endpoint,
            ) from exc

        return result
