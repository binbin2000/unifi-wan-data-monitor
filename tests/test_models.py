from copy import deepcopy

import pytest

from custom_components.unifi_wan_data_monitor.models import (
    InvalidData,
    discover_interfaces,
    parse_snapshot,
    schema_summary,
)


def test_supplied_shape_and_active_wan(payload):
    snap = parse_snapshot(payload)
    assert (snap.interface, snap.rx, snap.tx) == ("eth8", 10000000000, 500000000)
    assert snap.active_wan == "WAN2"
    assert snap.link is True


@pytest.mark.parametrize("shape", ["list", "wrapper", "single"])
def test_envelopes(payload, shape):
    device = payload["5"]
    inputs = {
        "list": [device],
        "wrapper": {"meta": {"rc": "ok"}, "data": [device]},
        "single": device,
    }
    assert parse_snapshot(inputs[shape]).rx == 10000000000


@pytest.mark.parametrize("value", [None, -1, 2.5, True, "NaN", "1e9"])
def test_invalid_counters_fail_instead_of_zero(payload, value):
    payload["5"]["port_table"][2]["rx_bytes"] = value
    with pytest.raises(InvalidData):
        parse_snapshot(payload)


def test_string_counter_and_unknown_active(payload):
    payload["5"]["port_table"][2]["rx_bytes"] = "10000000000"
    del payload["5"]["uplink"]
    assert parse_snapshot(payload).active_wan is None
    assert parse_snapshot(payload).rx == 10000000000


def test_link_does_not_mean_failover(payload):
    payload["5"]["uplink"]["name"] = "eth9"
    assert parse_snapshot(payload).link
    assert parse_snapshot(payload).active_wan == "WAN"


def test_multiple_gateways_requires_mac(payload):
    payload["6"] = deepcopy(payload["5"])
    payload["6"]["mac"] = "02:00:00:00:00:02"
    with pytest.raises(InvalidData):
        parse_snapshot(payload)
    assert parse_snapshot(payload, mac="02:00:00:00:00:02").mac.endswith("02")


def test_wrong_port_mapping_is_rejected(payload):
    payload["5"]["ethernet_overrides"][1]["networkgroup"] = "LAN"
    with pytest.raises(InvalidData):
        parse_snapshot(payload)


def test_discovery_lists_all_wans_but_no_lan(payload):
    choices = discover_interfaces(payload)
    assert {(s.interface, s.networkgroup) for s in choices} == {("eth8", "WAN2"), ("eth9", "WAN")}
    assert parse_snapshot(payload, interface="eth9").rx == 0


def test_discovery_allows_third_wan(payload):
    payload["5"]["ethernet_overrides"].append({"ifname": "eth7", "networkgroup": "WAN3"})
    payload["5"]["port_table"].append({"ifname": "eth7", "rx_bytes": 100, "tx_bytes": 50})
    assert any(s.interface == "eth7" for s in discover_interfaces(payload))


@pytest.mark.parametrize("key", ["port_table", "ethernet_overrides"])
def test_null_tables_are_schema_errors(payload, key):
    payload["5"][key] = None
    with pytest.raises(InvalidData):
        parse_snapshot(payload)


def test_null_uplink_is_unknown_not_a_failure(payload):
    payload["5"]["uplink"] = None
    assert parse_snapshot(payload).active_wan is None


def test_unrelated_null_overrides_do_not_hide_valid_gateway(payload):
    unrelated = {"mac": "02:00:00:00:00:ff", "port_table": [], "ethernet_overrides": None}
    entries = [unrelated, payload["5"]]
    assert {s.interface for s in discover_interfaces(entries)} == {"eth8", "eth9"}


def test_invalid_wan_on_another_device_does_not_hide_valid_gateway(payload):
    unrelated = deepcopy(payload["5"])
    unrelated["mac"] = "02:00:00:00:00:ff"
    unrelated["port_table"] = None
    assert len(discover_interfaces([unrelated, payload["5"]])) == 2


def test_schema_diagnostics_do_not_echo_response_data(payload):
    payload["secret-root-key"] = {"password": "must-not-leak", "mac": "must-not-leak"}
    payload["5"]["name"] = "must-not-leak"
    payload["5"]["token"] = "must-not-leak"
    summary = schema_summary(payload)
    assert "devices=1" in summary
    assert "wan_mappings=2" in summary
    assert "rx_tx_pairs=3" in summary
    assert "must-not-leak" not in summary
    assert "secret-root-key" not in summary
    assert payload["5"]["mac"] not in summary
    assert str(payload["5"]["port_table"][2]["rx_bytes"]) not in summary


def test_empty_or_unsupported_response_has_safe_zero_device_diagnostic():
    assert "devices=0" in schema_summary([])
    assert "devices=0" in schema_summary({"unrecognized": "must-not-leak"})
