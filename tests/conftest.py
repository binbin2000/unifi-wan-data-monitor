"""Load protocol/accounting modules without importing the Home Assistant adapter."""

import json
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "custom_components.unifi_wan_data_monitor"
for name, path in [
    ("custom_components", ROOT / "custom_components"),
    (PACKAGE, ROOT / "custom_components/unifi_wan_data_monitor"),
]:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


@pytest.fixture
def payload():
    return json.loads((ROOT / "tests/fixtures/udm_pro.json").read_text())
