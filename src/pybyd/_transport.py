"""HTTP transport with Bangcle envelope wrapping and cookie management."""

from __future__ import annotations

import json
import logging
from http.cookies import SimpleCookie
from typing import Any

import aiohttp

from pybyd._constants import USER_AGENT
from pybyd._crypto.bangcle import BangcleCodec
from pybyd.config import BydConfig
from pybyd.exceptions import BydTransportError

_logger = logging.getLogger(__name__)


class SecureTransport:
    """HTTP transport that handles Bangcle envelope encoding and cookie persistence.

    Parameters
    ----------
    config : BydConfig
        Client configuration (provides ``base_url``).
    codec : BangcleCodec
        Bangcle envelope codec.
    http_session : aiohttp.ClientSession
        HTTP session for making requests.
    """

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

    def _update_cookies(self, headers: Any) -> None:
        """Extract Set-Cookie headers and store them."""
        raw_cookies = headers.getall("Set-Cookie", [])
        for raw in raw_cookies:
            cookie: SimpleCookie = SimpleCookie()
            cookie.load(raw)
            for key, morsel in cookie.items():
                self._cookies[key] = morsel.value

    def _build_cookie_header(self) -> str:
        """Build a Cookie header string from stored cookies."""
        if not self._cookies:
            return ""
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items())

    async def post_secure(self, endpoint: str, outer_payload: dict[str, Any]) -> dict[str, Any]:
        """Send a signed request through the Bangcle envelope layer.

        1. JSON-encode the outer payload
        2. Bangcle-encode it
        3. POST as ``{"request": "<encoded>"}``
        4. Bangcle-decode the ``{"response": "<encoded>"}`` reply
        5. Return the decoded JSON dict

        Parameters
        ----------
        endpoint : str
            API path (e.g. ``"/app/account/login"``).
        outer_payload : dict
            The outer payload dict to send.

        Returns
        -------
        dict
            Decoded response payload.

        Raises
        ------
        BydTransportError
            On HTTP errors or missing/invalid response structure.
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
