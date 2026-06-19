from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class AirplusEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, device: dict) -> None:
        super().__init__(coordinator)
        self.device = device
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device["id"])},
            "name": device.get("friendlyName") or device.get("ctn") or device["id"],
            "manufacturer": "Philips",
            "model": device.get("ctn"),
        }

    @property
    def shadow(self) -> dict:
        return self.coordinator.data.get(self.device["id"], {})

    @property
    def reported(self) -> dict:
        return self.shadow.get("state", {}).get("reported", {})

    @property
    def desired(self) -> dict:
        return self.shadow.get("state", {}).get("desired", {})
