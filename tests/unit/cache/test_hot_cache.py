from __future__ import annotations

from mapi.cache.hot_cache import HotOpCache
from mapi.models.domain import Operation


class TestHotOpCache:
    def test_hot_op_cache_hit_and_score(self):
        cache = HotOpCache(maxsize=3)
        op1 = Operation(service="s1", path="/p1", method="GET")
        key1 = ("prov", "api", "src", "op1")

        assert cache.get(key1) is None
        cache.put(key1, op1)
        assert key1 in cache
        assert len(cache) == 1

        # Retrieve and verify score increases
        cached = cache.get(key1)
        assert cached is op1
        assert cache._frequencies[key1] == 2

    def test_hot_op_cache_eviction_lfu(self):
        cache = HotOpCache(maxsize=2)
        op1 = Operation(service="s", path="/1", method="GET")
        op2 = Operation(service="s", path="/2", method="GET")
        op3 = Operation(service="s", path="/3", method="GET")

        k1 = ("p", "a", "s", "1")
        k2 = ("p", "a", "s", "2")
        k3 = ("p", "a", "s", "3")

        cache.put(k1, op1)
        cache.put(k2, op2)
        # Boost k1 frequency
        cache.get(k1)
        cache.get(k1)
        assert cache._frequencies[k1] == 3
        assert cache._frequencies[k2] == 1

        # Insert 3rd item; k2 (lowest frequency) should be evicted
        cache.put(k3, op3)
        assert len(cache) == 2
        assert k1 in cache
        assert k3 in cache
        assert k2 not in cache

    def test_hot_op_cache_clear_matching(self):
        cache = HotOpCache(maxsize=10)
        cache.put(
            ("github", "REST", "src1", "op1"),
            Operation(service="s", path="/", method="GET"),
        )
        cache.put(
            ("github", "REST", "src1", "op2"),
            Operation(service="s", path="/", method="GET"),
        )
        cache.put(
            ("stripe", "REST", "src1", "op3"),
            Operation(service="s", path="/", method="GET"),
        )

        assert len(cache) == 3
        cache.clear_matching("github", "REST", "src1")
        assert len(cache) == 1
        assert ("stripe", "REST", "src1", "op3") in cache

    def test_hot_op_cache_stats_and_remove(self):
        cache = HotOpCache(maxsize=5)
        key = ("p", "a", "s", "op")
        op = Operation(service="s", path="/", method="GET")
        cache.put(key, op)
        stats = cache.stats()
        assert stats["size"] == 1
        assert stats["maxsize"] == 5
        cache.remove(key)
        assert len(cache) == 0
