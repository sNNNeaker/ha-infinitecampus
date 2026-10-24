"""Config flow for Infinite Campus."""

from __future__ import annotations

from typing import Any
import re
from urllib.parse import parse_qs, urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .api import InfiniteCampusAuthError, InfiniteCampusClient, InfiniteCampusError
from .const import (
    CONF_APP_NAME,
    CONF_BASE_URL,
    CONF_PORTAL_LOGIN_PAGE,
    DEFAULT_PORTAL_LOGIN_PAGE,
    DOMAIN,
)


def _extract_app_name_from_path(path: str) -> str | None:
    patterns = [
        r"/campus/portal/parents/([a-zA-Z0-9_-]+)\.jsp",
        r"/campus/portal/parent/([a-zA-Z0-9_-]+)\.jsp",
        r"/portal/parents/([a-zA-Z0-9_-]+)\.jsp",
        r"/portal/parent/([a-zA-Z0-9_-]+)\.jsp",
    ]
    for pattern in patterns:
        match = re.search(pattern, path)
        if match:
            return match.group(1)
    return None


def _parse_portal_input(value: str) -> tuple[str, str | None]:
    value = value.strip()
    if not value.startswith("http://") and not value.startswith("https://"):
        if "." in value:
            value = f"https://{value}"
        else:
            value = f"https://{value}.infinitecampus.org"

    parsed = urlparse(value)
    base_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    app_name = parse_qs(parsed.query).get("appName", [None])[0]
    if not app_name:
        app_name = _extract_app_name_from_path(parsed.path)
    return base_url, app_name


async def _validate_input(
    hass: HomeAssistant, data: dict[str, Any], base_url: str, app_name: str
) -> None:
    """Validate credentials by loading students."""
    session = async_get_clientsession(hass)
    client = InfiniteCampusClient(
        session,
        base_url,
        app_name,
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        DEFAULT_PORTAL_LOGIN_PAGE,
    )
    await client.async_get_students()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Infinite Campus."""

    VERSION = 1
    _data: dict[str, Any] | None = None
    _base_url: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url, app_name = _parse_portal_input(user_input[CONF_BASE_URL])
            await self.async_set_unique_id(
                f"{base_url}:{user_input[CONF_USERNAME]}"
            )
            self._abort_if_unique_id_configured()

            try:
                if not app_name:
                    self._data = user_input
                    self._base_url = base_url
                    return await self.async_step_app_name()
                await _validate_input(self.hass, user_input, base_url, app_name)
            except InfiniteCampusAuthError:
                errors["base"] = "invalid_auth"
            except InfiniteCampusError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data={
                        CONF_BASE_URL: base_url,
                        CONF_APP_NAME: app_name,
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_PORTAL_LOGIN_PAGE: DEFAULT_PORTAL_LOGIN_PAGE,
                    },
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_app_name(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if self._data is None or self._base_url is None:
            return await self.async_step_user()

        if user_input is not None:
            await self.async_set_unique_id(
                f"{self._base_url}:{self._data[CONF_USERNAME]}"
            )
            self._abort_if_unique_id_configured()

            try:
                await _validate_input(
                    self.hass,
                    self._data,
                    self._base_url,
                    user_input[CONF_APP_NAME].strip(),
                )
            except InfiniteCampusAuthError:
                errors["base"] = "invalid_auth"
            except InfiniteCampusError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=self._data[CONF_USERNAME],
                    data={
                        CONF_BASE_URL: self._base_url,
                        CONF_APP_NAME: user_input[CONF_APP_NAME].strip(),
                        CONF_USERNAME: self._data[CONF_USERNAME],
                        CONF_PASSWORD: self._data[CONF_PASSWORD],
                        CONF_PORTAL_LOGIN_PAGE: DEFAULT_PORTAL_LOGIN_PAGE,
                    },
                )

        return self.async_show_form(
            step_id="app_name",
            data_schema=vol.Schema({vol.Required(CONF_APP_NAME): str}),
            errors=errors,
        )
