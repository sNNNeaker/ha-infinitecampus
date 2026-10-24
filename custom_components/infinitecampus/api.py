"""API client for Infinite Campus."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.util import dt as dt_util


class InfiniteCampusError(Exception):
    """Base class for Infinite Campus errors."""


class InfiniteCampusAuthError(InfiniteCampusError):
    """Authentication error."""


class InfiniteCampusConnectionError(InfiniteCampusError):
    """Connection error."""


class _SessionExpired(Exception):
    """Internal: the portal session cookie is no longer accepted."""


class InfiniteCampusClient:
    """HTTP client for Infinite Campus portal endpoints."""

    _LOGIN_TTL = timedelta(hours=4)

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        app_name: str,
        username: str,
        password: str,
        portal_login_page: str,
    ) -> None:
        self._session = session
        self._base_url = self._normalize_base_url(base_url)
        self._app_name = app_name
        self._username = username
        self._password = password
        self._portal_login_page = portal_login_page
        self._last_login: datetime | None = None
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(4)

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        base = base_url.rstrip("/")
        if base.endswith("/campus"):
            base = base[: -len("/campus")]
        return base

    async def async_ensure_login(self) -> None:
        """Ensure the session is authenticated."""
        if self._last_login and dt_util.utcnow() - self._last_login < self._LOGIN_TTL:
            return
        async with self._lock:
            if self._last_login and dt_util.utcnow() - self._last_login < self._LOGIN_TTL:
                return
            await self.async_login()

    async def async_login(self) -> None:
        """Login to Infinite Campus."""
        url = f"{self._base_url}/campus/verify.jsp"
        portal_url = (
            f"portal/{self._portal_login_page}/{self._app_name}.jsp"
            f"?&rID={random.random()}"
        )
        payload = {
            "username": self._username,
            "password": self._password,
            "portalUrl": portal_url,
            "appName": self._app_name,
            "url": "nav-wrapper",
            "lang": "en",
            "portalLoginPage": self._portal_login_page,
        }

        try:
            async with self._session.post(
                url,
                data=payload,
                allow_redirects=False,
            ) as resp:
                if resp.status == 302:
                    self._last_login = dt_util.utcnow()
                    return
                if resp.status == 200:
                    if "JSESSIONID" in resp.cookies or "XSRF-TOKEN" in resp.cookies:
                        self._last_login = dt_util.utcnow()
                        return
                    raise InfiniteCampusAuthError("Login failed")
                if resp.status in (401, 403):
                    raise InfiniteCampusAuthError("Login failed")
                raise InfiniteCampusConnectionError(
                    f"Unexpected login status: {resp.status}"
                )
        except aiohttp.ClientError as err:
            raise InfiniteCampusConnectionError(str(err)) from err

    async def async_get_students(self) -> list[dict[str, Any]]:
        """Fetch students linked to the account."""
        return await self._request_json("GET", "/campus/api/portal/students")

    async def async_get_roster(self, person_id: int, date_str: str) -> list[dict[str, Any]]:
        """Fetch roster for a student."""
        params = {
            "_expand": "{sectionPlacements-{term}}",
            "_crossSite": "true",
            "_date": date_str,
            "personID": str(person_id),
        }
        return await self._request_json(
            "GET",
            "/campus/resources/portal/roster",
            params=params,
        )

    async def async_get_assignments_total(
        self, person_id: int, start: str, end: str
    ) -> int | None:
        """Fetch assignment total for a date range."""
        params = {
            "startDate": start,
            "endDate": end,
            "personID": str(person_id),
        }
        data = await self._request_json(
            "GET",
            "/campus/api/portal/assignment/byDateRangeTotal",
            params=params,
        )
        return self._coerce_int(data)

    async def async_get_assignments_list(self, person_id: int) -> list[dict[str, Any]]:
        """Fetch assignments list view."""
        params = {"personID": str(person_id)}
        data = await self._request_json(
            "GET",
            "/campus/api/portal/assignment/listView",
            params=params,
        )
        return data if isinstance(data, list) else []

    async def async_get_missing_total(self, person_id: int, term_id: int) -> int | None:
        """Fetch missing assignment total for a term."""
        params = {"personID": str(person_id), "termID": str(term_id)}
        data = await self._request_json(
            "GET",
            "/campus/api/portal/assignment/missingTotal",
            params=params,
        )
        return self._coerce_int(data)

    async def async_get_missing_assignments(
        self, person_id: int, term_id: int
    ) -> list[dict[str, Any]]:
        """Fetch missing assignments for a term."""
        params = {"personID": str(person_id), "termID": str(term_id)}
        data = await self._request_json(
            "GET",
            "/campus/api/portal/assignment/missing",
            params=params,
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            items = data.get("missingAssignments")
            return items if isinstance(items, list) else []
        return []

    async def async_get_grade_detail(
        self, person_id: int, section_id: int
    ) -> dict[str, Any]:
        """Fetch grade detail for a section."""
        params = {
            "classroomSectionID": str(section_id),
            "classroomTermID": "null",
            "personID": str(person_id),
        }
        return await self._request_json(
            "GET",
            f"/campus/resources/portal/grades/detail/{section_id}",
            params=params,
        )

    async def async_get_grades_overview(self, person_id: int) -> list[dict[str, Any]]:
        """Fetch grades overview for a student."""
        params = {"personID": str(person_id)}
        data = await self._request_json(
            "GET",
            "/campus/resources/portal/grades",
            params=params,
        )
        return data if isinstance(data, list) else []

    async def async_get_attendance_events(
        self, person_id: int, enrollment_id: int
    ) -> list[dict[str, Any]]:
        """Fetch attendance events for an enrollment."""
        params = {"personID": str(person_id), "enrollmentID": str(enrollment_id)}
        data = await self._request_json(
            "GET",
            "/campus/resources/portal/attendance/events",
            params=params,
        )
        return data if isinstance(data, list) else []

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None

    async def _request_json(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Request JSON; on an auth-looking response log in again and retry once."""
        for attempt in (1, 2):
            await self.async_ensure_login()
            try:
                result = await self._request_json_once(method, path, params)
            except _SessionExpired:
                # Cookie no longer valid: force a fresh login before retrying.
                self._last_login = None
                if attempt == 2:
                    raise InfiniteCampusAuthError(
                        "Authentication required"
                    ) from None
                continue
            return result
        raise InfiniteCampusAuthError("Authentication required")  # pragma: no cover

    async def _request_json_once(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with self._semaphore:
                async with self._session.request(
                    method, url, params=params, allow_redirects=False
                ) as resp:
                    if resp.status in (401, 403, 302):
                        raise _SessionExpired
                    if resp.status >= 400:
                        raise InfiniteCampusConnectionError(
                            f"Request failed: {resp.status}"
                        )
                    content_type = resp.headers.get("Content-Type", "")
                    if "application/json" in content_type:
                        return await resp.json()
                    if "text/html" in content_type:
                        raise _SessionExpired
                    text = (await resp.text()).strip()
                    if text == "":
                        return None
                    # Some endpoints return a raw integer.
                    try:
                        return int(text)
                    except ValueError:
                        raise InfiniteCampusConnectionError(
                            "Unexpected response format"
                        )
        except aiohttp.ClientError as err:
            raise InfiniteCampusConnectionError(str(err)) from err
