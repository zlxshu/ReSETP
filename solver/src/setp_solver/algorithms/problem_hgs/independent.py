"""Independent-depot subproblems for a frozen China81 Duty instance.

The paper defines each depot's outside option by serving only its own
responsibility customers with its own fleet.  These helpers preserve the
profiled road matrices, vehicle parameters, charging stations, tariffs, and
carbon inputs while removing every other depot and its customers.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from types import MappingProxyType

from setp_solver.china81 import China81Bundle
from setp_solver.instance_loader import Instance, RoadProfileMatrices
from setp_solver.search.multitrip_schedule import (
    DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
)

from .evaluation import (
    DutyEvaluationContext,
    FrozenMappingIdentity,
    mapping_sha256,
)
from .model import DutyIndividual


@dataclass(frozen=True)
class IndependentProfitRun:
    depot_id: str
    seed: int
    profit: float
    feasible: bool
    result_id: str


@dataclass(frozen=True)
class IndependentProfitFreeze:
    values: MappingProxyType
    identity_sha256: str
    selected_result_by_depot: MappingProxyType


def freeze_best_independent_profit(
    runs: Iterable[IndependentProfitRun],
) -> IndependentProfitFreeze:
    """Freeze each depot's best profit from exactly ten distinct seed runs."""

    by_depot: dict[str, list[IndependentProfitRun]] = {}
    for run in runs:
        by_depot.setdefault(str(run.depot_id), []).append(run)
    if not by_depot:
        raise ValueError("independent-profit freeze requires depot runs")
    values = {}
    selected = {}
    for depot_id, depot_runs in sorted(by_depot.items()):
        seeds = {int(run.seed) for run in depot_runs}
        if len(depot_runs) != 10 or len(seeds) != 10:
            raise ValueError(
                f"depot {depot_id!r} must have exactly ten distinct seed runs"
            )
        if any(not run.feasible for run in depot_runs):
            raise ValueError(
                f"depot {depot_id!r} has an infeasible independent run"
            )
        winner = max(
            depot_runs,
            key=lambda run: (float(run.profit), -int(run.seed), run.result_id),
        )
        values[depot_id] = float(winner.profit)
        selected[depot_id] = winner.result_id
    frozen_values = MappingProxyType(values)
    return IndependentProfitFreeze(
        values=frozen_values,
        identity_sha256=mapping_sha256(frozen_values),
        selected_result_by_depot=MappingProxyType(selected),
    )


def independent_bundle(
    bundle: China81Bundle,
    depot_id: str,
) -> China81Bundle:
    """Return one exact-profile subproblem for a depot's outside option."""

    if depot_id not in bundle.fleet_caps_by_depot:
        raise ValueError(f"unknown China81 depot {depot_id!r}")
    keep_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "f"
        or node.node_id == depot_id
        or (
            node.node_type.lower() == "c"
            and bundle.customer_home_depot.get(node.node_id) == depot_id
        )
    }
    nodes = [
        node for node in bundle.instance.nodes if node.node_id in keep_ids
    ]
    indices = [bundle.instance.node_index[node.node_id] for node in nodes]
    source_profiles = bundle.instance.road_profiles
    if source_profiles is None:
        distance_matrix = _slice_matrix(
            bundle.instance.distance_matrix,
            indices,
        )
        road_profiles = None
    else:
        road_profiles = MappingProxyType(
            {
                profile: RoadProfileMatrices(
                    distance_m=_slice_matrix(
                        matrices.distance_m,
                        indices,
                    ),
                    duration_s=_slice_matrix(
                        matrices.duration_s,
                        indices,
                    ),
                    sum_v2d_m3_s2=_slice_matrix(
                        matrices.sum_v2d_m3_s2,
                        indices,
                    ),
                )
                for profile, matrices in source_profiles.items()
            }
        )
        distance_matrix = road_profiles["cv"].distance_m
    caps = bundle.fleet_caps_by_depot[depot_id]
    instance = Instance(
        nodes=nodes,
        distance_matrix=[list(row) for row in distance_matrix],
        diesel_l_per_meter=bundle.instance.diesel_l_per_meter,
        ev_kwh_per_meter=bundle.instance.ev_kwh_per_meter,
        unit_distance_cost_per_meter=(
            bundle.instance.unit_distance_cost_per_meter
        ),
        num_cv=int(caps["num_cv"]),
        num_ev=int(caps["num_ev"]),
        road_profiles=road_profiles,
        vehicle_parameters=bundle.instance.vehicle_parameters,
        demand_mass_per_unit_kg=bundle.instance.demand_mass_per_unit_kg,
    )
    customer_home_depot = MappingProxyType(
        {
            customer_id: owner
            for customer_id, owner in bundle.customer_home_depot.items()
            if owner == depot_id
        }
    )
    return replace(
        bundle,
        instance=instance,
        customer_home_depot=customer_home_depot,
        fleet_caps_by_depot=MappingProxyType({depot_id: caps}),
        charger_scenario_by_node=MappingProxyType(
            {
                node_id: value
                for node_id, value in bundle.charger_scenario_by_node.items()
                if node_id in keep_ids
            }
        ),
        formal_search_allowed=False,
    )


def independent_individual(
    individual: DutyIndividual,
    bundle: China81Bundle,
    depot_id: str,
) -> DutyIndividual:
    """Select one depot's canonical vehicles and responsibility customers."""

    expected = {
        customer_id
        for customer_id, owner in bundle.customer_home_depot.items()
        if owner == depot_id
    }
    duties = tuple(
        duty
        for duty in individual.duties
        if duty.home_depot_id == depot_id
    )
    represented = {
        customer
        for duty in duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    unserved = tuple(
        customer
        for customer in individual.unserved_customers
        if customer in expected
    )
    if represented.union(unserved) != expected:
        missing = sorted(expected.difference(represented).difference(unserved))
        extra = sorted(represented.difference(expected))
        raise ValueError(
            "independent initial solution is not responsibility-pure: "
            f"missing={missing}, extra={extra}"
        )
    return DutyIndividual(
        duties=duties,
        unserved_customers=unserved,
        source=f"independent-depot:{depot_id}",
    )


def independent_context(
    bundle: China81Bundle,
    depot_id: str,
    *,
    carbon_quota_kg: float = 0.0,
    depot_charge_window_mode: str = DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    truth_sentinel_enabled: bool = True,
) -> DutyEvaluationContext:
    """Build a fairness-off evaluation context for one Pi0 search."""

    if set(bundle.fleet_caps_by_depot) != {depot_id}:
        raise ValueError("independent context requires a one-depot bundle")
    placeholder = {depot_id: 1.0}
    return DutyEvaluationContext(
        bundle=bundle,
        independent_profit=placeholder,
        independent_profit_identity=FrozenMappingIdentity(
            source_id=f"pi0-search-placeholder:{depot_id}",
            value_sha256=mapping_sha256(placeholder),
            externally_frozen=False,
        ),
        prior_profit={depot_id: 0.0},
        theta=0.0,
        carbon_quota_kg=float(carbon_quota_kg),
        depot_charge_window_mode=depot_charge_window_mode,
        fairness_enabled=False,
        incremental_full_truth_sentinel_enabled=bool(
            truth_sentinel_enabled
        ),
    )


def _slice_matrix(matrix, indices: list[int]):
    return tuple(
        tuple(float(matrix[left][right]) for right in indices)
        for left in indices
    )
