"""Embedding client and cache for semantic search."""

import hashlib
import json
import logging
from typing import Optional

import httpx
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """Redis-backed cache for embedding vectors.

    Key format: {prefix}:emb:{sha256(text)}
    """

    def __init__(self, redis: Redis, ttl: int = 86400, prefix: str = "hime"):
        self._redis = redis
        self._ttl = ttl
        self._prefix = prefix

    def _key(self, text: str) -> str:
        return f"{self._prefix}:emb:{hashlib.sha256(text.encode()).hexdigest()}"

    async def get(self, text: str) -> Optional[list[float]]:
        data = await self._redis.get(self._key(text))
        if data:
            return json.loads(data)
        return None

    async def set(self, text: str, embedding: list[float]) -> None:
        await self._redis.set(self._key(text), json.dumps(embedding), ex=self._ttl)

    async def mget(self, texts: list[str]) -> list[Optional[list[float]]]:
        if not texts:
            return []
        keys = [self._key(t) for t in texts]
        raw = await self._redis.mget(keys)
        return [json.loads(r) if r else None for r in raw]

    async def mset(self, pairs: list[tuple[str, list[float]]]) -> None:
        if not pairs:
            return
        pipe = self._redis.pipeline()
        for text, emb in pairs:
            pipe.set(self._key(text), json.dumps(emb), ex=self._ttl)
        await pipe.execute()

    async def stats(self) -> dict:
        count = 0
        cursor = 0
        pattern = f"{self._prefix}:emb:*"
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=200)
            count += len(keys)
            if cursor == 0:
                break
        return {"embeddings_cached": count, "prefix": f"{self._prefix}:emb:"}


class EmbeddingClient:
    """OpenAI-compatible embedding API client with Redis caching."""

    def __init__(
        self,
        api_url: str = "http://10.0.0.21:8080/v1",
        model: str = "qwen3-embedding-8b",
        dimension: int = 4096,
        redis_client: Redis | None = None,
        cache_prefix: str = "hime",
        cache_ttl: int = 86400,
    ):
        self._api_url = api_url.rstrip("/")
        self._model = model
        self._dimension = dimension
        self._client: Optional[httpx.AsyncClient] = None
        self._cache = EmbeddingCache(redis_client, ttl=cache_ttl, prefix=cache_prefix) if redis_client else None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Get embedding for a single text. Uses Redis cache if available."""
        if self._cache:
            cached = await self._cache.get(text)
            if cached:
                logger.debug("Embedding cache hit for text=%s", text[:50])
                return cached

        vector = await self._request_embedding(text)

        if self._cache and vector:
            await self._cache.set(text, vector)

        return vector

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts."""
        results = []
        for text in texts:
            vector = await self.embed(text)
            results.append(vector)
        return results

    async def _request_embedding(self, text: str) -> list[float]:
        """Call embedding API."""
        client = await self._get_client()
        try:
            resp = await client.post(
                f"{self._api_url}/embeddings",
                json={"model": self._model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            vector = data["data"][0]["embedding"]

            if len(vector) != self._dimension:
                logger.warning("Embedding dimension mismatch: expected %d, got %d", self._dimension, len(vector))

            logger.debug("Embedded text=%s -> vector[%d]", text[:50], len(vector))
            return vector
        except Exception as e:
            logger.error("Embedding API error: %s", e)
            return [0.0] * self._dimension

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
