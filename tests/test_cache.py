"""Tests for okama_mcp.cache — TTL+LRU cache keyed by canonical-JSON spec hash."""

from __future__ import annotations

from okama_mcp.cache import SpecCache, make_key


class FakeClock:
    """Monotonic-clock substitute for deterministic TTL testing."""

    def __init__(self, initial: float = 0.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestMakeKey:
    def test_same_dict_same_key(self) -> None:
        a = {"assets": ["SPY.US", "GLD.US"], "weights": [0.5, 0.5]}
        b = {"assets": ["SPY.US", "GLD.US"], "weights": [0.5, 0.5]}
        assert make_key(a) == make_key(b)

    def test_key_is_order_independent(self) -> None:
        a = {"assets": ["SPY.US"], "ccy": "USD"}
        b = {"ccy": "USD", "assets": ["SPY.US"]}
        assert make_key(a) == make_key(b)

    def test_different_spec_different_key(self) -> None:
        a = {"assets": ["SPY.US"]}
        b = {"assets": ["GLD.US"]}
        assert make_key(a) != make_key(b)

    def test_supports_nested_structures(self) -> None:
        a = {"x": {"a": 1, "b": [1, 2]}}
        b = {"x": {"b": [1, 2], "a": 1}}
        assert make_key(a) == make_key(b)


class TestSpecCache:
    def test_get_or_compute_returns_value(self) -> None:
        cache = SpecCache(max_size=4, ttl_seconds=60)
        result = cache.get_or_compute("k1", lambda: "computed")
        assert result == "computed"

    def test_get_or_compute_caches_value(self) -> None:
        cache = SpecCache(max_size=4, ttl_seconds=60)
        calls = []

        def factory() -> str:
            calls.append(1)
            return "x"

        cache.get_or_compute("k1", factory)
        cache.get_or_compute("k1", factory)
        cache.get_or_compute("k1", factory)
        assert len(calls) == 1

    def test_ttl_expiration(self) -> None:
        clock = FakeClock()
        cache = SpecCache(max_size=4, ttl_seconds=10, clock=clock)
        calls = []

        def factory() -> str:
            calls.append(1)
            return "x"

        cache.get_or_compute("k1", factory)
        clock.advance(5)
        cache.get_or_compute("k1", factory)
        assert len(calls) == 1  # still cached

        clock.advance(6)  # total 11 — past TTL
        cache.get_or_compute("k1", factory)
        assert len(calls) == 2  # recomputed

    def test_lru_eviction(self) -> None:
        cache = SpecCache(max_size=2, ttl_seconds=60)
        cache.get_or_compute("a", lambda: 1)
        cache.get_or_compute("b", lambda: 2)
        # touch "a" so "b" becomes the LRU entry
        cache.get_or_compute("a", lambda: 99)
        # adding "c" must evict "b" (the LRU), keeping "a" and "c"
        cache.get_or_compute("c", lambda: 3)

        calls_a: list[int] = []
        cache.get_or_compute("a", lambda: calls_a.append(1) or "new-a")
        assert calls_a == []  # "a" was kept

        calls_b: list[int] = []
        cache.get_or_compute("b", lambda: calls_b.append(1) or "new-b")
        assert calls_b == [1]  # "b" was evicted and had to be recomputed

    def test_clear_removes_all_entries(self) -> None:
        cache = SpecCache(max_size=4, ttl_seconds=60)
        cache.get_or_compute("k1", lambda: 1)
        cache.clear()
        calls = []
        cache.get_or_compute("k1", lambda: calls.append(1) or 2)
        assert len(calls) == 1

    def test_len_reflects_entry_count(self) -> None:
        cache = SpecCache(max_size=4, ttl_seconds=60)
        assert len(cache) == 0
        cache.get_or_compute("a", lambda: 1)
        cache.get_or_compute("b", lambda: 2)
        assert len(cache) == 2
