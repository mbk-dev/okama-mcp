"""Content-hash LRU+TTL cache for expensive okama objects.

Building a `Portfolio` or `EfficientFrontier` triggers HTTPS calls to api.okama.io
plus pandas/scipy machinery — easily hundreds of ms even for a small portfolio. The
AI is likely to call several tools in a row against the same `PortfolioSpec`, so we
cache the *constructed object* keyed by the sha256 of the canonical-JSON spec.

The cache is process-local: under HTTP transport with multiple workers each worker
gets its own copy. That's fine for v1 — we explicitly chose not to introduce Redis.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Any, TypeVar
from collections.abc import Callable

T = TypeVar("T")


def make_key(spec: Any) -> str:
    """Compute a stable sha256 hex digest of a JSON-serialisable spec.

    The serialisation is canonical (``sort_keys=True``, no whitespace), so dicts
    with the same content but different key order map to the same key.
    """
    payload = json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SpecCache:
    """LRU cache with per-entry TTL keyed by content hash.

    Parameters
    ----------
    max_size : int
        Maximum number of entries. When exceeded, the least-recently-used entry is
        evicted.
    ttl_seconds : float
        After this many seconds the entry is considered stale and recomputed on
        next access.
    clock : Callable[[], float], optional
        Monotonic-clock function. Injected for deterministic testing; defaults to
        :func:`time.monotonic`.
    """

    def __init__(
        self,
        max_size: int = 64,
        ttl_seconds: float = 3600.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._clock = clock or time.monotonic
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._store)

    def clear(self) -> None:
        self._store.clear()

    def get_or_compute(self, key: str, factory: Callable[[], T]) -> T:
        """Return the cached value for ``key`` or compute it via ``factory``."""
        now = self._clock()
        existing = self._store.get(key)
        if existing is not None:
            timestamp, value = existing
            if now - timestamp <= self._ttl:
                self._store.move_to_end(key)
                return value  # type: ignore[no-any-return]
            del self._store[key]

        value = factory()
        self._store[key] = (now, value)
        self._store.move_to_end(key)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)
        return value
