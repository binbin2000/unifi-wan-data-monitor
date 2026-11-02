"""UniFi WAN Data Monitor, monitoring only."""

from homeassistant.const import Platform

from .api import UniFiClient
from .const import PLATFORMS
from .coordinator import WanCoordinator


async def async_setup_entry(hass, entry):
    client = UniFiClient.create(entry.data)
    coordinator = WanCoordinator(hass, entry, client)
    try:
        await coordinator.load()
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(
            entry, [Platform(platform) for platform in PLATFORMS]
        )
    except BaseException:
        await client.close()
        raise
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.client.close()
    return unloaded


async def async_remove_entry(hass, entry):
    from homeassistant.helpers.storage import Store
    from .const import DOMAIN

    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
