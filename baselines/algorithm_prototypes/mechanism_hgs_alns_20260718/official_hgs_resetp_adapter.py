"""Neutral ReSETP adapter for the pinned, unmodified official HGS-CVRP core.

The official C++ library remains untouched.  This adapter only:

1. freezes each customer's depot responsibility from a shared initial solution;
2. sends each depot's capacity-only routing projection to the official C API;
3. maps the returned customer orders back through the common ReSETP decoder.

The adapter deliberately contains no ALNS education and no ReSETP mechanism
expert.  It is therefore suitable as the official-HGS control arm, but it must
not be described as an upstream solver for the full ReSETP model.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from setp_solver.algorithms.resetp_alns.support.order_decoder import (
    OrderDecodeContext,
    order_to_solution,
    route_customers,
    route_type_hints,
)
from setp_solver.solution import Solution


REPO = Path(__file__).resolve().parents[3]
OFFICIAL_COMMIT = "1a927955cd2861a29d978f0d359d6e647db9319c"
OFFICIAL_PREFIX = (
    REPO / "build/official-hgs-cvrp-1a927955cd28"
)
INSTALL_MANIFEST = (
    OFFICIAL_PREFIX / "install_manifest.json"
)
TRACKED_LICENSE = REPO / "third_party/hgs-cvrp/LICENSE"
REBUILD_SCRIPT = REPO / "scripts/setup_official_hgs_cvrp_20260718.py"
_LEGACY_LIBRARY = (
    OFFICIAL_PREFIX / "source/build-resetp/libhgscvrp.dylib"
)
_LEGACY_LIBRARY_SHA256 = (
    "0f12d6ebeda11652e81540d8b1b15455ce3e66bfee3e0367526e944fb85bb001"
)
try:
    _INSTALL_HINT = json.loads(
        INSTALL_MANIFEST.read_text(encoding="utf-8")
    )
except (FileNotFoundError, json.JSONDecodeError):
    _INSTALL_HINT = {}
OFFICIAL_LIBRARY = Path(
    str(_INSTALL_HINT.get("library", _LEGACY_LIBRARY))
)
OFFICIAL_LIBRARY_SHA256 = str(
    _INSTALL_HINT.get("library_sha256", _LEGACY_LIBRARY_SHA256)
)
DISTANCE_SCALE = 1_000.0
TOLERANCE = 1.0e-7


class _AlgorithmParameters(ctypes.Structure):
    _fields_ = [
        ("nbGranular", ctypes.c_int),
        ("mu", ctypes.c_int),
        ("lambda_", ctypes.c_int),
        ("nbElite", ctypes.c_int),
        ("nbClose", ctypes.c_int),
        ("nbIterPenaltyManagement", ctypes.c_int),
        ("targetFeasible", ctypes.c_double),
        ("penaltyDecrease", ctypes.c_double),
        ("penaltyIncrease", ctypes.c_double),
        ("seed", ctypes.c_int),
        ("nbIter", ctypes.c_int),
        ("nbIterTraces", ctypes.c_int),
        ("timeLimit", ctypes.c_double),
        ("useSwapStar", ctypes.c_int),
    ]


class _SolutionRoute(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_int),
        ("path", ctypes.POINTER(ctypes.c_int)),
    ]


class _NativeSolution(ctypes.Structure):
    _fields_ = [
        ("cost", ctypes.c_double),
        ("time", ctypes.c_double),
        ("n_routes", ctypes.c_int),
        ("routes", ctypes.POINTER(_SolutionRoute)),
    ]


@dataclass(frozen=True)
class HGSAdapterConfig:
    seed: int
    no_improvement_iterations: int = 100
    time_window_weight: float = 1.0

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.no_improvement_iterations <= 0:
            raise ValueError("no_improvement_iterations must be positive")
        if self.time_window_weight < 0:
            raise ValueError("time_window_weight must be non-negative")


@dataclass(frozen=True)
class HGSOrderResult:
    order: tuple[str, ...]
    customer_depot: dict[str, str]
    routes_by_depot: dict[str, tuple[tuple[str, ...], ...]]
    native_cost_by_depot: dict[str, float]
    native_cpu_seconds: float
    wall_seconds: float
    native_calls: int
    official_commit: str = OFFICIAL_COMMIT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_official_install() -> dict[str, Any]:
    manifest = json.loads(INSTALL_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "resetp.official-hgs-cvrp-install.v2":
        raise RuntimeError(
            "official HGS install manifest is not the portable v2 schema; "
            "rerun scripts/setup_official_hgs_cvrp_20260718.py"
        )
    if manifest.get("pinned_commit") != OFFICIAL_COMMIT:
        raise RuntimeError("official HGS commit drift")
    if manifest.get("license") != "MIT" or manifest.get("upstream_tests") != "PASS":
        raise RuntimeError("official HGS install lacks license or test evidence")
    binary = Path(str(manifest.get("binary", "")))
    if not binary.is_file() or sha256(binary) != manifest.get("binary_sha256"):
        raise RuntimeError("official HGS executable hash drift")
    library = Path(str(manifest.get("library", "")))
    if (
        library != OFFICIAL_LIBRARY
        or not library.is_file()
        or sha256(library) != manifest.get("library_sha256")
        or sha256(library) != OFFICIAL_LIBRARY_SHA256
    ):
        raise RuntimeError("official HGS shared-library hash drift")
    source_license = Path(str(manifest.get("source_dir", ""))) / "LICENSE"
    manifest_tracked_license = Path(
        str(manifest.get("tracked_license", ""))
    )
    manifest_rebuild_script = Path(
        str(manifest.get("rebuild_script", ""))
    )
    if (
        not source_license.is_file()
        or not TRACKED_LICENSE.is_file()
        or manifest_tracked_license != TRACKED_LICENSE
        or sha256(source_license) != manifest.get("license_sha256")
        or sha256(TRACKED_LICENSE)
        != manifest.get("tracked_license_sha256")
        or sha256(source_license) != sha256(TRACKED_LICENSE)
    ):
        raise RuntimeError("official HGS tracked-license chain drift")
    if (
        not REBUILD_SCRIPT.is_file()
        or manifest_rebuild_script != REBUILD_SCRIPT
        or sha256(REBUILD_SCRIPT) != manifest.get("rebuild_script_sha256")
    ):
        raise RuntimeError("official HGS rebuild entrypoint drift")
    for label, path in (("binary", binary), ("library", library)):
        try:
            path.resolve().relative_to(OFFICIAL_PREFIX.resolve())
        except ValueError as error:
            raise RuntimeError(
                f"official HGS {label} escaped the managed build prefix"
            ) from error
    return manifest


class OfficialHGSLibrary:
    """Small ctypes wrapper around the upstream ``solve_cvrp_dist_mtx`` API."""

    def __init__(self) -> None:
        verify_official_install()
        library = ctypes.CDLL(str(OFFICIAL_LIBRARY))
        library.default_algorithm_parameters.restype = _AlgorithmParameters
        library.solve_cvrp_dist_mtx.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_char,
            ctypes.c_int,
            ctypes.POINTER(_AlgorithmParameters),
            ctypes.c_char,
        ]
        library.solve_cvrp_dist_mtx.restype = ctypes.POINTER(_NativeSolution)
        library.delete_solution.argtypes = [ctypes.POINTER(_NativeSolution)]
        library.delete_solution.restype = None
        self._library = library

    def solve(
        self,
        *,
        instance: Any,
        depot_id: str,
        customer_ids: list[str],
        capacity: float,
        speed_m_per_second: float,
        max_vehicles: int,
        config: HGSAdapterConfig,
    ) -> tuple[tuple[tuple[str, ...], ...], float, float]:
        if not customer_ids:
            return (), 0.0, 0.0
        node_lookup = {node.node_id: node for node in instance.nodes}
        nodes = [node_lookup[depot_id], *(node_lookup[item] for item in customer_ids)]
        count = len(nodes)
        if count < 2:
            return (), 0.0, 0.0
        max_asymmetry = max(
            abs(
                float(instance.distance(left.node_id, right.node_id))
                - float(instance.distance(right.node_id, left.node_id))
            )
            for left in nodes
            for right in nodes
        )
        if max_asymmetry > TOLERANCE:
            raise ValueError(
                "official HGS-CVRP assumes a symmetric matrix; this neutral "
                "adapter refuses an asymmetric ReSETP projection"
            )

        vector = ctypes.c_double * count
        coordinates_x = vector(*(float(node.x) / DISTANCE_SCALE for node in nodes))
        coordinates_y = vector(*(float(node.y) / DISTANCE_SCALE for node in nodes))
        service_times = vector(*(0.0 for _ in nodes))
        demands = vector(*(float(node.demand) for node in nodes))
        temporal_anchor = {
            node.node_id: (
                0.5 * (float(node.ready_time) + float(node.due_time))
                if node.node_type.lower() == "c"
                else None
            )
            for node in nodes
        }

        def translated_distance(left: Any, right: Any) -> float:
            spatial = (
                float(instance.distance(left.node_id, right.node_id))
                / DISTANCE_SCALE
            )
            left_time = temporal_anchor[left.node_id]
            right_time = temporal_anchor[right.node_id]
            if left_time is None or right_time is None:
                return spatial
            temporal = (
                abs(float(left_time) - float(right_time))
                * float(speed_m_per_second)
                / DISTANCE_SCALE
            )
            return spatial + float(config.time_window_weight) * temporal

        matrix = (ctypes.c_double * (count * count))(
            *(
                translated_distance(left, right)
                for left in nodes
                for right in nodes
            )
        )
        parameters = self._library.default_algorithm_parameters()
        parameters.seed = int(config.seed)
        parameters.nbIter = int(config.no_improvement_iterations)
        parameters.nbIterTraces = 2_147_483_647
        parameters.timeLimit = 0.0
        parameters.useSwapStar = 1

        began = time.perf_counter()
        pointer = self._library.solve_cvrp_dist_mtx(
            count,
            coordinates_x,
            coordinates_y,
            matrix,
            service_times,
            demands,
            float(capacity),
            1.0e30,
            b"\x00",
            max(1, min(int(max_vehicles), len(customer_ids))),
            ctypes.byref(parameters),
            b"\x00",
        )
        wall_seconds = time.perf_counter() - began
        if not pointer:
            raise RuntimeError("official HGS C API returned a null solution")

        try:
            native = pointer.contents
            routes: list[tuple[str, ...]] = []
            for route_index in range(int(native.n_routes)):
                native_route = native.routes[route_index]
                route: list[str] = []
                for position in range(int(native_route.length)):
                    customer_index = int(native_route.path[position])
                    if customer_index < 1 or customer_index > len(customer_ids):
                        raise RuntimeError(
                            "official HGS returned an out-of-range customer index"
                        )
                    route.append(customer_ids[customer_index - 1])
                routes.append(tuple(route))
            flattened = [item for route in routes for item in route]
            if sorted(flattened) != sorted(customer_ids) or len(flattened) != len(
                set(flattened)
            ):
                raise RuntimeError("official HGS customer coverage is invalid")
            for route in routes:
                load = sum(float(node_lookup[item].demand) for item in route)
                if load > float(capacity) + TOLERANCE:
                    raise RuntimeError("official HGS capacity validation failed")
            reconstructed = sum(
                translated_distance(node_lookup[left], node_lookup[right])
                for route in routes
                for left, right in zip(
                    (depot_id, *route),
                    (*route, depot_id),
                    strict=True,
                )
            )
            if abs(reconstructed - float(native.cost)) > 1.0e-5:
                raise RuntimeError(
                    "official HGS native cost does not match independent matrix replay"
                )
            return tuple(routes), float(native.cost), float(native.time)
        finally:
            self._library.delete_solution(pointer)


def frozen_customer_depots(
    initial_solution: Solution,
    instance: Any,
) -> dict[str, str]:
    customer_depot: dict[str, str] = {}
    for route in initial_solution.routes:
        for customer_id in route_customers(route, instance):
            existing = customer_depot.setdefault(customer_id, route.home_depot_id)
            if existing != route.home_depot_id:
                raise ValueError(
                    f"customer {customer_id} appears under multiple depots"
                )
    depots = sorted(
        (node for node in instance.nodes if node.node_type.lower() == "d"),
        key=lambda node: node.node_id,
    )
    for customer in (
        node for node in instance.nodes if node.node_type.lower() == "c"
    ):
        customer_depot.setdefault(
            customer.node_id,
            min(
                depots,
                key=lambda depot: (
                    float(instance.distance(depot.node_id, customer.node_id)),
                    depot.node_id,
                ),
            ).node_id,
        )
    return customer_depot


def official_hgs_order(
    *,
    instance: Any,
    initial_solution: Solution,
    capacity: float,
    speed_m_per_second: float,
    config: HGSAdapterConfig,
    library: OfficialHGSLibrary | None = None,
) -> HGSOrderResult:
    started = time.perf_counter()
    engine = library or OfficialHGSLibrary()
    customer_depot = frozen_customer_depots(initial_solution, instance)
    depots = sorted(set(customer_depot.values()))
    route_limits = {
        depot_id: max(
            1,
            sum(
                route.home_depot_id == depot_id
                for route in initial_solution.routes
            ),
        )
        for depot_id in depots
    }
    routes_by_depot: dict[str, tuple[tuple[str, ...], ...]] = {}
    cost_by_depot: dict[str, float] = {}
    native_cpu = 0.0
    calls = 0
    for depot_index, depot_id in enumerate(depots):
        customers = sorted(
            customer_id
            for customer_id, assigned_depot in customer_depot.items()
            if assigned_depot == depot_id
        )
        if not customers:
            routes_by_depot[depot_id] = ()
            cost_by_depot[depot_id] = 0.0
            continue
        routes, native_cost, native_seconds = engine.solve(
            instance=instance,
            depot_id=depot_id,
            customer_ids=customers,
            capacity=capacity,
            speed_m_per_second=speed_m_per_second,
            max_vehicles=route_limits[depot_id],
            config=HGSAdapterConfig(
                seed=int(config.seed) + 104_729 * depot_index,
                no_improvement_iterations=config.no_improvement_iterations,
                time_window_weight=config.time_window_weight,
            ),
        )
        routes_by_depot[depot_id] = routes
        cost_by_depot[depot_id] = native_cost
        native_cpu += native_seconds
        calls += 1
    order = tuple(
        customer_id
        for depot_id in depots
        for route in routes_by_depot[depot_id]
        for customer_id in route
    )
    expected = sorted(customer_depot)
    if sorted(order) != expected or len(order) != len(set(order)):
        raise RuntimeError("multi-depot official-HGS projection lost customer identity")
    return HGSOrderResult(
        order=order,
        customer_depot=customer_depot,
        routes_by_depot=routes_by_depot,
        native_cost_by_depot=cost_by_depot,
        native_cpu_seconds=native_cpu,
        wall_seconds=time.perf_counter() - started,
        native_calls=calls,
    )


def decode_official_hgs_order(
    result: HGSOrderResult,
    *,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
    prices: Any,
    initial_solution: Solution,
    rng: Any,
) -> Solution:
    """Apply the same neutral ReSETP decoder to official-HGS customer orders."""

    context = OrderDecodeContext(
        instance=instance,
        prices=prices,
        carbon_profile=carbon_profile,
        rng=rng,
        depots_by_customer={
            customer_id: (depot_id,)
            for customer_id, depot_id in result.customer_depot.items()
        },
    )
    return order_to_solution(
        list(result.order),
        context,
        current_solution=initial_solution,
        type_hints=route_type_hints(initial_solution, instance),
    )
