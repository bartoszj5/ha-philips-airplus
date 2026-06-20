from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    UnitOfTime,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AirplusEntity


@dataclass(frozen=True, kw_only=True)
class AirplusSensorDescription(SensorEntityDescription):
    value_keys: tuple[str, ...] = ()
    ncp_keys: tuple[tuple[str, str], ...] = ()
    scale: float = 1


SENSORS: tuple[AirplusSensorDescription, ...] = (
    AirplusSensorDescription(
        key="pm25",
        translation_key="pm25",
        value_keys=("pm25",),
        ncp_keys=(("Status", "D03221"),),
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AirplusSensorDescription(
        key="allergen_index",
        translation_key="allergen_index",
        value_keys=("iaql", "iaql_allergen", "allergens"),
        ncp_keys=(("Status", "D03120"),),
    ),
    AirplusSensorDescription(
        key="air_quality_index",
        translation_key="air_quality_index",
        value_keys=("aqi", "aqil"),
    ),
    AirplusSensorDescription(
        key="air_quality_label",
        translation_key="air_quality_label",
        value_keys=("aqit",),
    ),
    AirplusSensorDescription(
        key="gas",
        translation_key="gas",
        value_keys=("gas", "gaslvl"),
    ),
    AirplusSensorDescription(
        key="temperature",
        translation_key="temperature",
        value_keys=("temp", "temperature"),
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    AirplusSensorDescription(
        key="humidity",
        translation_key="humidity",
        value_keys=("rh",),
        native_unit_of_measurement=PERCENTAGE,
    ),
    AirplusSensorDescription(
        key="target_humidity",
        translation_key="target_humidity",
        value_keys=("rhset",),
        native_unit_of_measurement=PERCENTAGE,
    ),
    AirplusSensorDescription(
        key="filter_lifetime",
        translation_key="filter_lifetime",
        value_keys=("fltsts0", "fltsts1", "fltsts2"),
        native_unit_of_measurement=PERCENTAGE,
    ),
    AirplusSensorDescription(
        key="display",
        translation_key="display",
        value_keys=("ddp",),
        ncp_keys=(("Status", "D03105"),),
        native_unit_of_measurement=PERCENTAGE,
    ),
    AirplusSensorDescription(
        key="fan_level",
        translation_key="fan_level",
        ncp_keys=(("Status", "D0310D"),),
    ),
    AirplusSensorDescription(
        key="main_filter_remaining",
        translation_key="main_filter_remaining",
        ncp_keys=(("filtRd", "D0540E"),),
        native_unit_of_measurement=UnitOfTime.HOURS,
    ),
    AirplusSensorDescription(
        key="pre_filter_remaining",
        translation_key="pre_filter_remaining",
        ncp_keys=(("filtRd", "D0520D"),),
        native_unit_of_measurement=UnitOfTime.HOURS,
    ),
    AirplusSensorDescription(
        key="product_state",
        translation_key="product_state",
        value_keys=("productState",),
    ),
    AirplusSensorDescription(
        key="product_error",
        translation_key="product_error",
        value_keys=("productError", "err"),
    ),
    AirplusSensorDescription(
        key="host_firmware",
        translation_key="host_firmware",
        value_keys=("hostFirmwareVersion",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AirplusSensorDescription(
        key="ncp_firmware",
        translation_key="ncp_firmware",
        value_keys=("ncpFirmwareVersion",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
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
        if _has_any_value(
            data["coordinator"].data.get(device["id"], {}),
            description.value_keys,
            description.ncp_keys,
        )
    )


class AirplusSensor(AirplusEntity, SensorEntity):
    entity_description: AirplusSensorDescription

    def __init__(self, coordinator, device: dict, description: AirplusSensorDescription) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_unique_id = f"{device['id']}_{description.key}"

    @property
    def native_value(self) -> Any:
        for key in self.entity_description.value_keys:
            if key in self.reported:
                return self._scale(self.reported[key])
            if key in self.desired:
                return self._scale(self.desired[key])
        for port_name, key in self.entity_description.ncp_keys:
            properties = self.ncp_properties(port_name)
            if key in properties:
                return self._scale(properties[key])
        return None

    def _scale(self, value: Any) -> Any:
        scale = self.entity_description.scale
        if scale == 1 or not isinstance(value, int | float):
            return value
        return value * scale


def _has_any_value(
    shadow: dict,
    keys: tuple[str, ...],
    ncp_keys: tuple[tuple[str, str], ...],
) -> bool:
    state = shadow.get("state", {})
    reported = state.get("reported", {})
    desired = state.get("desired", {})
    ncp = shadow.get("ncp", {})
    return any(key in reported or key in desired for key in keys) or any(
        key in ncp.get(port_name, {}) for port_name, key in ncp_keys
    )
