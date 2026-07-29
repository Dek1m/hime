"""Async HTTP client with proxy rotation."""

import asyncio
import logging
import time

import httpx

from hime.proxy import ProxyData

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
}


class HttpClient:
    """Async HTTP client with proxy rotation and retries."""

    def __init__(
        self,
        max_concurrent: int = 100,
        timeout: float = 15.0,
        retry_count: int = 3,
        retry_delay: float = 1.0,
    ):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._timeout = timeout
        self._retry_count = retry_count
        self._retry_delay = retry_delay

    async def fetch(
        self,
        url: str,
        proxy: ProxyData | None = None,
    ) -> str | None:
        """Fetch URL content. Returns HTML string or None on failure."""
        for attempt in range(self._retry_count):
            try:
                return await self._do_fetch(url, proxy)
            except Exception as e:
                logger.warning(
                    "Fetch attempt %d/%d failed for %s: %s",
                    attempt + 1,
                    self._retry_count,
                    url,
                    e,
                )
                if attempt < self._retry_count - 1:
                    delay = self._retry_delay * (2**attempt)
                    await asyncio.sleep(delay)
        return None

    async def _do_fetch(self, url: str, proxy: ProxyData | None) -> str:
        """Single fetch attempt."""
        proxy_url = proxy.url if proxy else None
        start = time.monotonic()

        async with self._semaphore:
            async with httpx.AsyncClient(
                proxy=proxy_url,
                timeout=self._timeout,
                follow_redirects=True,
                headers=DEFAULT_HEADERS,
            ) as client:
                resp = await client.get(url)
                elapsed_ms = (time.monotonic() - start) * 1000

                if resp.status_code == 429:
                    raise httpx.HTTPStatusError(
                        "Rate limited", request=resp.request, response=resp
                    )
                if resp.status_code >= 400:
                    logger.warning(
                        "HTTP %d from %s via %s (%.0fms)",
                        resp.status_code,
                        url,
                        proxy_url or "direct",
                        elapsed_ms,
                    )
                    return ""

                resp.raise_for_status()
                logger.debug(
                    "GET %s via %s — %d (%.0fms)",
                    url,
                    proxy_url or "direct",
                    resp.status_code,
                    elapsed_ms,
                )
                return resp.text

    async def close(self) -> None:
        """No-op — clients are created per-request."""
