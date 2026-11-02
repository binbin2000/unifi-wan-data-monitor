"""Check installable metadata and user-visible error translations."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/unifi_wan_data_monitor"


def test_package_metadata_and_translations():
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["domain"] == COMPONENT.name
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_polling"
    assert manifest["version"] == "0.1.1"
    assert (COMPONENT / "brand/icon.png").is_file()
    keys = {
        "invalid_host",
        "invalid_auth",
        "key_no_counters",
        "unsupported_endpoint",
        "invalid_data",
        "cannot_connect",
    }
    for language in ("sv", "en"):
        translation = json.loads(
            (COMPONENT / f"translations/{language}.json").read_text(encoding="utf-8")
        )
        assert keys <= translation["config"]["error"].keys()
        assert "interface" in translation["config"]["step"]
        assert "init" in translation["options"]["step"]


def test_all_component_python_parses_and_only_login_posts():
    for path in COMPONENT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_request"
            ):
                method = ast.literal_eval(node.args[0])
                assert method in ("GET", "POST")
                if method == "POST":
                    assert ast.literal_eval(node.args[1]) == "/api/auth/login"
