"""Shared device registration and coordinator lifecycle."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class WanEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key, name):
        super().__init__(coordinator)
        snap = coordinator.data["snapshot"]
        self._attr_unique_id = f"{coordinator.entry.unique_id}_{key}"
        self._attr_name = name.replace("WAN2", f"{snap.networkgroup} {snap.interface}")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, snap.mac)},
            name=snap.name,
            manufacturer="Ubiquiti",
            model=snap.model,
            sw_version=snap.firmware,
        )

    @property
    def snapshot(self):
        return self.coordinator.data["snapshot"]

    @property
    def accounting(self):
        return self.coordinator.data["accounting"]
