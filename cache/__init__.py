"""Redis cache for search results with UUID and vector search."""

import json
import hashlib
import logging
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class SearchCache:
    """
    Redis cache for search results with UUID and semantic vector search.

    Key format:
      - {prefix}:search:result:{uuid} — main result object (includes vector)
      - {prefix}:search:idx:{sha256(query)[:16]} — index: query hash -> uuid
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
        self._hits = 0
        self._misses = 0

    # ──────────── UUID-based cache ────────────

    async def set_with_vector(
        self,
        query: str,
        results: list[dict],
        vector: list[float] | None = None,
        lang: str = "ru",
        page: int = 1,
    ) -> str:
        """Store results with UUID and optional vector. Returns UUID."""
        result_uuid = str(uuid.uuid4())
        key = f"{self._prefix}:search:result:{result_uuid}"
        idx_key = f"{self._prefix}:search:idx:{hashlib.sha256(f'{query}:{lang}:{page}'.encode()).hexdigest()[:16]}"

        payload = {
            "uuid": result_uuid,
            "query": query,
            "lang": lang,
            "page": page,
            "vector": vector,
            "results": results,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        pipe = self._redis.pipeline()
        pipe.set(key, json.dumps(payload, ensure_ascii=False), ex=self._ttl)
        pipe.set(idx_key, result_uuid, ex=self._ttl)
        await pipe.execute()

        logger.debug("Cached result uuid=%s query='%s' (%d results, vector=%s)", result_uuid, query[:30], len(results), "yes" if vector else "no")
        return result_uuid

    async def get_by_uuid(self, result_uuid: str) -> Optional[dict]:
        """Get cached result by UUID."""
        key = f"{self._prefix}:search:result:{result_uuid}"
        data = await self._redis.get(key)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                await self._redis.delete(key)
        return None

    async def get_by_query(self, query: str, lang: str = "ru", page: int = 1) -> Optional[dict]:
        """Get cached result by query (via index)."""
        idx_key = f"{self._prefix}:search:idx:{hashlib.sha256(f'{query}:{lang}:{page}'.encode()).hexdigest()[:16]}"
        result_uuid = await self._redis.get(idx_key)
        if result_uuid:
            return await self.get_by_uuid(result_uuid)
        return None

    async def find_similar(
        self,
        vector: list[float],
        threshold: float = 0.85,
        limit: int = 5,
    ) -> list[dict]:
        """Find semantically similar cached results using cosine similarity.

        Scans all result keys and compares vectors.
        """
        matches: list[tuple[float, dict]] = []
        cursor = 0

        while True:
            cursor, keys = await self._redis.scan(cursor, match=f"{self._prefix}:search:result:*", count=100)
            for key in keys:
                data = await self._redis.get(key)
                if not data:
                    continue
                try:
                    item = json.loads(data)
                except json.JSONDecodeError:
                    continue

                stored_vector = item.get("vector")
                if not stored_vector or len(stored_vector) != len(vector):
                    continue

                similarity = _cosine_similarity(vector, stored_vector)
                if similarity >= threshold:
                    matches.append((similarity, item))

            if cursor == 0:
                break

        matches.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in matches[:limit]]

    # ──────────── Legacy compatibility ────────────

    async def get(self, query: str, lang: str = "ru", page: int = 1) -> Optional[list[dict]]:
        """Legacy: Get cached results by query."""
        item = await self.get_by_query(query, lang, page)
        if item:
            logger.info("Cache hit for query='%s'", query[:50])
            self._hits += 1
            return item.get("results")
        logger.info("Cache miss for query='%s'", query[:50])
        self._misses += 1
        return None

    async def set(self, query: str, results: list[dict], lang: str = "ru", page: int = 1) -> None:
        """Legacy: Cache search results."""
        await self.set_with_vector(query, results, vector=None, lang=lang, page=page)

    async def invalidate(self, query: str, lang: str = "ru", page: int = 1) -> bool:
        """Delete cached results."""
        idx_key = f"{self._prefix}:search:idx:{hashlib.sha256(f'{query}:{lang}:{page}'.encode()).hexdigest()[:16]}"
        result_uuid = await self._redis.get(idx_key)
        deleted = False
        if result_uuid:
            deleted = bool(await self._redis.delete(f"{self._prefix}:search:result:{result_uuid}"))
        await self._redis.delete(idx_key)
        return deleted

    async def stats(self) -> dict:
        """Get cache statistics with hit/miss rates."""
        total_keys = await self._redis.dbsize()

        search_result_count = 0
        search_idx_count = 0
        other_count = 0
        cursor = 0

        while True:
            cursor, keys = await self._redis.scan(cursor, match=f"{self._prefix}:*", count=200)
            for key in keys:
                if f"{self._prefix}:search:result:" in key:
                    search_result_count += 1
                elif f"{self._prefix}:search:idx:" in key:
                    search_idx_count += 1
                else:
                    other_count += 1
            if cursor == 0:
                break

        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
        miss_rate = self._misses / total_requests if total_requests > 0 else 0.0

        return {
            "total_keys": total_keys,
            "hime_keys": {
                "search_results": search_result_count,
                "search_indexes": search_idx_count,
                "other": other_count,
                "total": search_result_count + search_idx_count + other_count,
            },
            "hit_count": self._hits,
            "miss_count": self._misses,
            "hit_rate": round(hit_rate, 4),
            "miss_rate": round(miss_rate, 4),
        }

    async def close(self) -> None:
        await self._redis.close()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
