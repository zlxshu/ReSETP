"""PyVRP 0.12.2 route proposals with exact physical-asset identity.

PyVRP's compiled local search proposes a changed route skeleton.  It never
writes a Duty individual and never accepts a candidate.  Every physical asset
has its own one-available vehicle type, so the returned route can be mapped
back without guessing from route order.  Charging, carbon, collaboration,
profit participation, and complete feasibility remain in Duty evaluation.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from importlib.metadata import version

from pyvrp import Model
from pyvrp import Route as PyVRPRoute
from pyvrp import Solution as PyVRPSolution
from pyvrp import Trip as PyVRPTrip
from pyvrp._pyvrp import RandomNumberGenerator
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.search import LocalSearch, compute_neighbours
from pyvrp.solve import SolveParams

from setp_solver.instance_loader import Instance

from .evaluation import DutyEvaluationContext, FullEvaluation
from .model import DutyIndividual
from .operators import DutyMove, DutySkeletonMove

_ROUTE_COST_SCALE = 100_000


class PyVRPDutyRouteProposalEngine:
    """Use the fixed PyVRP local-search kernel as a proposal generator."""

    def __init__(
        self,
        context: DutyEvaluationContext,
        fleet_template: DutyIndividual,
        *,
        random_seed: int,
    ) -> None:
        if version("pyvrp") != "0.12.2":
            raise RuntimeError("Duty route proposals require PyVRP 0.12.2 HGS")
        self._context = context
        self._fleet_registry = tuple(
            (
                duty.physical_vehicle_id,
                duty.vehicle_type,
                duty.home_depot_id,
            )
            for duty in fleet_template.duties
        )
        (
            self._data,
            self._location_by_node_id,
            self._node_id_by_location,
            self._vehicle_type_by_duty_id,
            self._duty_id_by_vehicle_type,
        ) = _build_unique_asset_problem(context, fleet_template)
        params = SolveParams()
        rng = RandomNumberGenerator(seed=int(random_seed))
        self._local_search = LocalSearch(
            self._data,
            rng,
            compute_neighbours(self._data, params.neighbourhood),
        )
        self._node_operator_names: list[str] = []
        self._route_operator_names: list[str] = []
        for operator in params.node_ops:
            if operator.supports(self._data):
                self._local_search.add_node_operator(operator(self._data))
                self._node_operator_names.append(operator.__name__)
        for operator in params.route_ops:
            if operator.supports(self._data):
                self._local_search.add_route_operator(operator(self._data))
                self._route_operator_names.append(operator.__name__)
        penalty_manager = PenaltyManager.init_from(
            self._data,
            params.penalty,
        )
        self._cost_evaluator = penalty_manager.booster_cost_evaluator()
        self.source_id = "pyvrp-0.12.2-local-search-unique-duty-slots-v3"
        dynamic_identity = None
        if context.dynamic_state is not None:
            dynamic_identity = {
                "trigger_second": float(
                    context.dynamic_state.cut.trigger_second
                ),
                "assets": tuple(
                    (
                        asset_id,
                        float(asset.available_second),
                        float(asset.remaining_battery_kwh),
                        int(asset.next_trip_index),
                    )
                    for asset_id, asset in sorted(
                        context.dynamic_state.asset_states.items()
                    )
                ),
                "future_customers": tuple(
                    sorted(context.dynamic_state.future_customer_ids)
                ),
            }
        identity = {
            "source_id": self.source_id,
            "instance_id": context.bundle.instance_id,
            "fleet_registry": self._fleet_registry,
            "random_seed": int(random_seed),
            "node_operators": self._node_operator_names,
            "route_operators": self._route_operator_names,
            "neighbours": self._local_search.neighbours,
            "route_cost_scale": _ROUTE_COST_SCALE,
            "route_cost_scope": (
                "vehicle-fixed-plus-type-specific-non-energy-distance"
            ),
            "dynamic_state": dynamic_identity,
        }
        self.identity_sha256 = hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def propose(
        self,
        individual: DutyIndividual,
        evaluation: FullEvaluation,
        instance: Instance,
        *,
        include_whole_duty_type_exchange: bool,
    ) -> tuple[DutyMove, ...]:
        del evaluation, include_whole_duty_type_exchange
        if instance is not self._context.bundle.instance:
            raise ValueError("route proposal engine received another instance")
        if _fleet_registry(individual) != self._fleet_registry:
            raise ValueError("route proposal fleet registry changed")
        dynamic = self._context.dynamic_state
        if dynamic is None and any(
            _duty_locked(duty) for duty in individual.duties
        ):
            return ()
        if dynamic is not None and any(
            any(trip.locked_customer_prefix for trip in duty.trips)
            or any(session.locked for session in duty.charging_sessions)
            for duty in individual.duties
        ):
            raise ValueError(
                "dynamic route proposal received an editable future duty "
                "with an embedded lock"
            )
        warm = self._project(individual)
        improved = self._local_search(warm, self._cost_evaluator)
        replacements = self._decode_changes(individual, improved)
        components = _migration_components(individual, replacements)
        if not components:
            return ()
        proposal_sets = (
            (replacements, *components)
            if len(components) > 1
            else components
        )
        return tuple(
            DutySkeletonMove(
                action_id=(
                    "pyvrp-ls-skeleton:"
                    + hashlib.sha256(
                        repr(component).encode("utf-8")
                    ).hexdigest()[:16]
                ),
                channel="route_kernel",
                replacements=component,
                dynamic_future_only=dynamic is not None,
            )
            for component in proposal_sets
        )

    def random_skeleton_move(
        self,
        individual: DutyIndividual,
        *,
        random_seed: int,
    ) -> DutySkeletonMove | None:
        """Draw one PyVRP random route skeleton for population seeding."""

        if _fleet_registry(individual) != self._fleet_registry:
            raise ValueError("route proposal fleet registry changed")
        random_solution = PyVRPSolution.make_random(
            self._data,
            RandomNumberGenerator(seed=int(random_seed)),
        )
        educated_solution = self._local_search(
            random_solution,
            self._cost_evaluator,
        )
        replacements = self._decode_changes(individual, educated_solution)
        if not replacements:
            return None
        return DutySkeletonMove(
            action_id=f"pyvrp-random-educated-skeleton:{int(random_seed)}",
            channel="initial_population",
            replacements=replacements,
            dynamic_future_only=self._context.dynamic_state is not None,
        )

    def _project(self, individual: DutyIndividual) -> PyVRPSolution:
        routes: list[PyVRPRoute] = []
        for duty in individual.duties:
            vehicle_type = self._vehicle_type_by_duty_id[
                duty.physical_vehicle_id
            ]
            depot = self._location_by_node_id[duty.home_depot_id]
            trips = [
                PyVRPTrip(
                    self._data,
                    [
                        self._location_by_node_id[customer]
                        for customer in trip.customer_ids
                    ],
                    vehicle_type,
                    start_depot=depot,
                    end_depot=depot,
                )
                for trip in duty.trips
                if trip.customer_ids
            ]
            if trips:
                routes.append(
                    PyVRPRoute(self._data, trips, vehicle_type)
                )
        return PyVRPSolution(self._data, routes)

    def _decode_changes(
        self,
        individual: DutyIndividual,
        solution: PyVRPSolution,
    ) -> tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]:
        output: dict[str, tuple[tuple[str, ...], ...]] = {
            duty_id: () for duty_id, _vehicle_type, _depot in self._fleet_registry
        }
        for route in solution.routes():
            duty_id = self._duty_id_by_vehicle_type[int(route.vehicle_type())]
            if output[duty_id]:
                raise ValueError("PyVRP returned two routes for one physical asset")
            output[duty_id] = tuple(
                tuple(
                    self._node_id_by_location[int(location)]
                    for location in trip.visits()
                )
                for trip in route.trips()
                if trip.visits()
            )
        current = {
            duty.physical_vehicle_id: tuple(
                tuple(trip.customer_ids) for trip in duty.trips
            )
            for duty in individual.duties
        }
        return tuple(
            (duty_id, chain)
            for duty_id, chain in output.items()
            if chain != current[duty_id]
        )


def _build_unique_asset_problem(
    context: DutyEvaluationContext,
    fleet_template: DutyIndividual,
):
    bundle = context.bundle
    instance = bundle.instance
    model = Model()
    depots = [
        node for node in instance.nodes if node.node_type.lower() == "d"
    ]
    active_customers = (
        None
        if context.dynamic_state is None
        else context.dynamic_state.future_customer_ids
    )
    customers = [
        node
        for node in instance.nodes
        if node.node_type.lower() == "c"
        and (active_customers is None or node.node_id in active_customers)
    ]
    load_values = [
        *(node.demand for node in customers),
        *(
            instance.vehicle_profile(duty.vehicle_type).payload_capacity_kg
            for duty in fleet_template.duties
        ),
    ]
    load_scale = 10 ** max(
        (max(0, -Decimal(str(value)).as_tuple().exponent) for value in load_values),
        default=0,
    )
    location_object = {}
    location_by_node_id: dict[str, int] = {}
    node_id_by_location: dict[int, str] = {}
    for location, node in enumerate((*depots, *customers)):
        if node.node_type.lower() == "d":
            location_object[node.node_id] = model.add_depot(
                node.x,
                node.y,
                tw_early=round(node.ready_time),
                tw_late=round(node.due_time),
                name=node.node_id,
            )
        else:
            location_object[node.node_id] = model.add_client(
                node.x,
                node.y,
                delivery=round(float(node.demand) * load_scale),
                service_duration=round(node.service_time),
                tw_early=round(node.ready_time),
                tw_late=round(node.due_time),
                name=node.node_id,
            )
        location_by_node_id[node.node_id] = location
        node_id_by_location[location] = node.node_id

    profiles = {}
    for vehicle_type, depot_id in sorted(
        {
            (duty.vehicle_type, duty.home_depot_id)
            for duty in fleet_template.duties
        }
    ):
        profiles[(vehicle_type, depot_id)] = model.add_profile(
            name=f"{vehicle_type}@{depot_id}"
        )
    for left in (*depots, *customers):
        for right in (*depots, *customers):
            if left.node_id == right.node_id:
                continue
            for (vehicle_type, depot_id), profile in profiles.items():
                distance_m, duration_s, _ = instance.arc_metrics(
                    left.node_id,
                    right.node_id,
                    vehicle_type,
                    fallback_speed_mps=float(bundle.prices.v_speed_ms),
                )
                model.add_edge(
                    location_object[left.node_id],
                    location_object[right.node_id],
                    distance=_distance_cost_units(
                        distance_m,
                        instance.non_energy_distance_cost_per_km(
                            vehicle_type,
                            fallback=float(bundle.prices.c_km),
                        ),
                    ),
                    duration=max(0, round(duration_s)),
                    profile=profile,
                )

    vehicle_type_by_duty_id: dict[str, int] = {}
    duty_id_by_vehicle_type: dict[int, str] = {}
    max_reloads = max(0, len(customers) - 1)
    for vehicle_type_index, duty in enumerate(fleet_template.duties):
        vehicle = instance.vehicle_profile(duty.vehicle_type)
        depot = location_object[duty.home_depot_id]
        depot_open = next(
            node
            for node in depots
            if node.node_id == duty.home_depot_id
        )
        vehicle_tw_early = float(depot_open.ready_time)
        if context.dynamic_state is not None:
            asset = context.dynamic_state.asset_states[
                duty.physical_vehicle_id
            ]
            vehicle_tw_early = max(
                vehicle_tw_early,
                float(context.dynamic_state.cut.trigger_second),
                float(asset.available_second),
            )
        model.add_vehicle_type(
            num_available=1,
            capacity=round(float(vehicle.payload_capacity_kg) * load_scale),
            start_depot=depot,
            end_depot=depot,
            fixed_cost=_money_units(
                instance.vehicle_fixed_cost_per_day(
                    duty.vehicle_type,
                    fallback=bundle.prices.vehicle_fixed_cost,
                )
            ),
            tw_early=round(vehicle_tw_early),
            tw_late=round(depot_open.due_time),
            unit_distance_cost=1,
            unit_duration_cost=0,
            profile=profiles[(duty.vehicle_type, duty.home_depot_id)],
            name=duty.physical_vehicle_id,
            reload_depots=[depot],
            max_reloads=max_reloads,
        )
        vehicle_type_by_duty_id[duty.physical_vehicle_id] = vehicle_type_index
        duty_id_by_vehicle_type[vehicle_type_index] = duty.physical_vehicle_id
    return (
        model.data(),
        location_by_node_id,
        node_id_by_location,
        vehicle_type_by_duty_id,
        duty_id_by_vehicle_type,
    )


def _money_units(value: float | Decimal) -> int:
    """Encode one model-currency amount on the route-kernel integer scale."""

    scaled = Decimal(str(value)) * _ROUTE_COST_SCALE
    return max(0, int(scaled.to_integral_value(rounding=ROUND_HALF_UP)))


def _distance_cost_units(distance_m: float, rate_per_km: float) -> int:
    """Encode exact non-energy distance cost without proxying energy."""

    amount = Decimal(str(distance_m)) * Decimal(str(rate_per_km)) / 1_000
    return _money_units(amount)


def _fleet_registry(individual: DutyIndividual):
    return tuple(
        (
            duty.physical_vehicle_id,
            duty.vehicle_type,
            duty.home_depot_id,
        )
        for duty in individual.duties
    )


def _duty_locked(duty) -> bool:
    return bool(
        duty.has_dynamic_commitment
        or any(trip.locked_customer_prefix for trip in duty.trips)
        or any(session.locked for session in duty.charging_sessions)
    )


def _migration_components(
    individual: DutyIndividual,
    replacements: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...],
) -> tuple[tuple[tuple[str, tuple[tuple[str, ...], ...]], ...], ...]:
    """Split a skeleton diff by customer migration connectivity."""

    if not replacements:
        return ()
    replacement_by_id = dict(replacements)
    changed_ids = set(replacement_by_id)
    before_owner = {
        customer: duty.physical_vehicle_id
        for duty in individual.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    after_owner = dict(before_owner)
    for duty in individual.duties:
        if duty.physical_vehicle_id not in replacement_by_id:
            continue
        for trip in duty.trips:
            for customer in trip.customer_ids:
                after_owner.pop(customer, None)
    for duty in individual.duties:
        chain = replacement_by_id.get(duty.physical_vehicle_id)
        if chain is None:
            continue
        for customers in chain:
            for customer in customers:
                if customer in after_owner:
                    raise ValueError("route-kernel diff duplicates a customer")
                after_owner[customer] = duty.physical_vehicle_id
    if set(before_owner) != set(after_owner):
        raise ValueError("route-kernel diff changes the customer partition")

    adjacency = {duty_id: set() for duty_id in changed_ids}
    for customer, old_duty_id in before_owner.items():
        new_duty_id = after_owner[customer]
        if old_duty_id == new_duty_id:
            continue
        if old_duty_id not in changed_ids or new_duty_id not in changed_ids:
            raise ValueError("customer migration escapes the declared diff")
        adjacency[old_duty_id].add(new_duty_id)
        adjacency[new_duty_id].add(old_duty_id)

    components: list[tuple[str, ...]] = []
    unseen = set(changed_ids)
    while unseen:
        root = min(unseen)
        stack = [root]
        component: set[str] = set()
        while stack:
            duty_id = stack.pop()
            if duty_id in component:
                continue
            component.add(duty_id)
            stack.extend(adjacency[duty_id].difference(component))
        unseen.difference_update(component)
        components.append(tuple(sorted(component)))
    components.sort()
    return tuple(
        tuple(
            (duty_id, replacement_by_id[duty_id])
            for duty_id in component
        )
        for component in components
    )
