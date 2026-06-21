from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AirplusEntity


DISPLAY_LIGHT_KEYS = ("D03104", "D03105")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        entity
        for device in data["devices"]
        for entity in (
            AirplusPowerSwitch(data["coordinator"], data["client"], device),
            AirplusDisplayLightSwitch(data["coordinator"], data["client"], device),
        )
    )


class AirplusPowerSwitch(AirplusEntity, SwitchEntity):
    _attr_translation_key = "power"
    _attr_icon = "mdi:power"

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
        if "pwr" in self.reported:
            return str(self.reported["pwr"]) == "1"
        if "pwr" in self.desired:
            return str(self.desired["pwr"]) == "1"
        return None

    async def async_turn_on(self, **kwargs) -> None:
        await self.client.async_set_power(self.device, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.client.async_set_power(self.device, False)
        await self.coordinator.async_request_refresh()


class AirplusDisplayLightSwitch(AirplusEntity, SwitchEntity):
    _attr_translation_key = "display_light"
    _attr_icon = "mdi:brightness-6"

    def __init__(self, coordinator, client, device: dict) -> None:
        super().__init__(coordinator, device)
        self.client = client
        self._attr_unique_id = f"{device['id']}_display_light"

    @property
    def is_on(self) -> bool | None:
        value = self._raw_value
        if value is None:
            return None
        return value > 0

    @property
    def _raw_value(self) -> int | None:
        properties = self.ncp_properties("Status")
        for key in DISPLAY_LIGHT_KEYS:
            value = properties.get(key)
            if isinstance(value, int | float):
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    continue
        return None

    async def async_turn_on(self, **kwargs) -> None:
        await self._set_value(100)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set_value(0)

    async def _set_value(self, value: int) -> None:
        await self.client.async_set_ncp_properties(
            self.device,
            "Control",
            {key: value for key in DISPLAY_LIGHT_KEYS},
        )
        await self.coordinator.async_request_refresh()
