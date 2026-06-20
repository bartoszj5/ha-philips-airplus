from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AirplusEntity


@dataclass(frozen=True, kw_only=True)
class AirplusSelectDescription(SelectEntityDescription):
    value_key: str
    options_map: dict[str, str]
    ncp_port: str | None = None
    ncp_value_key: str | None = None
    ncp_set_port: str | None = None


MODE_OPTIONS = {
    "0": "Automatyczny",
    "17": "Sen",
    "1": "Prędkość 1",
    "2": "Prędkość 2",
    "18": "Turbo",
}

FAN_MODE_OPTIONS = {
    "1": "Poziom 1",
    "2": "Poziom 2",
    "3": "Poziom 3",
    "4": "Poziom 4",
    "5": "Poziom 5",
    "6": "Poziom 6",
    "7": "Poziom 7",
    "8": "Poziom 8",
    "9": "Poziom 9",
    "10": "Poziom 10",
    "81": "Poziom 11",
    "82": "Poziom 12",
}

SELECTS: tuple[AirplusSelectDescription, ...] = (
    AirplusSelectDescription(
        key="mode",
        translation_key="mode",
        value_key="mode",
        ncp_port="Status",
        ncp_value_key="D0310C",
        ncp_set_port="Control",
        options_map=MODE_OPTIONS,
    ),
    AirplusSelectDescription(
        key="fan_mode",
        translation_key="fan_mode",
        value_key="om",
        options_map=FAN_MODE_OPTIONS,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AirplusSelect(data["coordinator"], data["client"], device, description)
        for device in data["devices"]
        for description in SELECTS
        if _has_value(
            data["coordinator"].data.get(device["id"], {}),
            description.value_key,
            description.ncp_port,
            description.ncp_value_key,
        )
    )


class AirplusSelect(AirplusEntity, SelectEntity):
    entity_description: AirplusSelectDescription

    def __init__(
        self,
        coordinator,
        client,
        device: dict,
        description: AirplusSelectDescription,
    ) -> None:
        super().__init__(coordinator, device)
        self.client = client
        self.entity_description = description
        self._attr_unique_id = f"{device['id']}_{description.key}"

    @property
    def options(self) -> list[str]:
        raw = self._raw_value
        options = list(self.entity_description.options_map.values())
        if raw is not None and raw not in self.entity_description.options_map:
            options.append(str(raw))
        return options

    @property
    def current_option(self) -> str | None:
        raw = self._raw_value
        if raw is None:
            return None
        return self.entity_description.options_map.get(str(raw), str(raw))

    @property
    def _raw_value(self) -> str | None:
        key = self.entity_description.value_key
        if key in self.reported:
            return str(self.reported[key])
        if key in self.desired:
            return str(self.desired[key])
        ncp_port = self.entity_description.ncp_port
        ncp_value_key = self.entity_description.ncp_value_key
        if ncp_port and ncp_value_key:
            properties = self.ncp_properties(ncp_port)
            if ncp_value_key in properties:
                return str(properties[ncp_value_key])
        return None

    async def async_select_option(self, option: str) -> None:
        reverse_map = {
            label: value for value, label in self.entity_description.options_map.items()
        }
        value = reverse_map.get(option, option)
        if self.entity_description.ncp_set_port and self.entity_description.ncp_value_key:
            await self.client.async_set_ncp_properties(
                self.device,
                self.entity_description.ncp_set_port,
                {self.entity_description.ncp_value_key: _coerce_number(value)},
            )
        else:
            await self.client.async_set_shadow_state(
                self.device,
                {self.entity_description.value_key: value},
            )
        await self.coordinator.async_request_refresh()


def _has_value(
    shadow: dict,
    key: str,
    ncp_port: str | None,
    ncp_value_key: str | None,
) -> bool:
    state = shadow.get("state", {})
    reported = state.get("reported", {})
    desired = state.get("desired", {})
    ncp = shadow.get("ncp", {})
    return (
        key in reported
        or key in desired
        or (
            ncp_port is not None
            and ncp_value_key is not None
            and ncp_value_key in ncp.get(ncp_port, {})
        )
    )


def _coerce_number(value: str) -> str | int:
    try:
        return int(value)
    except ValueError:
        return value
