"""Load proxies from GitHub raw sources."""

import asyncio
import logging
import re
from typing import Optional

import httpx

from hime.config import load_config
from hime.proxy import ProxyData, ProxyType

logger = logging.getLogger(__name__)

_RAW_BASE = "https://raw.githubusercontent.com"

_DEFAULT_SOURCES: dict[str, list[str]] = {
    f"{_RAW_BASE}/TheSpeedX/SOCKS-List/master/http.txt": "http",
    f"{_RAW_BASE}/TheSpeedX/SOCKS-List/master/socks5.txt": "socks5",
    f"{_RAW_BASE}/ShiftyTR/Proxy-List/master/http.txt": "http",
    f"{_RAW_BASE}/ShiftyTR/Proxy-List/master/https.txt": "https",
    f"{_RAW_BASE}/monosans/proxy-list/main/proxies/http.txt": "http",
    f"{_RAW_BASE}/monosans/proxy-list/main/proxies/socks5.txt": "socks5",
    f"{_RAW_BASE}/clarketm/proxy-list/master/proxy-list-raw.txt": "http",
}

_PORT_RE = re.compile(r":(\d{2,5})$")


def _detect_type(line: str, fallback: str) -> Optional[ProxyType]:
    """Detect proxy type from line content or fallback hint."""
    lower = line.lower()
    if lower.startswith("socks5://"):
        return ProxyType.SOCKS5
    if lower.startswith("https://"):
        return ProxyType.HTTPS
    if lower.startswith("http://"):
        return ProxyType.HTTP
    mapping = {"http": ProxyType.HTTP, "https": ProxyType.HTTPS, "socks5": ProxyType.SOCKS5}
    return mapping.get(fallback)


def _parse_line(line: str, fallback_type: str) -> Optional[ProxyData]:
    """Parse a single proxy line into ProxyData.

    Formats supported:
        ip:port
        protocol://ip:port
        ip port
    """
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("//"):
        return None

    proxy_type = _detect_type(line, fallback_type)
    if proxy_type is None:
        return None

    # Strip protocol prefix if present
    for prefix in ("socks5://", "https://", "http://"):
        if line.lower().startswith(prefix):
            line = line[len(prefix) :]
            break

    # ip port (space-separated)
    parts = line.split()
    if len(parts) == 2 and parts[1].isdigit():
        ip = parts[0]
        port = int(parts[1])
        if 1 <= port <= 65535:
            return ProxyData(ip=ip, port=port, type=proxy_type)
        return None

    # ip:port
    match = _PORT_RE.search(line)
    if match:
        port = int(match.group(1))
        ip = line[: match.start()]
        if ip and 1 <= port <= 65535:
            return ProxyData(ip=ip, port=port, type=proxy_type)

    return None


async def _fetch_source(
    client: httpx.AsyncClient, url: str, fallback_type: str
) -> list[ProxyData]:
    """Fetch and parse a single source URL."""
    try:
        resp = await client.get(url, timeout=15.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP %s from %s", exc.response.status_code, url)
        return []
    except httpx.RequestError as exc:
        logger.warning("Network error fetching %s: %s", url, exc)
        return []

    proxies: list[ProxyData] = []
    for raw_line in resp.text.splitlines():
        proxy = _parse_line(raw_line, fallback_type)
        if proxy is not None:
            proxies.append(proxy)
    logger.info("Fetched %d proxies from %s", len(proxies), url)
    return proxies


async def load_all_proxies() -> list[ProxyData]:
    """Load proxies from all configured GitHub sources.

    Returns deduplicated list of ProxyData sorted by (ip, port).
    """
    config = load_config()
    sources = config.proxy.proxy_sources

    # Merge user sources with defaults (user sources take precedence)
    source_map: dict[str, str] = {}
    for url in sources:
        if url in _DEFAULT_SOURCES:
            source_map[url] = _DEFAULT_SOURCES[url]
        else:
            # Unknown source — default to http
            source_map[url] = "http"

    if not source_map:
        logger.warning("No proxy sources configured")
        return []

    logger.info("Loading proxies from %d sources...", len(source_map))

    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [
            _fetch_source(client, url, ftype) for url, ftype in source_map.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten and deduplicate
    seen: set[tuple[str, int]] = set()
    unique: list[ProxyData] = []
    for result in results:
        if isinstance(result, Exception):
            logger.error("Source fetch failed: %s", result)
            continue
        for proxy in result:
            key = (proxy.ip, proxy.port)
            if key not in seen:
                seen[key] = True
                unique.append(proxy)

    unique.sort(key=lambda p: (p.ip, p.port))
    logger.info("Loaded %d unique proxies from %d sources", len(unique), len(source_map))
    return unique
