"""Real aiohttp transport against a local disposable server, no UniFi secrets."""

from aiohttp import web

from custom_components.unifi_wan_data_monitor.api import UniFiClient


async def test_real_local_login_cookie_is_owned_by_integration(payload):
    calls = []

    async def login(request):
        body = await request.json()
        assert body == {"username": "test-user", "password": "test-password", "rememberMe": False}
        assert request.cookies == {}
        calls.append("login")
        response = web.json_response({})
        response.set_cookie("test_session", "test-only-session", httponly=True)
        return response

    async def devices(request):
        assert request.cookies.get("test_session") == "test-only-session"
        assert "X-API-Key" not in request.headers
        calls.append("devices")
        return web.json_response(payload)

    app = web.Application()
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/proxy/network/v2/api/site/default/device", devices)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    client = UniFiClient.create(
        {
            "host": "https://192.0.2.1",
            "auth_mode": "local",
            "username": "test-user",
            "password": "test-password",
        }
    )
    # HTTP is allowed only by overriding the test transport origin, never config input.
    client.origin = f"http://127.0.0.1:{port}"
    try:
        snapshots = await client.discover()
        assert len(snapshots) == 2
        await client.fetch()
        assert calls == ["login", "devices", "devices"]
    finally:
        await client.close()
        await runner.cleanup()


async def test_real_key_transport_never_uses_cookies(payload):
    async def sites(request):
        assert request.headers["X-API-Key"] == "test-key"
        response = web.json_response({"data": []})
        response.set_cookie("ignored_cookie", "test-value")
        return response

    async def devices(request):
        assert request.headers["X-API-Key"] == "test-key"
        assert not request.cookies
        return web.json_response(payload)

    app = web.Application()
    app.router.add_get("/proxy/network/integration/v1/sites", sites)
    app.router.add_get("/proxy/network/v2/api/site/default/device", devices)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    client = UniFiClient.create(
        {"host": "https://192.0.2.1", "auth_mode": "api_key", "api_key": "test-key"}
    )
    client.origin = f"http://127.0.0.1:{port}"
    try:
        assert (await client.verify()).networkgroup == "WAN2"
    finally:
        await client.close()
        await runner.cleanup()
