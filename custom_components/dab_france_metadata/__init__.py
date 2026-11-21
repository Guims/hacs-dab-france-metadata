"""Optional metadata integration."""
import asyncio
import logging
import re
import time
from urllib.parse import urlsplit, urlunsplit, urljoin

import aiohttp
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.helpers.aiohttp_client import async_get_clientsession

DOMAIN = "dab_france_metadata"
_LOGGER = logging.getLogger(__name__)
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
                        result = await asyncio.wait_for(read_title(url), timeout=10)
                    except Exception as err:
                        _LOGGER.debug('Metadata station %s: %s', station, type(err).__name__)
                        continue
                    if result and any(ch.isalpha() for ch in result):
                        _LOGGER.debug("Metadata available for %s", station)
                        break
                    result = ""
                _LOGGER.debug("Metadata lookup %s: %s", station, bool(result))
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

async def checked_stream(client, url):
    import ipaddress
    for hop in range(4):
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            raise ValueError('Unsafe redirect')
        try:
            ip = ipaddress.ip_address(parts.hostname)
        except ValueError:
            ip = None
        if ip is not None and not ip.is_global:
            raise ValueError('Non-public redirect')
        response = await client.get(url, headers={'Icy-MetaData': '1'}, allow_redirects=False)
        if response.status not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get('Location')
        response.release()
        if not location or hop == 3:
            raise ValueError('Redirect limit or missing location')
        url = urljoin(url, location)
        target = urlsplit(url)
        _LOGGER.debug('ICY redirect to %s', urlunsplit((target.scheme, target.hostname or '', target.path, '', '')))
    raise ValueError('Redirect limit')

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
    label = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    _LOGGER.debug("Metadata probing %s", label)
    connector = aiohttp.TCPConnector(resolver=PublicResolver())
    async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=10), trust_env=False) as client:
        status_url = urlunsplit((parts.scheme, parts.netloc, "/status-json.xsl", "", ""))
        try:
            async with client.get(status_url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=3)) as response:
                _LOGGER.debug("Icecast %s HTTP %s", label, response.status)
                if response.status == 200:
                    raw = await response.content.read(262145)
                    # Read to EOF with a strict size ceiling.
                    while len(raw) <= 262144 and not response.content.at_eof():
                        chunk = await response.content.read(262145 - len(raw))
                        if not chunk:
                            break
                        raw += chunk
                    if len(raw) <= 262144:
                        import json
                        sources = json.loads(raw).get("icestats", {}).get("source", [])
                        if isinstance(sources, dict):
                            sources = [sources]
                        for source in sources:
                            if urlsplit(str(source.get("listenurl", ""))).path == parts.path:
                                title = " — ".join(str(source.get(k) or "").strip() for k in ("artist", "title") if source.get(k))
                                _LOGGER.debug("Icecast %s title=%r", label, title[:200])
                                if any(ch.isalpha() for ch in title):
                                    return title[:500]
                        _LOGGER.debug("Icecast %s no usable matching title", label)
        except Exception as err:
            _LOGGER.debug("Icecast %s unavailable: %s", label, type(err).__name__)
        async with await checked_stream(client, url) as response:
            _LOGGER.debug('ICY %s HTTP %s content-type=%r icy-metaint=%r', label, response.status, response.headers.get('Content-Type'), response.headers.get('icy-metaint'))
            if response.status != 200:
                _LOGGER.debug('ICY %s rejected HTTP status', label)
                return ""
            interval = int(response.headers.get("icy-metaint", "0"))
            if not 0 < interval <= 524288:
                _LOGGER.debug("ICY %s missing or invalid metadata interval", label)
                return ""
            for _ in range(8):
                await response.content.readexactly(interval)
                size = (await response.content.readexactly(1))[0] * 16
                raw = await response.content.readexactly(size)
                try:
                    decoded = raw.decode("utf-8")
                except UnicodeDecodeError:
                    decoded = raw.decode("cp1252", errors="replace")
                match = re.search(r"StreamTitle='(.*?)';", decoded, re.S)
                _LOGGER.debug('ICY %s StreamTitle=%r metadata_bytes=%s', label, match.group(1)[:200] if match else None, size)
                if match and any(ch.isalpha() for ch in match.group(1)):
                    return match.group(1).strip()[:500]
                _LOGGER.debug("ICY %s rejected empty or nonalphabetic title", label)
    return ""
