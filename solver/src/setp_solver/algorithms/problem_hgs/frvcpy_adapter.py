"""Direct adapter for the frozen frvcpy 2020.1035 implementation.

The upstream ``core.py``, ``algorithm.py``, and ``solver.py`` are loaded and
executed unchanged from the harvested snapshot at commit
``d50ad0dfedce3e8b8d5f741be6473a27012ece02``.  They remain Copyright 2020
ND Kullman, A Froger, JE Mendoza, and JC Goodson and are licensed under
Apache-2.0; the complete retained license is at
``third_party/harvested_materials/04_ev_charging/``
``frvcpy_2020_1035/upstream/LICENSE``.

This file only translates one load-dependent project route into frvcpy's
fixed energy/time matrices and translates the returned station/amount plan
back.  It does not reproduce or replace frvcpy's labeling algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import importlib.util
import math
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

from setp_solver.charging_curve import curve_for_charging_node
from setp_solver.cost import _arc_loads, ev_instance_arc_energy_kwh
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.solution import Route
from setp_solver.station_copies import physical_station_id


FRVCPY_COMMIT = "d50ad0dfedce3e8b8d5f741be6473a27012ece02"
FRVCPY_SOURCE_SHA256 = {
    "core.py": "e1a0eefd9cf614086d884cdbd4544418e5f4c4d3e1fab52eadc50b7dccb21365",
    "algorithm.py": "82ac70b50dcf1e432ca560c98d8030da09f20ad96ee628afb8ccdcfe1c07a743",
    "solver.py": "bb7a466f774eb8b2e435e9b7335f9b67edb50ecd22110923c70d718c1a941b93",
    "LICENSE": "c95bae1d1ce0235ecccd3560b772ec1efb97f348a79f0fbe0a634f0c2ccefe2c",
}
_INACCESSIBLE_TIME_SECONDS = 1.0e15
_TOL = 1.0e-7


@dataclass(frozen=True)
class FrvcpyChargingDecision:
    """One upstream-selected charge, with the project energy ledger attached."""

    station_id: str
    node_type: str
    energy_kwh: float
    start_energy_kwh: float
    end_energy_kwh: float


@dataclass(frozen=True)
class FrvcpyRoutePlan:
    """Translated fixed-route result returned by the unmodified solver."""

    route: Route
    charging_decisions: tuple[FrvcpyChargingDecision, ...]
    traversal_duration_seconds: float
    final_energy_kwh: float


@dataclass(frozen=True)
class _ChargingVertex:
    station_id: str
    node_type: str
    physical_node_id: str
    allowed_gap: int | None
    terminal_only: bool = False


def _source_root() -> Path:
    repo = Path(__file__).resolve().parents[5]
    return (
        repo
        / "third_party"
        / "harvested_materials"
        / "04_ev_charging"
        / "frvcpy_2020_1035"
        / "upstream"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_upstream_snapshot(root: Path) -> None:
    for name, expected in FRVCPY_SOURCE_SHA256.items():
        path = root / ("src/frvcpy" if name != "LICENSE" else "") / name
        actual = _sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"harvested frvcpy source hash mismatch for {path}: {actual}"
            )


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load harvested frvcpy module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _frvcpy_solver_class():
    """Load the pinned upstream solver without its unused XML dependency."""

    root = _source_root()
    _verify_upstream_snapshot(root)
    source = root / "src" / "frvcpy"

    existing = sys.modules.get("frvcpy")
    if existing is not None:
        package_paths = tuple(str(path) for path in getattr(existing, "__path__", ()))
        if str(source) not in package_paths:
            raise RuntimeError(
                "another frvcpy package is already imported; refusing to mix it "
                "with the pinned harvested snapshot"
            )
        solver_module = sys.modules.get("frvcpy.solver")
        if solver_module is not None:
            return solver_module.Solver
    else:
        package = ModuleType("frvcpy")
        package.__path__ = [str(source)]
        sys.modules["frvcpy"] = package

    package = sys.modules["frvcpy"]
    core = _load_module("frvcpy.core", source / "core.py")
    package.core = core
    algorithm = _load_module("frvcpy.algorithm", source / "algorithm.py")
    package.algorithm = algorithm

    translator = ModuleType("frvcpy.translator")

    def _unsupported_xml(*_args, **_kwargs):
        raise RuntimeError("the ReSETP frvcpy adapter accepts dictionaries only")

    translator.translate = _unsupported_xml
    sys.modules["frvcpy.translator"] = translator
    package.translator = translator

    xmltodict = sys.modules.get("xmltodict")
    inserted_xml_stub = xmltodict is None
    if inserted_xml_stub:
        xmltodict = ModuleType("xmltodict")
        xmltodict.unparse = _unsupported_xml
        sys.modules["xmltodict"] = xmltodict
    try:
        solver = _load_module("frvcpy.solver", source / "solver.py")
    finally:
        if inserted_xml_stub:
            sys.modules.pop("xmltodict", None)
    package.solver = solver
    return solver.Solver


def _price(prices: PriceParameters | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _travel_and_energy(
    instance: Instance,
    from_node_id: str,
    to_node_id: str,
    load_kg: float,
    prices: PriceParameters | Any,
) -> tuple[float, float]:
    _, travel_seconds, _ = instance.arc_metrics(
        from_node_id,
        to_node_id,
        "ev",
        fallback_speed_mps=_price(prices, "v_speed_ms"),
    )
    energy_kwh = ev_instance_arc_energy_kwh(
        instance,
        from_node_id,
        to_node_id,
        load_kg,
        prices,
    )
    return float(travel_seconds), float(energy_kwh)


def _station_technology(
    node: Node,
    *,
    capacity_kwh: float,
    prices: PriceParameters | Any,
) -> tuple[tuple[tuple[float, ...], tuple[float, ...]], str]:
    if node.node_type.lower() == "d":
        power = _price(prices, "depot_charge_power_kw")
    else:
        if node.charge_power_kw is None:
            raise ValueError(
                f"public station {node.node_id!r} has no registered power"
            )
        power = float(node.charge_power_kw)
    curve = curve_for_charging_node(
        prices,
        node_type=node.node_type,
        capacity_kwh=capacity_kwh,
        reference_power_kw=power,
    )
    key = (
        tuple(float(value) for value in curve.cumulative_seconds),
        tuple(float(value) for value in curve.energy_breakpoints_kwh),
    )
    return key, curve.curve_id


def _build_frvcpy_instance(
    route: Route,
    instance: Instance,
    prices: PriceParameters | Any,
) -> tuple[
    dict[str, Any],
    list[int],
    dict[int, _ChargingVertex],
    list[list[float]],
]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    if route.vehicle_type.lower() != "ev":
        raise ValueError("frvcpy charging requires an EV route")
    if (
        len(route.node_sequence) < 2
        or route.node_sequence[0] != route.home_depot_id
        or route.node_sequence[-1] != route.home_depot_id
    ):
        raise ValueError("frvcpy charging requires a depot-to-depot fixed route")
    if any(node_id not in node_lookup for node_id in route.node_sequence):
        raise ValueError("frvcpy fixed route contains an unknown node")

    capacity = instance.battery_capacity_kwh(
        fallback=_price(prices, "B_battery_kwh"),
    )
    loads = _arc_loads(route.node_sequence, node_lookup)
    public_groups: dict[str, list[Node]] = {}
    for node in instance.nodes:
        if node.node_type.lower() == "f":
            public_groups.setdefault(physical_station_id(node), []).append(node)
    for group in public_groups.values():
        group.sort(key=lambda node: (node.physical_station_id is not None, node.node_id))
    home = node_lookup[route.home_depot_id]

    route_count = len(route.node_sequence)
    vertices: list[_ChargingVertex] = [
        _ChargingVertex(
            station_id=route.home_depot_id,
            node_type="d",
            physical_node_id=route.home_depot_id,
            allowed_gap=0,
        )
    ]
    for gap in range(route_count - 1):
        for group in public_groups.values():
            node = group[min(gap, len(group) - 1)]
            vertices.append(
                _ChargingVertex(
                    station_id=node.node_id,
                    node_type="f",
                    physical_node_id=node.node_id,
                    allowed_gap=gap,
                )
            )
    vertices.append(
        _ChargingVertex(
            station_id="__frvcpy_terminal_soc_zero__",
            node_type="d",
            physical_node_id=route.home_depot_id,
            allowed_gap=None,
            terminal_only=True,
        )
    )
    count = route_count + len(vertices)
    inaccessible_energy = capacity + 1.0
    energy = [
        [inaccessible_energy for _ in range(count)] for _ in range(count)
    ]
    time = [
        [_INACCESSIBLE_TIME_SECONDS for _ in range(count)]
        for _ in range(count)
    ]
    for index in range(count):
        energy[index][index] = 0.0
        time[index][index] = 0.0

    for gap, (from_id, to_id) in enumerate(
        zip(route.node_sequence, route.node_sequence[1:])
    ):
        travel, required = _travel_and_energy(
            instance,
            from_id,
            to_id,
            loads[gap],
            prices,
        )
        time[gap][gap + 1] = travel
        energy[gap][gap + 1] = required

    vertex_by_index = {
        route_count + offset: vertex
        for offset, vertex in enumerate(vertices)
    }
    by_gap: dict[int, list[int]] = {}
    for index, vertex in vertex_by_index.items():
        if vertex.allowed_gap is not None:
            by_gap.setdefault(vertex.allowed_gap, []).append(index)

    for gap, station_indices in by_gap.items():
        from_id = route.node_sequence[gap]
        to_id = route.node_sequence[gap + 1]
        for station_index in station_indices:
            station = vertex_by_index[station_index]
            travel, required = _travel_and_energy(
                instance,
                from_id,
                station.physical_node_id,
                loads[gap],
                prices,
            )
            time[gap][station_index] = travel
            energy[gap][station_index] = required
            travel, required = _travel_and_energy(
                instance,
                station.physical_node_id,
                to_id,
                loads[gap],
                prices,
            )
            time[station_index][gap + 1] = travel
            energy[station_index][gap + 1] = required
        for left in station_indices:
            for right in station_indices:
                if left == right:
                    continue
                left_vertex = vertex_by_index[left]
                right_vertex = vertex_by_index[right]
                travel, required = _travel_and_energy(
                    instance,
                    left_vertex.physical_node_id,
                    right_vertex.physical_node_id,
                    loads[gap],
                    prices,
                )
                time[left][right] = travel
                energy[left][right] = required

    depot_index = route_count
    time[0][depot_index] = 0.0
    energy[0][depot_index] = 0.0
    terminal_index = count - 1
    time[route_count - 1][terminal_index] = 0.0
    energy[route_count - 1][terminal_index] = 0.0

    technology_ids: dict[
        tuple[tuple[float, ...], tuple[float, ...]], str
    ] = {}
    breakpoints: list[dict[str, Any]] = []
    css: list[dict[str, Any]] = []
    for index, vertex in vertex_by_index.items():
        station_node = (
            home
            if vertex.node_type == "d"
            else node_lookup[vertex.physical_node_id]
        )
        key, _curve_id = _station_technology(
            station_node,
            capacity_kwh=capacity,
            prices=prices,
        )
        technology = technology_ids.get(key)
        if technology is None:
            technology = f"resetp_curve_{len(technology_ids)}"
            technology_ids[key] = technology
            breakpoints.append(
                {
                    "cs_type": technology,
                    "time": list(key[0]),
                    "charge": list(key[1]),
                }
            )
        css.append({"node_id": index, "cs_type": technology})

    process_times = [
        float(node_lookup[node_id].service_time)
        for node_id in route.node_sequence
    ] + [0.0 for _ in vertices]
    translated = {
        "energy_matrix": energy,
        "time_matrix": time,
        "process_times": process_times,
        "max_q": capacity,
        "breakpoints_by_type": breakpoints,
        "css": css,
    }
    return translated, list(range(route_count)), vertex_by_index, energy


def solve_fixed_route_charging(
    route: Route,
    instance: Instance,
    prices: PriceParameters | Any,
    *,
    initial_energy_kwh: float,
) -> FrvcpyRoutePlan:
    """Use unmodified frvcpy to choose charging sites and amounts."""

    translated, fixed_route, vertex_by_index, energy_matrix = (
        _build_frvcpy_instance(route, instance, prices)
    )
    capacity = float(translated["max_q"])
    initial = float(initial_energy_kwh)
    if not math.isfinite(initial) or initial < -_TOL or initial > capacity + _TOL:
        raise ValueError("frvcpy initial energy is outside battery bounds")
    initial = min(capacity, max(0.0, initial))

    solver_class = _frvcpy_solver_class()
    objective, raw_route = solver_class(
        translated,
        fixed_route,
        initial,
        multi_insert=True,
        check_tri=False,
    ).solve()
    if raw_route is None or not math.isfinite(float(objective)):
        raise ValueError("frvcpy found no energy-feasible charging plan")

    position_nodes = {
        index: node_id for index, node_id in enumerate(route.node_sequence)
    }
    repaired_nodes: list[str] = []
    decisions: list[FrvcpyChargingDecision] = []
    used_public_nodes: set[str] = set()
    battery = initial
    previous_index: int | None = None
    for raw_index, raw_amount in raw_route:
        index = int(raw_index)
        if previous_index is not None:
            battery -= float(energy_matrix[previous_index][index])
            if battery < -_TOL:
                raise ValueError("frvcpy output fails translated energy replay")
            battery = max(0.0, battery)
        if index in position_nodes:
            repaired_nodes.append(position_nodes[index])
        else:
            vertex = vertex_by_index[index]
            if vertex.terminal_only:
                raise ValueError("frvcpy output unexpectedly visits terminal SOC node")
            amount = float(raw_amount)
            if not math.isfinite(amount) or amount < -_TOL:
                raise ValueError("frvcpy returned an invalid charging amount")
            amount = max(0.0, amount)
            start = battery
            end = start + amount
            if end > capacity + _TOL:
                raise ValueError("frvcpy output exceeds battery capacity")
            end = min(capacity, end)
            decisions.append(
                FrvcpyChargingDecision(
                    station_id=vertex.station_id,
                    node_type=vertex.node_type,
                    energy_kwh=end - start,
                    start_energy_kwh=start,
                    end_energy_kwh=end,
                )
            )
            battery = end
            if vertex.node_type == "f":
                if vertex.station_id in used_public_nodes:
                    raise ValueError(
                        "frvcpy selected a repeated public station but the "
                        "current Route schema has no occurrence identity"
                    )
                used_public_nodes.add(vertex.station_id)
                repaired_nodes.append(vertex.station_id)
        previous_index = index

    if not repaired_nodes or repaired_nodes[0] != route.home_depot_id:
        raise ValueError("frvcpy output lost the route origin")
    if repaired_nodes[-1] != route.home_depot_id:
        raise ValueError("frvcpy output lost the route destination")
    return FrvcpyRoutePlan(
        route=Route(
            vehicle_id=route.vehicle_id,
            vehicle_type=route.vehicle_type,
            home_depot_id=route.home_depot_id,
            node_sequence=repaired_nodes,
        ),
        charging_decisions=tuple(decisions),
        traversal_duration_seconds=float(objective),
        final_energy_kwh=float(battery),
    )
