"""Tests for Redis query cache (query_cache.py)."""

from unittest.mock import MagicMock, patch

import pytest

from backend.cache.query_cache import QueryCache


@pytest.fixture()
def cache(monkeypatch):
    with patch("redis.from_url") as mock_redis:
        instance = MagicMock()
        mock_redis.return_value = instance
        qc = QueryCache(redis_url="redis://localhost:6380")
        qc._client = instance
        yield qc, instance


def test_cache_miss_returns_none(cache):
    qc, mock_client = cache
    mock_client.get.return_value = None
    result = qc.get("find_symbol", {"name": "Foo"})
    assert result is None


def test_cache_hit_returns_data(cache):
    import json
    qc, mock_client = cache
    data = [{"qualified_name": "mod.Foo", "symbol_type": "class"}]
    mock_client.get.return_value = json.dumps(data)
    result = qc.get("find_symbol", {"name": "Foo"})
    assert result == data


def test_cache_set_calls_setex(cache):
    qc, mock_client = cache
    qc.set("find_symbol", {"name": "Bar"}, [{"x": 1}])
    mock_client.setex.assert_called_once()


def test_invalidate_all(cache):
    qc, mock_client = cache
    mock_client.scan_iter.return_value = ["cg:cache:find_symbol:abc"]
    mock_client.delete.return_value = 1
    deleted = qc.invalidate_all()
    assert deleted == 1


def test_make_key_stable():
    # Same args always produce the same key
    k1 = QueryCache._make_key("find_symbol", {"name": "Foo", "limit": 10})
    k2 = QueryCache._make_key("find_symbol", {"limit": 10, "name": "Foo"})
    assert k1 == k2


def test_make_key_differs_by_args():
    k1 = QueryCache._make_key("find_symbol", {"name": "Foo"})
    k2 = QueryCache._make_key("find_symbol", {"name": "Bar"})
    assert k1 != k2
