"""Adapter tests use actual Home Assistant classes, never HA stand-ins."""

import asyncio
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def payload():
    return json.loads((ROOT / "tests/fixtures/udm_pro.json").read_text())


@pytest.fixture
async def hass(tmp_path):
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntries

    instance = HomeAssistant(str(tmp_path))
    instance.config_entries = ConfigEntries(instance, {})
    await instance.config.async_set_time_zone("Europe/Stockholm")
    yield instance
    await instance.async_stop(force=True)
    await asyncio.sleep(0)
