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


class CheckProgress:
    """Track health check progress."""

    def __init__(self):
        self.total: int = 0
        self.checked: int = 0
        self.active: int = 0
        self.dead: int = 0
        self.running: bool = False
        self.started_at: float = 0.0
        self.finished_at: float = 0.0

    def reset(self, total: int) -> None:
        self.total = total
        self.checked = 0
        self.active = 0
        self.dead = 0
        self.running = True
        self.started_at = time.time()
        self.finished_at = 0.0

    def on_result(self, alive: bool) -> None:
        if self.checked < self.total:
            self.checked += 1
        if alive:
            self.active += 1
        else:
            self.dead += 1

    def finish(self) -> None:
        self.running = False
        self.finished_at = time.time()

    def to_dict(self) -> dict:
        elapsed = (self.finished_at or time.time()) - self.started_at if self.started_at else 0
        unknown = max(0, self.total - self.checked)
        return {
            "running": self.running,
            "total": self.total,
            "checked": self.checked,
            "active": self.active,
            "dead": self.dead,
            "unknown": unknown,
            "progress_pct": round(min(100, self.checked / self.total * 100), 1) if self.total else 0,
            "elapsed_sec": round(elapsed, 1),
        }


class RateLimiter:
    """Token bucket rate limiter per proxy."""

    def __init__(self, refill_interval: float = 300.0):
        self._refill_interval = refill_interval
        self._last_used: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def can_proceed(self, proxy_url: str) -> bool:
        async with self._lock:
            now = time.monotonic()
            last = self._last_used.get(proxy_url, 0.0)
            if now - last >= self._refill_interval:
                self._last_used[proxy_url] = now
                return True
            return False

    async def wait_time(self, proxy_url: str) -> float:
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
        """Check if proxy is alive. Returns (alive, latency_ms)."""
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                proxy=proxy.url,
                timeout=self._timeout,
                follow_redirects=False,
            ) as client:
                resp = await client.get(self._test_url)
                latency_ms = (time.monotonic() - start) * 1000
                alive = resp.status_code == 200
                return alive, latency_ms
        except Exception:
            latency_ms = (time.monotonic() - start) * 1000
            return False, latency_ms


class ProxyManager:
    """
    Proxy manager with round-robin rotation.

    Features:
    - Round-robin rotation through active proxies
    - Background health checks with progress tracking
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
        self.progress = CheckProgress()

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
        """Get next available proxy using round-robin."""
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
            return None

    async def report_success(self, proxy: ProxyData, latency: float = 0.0) -> None:
        """Report successful request. latency in ms."""
        async with self._lock:
            proxy.mark_success(latency)
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
        """Run health checks on all proxies with progress tracking."""
        logger.info("Running health checks on %d proxies...", len(self._proxies))
        self.progress.reset(len(self._proxies))

        batch_size = 50
        for i in range(0, len(self._proxies), batch_size):
            batch = self._proxies[i : i + batch_size]
            tasks = [self._check_one(p) for p in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

        self.progress.finish()
        logger.info(
            "Health checks done. Active: %d/%d, latency_ms avg: %.0f",
            self.progress.active,
            self.progress.total,
            self.progress.active and (sum(p.latency_ms for p in self._proxies if p.status == ProxyStatus.ACTIVE and p.latency_ms > 0) / max(1, self.progress.active)),
        )

        async with self._lock:
            self._rebuild_cycle()

    async def _check_one(self, proxy: ProxyData) -> None:
        """Check a single proxy."""
        alive, latency_ms = await self._checker.check(proxy)
        async with self._lock:
            proxy.mark_checked(alive, latency_ms)
            self.progress.on_result(alive)
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
