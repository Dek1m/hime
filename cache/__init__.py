"""Redis cache for search results."""

import json
import hashlib
from typing import Optional

from redis.asyncio import Redis


class SearchCache:
    """
    Redis cache for search results.

    Key format: {prefix}:search:{sha256(query:lang:page)[:16]}
    TTL: 1 hour by default
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        prefix: str = "hime",
        ttl: int = 3600,
    ):
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix
        self._ttl = ttl

    def _make_key(self, query: str, lang: str = "ru", page: int = 1) -> str:
        """Generate cache key from query parameters."""
        raw = f"{query}:{lang}:{page}"
        hash_val = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"{self._prefix}:search:{hash_val}"

    async def get(
        self, query: str, lang: str = "ru", page: int = 1
    ) -> Optional[list[dict]]:
        """
        Get cached results.

        Returns list of result dicts or None if not cached.
        """
        key = self._make_key(query, lang, page)
        data = await self._redis.get(key)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                await self._redis.delete(key)
        return None

    async def set(
        self,
        query: str,
        results: list[dict],
        lang: str = "ru",
        page: int = 1,
    ) -> None:
        """Cache search results."""
        key = self._make_key(query, lang, page)
        await self._redis.set(key, json.dumps(results, ensure_ascii=False), ex=self._ttl)

    async def invalidate(
        self, query: str, lang: str = "ru", page: int = 1
    ) -> bool:
        """Delete cached results. Returns True if key existed."""
        key = self._make_key(query, lang, page)
        return bool(await self._redis.delete(key))

    async def stats(self) -> dict:
        """Get cache statistics."""
        info = await self._redis.info("keyspace")
        keys = await self._redis.dbsize()
        return {
            "total_keys": keys,
            "info": info,
        }

    async def close(self) -> None:
        """Close Redis connection."""
        await self._redis.close()
