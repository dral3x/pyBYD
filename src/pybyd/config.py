"""Client configuration for pybyd."""

from __future__ import annotations

import dataclasses
import os
from typing import Any


@dataclasses.dataclass(frozen=True)
class DeviceProfile:
    """Device identity fields sent with every request.

    These correspond to the outer payload fields that identify
    the mobile device to the BYD API.
    """

    ostype: str = "and"
    imei: str = "BANGCLE01234"
    mac: str = "00:00:00:00:00:00"
    model: str = "POCO F1"
    sdk: str = "35"
    mod: str = "Xiaomi"
    imei_md5: str = "00000000000000000000000000000000"
    mobile_brand: str = "XIAOMI"
    mobile_model: str = "POCO F1"
    device_type: str = "0"
    network_type: str = "wifi"
    os_type: str = "15"
    os_version: str = "35"


@dataclasses.dataclass(frozen=True)
class BydConfig:
    """Client configuration.

    Parameters
    ----------
    username : str
        BYD account email or phone number.
    password : str
        BYD account password.
    base_url : app
        API base URL. Defaults to the EU overseas endpoint.
    country_code : str
        ISO country code (e.g. ``"NL"``).
    language : str
        Language code (e.g. ``"en"``).
    time_zone : str
        IANA time zone string.
    app_version : str
        App version string sent to the API.
    app_inner_version : str
        Internal app version number.
    soft_type : str
        Software type identifier.
    tbox_version : str
        T-Box version for vehicle communication.
    is_auto : str
        Auto-login flag.
    control_pin : str or None
        6-digit remote control PIN set in the BYD app. Required for
        vehicle control commands (lock, unlock, climate, etc.).
        The PIN is hashed with MD5 before sending to the API.
    device : DeviceProfile
        Device identity fields.
    """

    username: str
    password: str
    base_url: str = "https://dilinkappoversea-eu.byd.auto"
    country_code: str = "NL"
    language: str = "en"
    time_zone: str = "Europe/Amsterdam"
    app_version: str = "3.2.2"
    app_inner_version: str = "322"
    soft_type: str = "0"
    tbox_version: str = "3"
    is_auto: str = "1"
    control_pin: str | None = None
    device: DeviceProfile = dataclasses.field(default_factory=DeviceProfile)

    @classmethod
    def from_env(cls, **overrides: Any) -> BydConfig:
        """Create configuration from environment variables.

        Reads ``BYD_USERNAME``, ``BYD_PASSWORD``, and optional ``BYD_*``
        variables matching the Node.js client's convention. Explicit
        keyword arguments override environment values.

        Parameters
        ----------
        **overrides
            Explicit field values that take precedence over env vars.

        Returns
        -------
        BydConfig
            Populated configuration.
        """
        env = os.environ

        device_kwargs: dict[str, str] = {}
        _ENV_DEVICE_MAP = {
            "BYD_OSTYPE": "ostype",
            "BYD_IMEI": "imei",
            "BYD_MAC": "mac",
            "BYD_MODEL": "model",
            "BYD_SDK": "sdk",
            "BYD_MOD": "mod",
            "BYD_IMEI_MD5": "imei_md5",
            "BYD_MOBILE_BRAND": "mobile_brand",
            "BYD_MOBILE_MODEL": "mobile_model",
            "BYD_DEVICE_TYPE": "device_type",
            "BYD_NETWORK_TYPE": "network_type",
            "BYD_OS_TYPE": "os_type",
            "BYD_OS_VERSION": "os_version",
        }
        for env_key, field_name in _ENV_DEVICE_MAP.items():
            val = env.get(env_key)
            if val is not None:
                device_kwargs[field_name] = val

        # Allow overriding device fields via a nested dict
        device_overrides = overrides.pop("device", None)
        if isinstance(device_overrides, dict):
            device_kwargs.update(device_overrides)
        elif isinstance(device_overrides, DeviceProfile):
            device_kwargs = dataclasses.asdict(device_overrides)

        device = DeviceProfile(**device_kwargs) if device_kwargs else DeviceProfile()

        _ENV_CONFIG_MAP = {
            "BYD_USERNAME": "username",
            "BYD_PASSWORD": "password",
            "BYD_COUNTRY_CODE": "country_code",
            "BYD_LANGUAGE": "language",
            "BYD_TIME_ZONE": "time_zone",
            "BYD_APP_VERSION": "app_version",
            "BYD_APP_INNER_VERSION": "app_inner_version",
            "BYD_SOFT_TYPE": "soft_type",
            "BYD_TBOX_VERSION": "tbox_version",
            "BYD_IS_AUTO": "is_auto",
            "BYD_CONTROL_PIN": "control_pin",
        }
        config_kwargs: dict[str, Any] = {"device": device}
        for env_key, field_name in _ENV_CONFIG_MAP.items():
            val = env.get(env_key)
            if val is not None:
                config_kwargs[field_name] = val

        config_kwargs.update(overrides)

        return cls(**config_kwargs)
