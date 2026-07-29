"""Application orchestrator — ties all modules together."""

import logging
from urllib.parse import quote_plus

from hime.cache import SearchCache
from hime.config import AppConfig, load_config
from hime.proxy import ProxyStatus
from hime.proxy.manager import ProxyManager
from hime.scraper import SearchResult
from hime.scraper.client import HttpClient
from hime.scraper.google_parser import GoogleParser
from hime.storage import ProxyStore

logger = logging.getLogger(__name__)

# Google search URL template
_GOOGLE_URL = "https://{domain}/search?q={query}&hl={lang}&start={start}"


class App:
    """Main application orchestrator."""

    def __init__(self):
        self._config: AppConfig | None = None
        self._cache: SearchCache | None = None
        self._store: ProxyStore | None = None
        self._manager: ProxyManager | None = None
        self._client: HttpClient | None = None
        self._parser: GoogleParser | None = None

    async def init(self) -> None:
        """Load config, connect to Redis/SQLite, start ProxyManager."""
        self._config = load_config()
        logging.basicConfig(level=getattr(logging, self._config.log_level))

        self._cache = SearchCache(
            redis_url=self._config.redis_url,
            prefix=self._config.cache.prefix,
            ttl=self._config.cache.ttl,
        )
        self._store = ProxyStore(self._config.sqlite_path)
        self._client = HttpClient(
            max_concurrent=self._config.scraper.max_concurrent,
            timeout=self._config.scraper.request_timeout,
            retry_count=self._config.scraper.retry_count,
            retry_delay=self._config.scraper.retry_delay,
        )
        self._parser = GoogleParser()

        proxies = self._store.get_active()
        self._manager = ProxyManager(self._config.proxy)
        await self._manager.start(proxies)

        logger.info(
            "App initialized: %d active proxies, cache_ttl=%ds",
            len(proxies),
            self._config.cache.ttl,
        )

    async def search(
        self,
        query: str,
        lang: str = "ru",
        page: int = 1,
    ) -> list[SearchResult]:
        """
        Execute search with caching and proxy rotation.

        Flow: cache → proxy → rate limit → HTTP → parse → cache store → return
        """
        assert self._cache is not None
        assert self._manager is not None
        assert self._client is not None
        assert self._parser is not None

        # 1. Check cache
        cached = await self._cache.get(query, lang, page)
        if cached is not None:
            logger.info("Cache hit for query='%s' lang=%s page=%d", query, lang, page)
            return [SearchResult.from_dict(r) for r in cached]

        # 2. Get proxy
        proxy = await self._manager.get_proxy()
        if proxy is None:
            logger.error("No available proxy for query='%s'", query)
            return []

        # 3. Build URL
        start = (page - 1) * 10
        url = _GOOGLE_URL.format(
            domain=self._config.scraper.search_domain,
            query=quote_plus(query),
            lang=lang,
            start=start,
        )

        # 4. Fetch
        html = await self._client.fetch(url, proxy)
        if html is None:
            await self._manager.report_failure(proxy)
            return []

        # 5. Parse
        results = self._parser.parse(html, query)

        # 6. Report success
        await self._manager.report_success(proxy, 0.0)

        # 7. Cache results
        if results:
            await self._cache.set(
                query,
                [r.to_dict() for r in results],
                lang,
                page,
            )

        return results

    async def close(self) -> None:
        """Close all connections."""
        if self._manager:
            await self._manager.stop()
        if self._cache:
            await self._cache.close()
        if self._client:
            await self._client.close()
