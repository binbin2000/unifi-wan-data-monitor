"""Strict parsing of the internal UniFi device response (no HA dependency)."""

from dataclasses import dataclass
import re
from typing import Any


class InvalidData(Exception):
    """Unsupported or incomplete payload. Never replace missing counters with zero."""


@dataclass(frozen=True)
class Snapshot:
    mac: str
    name: str
    model: str
    firmware: str
    interface: str
    rx: int
    tx: int
    uptime: int | None
    link: bool | None
    active_wan: str | None
    reported_at: int | None = None
    networkgroup: str = "WAN2"


def devices(payload: Any) -> list[dict]:
    """Accept lists, a data wrapper, a single device or numeric-keyed maps."""
    if isinstance(payload, dict):
        if "meta" in payload:
            if not isinstance(payload["meta"], dict) or payload["meta"].get("rc") != "ok":
                raise InvalidData("API reported an error")
        if "data" in payload:
            return devices(payload["data"])
        if "port_table" in payload:
            return [payload]
        payload = list(payload.values())
    if not isinstance(payload, list):
        raise InvalidData("Expected device list")
    return [d for d in payload if isinstance(d, dict) and "port_table" in d]


def counter(value: Any) -> int:
    """Require integer bytes. Floats, negative and missing values are invalid."""
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if type(value) is not int or value < 0:
        raise InvalidData("Invalid port byte counter")
    return value


def is_wan(group: Any) -> bool:
    return isinstance(group, str) and re.fullmatch(r"WAN\d*", group) is not None


def records(device: dict, key: str) -> list:
    value = device.get(key, [])
    if not isinstance(value, list):
        raise InvalidData("Invalid interface table")
    return value


def schema_summary(payload: Any) -> str:
    """Only fixed labels and counts; never echo device keys, identifiers or values."""
    shape = (
        "object" if isinstance(payload, dict) else "list" if isinstance(payload, list) else "other"
    )
    try:
        entries = devices(payload)
    except InvalidData:
        entries = []
    ports = mappings = counters = identifiers = malformed = 0
    for device in entries:
        identifiers += bool(device.get("mac"))
        overrides = device.get("ethernet_overrides")
        table = device.get("port_table")
        if not isinstance(overrides, list) or not isinstance(table, list):
            malformed += 1
        if isinstance(overrides, list):
            mappings += sum(
                isinstance(p, dict) and is_wan(p.get("networkgroup")) for p in overrides
            )
        if isinstance(table, list):
            for port in table:
                if not isinstance(port, dict):
                    continue
                ports += 1
                try:
                    counter(port.get("rx_bytes"))
                    counter(port.get("tx_bytes"))
                except InvalidData:
                    continue
                counters += 1
    return (
        f"shape={shape}; devices={len(entries)}; with_mac={identifiers}; "
        f"ports={ports}; rx_tx_pairs={counters}; wan_mappings={mappings}; "
        f"incomplete_tables={malformed}"
    )


def discover_interfaces(payload: Any) -> list[Snapshot]:
    """Offer only WAN interfaces with real, valid byte counters."""
    found = []
    for device in devices(payload):
        # APs/switches can have null/absent override tables. They must not prevent
        # discovery of a different gateway with valid WAN counters.
        overrides = device.get("ethernet_overrides")
        if not isinstance(overrides, list):
            continue
        for override in overrides:
            if isinstance(override, dict) and is_wan(override.get("networkgroup")):
                try:
                    found.append(
                        parse_snapshot([device], str(device.get("mac", "")), override["ifname"])
                    )
                except (InvalidData, KeyError):
                    continue
    if not found:
        raise InvalidData("No readable WAN interfaces found")
    identities = [(s.mac, s.interface) for s in found]
    if len(set(identities)) != len(identities):
        raise InvalidData("Ambiguous WAN interface mapping")
    return found


def parse_snapshot(payload: Any, mac: str = "", interface: str = "eth8") -> Snapshot:
    candidates = []
    for device in devices(payload):
        if mac and str(device.get("mac", "")).lower() != mac.lower():
            continue
        groups = {
            p.get("ifname"): p.get("networkgroup")
            for p in records(device, "ethernet_overrides")
            if isinstance(p, dict)
        }
        # Never silently monitor a LAN interface after a port reassignment.
        if is_wan(groups.get(interface)):
            candidates.append((device, groups))
    if len(candidates) != 1:
        raise InvalidData("Expected exactly one gateway with selected WAN interface")
    device, groups = candidates[0]
    ports = [
        p
        for p in records(device, "port_table")
        if isinstance(p, dict) and p.get("ifname") == interface
    ]
    if len(ports) != 1 or not device.get("mac"):
        raise InvalidData("Missing or ambiguous WAN port")
    port = ports[0]
    # uplink.name in the supplied UDM-Pro fixture identifies the active WAN.
    # Link-up and traffic alone do not establish that failover is active.
    uplink = device.get("uplink")
    active_name = uplink.get("name") if isinstance(uplink, dict) else None
    active = groups.get(active_name)
    if not is_wan(active):
        active = None
    stats = device.get("system-stats")
    uptime = device.get("uptime", stats.get("uptime") if isinstance(stats, dict) else None)
    if type(uptime) is not int or uptime < 0:
        uptime = None
    link = port.get("up") if type(port.get("up")) is bool else None
    return Snapshot(
        str(device["mac"]).lower(),
        str(device.get("name", "UDM Pro")),
        str(device.get("model", "UDMPRO")),
        str(device.get("version", "")),
        interface,
        counter(port.get("rx_bytes")),
        counter(port.get("tx_bytes")),
        uptime,
        link,
        active,
        device.get("last_seen") if type(device.get("last_seen")) is int else None,
        groups[interface],
    )
