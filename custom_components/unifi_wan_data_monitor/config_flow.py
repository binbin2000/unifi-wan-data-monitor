"""Validate authentication and actual counters before offering a WAN selection."""

import math

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import CannotConnect, InvalidAuth, UniFiClient, UnsupportedEndpoint, normalize_url
from .const import DEFAULTS, DOMAIN
from .models import InvalidData


def connection_schema(defaults, mode):
    fields = {
        vol.Required("host", default=defaults.get("host", "https://192.0.2.1")): str,
        vol.Required("site", default=defaults.get("site", "default")): vol.All(
            str, vol.Length(min=1)
        ),
        vol.Required("verify_ssl", default=defaults.get("verify_ssl", True)): bool,
    }
    if mode == "api_key":
        fields[vol.Required("api_key")] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    else:
        fields[vol.Required("username", default=defaults.get("username", ""))] = str
        fields[vol.Required("password")] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    return vol.Schema(fields)


def finite_nonnegative(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise vol.Invalid("Must be finite and nonnegative")
    return value


def options_schema(options):
    return vol.Schema(
        {
            vol.Required("quota_gb", default=options["quota_gb"]): vol.All(
                finite_nonnegative, vol.Range(min=0.001)
            ),
            vol.Required("billing_day", default=options["billing_day"]): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=31)
            ),
            vol.Required("poll_interval", default=options["poll_interval"]): vol.All(
                vol.Coerce(int), vol.Range(min=30, max=3600)
            ),
            vol.Required("initial_used_gb", default=options["initial_used_gb"]): finite_nonnegative,
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.mode = "api_key"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self.mode = user_input["auth_mode"]
            return await self.async_step_connection()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("auth_mode", default=self.mode): vol.In(["api_key", "local"]),
                }
            ),
        )

    async def async_step_connection(self, user_input=None):
        errors = {}
        details = "not_read"
        existing = None
        if self.source in ("reauth", "reconfigure"):
            existing = (
                self._get_reauth_entry()
                if self.source == "reauth"
                else self._get_reconfigure_entry()
            )
        defaults = dict(existing.data) if existing else {}
        if user_input is not None:
            # Keep non-secret fields after errors, without prepopulating secrets.
            defaults.update(
                {
                    key: user_input[key]
                    for key in ("host", "site", "verify_ssl", "username")
                    if key in user_input
                }
            )
            data = dict(user_input, auth_mode=self.mode)
            client = None
            try:
                data["host"] = normalize_url(data["host"])
                # Reauth cannot silently replace the gateway; reconfigure also keeps
                # accounting attached to the same physical gateway/interface.
                if existing:
                    data["gateway_mac"] = existing.data["gateway_mac"]
                    data["interface"] = existing.data["interface"]
                    data["device_endpoint"] = existing.data.get("device_endpoint", "v2")
                client = UniFiClient.create(data)
                if existing:
                    snap = await client.verify()
                else:
                    self.interfaces = await client.discover()
                    data["device_endpoint"] = client.device_endpoint
            except ValueError:
                errors["host"] = "invalid_host"
            except InvalidAuth:
                errors["base"] = (
                    "key_no_counters"
                    if client and client.official_sites_verified
                    else "invalid_auth"
                )
            except UnsupportedEndpoint:
                errors["base"] = "unsupported_endpoint"
            except InvalidData:
                details = client.last_schema_summary if client else "not_read"
                errors["base"] = (
                    "key_incomplete_data"
                    if client and client.official_sites_verified
                    else "invalid_data"
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            finally:
                if client:
                    await client.close()
            if not errors:
                if existing:
                    unique = f"{snap.mac}_{data['site']}_{snap.interface}"
                    await self.async_set_unique_id(unique)
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(existing, data=data)
                self.connection_data = data
                return await self.async_step_interface()
        return self.async_show_form(
            step_id="connection",
            data_schema=connection_schema(defaults, self.mode),
            errors=errors,
            description_placeholders={"details": details},
        )

    async def async_step_interface(self, user_input=None):
        choices = {f"{s.mac}|{s.interface}": s for s in self.interfaces}
        if user_input is not None:
            snap = choices[user_input["wan_interface"]]
            self.connection_data.update(gateway_mac=snap.mac, interface=snap.interface)
            self.entry_title = f"{snap.name}: {snap.networkgroup} / {snap.interface}"
            await self.async_set_unique_id(
                f"{snap.mac}_{self.connection_data['site']}_{snap.interface}"
            )
            self._abort_if_unique_id_configured()
            return await self.async_step_quota()
        preferred = next(
            (key for key, snap in choices.items() if snap.interface == "eth8"), next(iter(choices))
        )
        return self.async_show_form(
            step_id="interface",
            data_schema=vol.Schema(
                {
                    vol.Required("wan_interface", default=preferred): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": key,
                                    "label": f"{snap.name}: {snap.networkgroup} / {snap.interface} ({snap.mac})",
                                }
                                for key, snap in choices.items()
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_quota(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=self.entry_title, data=self.connection_data, options=user_input
            )
        return self.async_show_form(step_id="quota", data_schema=options_schema(DEFAULTS))

    async def async_step_reauth(self, entry_data):
        self.mode = entry_data["auth_mode"]
        return await self.async_step_user()

    async def async_step_reconfigure(self, user_input=None):
        self.mode = self._get_reconfigure_entry().data["auth_mode"]
        return await self.async_step_user()


class OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=options_schema(DEFAULTS | self.config_entry.options)
        )
