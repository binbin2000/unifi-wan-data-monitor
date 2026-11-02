"""Read-only UniFi client with isolated, fresh session authentication."""

import asyncio
import json
from urllib.parse import quote, urlsplit

import aiohttp

from .models import Snapshot, discover_interfaces, parse_snapshot


class CannotConnect(Exception):
    """Network, HTTP, TLS or protocol error, without sensitive response text."""


class InvalidAuth(Exception):
    """Credentials rejected or session renewal failed."""


class UnsupportedEndpoint(Exception):
    """Device endpoint is not supported."""


def normalize_url(value: str) -> str:
    """HTTPS only; reject embedded credentials, query, fragments and paths."""
    value = value.strip().rstrip("/")
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Enter an HTTPS console origin, without credentials or path")
    _ = parsed.port  # Validate a malformed port.
    return value


class UniFiClient:
    """API key mode never sends credentials as cookies or tries another auth mode."""

    def __init__(self, session: aiohttp.ClientSession, config: dict):
        self.session = session
        self.config = config
        self.origin = normalize_url(config["host"])
        self.logged_in = False
        self.official_sites_verified = False

    @classmethod
    def create(cls, config: dict) -> "UniFiClient":
        config = dict(config, host=normalize_url(config["host"]))
        # Own cookie jar, including IP hosts; never share HA's global session.
        jar = (
            aiohttp.CookieJar(unsafe=True)
            if config["auth_mode"] == "local"
            else aiohttp.DummyCookieJar()
        )
        session = aiohttp.ClientSession(cookie_jar=jar, timeout=aiohttp.ClientTimeout(total=20))
        return cls(session, config)

    async def close(self) -> None:
        await self.session.close()

    async def _request(self, method: str, path: str, **kwargs):
        headers = (
            {"X-API-Key": self.config["api_key"]} if self.config["auth_mode"] == "api_key" else {}
        )
        try:
            async with self.session.request(
                method,
                self.origin + path,
                headers=headers,
                ssl=self.config.get("verify_ssl", True),
                allow_redirects=False,
                **kwargs,
            ) as response:
                if response.status in (401, 403, 499):
                    raise InvalidAuth("Authentication rejected")
                if response.status in (404, 405):
                    raise UnsupportedEndpoint("Endpoint unavailable")
                if response.status != 200:
                    raise CannotConnect(f"HTTP {response.status}")
                # Do not include response bodies, request headers or credentials in errors.
                payload = await response.json()
                if isinstance(payload, dict) and "meta" in payload:
                    meta = payload["meta"]
                    if (
                        isinstance(meta, dict)
                        and meta.get("rc") == "error"
                        and meta.get("msg")
                        in {
                            "api.err.LoginRequired",
                            "api.err.Invalid",
                            "api.err.InvalidCredentials",
                            "api.err.NoPermission",
                        }
                    ):
                        raise InvalidAuth("Authentication rejected")
                    if not isinstance(meta, dict) or meta.get("rc") != "ok":
                        raise CannotConnect("API error envelope")
                return payload
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError):
            raise CannotConnect("Connection, TLS or JSON error") from None

    async def login(self) -> None:
        await self._request(
            "POST",
            "/api/auth/login",
            json={
                "username": self.config["username"],
                "password": self.config["password"],
                "rememberMe": False,
            },
        )
        self.logged_in = True

    async def _fetch_payload(self):
        if self.config["auth_mode"] == "local" and not self.logged_in:
            await self.login()
        site = quote(self.config.get("site", "default"), safe="")
        path = (
            f"/proxy/network/v2/api/site/{site}/device"
            "?separateUnmanaged=true&includeTrafficUsage=true"
        )
        try:
            payload = await self._request("GET", path)
        except InvalidAuth:
            if self.config["auth_mode"] != "local":
                raise
            # Only one renewal attempt per poll. Invalid credentials trigger HA reauth.
            self.logged_in = False
            self.session.cookie_jar.clear()
            await self.login()
            payload = await self._request("GET", path)
        return payload

    async def fetch(self) -> Snapshot:
        return parse_snapshot(
            await self._fetch_payload(),
            self.config.get("gateway_mac", ""),
            self.config.get("interface", "eth8"),
        )

    async def verify(self) -> Snapshot:
        """Do not accept official sites alone as proof of byte-counter access."""
        await self.verify_official_sites()
        return await self.fetch()

    async def verify_official_sites(self):
        if self.config["auth_mode"] == "api_key":
            sites = await self._request("GET", "/proxy/network/integration/v1/sites")
            if not isinstance(sites, dict) or not isinstance(sites.get("data"), list):
                raise CannotConnect("Unexpected official sites response")
            self.official_sites_verified = True

    async def discover(self) -> list[Snapshot]:
        await self.verify_official_sites()
        return discover_interfaces(await self._fetch_payload())
