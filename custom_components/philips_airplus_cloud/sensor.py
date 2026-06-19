from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AirplusEntity


@dataclass(frozen=True, kw_only=True)
class AirplusSensorDescription(SensorEntityDescription):
    value_key: str


SENSORS: tuple[AirplusSensorDescription, ...] = (
    AirplusSensorDescription(key="product_state", translation_key="product_state", value_key="productState"),
    AirplusSensorDescription(key="product_error", translation_key="product_error", value_key="productError"),
    AirplusSensorDescription(key="host_firmware", translation_key="host_firmware", value_key="hostFirmwareVersion"),
    AirplusSensorDescription(key="ncp_firmware", translation_key="ncp_firmware", value_key="ncpFirmwareVersion"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AirplusSensor(data["coordinator"], device, description)
        for device in data["devices"]
        for description in SENSORS
    )


class AirplusSensor(AirplusEntity, SensorEntity):
    entity_description: AirplusSensorDescription

    def __init__(self, coordinator, device: dict, description: AirplusSensorDescription) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_unique_id = f"{device['id']}_{description.key}"

    @property
    def native_value(self) -> Any:
        return self.reported.get(self.entity_description.value_key)
