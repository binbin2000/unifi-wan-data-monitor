from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from homeassistant.const import UnitOfInformation
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.unifi_wan_data_monitor.accounting import Accounting
from custom_components.unifi_wan_data_monitor.api import InvalidAuth
from custom_components.unifi_wan_data_monitor.binary_sensor import WanBinarySensor
from custom_components.unifi_wan_data_monitor.config_flow import ConfigFlow, options_schema
from custom_components.unifi_wan_data_monitor.const import DEFAULTS
from custom_components.unifi_wan_data_monitor.coordinator import WanCoordinator
from custom_components.unifi_wan_data_monitor.models import parse_snapshot
from custom_components.unifi_wan_data_monitor.sensor import DESCRIPTIONS, WanSensor


def entry():
    result = MagicMock()
    result.entry_id = "test-entry"
    result.unique_id = "02:00:00:00:00:01_default_eth8"
    result.options = DEFAULTS.copy()
    result.data = {"interface": "eth8"}
    result.pref_disable_polling = False
    return result


async def test_config_flow_discovers_selects_and_creates_entry(hass, payload):
    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    flow.flow_id = "test-flow"
    assert (await flow.async_step_user({"auth_mode": "local"}))["step_id"] == "connection"
    snap = parse_snapshot(payload)
    client = MagicMock(
        device_endpoint="v2",
        discover=AsyncMock(
            return_value=[snap, replace(snap, interface="eth9", networkgroup="WAN")]
        ),
        close=AsyncMock(),
    )
    with patch(
        "custom_components.unifi_wan_data_monitor.config_flow.UniFiClient.create",
        return_value=client,
    ):
        result = await flow.async_step_connection(
            {
                "host": "192.0.2.1",
                "site": "default",
                "username": "test-user",
                "password": "test-password",
                "verify_ssl": True,
            }
        )
    assert result["step_id"] == "interface"
    # Submit through the actual HA schema, rather than skipping its validation.
    wan = f"{snap.name}: WAN / eth9 ({snap.mac})"
    submitted = result["data_schema"]({"wan_interface": wan})
    result = await flow.async_step_interface(submitted)
    assert result["step_id"] == "quota"
    result = await flow.async_step_quota(DEFAULTS.copy())
    assert result["data"]["interface"] == "eth9"
    assert result["data"]["device_endpoint"] == "v2"
    assert result["options"]["quota_gb"] == 100
    client.close.assert_awaited_once()


async def test_interface_picker_serialized_labels_defaults_and_submissions(hass, payload):
    import json
    import voluptuous as vol
    from homeassistant.helpers import config_validation as cv

    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    snap = parse_snapshot(payload)
    flow.interfaces = [snap, replace(snap, interface="eth9", networkgroup="WAN")]
    result = await flow.async_step_interface()
    schema = result["data_schema"]
    try:
        from probatio import to_field_list
    except ImportError:
        from voluptuous_serialize import convert as to_field_list
    wire = json.loads(json.dumps(to_field_list(schema, custom_serializer=cv.custom_serializer)))
    field = wire[0]
    assert field["name"] == "wan_interface"
    options = field["selector"]["select"]["options"]
    assert field["selector"]["select"]["mode"] == "list"
    assert all(isinstance(value, str) for value in options)
    assert field["default"] in options
    assert schema({})["wan_interface"] == field["default"]
    for visible_option in options:
        assert schema({"wan_interface": visible_option})["wan_interface"] == visible_option
    with pytest.raises(vol.Invalid):
        schema({"wan_interface": "not-a-discovered-WAN"})


async def test_flow_rejects_auth_and_closes_session(hass):
    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    client = MagicMock(
        discover=AsyncMock(side_effect=InvalidAuth),
        close=AsyncMock(),
        official_sites_verified=False,
    )
    with patch(
        "custom_components.unifi_wan_data_monitor.config_flow.UniFiClient.create",
        return_value=client,
    ):
        result = await flow.async_step_connection(
            {"host": "192.0.2.1", "site": "default", "api_key": "test-key", "verify_ssl": True}
        )
    assert result["errors"] == {"base": "invalid_auth"}
    client.close.assert_awaited_once()


async def test_coordinator_persists_and_does_not_advance_after_disk_error(hass, payload):
    snap = parse_snapshot(payload)
    client = MagicMock(fetch=AsyncMock(return_value=snap))
    coordinator = WanCoordinator(hass, entry(), client)
    coordinator.store = MagicMock(async_save=AsyncMock(), async_load=AsyncMock(return_value=None))
    await coordinator.load()
    data = await coordinator._async_update_data()
    baseline = coordinator.accounting.state["last"]["rx"]
    assert data["snapshot"] == snap
    coordinator.store.async_save.side_effect = OSError
    client.fetch.return_value = replace(snap, rx=snap.rx + 100)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert coordinator.accounting.state["last"]["rx"] == baseline


@pytest.mark.parametrize(
    "official_verified,expected",
    [
        (True, "key_incomplete_data"),
        (False, "invalid_data"),
    ],
)
async def test_flow_explains_missing_counter_schema(hass, official_verified, expected):
    from custom_components.unifi_wan_data_monitor.models import InvalidData

    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    client = MagicMock(
        discover=AsyncMock(side_effect=InvalidData),
        close=AsyncMock(),
        official_sites_verified=official_verified,
        last_schema_summary="shape=list; devices=0",
    )
    with patch(
        "custom_components.unifi_wan_data_monitor.config_flow.UniFiClient.create",
        return_value=client,
    ):
        result = await flow.async_step_connection(
            {"host": "192.0.2.1", "site": "default", "api_key": "test-key", "verify_ssl": True}
        )
    assert result["errors"]["base"] == expected
    assert result["description_placeholders"]["details"] == "shape=list; devices=0"
    client.close.assert_awaited_once()


async def test_connection_error_retains_address_site_tls_and_username_but_not_password(hass):
    from custom_components.unifi_wan_data_monitor.models import InvalidData

    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    flow.mode = "local"
    client = MagicMock(
        discover=AsyncMock(side_effect=InvalidData),
        close=AsyncMock(),
        official_sites_verified=False,
        last_schema_summary="devices=0",
    )
    with patch(
        "custom_components.unifi_wan_data_monitor.config_flow.UniFiClient.create",
        return_value=client,
    ):
        result = await flow.async_step_connection(
            {
                "host": "https://console.example.test",
                "site": "test-site",
                "username": "test-user",
                "password": "do-not-retain",
                "verify_ssl": False,
            }
        )
    keys = {str(key): key for key in result["data_schema"].schema}
    assert keys["host"].default() == "https://console.example.test"
    assert keys["site"].default() == "test-site"
    assert keys["username"].default() == "test-user"
    assert keys["verify_ssl"].default() is False
    import voluptuous as vol

    assert keys["password"].default is vol.UNDEFINED


async def test_authentication_requests_reauth(hass):
    coordinator = WanCoordinator(hass, entry(), MagicMock(fetch=AsyncMock(side_effect=InvalidAuth)))
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_real_storage_checkpoint_restores_after_restart(hass, payload):
    from datetime import timedelta
    from homeassistant.util import dt as dt_util

    snap = parse_snapshot(payload)
    now = dt_util.now()
    first = WanCoordinator(hass, entry(), MagicMock(fetch=AsyncMock(return_value=snap)))
    with patch(
        "custom_components.unifi_wan_data_monitor.coordinator.dt_util.now", return_value=now
    ):
        await first._async_update_data()
    second = WanCoordinator(
        hass,
        entry(),
        MagicMock(fetch=AsyncMock(return_value=replace(snap, rx=snap.rx + 100, tx=snap.tx + 25))),
    )
    await second.load()
    assert second.accounting.state["last"]["rx"] == snap.rx
    with patch(
        "custom_components.unifi_wan_data_monitor.coordinator.dt_util.now",
        return_value=now + timedelta(seconds=60),
    ):
        result = await second._async_update_data()
    assert result["accounting"]["month_rx"] == 100
    assert result["accounting"]["month_tx"] == 25


async def test_invalid_sample_preserves_previous_checkpoint(hass, payload):
    from custom_components.unifi_wan_data_monitor.models import InvalidData

    client = MagicMock(fetch=AsyncMock(return_value=parse_snapshot(payload)))
    coordinator = WanCoordinator(hass, entry(), client)
    coordinator.store = MagicMock(async_save=AsyncMock())
    await coordinator._async_update_data()
    saved = coordinator.accounting.state.copy()
    client.fetch.side_effect = InvalidData
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert coordinator.accounting.state == saved
    assert coordinator.store.async_save.await_count == 1


async def test_options_flow_shows_and_saves_valid_settings(hass):
    from custom_components.unifi_wan_data_monitor.config_flow import OptionsFlow

    flow = OptionsFlow()
    flow.hass = hass
    with patch.object(
        OptionsFlow,
        "config_entry",
        new_callable=PropertyMock,
        return_value=entry(),
    ):
        result = await flow.async_step_init()
        assert result["step_id"] == "init"
        result = await flow.async_step_init(DEFAULTS | {"billing_day": 15})
    assert result["data"]["billing_day"] == 15


async def test_sensor_values_quota_and_selected_primary_wan(hass, payload):
    snap = parse_snapshot(payload, interface="eth9")
    coordinator = WanCoordinator(hass, entry(), MagicMock())
    a = Accounting()
    from homeassistant.util import dt as dt_util

    a.update(snap, dt_util.now(), 1, 60, 110)
    coordinator.async_set_updated_data({"snapshot": snap, "accounting": a.state})
    sensors = {desc[0]: WanSensor(coordinator, *desc) for desc in DESCRIPTIONS}
    assert sensors["month_used"].native_value == 110_000_000_000
    assert sensors["month_used"].native_unit_of_measurement == UnitOfInformation.BYTES
    assert sensors["remaining"].native_value == 0
    assert sensors["percent"].native_value == 110
    assert "WAN eth9" in sensors["month_used"].name
    assert WanBinarySensor(coordinator, "active", "Selected active").is_on is False
    assert WanBinarySensor(coordinator, "failover", "Secondary active").is_on is True
    assert WanBinarySensor(coordinator, "quota_exceeded", "Quota").is_on is True
    coordinator.async_set_updated_data(
        {"snapshot": replace(snap, active_wan=None), "accounting": a.state}
    )
    assert WanBinarySensor(coordinator, "failover", "Secondary active").is_on is None
    await coordinator.async_shutdown()


@pytest.mark.parametrize(
    "change",
    [
        {"billing_day": 0},
        {"billing_day": 32},
        {"quota_gb": float("nan")},
        {"quota_gb": 0},
        {"poll_interval": 10},
        {"initial_used_gb": -1},
    ],
)
def test_options_reject_invalid_values(change):
    import voluptuous as vol

    with pytest.raises(vol.Invalid):
        options_schema(DEFAULTS)(DEFAULTS | change)
