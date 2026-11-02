"""Counters, billing cycle and WAN status sensors."""

from datetime import date

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfInformation

from .entity import WanEntity

# key, display name, unit, device class, state class
DESCRIPTIONS = [
    ("raw_rx", "WAN2 port RX", "B", SensorDeviceClass.DATA_SIZE, SensorStateClass.TOTAL_INCREASING),
    ("raw_tx", "WAN2 port TX", "B", SensorDeviceClass.DATA_SIZE, SensorStateClass.TOTAL_INCREASING),
    ("total_rx", "WAN2 observed RX", "B", SensorDeviceClass.DATA_SIZE, SensorStateClass.TOTAL),
    ("total_tx", "WAN2 observed TX", "B", SensorDeviceClass.DATA_SIZE, SensorStateClass.TOTAL),
    (
        "month_used",
        "WAN2 cycle usage",
        "B",
        SensorDeviceClass.DATA_SIZE,
        SensorStateClass.TOTAL_INCREASING,
    ),
    (
        "remaining",
        "WAN2 quota remaining",
        "GB",
        SensorDeviceClass.DATA_SIZE,
        SensorStateClass.MEASUREMENT,
    ),
    ("percent", "WAN2 quota used", PERCENTAGE, None, SensorStateClass.MEASUREMENT),
    ("active_wan", "Active WAN", None, None, None),
    ("cycle", "Billing cycle start", None, SensorDeviceClass.DATE, None),
    ("coverage", "WAN2 accounting coverage", None, SensorDeviceClass.ENUM, None),
]


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(WanSensor(entry.runtime_data, *desc) for desc in DESCRIPTIONS)


class WanSensor(WanEntity, SensorEntity):
    def __init__(self, coordinator, key, name, unit, device_class, state_class):
        super().__init__(coordinator, key, name)
        self.key = key
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        if unit == "B":
            self._attr_native_unit_of_measurement = UnitOfInformation.BYTES
            self._attr_suggested_unit_of_measurement = UnitOfInformation.GIGABYTES
            self._attr_suggested_display_precision = 3
        if key in ("raw_rx", "raw_tx"):
            # Raw values can reset or be stale: exposed for diagnostics only.
            # Avoid feeding potentially discontinuous samples into long-term sums.
            self._attr_state_class = None
            self._attr_entity_registry_enabled_default = False
        if key == "coverage":
            self._attr_options = ["partial"]

    @property
    def native_value(self):
        state = self.accounting
        used = state["month_rx"] + state["month_tx"] + state["month_offset"]
        quota = self.coordinator.settings["quota_gb"]
        values = {
            "raw_rx": self.snapshot.rx,
            "raw_tx": self.snapshot.tx,
            "total_rx": state["total_rx"],
            "total_tx": state["total_tx"],
            "month_used": used,
            "remaining": max(0, quota - used / 1e9),
            "percent": round(used / (quota * 1e9) * 100, 2),
            "active_wan": self.snapshot.active_wan,
            "cycle": date.fromisoformat(state["cycle"]),
            "coverage": state["coverage"],
        }
        return values[self.key]

    @property
    def extra_state_attributes(self):
        if self.key not in ("month_used", "coverage"):
            return None
        return {
            "coverage_note": self.accounting["note"],
            "counter_reset_count": self.accounting["resets"],
            "cycle_rx_bytes": self.accounting["month_rx"],
            "cycle_tx_bytes": self.accounting["month_tx"],
            "initial_usage_bytes": self.accounting["month_offset"],
            "quota_bytes": round(self.coordinator.settings["quota_gb"] * 1e9),
        }
