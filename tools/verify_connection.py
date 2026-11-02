"""Interactive local probe: credentials are prompted, never CLI arguments or files."""

import argparse
import asyncio
from getpass import getpass
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
for name, path in [
    ("custom_components", ROOT / "custom_components"),
    ("custom_components.unifi_wan_data_monitor", ROOT / "custom_components/unifi_wan_data_monitor"),
]:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module

from custom_components.unifi_wan_data_monitor.api import (  # noqa: E402
    CannotConnect,
    InvalidAuth,
    UniFiClient,
    UnsupportedEndpoint,
)
from custom_components.unifi_wan_data_monitor.models import InvalidData  # noqa: E402


async def main(args):
    config = {
        "host": args.host,
        "site": args.site,
        "auth_mode": args.mode,
        "verify_ssl": not args.insecure,
    }
    if args.mode == "api_key":
        config["api_key"] = getpass("Local API key (hidden): ")
    else:
        config["username"] = input("Local UniFi username: ")
        config["password"] = getpass("Local password (hidden): ")
    client = UniFiClient.create(config)
    try:
        snapshots = await client.discover()
        print("Authentication and internal device endpoint verified.")
        for snap in snapshots:
            print(
                f"{snap.networkgroup}/{snap.interface}: RX={snap.rx} B, TX={snap.tx} B; "
                f"active WAN={snap.active_wan or 'unknown'}"
            )
        return 0
    except InvalidAuth:
        if client.official_sites_verified:
            print(
                "API key works for official sites, but not for internal port counters. "
                "Try --mode local with a dedicated local account."
            )
        else:
            print("Authentication rejected. Check local credentials and permissions.")
    except UnsupportedEndpoint:
        print("Endpoint unavailable on this console/version.")
    except InvalidData:
        print("Endpoint answered, but no unambiguous WAN byte counters were found.")
    except CannotConnect:
        print("Connection/TLS/HTTP/JSON failed. No response body was logged.")
    finally:
        await client.close()
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="https://192.0.2.1")
    parser.add_argument("--site", default="default")
    parser.add_argument("--mode", choices=["api_key", "local"], default="api_key")
    parser.add_argument(
        "--insecure", action="store_true", help="Disable TLS verification explicitly"
    )
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(main(args)))
    except (ValueError, KeyboardInterrupt):
        print("Invalid console URL or cancelled.")
        raise SystemExit(2) from None
