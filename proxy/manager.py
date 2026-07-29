"""Proxy manager with round-robin rotation, health checks, and rate limiting."""

import asyncio
import itertools
import logging
import time
from typing import TYPE_CHECKING, Optional

import httpx

from hime.config import ProxyConfig
from hime.proxy import ProxyData, ProxyStatus

if TYPE_CHECKING:
    from hime.storage import ProxyStore

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter per proxy.

    Allows 1 request per proxy every `refill_interval` seconds.
    """

    def __init__(self, refill_interval: float = 300.0):
        self._refill_interval = refill_interval
        self._last_used: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def can_proceed(self, proxy_url: str) -> bool:
        """Check if proxy can be used now."""
        async with self._lock:
            now = time.monotonic()
            last = self._last_used.get(proxy_url, 0.0)
            if now - last >= self._refill_interval:
                self._last_used[proxy_url] = now
                return True
            return False

    async def wait_time(self, proxy_url: str) -> float:
        """Get seconds to wait before proxy can be used."""
        now = time.monotonic()
        last = self._last_used.get(proxy_url, 0.0)
        elapsed = now - last
        if elapsed >= self._refill_interval:
            return 0.0
        return self._refill_interval - elapsed


class ProxyChecker:
    """Health checker for proxies."""

    def __init__(self, timeout: float = 5.0, test_url: str = "https://httpbin.org/ip"):
        self._timeout = timeout
        self._test_url = test_url

    async def check(self, proxy: ProxyData) -> tuple[bool, float]:
        """
        Check if proxy is alive.

        Returns (alive, response_time_ms).
        """
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                proxy=proxy.url,
                timeout=self._timeout,
                follow_redirects=False,
            ) as client:
                resp = await client.get(self._test_url)
                elapsed_ms = (time.monotonic() - start) * 1000
                alive = resp.status_code == 200
                return alive, elapsed_ms
        except Exception:
            elapsed_ms = (time.monotonic() - start) * 1000
            return False, elapsed_ms


class ProxyManager:
    """
    Proxy manager with round-robin rotation.

    Features:
    - Round-robin rotation through active proxies
    - Background health checks
    - Rate limiting per proxy
    - Automatic dead proxy removal
    """

    def __init__(self, config: ProxyConfig):
        self._config = config
        self._proxies: list[ProxyData] = []
        self._active_cycle: Optional[itertools.cycle] = None
        self._lock = asyncio.Lock()
        self._rate_limiter = RateLimiter(refill_interval=300.0)
        self._checker = ProxyChecker(
            timeout=config.health_check_timeout,
            test_url=config.health_check_url,
        )
        self._check_task: Optional[asyncio.Task] = None
        self._stats = {"requests": 0, "failures": 0, "cache_hits": 0}
        self._store: Optional["ProxyStore"] = None

    async def start(
        self, proxies: list[ProxyData], store: Optional["ProxyStore"] = None
    ) -> None:
        """Initialize and start background health checks."""
        self._proxies = proxies
        self._store = store
        self._rebuild_cycle()
        self._check_task = asyncio.create_task(self._health_check_loop())
        logger.info(
            "ProxyManager started with %d proxies (%d active)",
            len(self._proxies),
            len([p for p in self._proxies if p.status == ProxyStatus.ACTIVE]),
        )

    async def stop(self) -> None:
        """Stop background tasks."""
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass

    async def get_proxy(self) -> Optional[ProxyData]:
        """
        Get next available proxy using round-robin.

        Returns None if no proxy is available.
        """
        async with self._lock:
            if not self._active_cycle:
                return None

            attempts = 0
            while attempts < len(self._proxies):
                proxy = next(self._active_cycle)
                if proxy.is_available:
                    can_use = await self._rate_limiter.can_proceed(proxy.url)
                    if can_use:
                        self._stats["requests"] += 1
                        return proxy
                attempts += 1

            # All proxies busy or dead
            return None

    async def report_success(self, proxy: ProxyData, response_time_ms: float) -> None:
        """Report successful request."""
        async with self._lock:
            proxy.mark_success(response_time_ms)
            if self._store:
                self._store.update_last_used(proxy)

    async def report_failure(self, proxy: ProxyData) -> None:
        """Report failed request."""
        async with self._lock:
            proxy.mark_failure()
            self._stats["failures"] += 1
            if proxy.failure_count >= self._config.max_failures:
                logger.warning(
                    "Proxy %s marked dead after %d failures",
                    proxy.url,
                    proxy.failure_count,
                )
                self._rebuild_cycle()
            if self._store:
                self._store.upsert(proxy)

    def _rebuild_cycle(self) -> None:
        """Rebuild round-robin cycle with active proxies."""
        active = [p for p in self._proxies if p.is_available]
        self._active_cycle = itertools.cycle(active) if active else None

    async def _health_check_loop(self) -> None:
        """Background health check every N seconds."""
        while True:
            try:
                await asyncio.sleep(self._config.check_interval)
                await self._run_health_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health check error: %s", e)

    async def _run_health_checks(self) -> None:
        """Run health checks on all proxies."""
        logger.info("Running health checks on %d proxies...", len(self._proxies))

        # Check in batches of 50
        batch_size = 50
        for i in range(0, len(self._proxies), batch_size):
            batch = self._proxies[i : i + batch_size]
            tasks = [self._check_one(p) for p in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

        active_count = len([p for p in self._proxies if p.is_available])
        logger.info(
            "Health checks done. Active: %d/%d", active_count, len(self._proxies)
        )

        # Rebuild cycle after checks
        async with self._lock:
            self._rebuild_cycle()

    async def _check_one(self, proxy: ProxyData) -> None:
        """Check a single proxy."""
        alive, response_time = await self._checker.check(proxy)
        async with self._lock:
            proxy.mark_checked(alive, response_time)
            if self._store:
                self._store.upsert(proxy)

    def get_stats(self) -> dict:
        """Get manager statistics."""
        active = len([p for p in self._proxies if p.is_available])
        return {
            **self._stats,
            "total_proxies": len(self._proxies),
            "active_proxies": active,
            "dead_proxies": len(self._proxies) - active,
        }
