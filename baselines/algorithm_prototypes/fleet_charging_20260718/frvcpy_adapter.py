"""FC-C02 adapter around the Apache-2.0 frvcpy fixed-route oracle."""

from __future__ import annotations

import json
from dataclasses import dataclass

from contracts import (
    ChargingOracle,
    ChargingOracleResult,
    FixedRouteChargingRequest,
    ProbeCounters,
)


FRVCPY_PROVENANCE = {
    "package": "frvcpy",
    "version": "0.1.1",
    "repository": "https://github.com/e-VRO/frvcpy",
    "commit_verified_in_research": "508333090a29b98125824c7f2fb914d14f2a20ec",
    "license": "Apache-2.0",
    "scope": "isolated fixed-route oracle only",
}


class FrvcpyUnavailableError(RuntimeError):
    pass


class FrvcpyOracleAdapter:
    """Lazily import frvcpy so the formal project gains no dependency."""

    backend_name = "frvcpy-0.1.1"

    def solve(
        self,
        request: FixedRouteChargingRequest,
        counters: ProbeCounters,
    ) -> ChargingOracleResult:
        try:
            from frvcpy import solver
        except ImportError as exc:
            raise FrvcpyUnavailableError(
                "frvcpy is not installed; run this isolated prototype in its "
                "temporary EA-001 virtual environment"
            ) from exc

        counters.route_oracle_calls += 1
        engine = solver.Solver(
            request.instance,
            list(request.route),
            request.initial_energy,
        )
        objective, stops = engine.solve()
        feasible = stops is not None and objective != float("inf")
        normalized_stops = tuple(
            (int(node), None if amount is None else float(amount))
            for node, amount in (stops or [])
        )
        return ChargingOracleResult(
            objective=float(objective),
            stops=normalized_stops,
            backend=self.backend_name,
            feasible=feasible,
        )


@dataclass
class CachingChargingOracle:
    """Count cache hits separately; never hide complete evaluations."""

    backend: ChargingOracle

    def __post_init__(self) -> None:
        self._cache: dict[str, ChargingOracleResult] = {}

    @staticmethod
    def _key(request: FixedRouteChargingRequest) -> str:
        payload = {
            "instance": request.instance,
            "route": request.route,
            "initial_energy": request.initial_energy,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def solve(
        self,
        request: FixedRouteChargingRequest,
        counters: ProbeCounters,
    ) -> ChargingOracleResult:
        key = self._key(request)
        if key in self._cache:
            counters.oracle_cache_hits += 1
            return self._cache[key]
        result = self.backend.solve(request, counters)
        self._cache[key] = result
        return result


def build_fc_c02_abstract_micro_request() -> FixedRouteChargingRequest:
    """Build a tiny nonlinear instance with no real-world parameter claim."""

    instance = {
        "max_q": 10.0,
        "t_max": 30.0,
        "css": [{"node_id": 2, "cs_type": 0}],
        "process_times": [0.0, 0.0, 0.0],
        "breakpoints_by_type": [
            {
                "cs_type": 0,
                "time": [0.0, 1.0, 3.0],
                "charge": [0.0, 6.0, 10.0],
            }
        ],
        "energy_matrix": [
            [0.0, 4.0, 2.0],
            [8.0, 0.0, 2.0],
            [4.0, 2.0, 0.0],
        ],
        "time_matrix": [
            [0.0, 1.0, 1.0],
            [1.0, 0.0, 1.0],
            [1.0, 1.0, 0.0],
        ],
    }
    return FixedRouteChargingRequest(
        instance=instance,
        route=(0, 1, 0),
        initial_energy=6.0,
        request_id="FC-C02-ABSTRACT-NL-01",
    )

