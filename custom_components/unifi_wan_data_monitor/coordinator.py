"""One shared poll, durable checkpoint before exposing new totals."""

from copy import deepcopy
from datetime import timedelta
import logging

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .accounting import Accounting
from .api import CannotConnect, InvalidAuth, UnsupportedEndpoint
from .const import DEFAULTS, DOMAIN, NAME
from .models import InvalidData

LOGGER = logging.getLogger(__name__)


class WanCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        self.client = client
        self.entry = entry
        self.settings = DEFAULTS | entry.options
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.accounting = Accounting()
        super().__init__(
            hass,
            LOGGER,
            name=NAME,
            config_entry=entry,
            update_interval=timedelta(seconds=self.settings["poll_interval"]),
        )

    async def load(self):
        self.accounting = Accounting(await self.store.async_load())

    async def _async_update_data(self):
        try:
            snap = await self.client.fetch()
        except InvalidAuth:
            raise ConfigEntryAuthFailed("UniFi credentials rejected") from None
        except (CannotConnect, UnsupportedEndpoint, InvalidData):
            raise UpdateFailed("Cannot read valid selected WAN port counters") from None
        # A failed disk write must not advance the in-memory baseline.
        candidate = Accounting(deepcopy(self.accounting.state))
        candidate.update(
            snap,
            dt_util.now(),
            self.settings["billing_day"],
            self.settings["poll_interval"],
            self.settings["initial_used_gb"],
        )
        try:
            await self.store.async_save(candidate.state)
        except (OSError, ValueError):
            raise UpdateFailed("Could not persist WAN accounting checkpoint") from None
        self.accounting = candidate
        return {"snapshot": snap, "accounting": candidate.state}
