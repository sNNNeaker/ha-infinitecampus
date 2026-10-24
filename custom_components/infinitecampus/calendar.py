"""Calendar platform for Infinite Campus (per-day attendance)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import (
    InfiniteCampusDataUpdateCoordinator,
    StudentSnapshot,
    attendance_today,
)

_STATUS_SUMMARY = {
    "absent": "Absent",
    "partial": "Partial absence",
    "tardy": "Tardy",
}
_EXCUSE_SUFFIX = {
    True: " (excused)",
    False: " (unexcused)",
    "mixed": " (partly excused)",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: InfiniteCampusDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        InfiniteCampusAttendanceCalendar(coordinator, student)
        for student in coordinator.data.values()
    )


class InfiniteCampusAttendanceCalendar(
    CoordinatorEntity[InfiniteCampusDataUpdateCoordinator], CalendarEntity
):
    """Calendar with one all-day event per day with absence or tardy."""

    _attr_icon = "mdi:calendar-account"

    def __init__(
        self,
        coordinator: InfiniteCampusDataUpdateCoordinator,
        student: StudentSnapshot,
    ) -> None:
        super().__init__(coordinator)
        self._person_id = student.person_id
        self._student_name = student.name
        self._attr_unique_id = f"{student.person_id}_attendance_calendar"
        self._attr_name = f"{student.name} Attendance"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._person_id))},
            name=self._student_name,
            manufacturer="Infinite Campus",
            model="Student",
        )

    def _days(self) -> list[dict[str, Any]]:
        student = self.coordinator.data.get(self._person_id)
        return student.attendance_days if student else []

    @property
    def event(self) -> CalendarEvent | None:
        today = attendance_today(self._days(), dt_util.now().date())
        return _build_event(today) if today else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        start = _to_date(start_date)
        end = _to_date(end_date)
        events: list[CalendarEvent] = []
        for day in self._days():
            day_date = _parse(day.get("date"))
            if day_date is None:
                continue
            if day_date < end and day_date + timedelta(days=1) > start:
                events.append(_build_event(day))
        events.sort(key=lambda item: item.start)
        return events


def _to_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return dt_util.as_local(value).date()
    return value


def _parse(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _build_event(day: dict[str, Any]) -> CalendarEvent:
    day_date = _parse(day.get("date")) or dt_util.now().date()
    periods = [
        f"P{name}" if str(name).strip().isdigit() else str(name)
        for name in day.get("periods") or []
    ]
    summary = _STATUS_SUMMARY.get(day.get("status"), "Attendance")
    summary += _EXCUSE_SUFFIX.get(day.get("excused"), "")
    if periods:
        summary += ": " + ", ".join(periods)
    lines: list[str] = []
    if day.get("courses"):
        lines.append(", ".join(day["courses"]))
    if day.get("codes"):
        lines.append("Codes: " + ", ".join(day["codes"]))
    return CalendarEvent(
        start=day_date,
        end=day_date + timedelta(days=1),
        summary=summary,
        description="\n".join(lines) or None,
    )
