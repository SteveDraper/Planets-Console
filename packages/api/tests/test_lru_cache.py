"""Unit tests for the shared OrderedDict LRU."""

from api.lru_cache import LruCache


def test_lru_evicts_least_recently_used() -> None:
    cache: LruCache[str, int] = LruCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert "a" not in cache
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert len(cache) == 2


def test_lru_get_moves_key_to_recent() -> None:
    cache: LruCache[str, int] = LruCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    cache.put("c", 3)
    assert "b" not in cache
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_lru_drop_and_clear() -> None:
    cache: LruCache[str, str] = LruCache(4)
    cache.put("a", "x")
    cache.drop("a")
    cache.drop("missing")
    assert cache.get("a") is None
    cache.put("b", "y")
    cache.clear()
    assert len(cache) == 0
    assert "b" not in cache
