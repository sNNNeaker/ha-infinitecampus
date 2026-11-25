"""Binary sensor platform for Infinite Campus: school day today."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    day_event_name,
)

# How far ahead `upcoming_school_days` looks (today included).
UPCOMING_DAYS = 14


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: InfiniteCampusDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        InfiniteCampusSchoolDay(coordinator, student)
        for student in coordinator.data.values()
    )


class InfiniteCampusSchoolDay(
    CoordinatorEntity[InfiniteCampusDataUpdateCoordinator], BinarySensorEntity
):
    """On when today is an instructional day in the student's school calendar."""

    _attr_icon = "mdi:school"

    def __init__(
        self,
        coordinator: InfiniteCampusDataUpdateCoordinator,
        student: StudentSnapshot,
    ) -> None:
        super().__init__(coordinator)
        self._person_id = student.person_id
        self._student_name = student.name
        self._attr_unique_id = f"{student.person_id}_school_day"
        self._attr_name = f"{student.name} School day"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._person_id))},
            name=self._student_name,
            manufacturer="Infinite Campus",
            model="Student",
        )

    def _student(self) -> StudentSnapshot | None:
        return self.coordinator.data.get(self._person_id)

    @property
    def available(self) -> bool:
        student = self._student()
        return super().available and bool(student and student.instructional_days)

    @property
    def is_on(self) -> bool | None:
        student = self._student()
        if not student or not student.instructional_days:
            return None
        return dt_util.now().date().isoformat() in student.instructional_days

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        student = self._student()
        if not student or not student.instructional_days:
            return None
        today = dt_util.now().date()
        days = student.instructional_days
        horizon = (today + timedelta(days=UPCOMING_DAYS - 1)).isoformat()
        return {
            "reason": day_event_name(student.day_events, today),
            "next_school_day": next((d for d in days if d > today.isoformat()), None),
            "upcoming_school_days": [
                d for d in days if today.isoformat() <= d <= horizon
            ],
            "first_day": days[0],
            "last_day": days[-1],
        }
