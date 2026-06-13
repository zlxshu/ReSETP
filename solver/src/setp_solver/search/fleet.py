"""Fleet diagnostics for EV-enabled E5 search probes.

v2026-06-11: Adds H0/H1 diagnostics for paper_main.tex lines 190, 218,
262, 282-285, 541, 665, and 673. These helpers only inspect generated
bundles and existing route energy; they do not alter cost.py/check.py model
semantics. Use ``infer_fleet_limits`` before construction and
``fleet_probe_diagnostic`` to explain whether an E5 probe can carry an EV
charging signal.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ..cost import _arc_loads, ev_arc_energy_kwh
from ..instance_loader import Instance
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import Route, Solution

UNBOUNDED_FLEET = 1_000_000


@dataclass(frozen=True)
class FleetLimits:
    cv: int = UNBOUNDED_FLEET
    ev: int = UNBOUNDED_FLEET
    source: str = "unbounded fleet: vehicle_fixed_cost penalizes vehicle usage"


@dataclass(frozen=True)
class RouteEnergySummary:
    vehicle_id: str
    vehicle_type: str
    node_sequence: tuple[str, ...]
    ev_kwh: float
    needs_charge: bool


@dataclass(frozen=True)
class VehicleTypeSemantics:
    conclusion: str
    evidence_lines: tuple[str, ...]


@dataclass(frozen=True)
class FleetProbeDiagnostic:
    fleet_limits: FleetLimits
    customer_count: int
    battery_kwh: float
    route_energy: tuple[RouteEnergySummary, ...]
    charging_candidate_count: int
    vehicle_type_semantics: VehicleTypeSemantics


def infer_fleet_limits(bundle_dir: str | Path) -> FleetLimits:
    """Return the current unbounded fleet policy for the generated bundle.

    v2026-06-12: N0 retry follows the clarified model policy: generated
    bundles do not impose m^g/m^e hard caps. Existing manifest counts are
    ignored as feasibility limits; fixed vehicle cost remains the mechanism
    that encourages fewer routes.
    """

    _ = bundle_dir
    return FleetLimits()


def route_ev_energy_summary(
    route: Route,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> RouteEnergySummary:
    """Return EV-driving energy for ``route`` under the shared CMEM helper."""

    node_lookup = {node.node_id: node for node in instance.nodes}
    loads = _arc_loads(route.node_sequence, node_lookup)
    ev_kwh = sum(
        ev_arc_energy_kwh(instance.distance(from_node, to_node), load_kg, prices)
        for (from_node, to_node), load_kg in zip(zip(route.node_sequence, route.node_sequence[1:]), loads)
    )
    battery = _price(prices, "B_battery_kwh")
    return RouteEnergySummary(
        route.vehicle_id,
        route.vehicle_type.lower(),
        tuple(route.node_sequence),
        ev_kwh,
        ev_kwh > battery + 1e-9,
    )


def vehicle_type_semantics_report() -> VehicleTypeSemantics:
    """Report the paper evidence for vehicle-type dispatch semantics.

    v2026-06-11: H1 gate helper. The cited lines show vehicle sets by type,
    dispatch variable z_k^tau, CV/EV objective terms, algorithm inputs/outputs,
    and experiment text on vehicle assignment/type split. The conclusion is
    deliberately diagnostic text for user review, not a new checker rule.
    """

    evidence = (
        "paper_main.tex:190 defines K^tau, K^{g,tau}, K^{e,tau}, and callable vehicles by depot.",
        "paper_main.tex:218 defines z_k^tau as the vehicle dispatch variable.",
        "paper_main.tex:262 and 282-285 split emissions/costs by CV and EV terms.",
        "paper_main.tex:541 says the algorithm receives available vehicles and outputs routes/charging.",
        "paper_main.tex:665 and 673 require reporting vehicle assignment/type split and carbon effects.",
    )
    return VehicleTypeSemantics(
        "车型是可用车队内的派遣/车型选择问题, 不是客户固定指派。",
        evidence,
    )


def fleet_probe_diagnostic(
    bundle_dir: str | Path,
    solution: Solution,
    instance: Instance,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> FleetProbeDiagnostic:
    """Return the H0/H1 diagnostic payload for an E5 EV probe."""

    summaries = tuple(route_ev_energy_summary(route, instance, prices) for route in solution.routes)
    customer_count = sum(1 for node in instance.nodes if node.node_type.lower() == "c")
    return FleetProbeDiagnostic(
        infer_fleet_limits(bundle_dir),
        customer_count,
        _price(prices, "B_battery_kwh"),
        summaries,
        sum(1 for row in summaries if row.needs_charge),
        vehicle_type_semantics_report(),
    )


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


def _first_number(values: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    normalized = {key.lower().replace("-", "_").replace(" ", "_"): value for key, value in values.items()}
    for key, value in normalized.items():
        leaf = key.rsplit(".", 1)[-1]
        if leaf in keys:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _price(prices: PriceParameters | dict[str, float] | Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))
