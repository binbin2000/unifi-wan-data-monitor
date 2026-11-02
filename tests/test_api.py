import json
from unittest.mock import AsyncMock

import aiohttp
import pytest

from custom_components.unifi_wan_data_monitor.api import (
    CannotConnect,
    InvalidAuth,
    UniFiClient,
    UnsupportedEndpoint,
    normalize_url,
)


class Response:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.cookie_jar = aiohttp.CookieJar(unsafe=True)
        self.close = AsyncMock()

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)


def config(mode="api_key"):
    return {
        "host": "https://192.0.2.1",
        "auth_mode": mode,
        "api_key": "test-only-key",
        "username": "test-only-user",
        "password": "test-only-password",
    }


async def test_key_verifies_sites_and_actual_counter_endpoint(payload):
    session = Session([Response(payload={"data": []}), Response(payload=payload)])
    client = UniFiClient(session, config())
    assert (await client.verify()).rx == 10000000000
    assert client.official_sites_verified
    assert "wan_mappings=2" in client.last_schema_summary
    assert all(c[0] == "GET" for c in session.calls)
    assert all(c[2]["headers"] == {"X-API-Key": "test-only-key"} for c in session.calls)
    assert all(c[2]["allow_redirects"] is False for c in session.calls)
    assert "includeTrafficUsage=true" in session.calls[-1][1]


async def test_sites_success_does_not_mask_private_endpoint_rejection():
    session = Session([Response(payload={"data": []}), Response(403)])
    client = UniFiClient(session, config())
    with pytest.raises(InvalidAuth):
        await client.verify()
    assert client.official_sites_verified
    assert len(session.calls) == 2


async def test_local_login_and_one_session_renewal(payload):
    session = Session(
        [Response(payload={}), Response(401), Response(payload={}), Response(payload=payload)]
    )
    client = UniFiClient(session, config("local"))
    await client.fetch()
    assert [c[0] for c in session.calls] == ["POST", "GET", "POST", "GET"]
    assert session.calls[0][1].endswith("/api/auth/login")
    assert session.calls[0][2]["json"]["rememberMe"] is False
    assert all(not c[2]["headers"] for c in session.calls)


async def test_no_infinite_relogin():
    session = Session([Response(payload={}), Response(401), Response(403)])
    client = UniFiClient(session, config("local"))
    with pytest.raises(InvalidAuth):
        await client.fetch()
    assert len(session.calls) == 3


@pytest.mark.parametrize(
    "status,error",
    [
        (401, InvalidAuth),
        (403, InvalidAuth),
        (404, UnsupportedEndpoint),
        (429, CannotConnect),
        (302, CannotConnect),
        (500, CannotConnect),
    ],
)
async def test_http_errors_do_not_echo_secrets(status, error):
    client = UniFiClient(Session([Response(status, {"secret": "do-not-echo"})]), config())
    with pytest.raises(error) as exc:
        await client.fetch()
    assert "do-not-echo" not in str(exc.value)


async def test_invalid_json():
    client = UniFiClient(Session([Response(payload=json.JSONDecodeError("x", "x", 0))]), config())
    with pytest.raises(CannotConnect):
        await client.fetch()


async def test_http_200_login_required_renews_local_session(payload):
    session = Session(
        [
            Response(payload={}),
            Response(payload={"meta": {"rc": "error", "msg": "api.err.LoginRequired"}}),
            Response(payload={}),
            Response(payload=payload),
        ]
    )
    client = UniFiClient(session, config("local"))
    await client.fetch()
    assert [call[0] for call in session.calls] == ["POST", "GET", "POST", "GET"]


async def test_malformed_meta_is_protocol_error():
    client = UniFiClient(Session([Response(payload={"meta": None})]), config())
    with pytest.raises(CannotConnect):
        await client.fetch()


@pytest.mark.parametrize(
    "url",
    [
        "http://192.0.2.1",
        "https://u:p@example.com",
        "https://example.com/path",
        "https://example.com?key=abc",
        "https://example.com/#x",
    ],
)
def test_origin_validation(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_origin_defaults_to_https():
    assert normalize_url("192.0.2.1/") == "https://192.0.2.1"


async def test_discovery_uses_classic_when_v2_has_no_device_records(payload):
    session = Session(
        [
            Response(payload={"data": []}),
            Response(payload={"devices": []}),
            Response(payload={"meta": {"rc": "ok"}, "data": [payload["5"]]}),
            Response(payload=payload),
        ]
    )
    client = UniFiClient(session, config())
    snapshots = await client.discover()
    assert client.device_endpoint == "classic"
    assert {s.counter_source for s in snapshots} == {"classic"}
    assert session.calls[2][1].endswith("/proxy/network/api/s/default/stat/device")
    assert (await client.fetch()).counter_source == "classic"
    assert session.calls[-1][1].endswith("/stat/device")
    assert all(c[0] == "GET" for c in session.calls)


async def test_discovery_does_not_fallback_when_v2_is_valid(payload):
    session = Session(
        [Response(payload={"data": []}), Response(payload={"data": {"devices": [payload["5"]]}})]
    )
    client = UniFiClient(session, config())
    assert len(await client.discover()) == 2
    assert client.device_endpoint == "v2"
    assert len(session.calls) == 2


async def test_discovery_combines_safe_diagnostics_when_both_endpoints_lack_counters():
    from custom_components.unifi_wan_data_monitor.models import InvalidData

    session = Session(
        [
            Response(payload={"data": []}),
            Response(payload={"private": "do-not-echo"}),
            Response(payload={"data": []}),
        ]
    )
    client = UniFiClient(session, config())
    with pytest.raises(InvalidData):
        await client.discover()
    assert "endpoint=v2" in client.last_schema_summary
    assert "endpoint=classic" in client.last_schema_summary
    assert "do-not-echo" not in client.last_schema_summary
    assert "private" not in client.last_schema_summary


async def test_polling_saved_endpoint_never_tries_another_source():
    from custom_components.unifi_wan_data_monitor.models import InvalidData

    session = Session([Response(payload={"data": []})])
    client = UniFiClient(session, config() | {"device_endpoint": "classic"})
    with pytest.raises(InvalidData):
        await client.fetch()
    assert len(session.calls) == 1
    assert session.calls[0][1].endswith("/stat/device")
