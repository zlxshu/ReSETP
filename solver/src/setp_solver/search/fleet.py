"""Fleet limits and route-energy helpers.

v2026-06-11: Adds H0/H1 diagnostics for paper_main.tex lines 190, 218,
262, 282-285, 541, 665, and 673. These helpers only inspect generated
bundles and existing route energy; they do not alter cost.py/check.py model
semantics. Use ``infer_fleet_limits`` before construction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any

from ..cost import _arc_loads, ev_instance_arc_energy_kwh
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import Route, Solution, route_trip_vehicle_id

UNBOUNDED_FLEET = 1_000_000


@dataclass(frozen=True)
class FleetLimits:
    cv: int = UNBOUNDED_FLEET
    ev: int = UNBOUNDED_FLEET
    source: str = "unbounded fleet: vehicle_fixed_cost penalizes vehicle usage"


@dataclass(frozen=True)
class RouteEnergySummary:
    ev_kwh: float


def normalize_solution_vehicle_trips(
    solution: Solution,
    instance: Instance,
    *,
    max_cv: int | None = None,
    max_ev: int | None = None,
) -> Solution:
    """Retag route ids so finite fleet caps count physical vehicles, not trips.

    The solver's ``Route`` schema has one id shared by the route and its
    charging actions. Reusing exactly the same id across EV trips would make
    the battery checker sum unrelated charging actions. This helper therefore
    emits unique trip ids such as ``EV1#T2`` while the checker counts only the
    physical prefix ``EV1``.
    """

    limits = {
        "cv": _limit_or_route_count(max_cv if max_cv is not None else getattr(instance, "num_cv", None), solution, "cv"),
        "ev": _limit_or_route_count(max_ev if max_ev is not None else getattr(instance, "num_ev", None), solution, "ev"),
    }
    planned_ids: dict[int, str] = {}
    for vehicle_type in ("cv", "ev"):
        route_items = [
            (idx, route)
            for idx, route in enumerate(solution.routes)
            if route.vehicle_type.lower() == vehicle_type
        ]
        if not route_items:
            continue
        cap = limits[vehicle_type]
        if cap <= 0:
            raise ValueError(f"HALT_FLEET_PACKING: no {vehicle_type.upper()} vehicles available for {len(route_items)} routes")
        planned_ids.update(_trip_ids_for_type(route_items, cap, vehicle_type.upper()))

    old_to_new: dict[str, str] = {}
    new_routes: list[Route] = []
    for idx, route in enumerate(solution.routes):
        new_id = planned_ids.get(idx, route.vehicle_id)
        if route.vehicle_id in old_to_new and old_to_new[route.vehicle_id] != new_id:
            raise ValueError(f"HALT_FLEET_PACKING: duplicate route id {route.vehicle_id} cannot be safely retagged")
        old_to_new[route.vehicle_id] = new_id
        new_routes.append(replace(route, vehicle_id=new_id))

    new_actions = [
        replace(action, vehicle_id=old_to_new.get(action.vehicle_id, action.vehicle_id))
        for action in solution.charging_actions
    ]
    return Solution(routes=new_routes, charging_actions=new_actions, cross_site_services=solution.cross_site_services)


def infer_fleet_limits(bundle_dir: str | Path) -> FleetLimits:
    """Return structural CV/EV fleet limits for the generated bundle.

    v2026-06-26: num_cv/num_ev are restored as hard upper bounds when a
    generated bundle or exported EVRPTW-MF text file carries them. Older
    ad-hoc fixtures without fleet metadata fall back to unbounded limits.
    """

    path = Path(bundle_dir)
    limits = _fleet_limits_from_bundle(path)
    if limits is not None:
        return limits
    return FleetLimits()


def _limit_or_route_count(value: int | None, solution: Solution, vehicle_type: str) -> int:
    if value is None:
        return max(1, sum(1 for route in solution.routes if route.vehicle_type.lower() == vehicle_type))
    if int(value) >= UNBOUNDED_FLEET:
        return max(1, sum(1 for route in solution.routes if route.vehicle_type.lower() == vehicle_type))
    return int(value)


def _trip_ids_for_type(route_items: list[tuple[int, Route]], cap: int, prefix: str) -> dict[int, str]:
    slot_count = max(1, min(int(cap), len(route_items)))
    slots = [f"{prefix}{idx}" for idx in range(1, slot_count + 1)]
    trip_counts: dict[str, int] = {}
    out: dict[int, str] = {}
    for pos, (idx, _route) in enumerate(route_items):
        base_id = slots[pos % len(slots)]
        trip_counts[base_id] = trip_counts.get(base_id, 0) + 1
        out[idx] = route_trip_vehicle_id(base_id, trip_counts[base_id])
    return out


def _fleet_limits_from_bundle(path: Path) -> FleetLimits | None:
    if path.is_file():
        return _fleet_limits_from_text(path)

    for json_name in ("instance.json", "scenario_manifest.json"):
        json_path = path / json_name
        if not json_path.exists():
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        flattened = _flatten_dict(data)
        cv = _optional_int(_first_present(flattened, "metadata.num_cv", "config.num_cv", "num_cv"))
        ev = _optional_int(_first_present(flattened, "metadata.num_ev", "config.num_ev", "num_ev"))
        if cv is not None or ev is not None:
            return FleetLimits(
                cv=cv if cv is not None else UNBOUNDED_FLEET,
                ev=ev if ev is not None else UNBOUNDED_FLEET,
                source=f"{json_name}: num_cv/num_ev hard fleet caps",
            )

    for text_name in ("instance_evrptwmf.txt", "instance.txt"):
        text_path = path / text_name
        if text_path.exists():
            limits = _fleet_limits_from_text(text_path)
            if limits is not None:
                return limits
    return None


def _fleet_limits_from_text(path: Path) -> FleetLimits | None:
    cv: int | None = None
    ev: int | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if "numPetrolVeh" in line:
            cv = _slash_int(line)
        elif "numElectroVeh" in line:
            ev = _slash_int(line)
    if cv is None and ev is None:
        return None
    return FleetLimits(
        cv=cv if cv is not None else UNBOUNDED_FLEET,
        ev=ev if ev is not None else UNBOUNDED_FLEET,
        source=f"{path.name}: numPetrolVeh/numElectroVeh hard fleet caps",
    )


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in {None, ""}:
            return data[key]
    return None


def _slash_int(line: str) -> int | None:
    import re

    match = re.search(r"/\s*([0-9]+)\s*/", line)
    return int(match.group(1)) if match else None


def route_ev_energy_summary(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> RouteEnergySummary:
    """Return EV-driving energy for ``route`` under the shared CMEM helper."""

    node_lookup = {node.node_id: node for node in instance.nodes}
    loads = _arc_loads(route.node_sequence, node_lookup)
    ev_kwh = sum(
        ev_instance_arc_energy_kwh(
            instance,
            from_node,
            to_node,
            load_kg,
            prices,
        )
        for (from_node, to_node), load_kg in zip(zip(route.node_sequence, route.node_sequence[1:]), loads)
    )
    return RouteEnergySummary(ev_kwh)


def _flatten_dict(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def visit(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(f"{prefix}.{key}" if prefix else str(key), child)
        else:
            out[prefix] = value

    visit("", data)
    return out


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
