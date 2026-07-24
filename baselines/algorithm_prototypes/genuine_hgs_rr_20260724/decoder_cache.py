"""Fail-closed route-local decoder cache with auditable hit statistics."""

from __future__ import annotations

from dataclasses import dataclass
import math

from contracts import DecoderCacheKey


@dataclass(frozen=True)
class CachedRouteLocalResult:
    feasible: bool
    route_local_cost: float | None

    def __post_init__(self) -> None:
        if self.feasible:
            if self.route_local_cost is None or not math.isfinite(
                float(self.route_local_cost)
            ):
                raise ValueError("feasible cached route requires a finite cost")
        elif self.route_local_cost is not None:
            raise ValueError("infeasible cached route cannot carry a cost")


class RouteLocalDecoderCache:
    """Cache only route-local feasibility/cost, never full-solution scores."""

    def __init__(self) -> None:
        self._values: dict[
            str,
            tuple[DecoderCacheKey, CachedRouteLocalResult],
        ] = {}
        self._hits = 0
        self._misses = 0

    def get(
        self,
        key: DecoderCacheKey,
    ) -> CachedRouteLocalResult | None:
        row = self._values.get(key.digest())
        if row is None:
            self._misses += 1
            return None
        stored_key, value = row
        if stored_key != key:
            raise RuntimeError("decoder cache digest collision")
        self._hits += 1
        return value

    def put(
        self,
        key: DecoderCacheKey,
        value: CachedRouteLocalResult,
    ) -> None:
        digest = key.digest()
        existing = self._values.get(digest)
        if existing is not None and existing[0] != key:
            raise RuntimeError("decoder cache digest collision")
        self._values[digest] = (key, value)

    def as_dict(self) -> dict[str, int | float]:
        requests = self._hits + self._misses
        return {
            "entries": len(self._values),
            "hits": self._hits,
            "misses": self._misses,
            "requests": requests,
            "hit_rate": (self._hits / requests if requests else 0.0),
        }
