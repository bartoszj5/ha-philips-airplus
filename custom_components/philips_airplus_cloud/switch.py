from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AirplusEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AirplusPowerSwitch(data["coordinator"], data["client"], device)
        for device in data["devices"]
    )


class AirplusPowerSwitch(AirplusEntity, SwitchEntity):
    _attr_translation_key = "power"

    def __init__(self, coordinator, client, device: dict) -> None:
        super().__init__(coordinator, device)
        self.client = client
        self._attr_unique_id = f"{device['id']}_power"

    @property
    def is_on(self) -> bool | None:
        if "powerOn" in self.reported:
            return bool(self.reported["powerOn"])
        if "powerOn" in self.desired:
            return bool(self.desired["powerOn"])
        return None

    async def async_turn_on(self, **kwargs) -> None:
        await self.client.async_set_power(self.device, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.client.async_set_power(self.device, False)
        await self.coordinator.async_request_refresh()
