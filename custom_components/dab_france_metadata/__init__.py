"""Optional metadata integration."""
import asyncio
import re
import time
from urllib.parse import urlsplit

import aiohttp
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.helpers.aiohttp_client import async_get_clientsession

DOMAIN = "dab_france_metadata"
CATALOG = "https://raw.githubusercontent.com/Guims/hacs-dab-france/main/catalog/stations.json"

async def async_setup(hass, config):
    if hass.data.get(DOMAIN):
        return True
    session = async_get_clientsession(hass)
    cache = {}
    allowed = {}
    expires = 0
    lock = asyncio.Lock()
    slots = asyncio.Semaphore(3)

    @websocket_api.websocket_command({vol.Required("type"): DOMAIN + "/title", vol.Required("station"): str})
    @websocket_api.async_response
    async def title(hass, connection, msg):
        nonlocal allowed, expires
        station = msg["station"]
        try:
            async with lock:
                if time.monotonic() > expires:
                    async with session.get(CATALOG, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        response.raise_for_status()
                        data = await response.json(content_type=None)
                    allowed = {s["id"]: [t["url"] for t in s["streams"] if t.get("ok") and t["url"].startswith("https://")] for s in data["stations"]}
                    expires = time.monotonic() + 300
            if station not in allowed:
                connection.send_error(msg["id"], "unknown_station", "Station inconnue")
                return
            # Never accept a caller-supplied URL. Restrict outbound connections to
            # the public catalogue; disable redirects and reject private DNS results.
            async with slots:
                old = cache.get(station)
                if old and time.monotonic() - old[0] < 25:
                    connection.send_result(msg["id"], {"title": old[1]})
                    return
                result = ""
                for url in allowed[station][:2]:
                    try:
                        result = await read_title(url)
                    except Exception:
                        continue
                    if result:
                        break
                cache[station] = (time.monotonic(), result)
            connection.send_result(msg["id"], {"title": result})
        except Exception:
            connection.send_error(msg["id"], "metadata_unavailable", "Métadonnées indisponibles")

    websocket_api.async_register_command(hass, title)
    hass.data[DOMAIN] = True
    return True

async def async_setup_entry(hass, entry):
    return await async_setup(hass, {})

class PublicResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host, port=0, family=0):
        import socket
        import ipaddress
        entries = await asyncio.get_running_loop().getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)
        result = []
        for fam, _, proto, _, addr in entries:
            if not ipaddress.ip_address(addr[0]).is_global:
                raise ValueError("Non-public address")
            result.append(dict(hostname=host, host=addr[0], port=port, family=fam, proto=proto, flags=0))
        return result

    async def close(self):
        pass

async def read_title(url):
    import ipaddress
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or not parts.hostname:
        return ""
    try:
        address = ipaddress.ip_address(parts.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return ""
    connector = aiohttp.TCPConnector(resolver=PublicResolver())
    async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=10), trust_env=False) as client:
        async with client.get(url, headers={"Icy-MetaData": "1"}, allow_redirects=False) as response:
            if response.status != 200:
                return ""
            interval = int(response.headers.get("icy-metaint", "0"))
            if not 0 < interval <= 524288:
                return ""
            for _ in range(3):
                await response.content.readexactly(interval)
                size = (await response.content.readexactly(1))[0] * 16
                raw = await response.content.readexactly(size)
                try:
                    decoded = raw.decode("utf-8")
                except UnicodeDecodeError:
                    decoded = raw.decode("cp1252", errors="replace")
                match = re.search(r"StreamTitle='(.*?)';", decoded, re.S)
                if match and match.group(1).strip():
                    return match.group(1).strip()[:500]
    return ""
