"""WAN2 active uplink, physical link and quota status."""

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import WanEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        WanBinarySensor(entry.runtime_data, key, name)
        for key, name in [
            ("active", "WAN2 active uplink"),
            ("failover", "Secondary WAN active"),
            ("link", "WAN2 link"),
            ("quota_exceeded", "WAN2 quota exceeded"),
        ]
    )


class WanBinarySensor(WanEntity, BinarySensorEntity):
    def __init__(self, coordinator, key, name):
        super().__init__(coordinator, key, name)
        self.key = key

    @property
    def is_on(self):
        if self.key == "active":
            return (
                None
                if self.snapshot.active_wan is None
                else self.snapshot.active_wan == self.snapshot.networkgroup
            )
        if self.key == "failover":
            return None if self.snapshot.active_wan is None else self.snapshot.active_wan != "WAN"
        if self.key == "link":
            return self.snapshot.link
        used = sum(self.accounting[key] for key in ("month_rx", "month_tx", "month_offset"))
        return used >= self.coordinator.settings["quota_gb"] * 1e9
