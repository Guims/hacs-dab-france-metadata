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

def clean_title(value):
    title = str(value or "").strip()
    if not any(ch.isalpha() for ch in title):
        return ""
    if re.fullmatch(r"[A-Z]{1,5}[-_]?\d+(?:\s*-\s*[A-Z]{1,5}[-_]?\d+)?", title, re.I):
        return ""
    return title[:500]

# Explicit station slugs; no inferred numeric ID or arbitrary client URL.
RADIOKING = {"onde-porteuse": "londeporteuse-paris", "tsugi-radio": "tsugi-radio"}

# Known endpoint shape; station mapping remains experimental.
RADIO_METADATA_IDS = {"france-inter": "franceinter", "france-musique": "francemusique", "fip": "fip"}
_metadata_retry = {}

async def central_title(station):
    # Try explicit aliases, then the catalogue ID, never a caller-provided URL.
    if time.monotonic() < _metadata_retry.get(station, 0):
        return ""
    from urllib.parse import urlencode
    identifier = RADIO_METADATA_IDS.get(station, station)
    if not re.fullmatch(r"[a-z0-9-]{1,100}", identifier):
        return ""
    url = "https://radio-metadata.fr/api?" + urlencode({"id": identifier})
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=PublicResolver()), timeout=aiohttp.ClientTimeout(total=6), trust_env=False) as client:
            async with client.get(url, allow_redirects=False) as response:
                if response.status != 200:
                    _metadata_retry[station] = time.monotonic() + 900
                    return ""
                raw = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    raw.extend(chunk)
                    if len(raw) > 262144:
                        return ""
                import json
                payload = json.loads(raw)
                data = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(data, dict):
                    title = clean_title(data.get("title"))
                    artist = clean_title(data.get("artist"))
                    if title and artist:
                        _LOGGER.debug("Radio-Metadata candidate %s", station)
                        return f"{artist} — {title}"
                _metadata_retry[station] = time.monotonic() + 300
    except Exception as err:
        _metadata_retry[station] = time.monotonic() + 300
        _LOGGER.debug("Radio-Metadata %s: %s", station, type(err).__name__)
    return ""

async def provider_title(station):
    central = await central_title(station)
    if central:
        return central
    slug = RADIOKING.get(station)
    if not slug:
        return ""
    url = f"https://api.radioking.io/widget/radio/{slug}/track/current?format=json"
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=PublicResolver()), timeout=aiohttp.ClientTimeout(total=5), trust_env=False) as client:
            async with client.get(url, allow_redirects=False) as response:
                if response.status != 200:
                    return ""
                raw = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    raw.extend(chunk)
                    if len(raw) > 262144:
                        return ""
                import json
                data = json.loads(raw)
                if not isinstance(data, dict):
                    return ""
                title = clean_title(data.get("title"))
                artist = clean_title(data.get("artist"))
                if title and artist and artist.casefold() not in title.casefold():
                    title = f"{artist} — {title}"
                return title
    except Exception as err:
        _LOGGER.debug("RadioKing %s: %s", station, type(err).__name__)
        return ""

async def async_setup(hass, config):
    if hass.data.get(DOMAIN):
        return True
    session = async_get_clientsession(hass)
    cache = {}
    allowed = {}
    expires = 0
    lock = asyncio.Lock()
    workers = {}
    leases = {}

    async def watch(station, urls):
        def publish(value):
            value = clean_title(value)
            if value:
                cache[station] = (time.monotonic(), value)
                _LOGGER.debug("Metadata available for %s: %r", station, value[:200])
        try:
            while time.monotonic() < leases.get(station, 0):
                api_title = await provider_title(station)
                if api_title:
                    publish(api_title)
                    await asyncio.sleep(60)
                    continue
                for url in urls[:2]:
                    if time.monotonic() >= leases.get(station, 0):
                        break
                    try:
                        await asyncio.wait_for(read_title(url, publish, lambda: leases.get(station, 0) > time.monotonic()), timeout=45)
                    except Exception as err:
                        _LOGGER.debug("Metadata watcher %s: %s", station, type(err).__name__)
                await asyncio.sleep(5)
        finally:
            workers.pop(station, None)
            leases.pop(station, None)
            cache.pop(station, None)
            _LOGGER.debug("Metadata watcher closed: %s", station)

    async def stop_watchers(event):
        tasks = list(workers.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    hass.bus.async_listen_once("homeassistant_stop", stop_watchers)

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
            # Station IDs only; at most three shared background connections.
            leases[station] = time.monotonic() + 95
            if station not in workers:
                if len(workers) >= 3:
                    leases.pop(station, None)
                    connection.send_result(msg["id"], {"title": ""})
                    return
                workers[station] = hass.async_create_background_task(
                    watch(station, allowed[station]), "dab_metadata_" + station)
                _LOGGER.debug("Metadata watcher started: %s", station)
            old = cache.get(station)
            result = old[1] if old and time.monotonic() - old[0] < 90 else ""
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

async def read_title(url, publish, active):
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
    async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=None, connect=5, sock_read=8), trust_env=False) as client:
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
                                if clean_title(title):
                                    publish(title[:500])
                                    return
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
            while active():
                await response.content.readexactly(interval)
                size = (await response.content.readexactly(1))[0] * 16
                raw = await response.content.readexactly(size)
                try:
                    decoded = raw.decode("utf-8")
                except UnicodeDecodeError:
                    decoded = raw.decode("cp1252", errors="replace")
                match = re.search(r"StreamTitle='(.*?)';", decoded, re.S)
                if match and clean_title(match.group(1)):
                    publish(clean_title(match.group(1)))
                elif match and match.group(1).strip():
                    _LOGGER.debug("ICY %s rejected nonalphabetic title", label)
    return ""
