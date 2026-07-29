"""Embedding client for semantic search."""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """OpenAI-compatible embedding API client.

    Vectors are stored inside SearchCache result objects via set_with_vector().
    No separate embedding cache — everything goes through SearchCache.
    """

    def __init__(
        self,
        api_url: str = "http://10.0.0.21:8080/v1",
        model: str = "qwen3-embedding-8b",
        dimension: int = 4096,
    ):
        self._api_url = api_url.rstrip("/")
        self._model = model
        self._dimension = dimension
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Get embedding for a single text via API."""
        logger.debug("Embedding call text='%s'", text[:50])
        return await self._request_embedding(text)

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
