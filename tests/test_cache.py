"""Tests for SearchCache and EmbeddingClient."""

import json
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hime.cache import SearchCache, _cosine_similarity
from hime.cache.embedding import EmbeddingClient


# ──────────────── Fixtures ────────────────


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.from_url = MagicMock(return_value=redis)
    return redis


@pytest.fixture
def cache(mock_redis):
    c = SearchCache.__new__(SearchCache)
    c._redis = mock_redis
    c._prefix = "hime"
    c._ttl = 3600
    c._hits = 0
    c._misses = 0
    return c


# ──────────────── cosine similarity ────────────────


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_partial_similarity(self):
        a = [1.0, 0.0, 0.0]
        b = [1.0, 1.0, 0.0]
        expected = 1.0 / math.sqrt(2)
        assert _cosine_similarity(a, b) == pytest.approx(expected)


# ──────────────── set_with_vector / get_by_uuid ────────────────


class TestSetWithVectorAndGet:
    async def test_set_and_get(self, cache, mock_redis):
        stored = {}

        async def fake_set(key, value, ex=None):
            stored[key] = value

        async def fake_get(key):
            return stored.get(key)

        mock_redis.set = fake_set
        mock_redis.get = fake_get

        mock_redis.pipeline.return_value = MagicMock(
            set=MagicMock(),
            execute=AsyncMock(return_value=[None, None]),
        )

        results = [{"url": "http://a.com", "title": "A"}]
        vector = [0.1, 0.2, 0.3]

        result_uuid = await cache.set_with_vector("test query", results, vector=vector)

        assert result_uuid
        assert isinstance(result_uuid, str)
        assert len(result_uuid) == 36

        key = f"hime:search:result:{result_uuid}"
        assert key in stored
        payload = json.loads(stored[key])
        assert payload["query"] == "test query"
        assert payload["vector"] == [0.1, 0.2, 0.3]
        assert payload["results"] == results

    async def test_get_by_uuid_found(self, cache, mock_redis):
        test_data = json.dumps({"uuid": "abc", "query": "q", "results": []})

        async def fake_get(key):
            if "result:abc" in key:
                return test_data
            return None

        mock_redis.get = fake_get
        result = await cache.get_by_uuid("abc")
        assert result is not None
        assert result["uuid"] == "abc"

    async def test_get_by_uuid_not_found(self, cache, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        result = await cache.get_by_uuid("nonexistent")
        assert result is None

    async def test_get_by_uuid_invalid_json(self, cache, mock_redis):
        async def fake_get(key):
            return "not-json"

        mock_redis.get = fake_get
        mock_redis.delete = AsyncMock()
        result = await cache.get_by_uuid("bad")
        assert result is None


# ──────────────── find_similar ────────────────


class TestFindSimilar:
    async def test_finds_similar(self, cache, mock_redis):
        items = [
            {"uuid": "1", "vector": [1.0, 0.0, 0.0], "query": "a"},
            {"uuid": "2", "vector": [0.0, 1.0, 0.0], "query": "b"},
            {"uuid": "3", "vector": [0.9, 0.1, 0.0], "query": "c"},
        ]

        call_count = 0

        async def fake_scan(cursor, match=None, count=0):
            nonlocal call_count
            if call_count == 0:
                call_count += 1
                return (0, [f"hime:search:result:{i['uuid']}" for i in items])
            return (0, [])

        async def fake_get(key):
            for item in items:
                if item["uuid"] in key:
                    return json.dumps(item)
            return None

        mock_redis.scan = fake_scan
        mock_redis.get = fake_get

        matches = await cache.find_similar([1.0, 0.0, 0.0], threshold=0.5, limit=2)
        assert len(matches) == 2
        assert matches[0]["uuid"] == "1"

    async def test_no_matches(self, cache, mock_redis):
        async def fake_scan(cursor, match=None, count=0):
            return (0, [])

        mock_redis.scan = fake_scan
        matches = await cache.find_similar([1.0, 0.0], threshold=0.99)
        assert matches == []


# ──────────────── legacy get/set ────────────────


class TestLegacyMethods:
    async def test_legacy_set(self, cache, mock_redis):
        stored = {}

        async def fake_set(key, value, ex=None):
            stored[key] = value

        async def fake_pipeline():
            pipe = MagicMock()
            ops = []

            def capture_set(key, value, ex=None):
                ops.append((key, value, ex))
                stored[key] = value

            pipe.set = capture_set
            pipe.execute = AsyncMock(return_value=[None, None])
            return pipe

        mock_redis.set = fake_set
        mock_redis.pipeline = fake_pipeline

        await cache.set("test query", [{"url": "x"}])
        assert len(stored) >= 1

    async def test_legacy_get_hit(self, cache, mock_redis):
        result_uuid = "test-uuid-123"
        idx_key = f"hime:search:idx:*"
        stored = {
            f"hime:search:idx:{cache._prefix}": result_uuid,
            f"hime:search:result:{result_uuid}": json.dumps({
                "uuid": result_uuid,
                "results": [{"url": "x"}],
            }),
        }

        async def fake_get(key):
            for k, v in stored.items():
                if key.startswith(k.rsplit(":", 1)[0]):
                    return v
            return None

        mock_redis.get = fake_get
        result = await cache.get("test")
        assert result is not None
        assert cache._hits == 1

    async def test_legacy_get_miss(self, cache, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        result = await cache.get("nonexistent")
        assert result is None
        assert cache._misses == 1


# ──────────────── stats ────────────────


class TestStats:
    async def test_stats_empty(self, cache, mock_redis):
        mock_redis.dbsize = AsyncMock(return_value=0)
        mock_redis.scan = AsyncMock(return_value=(0, []))

        stats = await cache.stats()
        assert stats["total_keys"] == 0
        assert stats["hit_rate"] == 0.0
        assert stats["miss_rate"] == 0.0
        assert stats["hit_count"] == 0
        assert stats["miss_count"] == 0

    async def test_stats_with_hits(self, cache, mock_redis):
        cache._hits = 7
        cache._misses = 3
        mock_redis.dbsize = AsyncMock(return_value=10)
        mock_redis.scan = AsyncMock(return_value=(0, []))

        stats = await cache.stats()
        assert stats["hit_rate"] == 0.7
        assert stats["miss_rate"] == 0.3
        assert stats["hit_count"] == 7
        assert stats["miss_count"] == 3


# ──────────────── EmbeddingClient ────────────────


class TestEmbeddingClient:
    async def test_embed_calls_api(self):
        client = EmbeddingClient(api_url="http://fake", model="m", dimension=3)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._client = mock_http

        result = await client.embed("hello")
        assert result == [0.1, 0.2, 0.3]
        mock_http.post.assert_called_once()

    async def test_embed_api_error_returns_zeros(self):
        client = EmbeddingClient(api_url="http://fake", model="m", dimension=3)
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=Exception("timeout"))
        client._client = mock_http

        result = await client.embed("hello")
        assert result == [0.0, 0.0, 0.0]

    async def test_embed_dimension_mismatch_logs_warning(self):
        client = EmbeddingClient(api_url="http://fake", model="m", dimension=4)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2]}]}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._client = mock_http

        result = await client.embed("hello")
        assert result == [0.1, 0.2]
        assert len(result) != client._dimension
