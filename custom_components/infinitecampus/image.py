"""Image platform for Infinite Campus: the student's portal photo."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import InfiniteCampusError
from .const import DOMAIN
from .coordinator import InfiniteCampusDataUpdateCoordinator, StudentSnapshot

_LOGGER = logging.getLogger(__name__)

# School photos change about once a year; check daily.
PHOTO_REFRESH = timedelta(hours=24)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: InfiniteCampusDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        InfiniteCampusStudentPhoto(coordinator, student)
        for student in coordinator.data.values()
    )


class InfiniteCampusStudentPhoto(
    CoordinatorEntity[InfiniteCampusDataUpdateCoordinator], ImageEntity
):
    """The student's photo from the parent portal."""

    _attr_icon = "mdi:account-box"

    def __init__(
        self,
        coordinator: InfiniteCampusDataUpdateCoordinator,
        student: StudentSnapshot,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._person_id = student.person_id
        self._student_name = student.name
        self._attr_unique_id = f"{student.person_id}_photo"
        self._attr_name = f"{student.name} Photo"
        self._image: bytes | None = None
        self._checked: datetime | None = None
        self._fetching = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._person_id))},
            name=self._student_name,
            manufacturer="Infinite Campus",
            model="Student",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_refresh_photo()

    @callback
    def _handle_coordinator_update(self) -> None:
        # _checked stays None after a failed fetch, so the next update retries.
        if not self._fetching and (
            self._checked is None
            or dt_util.utcnow() - self._checked >= PHOTO_REFRESH
        ):
            self.hass.async_create_task(self._async_refresh_photo())
        super()._handle_coordinator_update()

    async def _async_refresh_photo(self) -> None:
        """Fetch the photo; keep the old one if the portal is unreachable."""
        self._fetching = True
        try:
            photo = await self.coordinator.client.async_get_photo(self._person_id)
        except InfiniteCampusError as err:
            _LOGGER.debug("Could not fetch photo for %s: %s", self._person_id, err)
            return
        finally:
            self._fetching = False
        self._checked = dt_util.utcnow()
        image, content_type = photo if photo else (None, "image/jpeg")
        if image != self._image:
            self._image = image
            self._attr_content_type = content_type
            self._attr_image_last_updated = self._checked if image else None
            self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        return self._image
