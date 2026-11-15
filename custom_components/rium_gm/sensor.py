"""Capteurs : débit de dose, taux de comptage, cumul, température, batterie."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import RiumEntity
from .reader import RiumState


@dataclass(frozen=True, kw_only=True)
class RiumSensorDescription(SensorEntityDescription):
    value: Callable[[RiumState], float | int | None]
    needs_rate: bool = False


SENSORS = (
    RiumSensorDescription(
        key="dose_rate", native_unit_of_measurement="\u03bcSv/h", icon="mdi:radioactive",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=3,
        value=lambda s: s.dose_rate, needs_rate=True,
    ),
    RiumSensorDescription(
        key="count_rate", native_unit_of_measurement="cps", icon="mdi:pulse",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
        value=lambda s: s.cps, needs_rate=True,
    ),
    RiumSensorDescription(
        key="total_hits", native_unit_of_measurement="counts", icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING, value=lambda s: s.total_hits,
    ),
    RiumSensorDescription(
        key="temperature", device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT, entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.temperature,
    ),
    RiumSensorDescription(
        key="battery", device_class=SensorDeviceClass.BATTERY, native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda s: s.battery,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry, add: AddEntitiesCallback) -> None:
    add(RiumSensor(entry.runtime_data, entry, d) for d in SENSORS)


class RiumSensor(RiumEntity, SensorEntity):
    entity_description: RiumSensorDescription

    def __init__(self, coordinator, entry, description: RiumSensorDescription) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        s = self.coordinator.data
        return super().available and s is not None and s.connected and self.native_value is not None

    @property
    def native_value(self):
        s = self.coordinator.data
        return None if s is None else self.entity_description.value(s)

    @property
    def extra_state_attributes(self):
        s = self.coordinator.data
        if not self.entity_description.needs_rate or s is None:
            return None
        return {"window_s": round(s.window_s), "device_id": s.device_id, "protocol_version": s.version}
