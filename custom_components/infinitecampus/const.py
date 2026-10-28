"""Constants for the Infinite Campus integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "infinitecampus"

CONF_BASE_URL = "base_url"
CONF_APP_NAME = "app_name"
CONF_PORTAL_LOGIN_PAGE = "portal_login_page"

DEFAULT_PORTAL_LOGIN_PAGE = "parents"
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=15)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.CALENDAR, Platform.IMAGE]
