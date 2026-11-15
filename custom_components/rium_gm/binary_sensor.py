from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory

from .entity import RiumEntity


async def async_setup_entry(hass, entry, add) -> None:
    add([RiumConnected(entry.runtime_data, entry, "connected")])


class RiumConnected(RiumEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.connected)
