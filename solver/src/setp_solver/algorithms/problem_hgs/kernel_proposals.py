"""Independent foundation-kernel proposals with exact physical-asset identity.

The copied compiled local search proposes a changed route skeleton.  It never
writes a Duty individual and never accepts a candidate.  Every physical asset
has its own one-available vehicle type, so the returned route can be mapped
back without guessing from route order.  Charging, carbon, collaboration,
profit participation, and complete feasibility remain in Duty evaluation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal

from setp_hgs_kernel import Model, __version__ as kernel_version
from setp_hgs_kernel import Route as IndependentKernelRoute
from setp_hgs_kernel import Solution as IndependentKernelSolution
from setp_hgs_kernel import Trip as IndependentKernelTrip
from setp_hgs_kernel._setp_hgs_kernel import RandomNumberGenerator
from setp_hgs_kernel.PenaltyManager import PenaltyManager
from setp_hgs_kernel.repair import greedy_repair
from setp_hgs_kernel.search import DepotSplit, LocalSearch, compute_neighbours
from setp_hgs_kernel.solve import SolveParams

from setp_solver.cost import (
    cv_instance_arc_fuel_liters,
    diesel_price_for_route,
    ev_instance_arc_energy_kwh,
    time_profile_rows_for_node,
)
from setp_solver.instance_loader import Instance
from setp_solver.solution import Route
from setp_solver.field_rename_compat import calendar_row_number

from .evaluation import (
    DutyEvaluationContext,
    FullEvaluation,
)
from .model import DutyIndividual
from .operators import DutyMove, DutySkeletonMove

_ROUTE_COST_SCALE = 100_000


class IndependentKernelDutyRouteProposalEngine:
    """Use the copied local-search kernel as a proposal generator."""

    def __init__(
        self,
        context: DutyEvaluationContext,
        fleet_template: DutyIndividual,
        *,
        random_seed: int,
        stream_role: str = "main_route",
        include_propulsion_proxy: bool = True,
        depot_assignment_operator_enabled: bool = False,
        rebuilt_volume_capacity_enabled: bool = False,
        rebuilt_shift_neighbours_only: bool = False,
        cross_depot_enabled: bool = True,
        multi_trip_enabled: bool = True,
        type_exchange_enabled: bool = True,
        shift_aware_ev_unit_cost_enabled: bool = False,
    ) -> None:
        if kernel_version != "0.12.2":
            raise RuntimeError("Duty route proposals require IndependentKernel 0.12.2 HGS")
        self._context = context
        self.stream_role = str(stream_role)
        self.include_propulsion_proxy = bool(include_propulsion_proxy)
        self.depot_assignment_operator_enabled = bool(
            depot_assignment_operator_enabled
        )
        self.rebuilt_volume_capacity_enabled = bool(
            rebuilt_volume_capacity_enabled
        )
        self.rebuilt_shift_neighbours_only = bool(
            rebuilt_shift_neighbours_only
        )
        self.cross_depot_enabled = bool(cross_depot_enabled)
        self.multi_trip_enabled = bool(multi_trip_enabled)
        self.type_exchange_enabled = bool(type_exchange_enabled)
        self.depot_assignment_operator_enabled = bool(
            self.depot_assignment_operator_enabled
            and self.cross_depot_enabled
        )
        self.shift_aware_ev_unit_cost_enabled = bool(
            shift_aware_ev_unit_cost_enabled
        )
        if not self.stream_role:
            raise ValueError("route proposal stream role cannot be empty")
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
            self._shift_aware_ev_proxy,
        ) = _build_unique_asset_problem(
            context,
            fleet_template,
            include_propulsion_proxy=self.include_propulsion_proxy,
            include_rebuilt_volume_capacity=(
                self.rebuilt_volume_capacity_enabled
            ),
            cross_depot_enabled=self.cross_depot_enabled,
            multi_trip_enabled=self.multi_trip_enabled,
            type_exchange_enabled=self.type_exchange_enabled,
            shift_aware_ev_unit_cost_enabled=(
                self.shift_aware_ev_unit_cost_enabled
            ),
        )
        self._customer_home_depot_by_id = {
            customer: duty.home_depot_id
            for duty in fleet_template.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        }
        self._customer_vehicle_type_by_id = {
            customer: duty.vehicle_type
            for duty in fleet_template.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        }
        params = SolveParams()
        rng = RandomNumberGenerator(seed=int(random_seed))
        self._rng = rng
        self._initialization_rng_stream_count = 1
        self._native_random_solution_calls = 0
        self._greedy_repair_calls = 0
        self._initialization_prepopulation_local_search_calls = 0
        neighbours = compute_neighbours(self._data, params.neighbourhood)
        if self.rebuilt_shift_neighbours_only:
            neighbours = self._restrict_neighbours_to_rebuilt_shift(params.neighbourhood)
        self._local_search = LocalSearch(self._data, rng, neighbours)
        self._node_operator_names: list[str] = []
        self._route_operator_names: list[str] = []
        self._depot_split_operator = None
        self._depot_split_evaluations = 0
        self._depot_split_applications = 0
        for operator in params.node_ops:
            if (
                not self.multi_trip_enabled
                and operator.__name__ == "RelocateWithDepot"
            ):
                continue
            if operator.supports(self._data):
                self._local_search.add_node_operator(operator(self._data))
                self._node_operator_names.append(operator.__name__)
        if (
            self.depot_assignment_operator_enabled
            and self.cross_depot_enabled
            and DepotSplit.supports(
                self._data
            )
        ):
            self._depot_split_operator = DepotSplit(
                self._data,
                self._compatible_vehicle_groups(),
            )
            self._local_search.add_node_operator(self._depot_split_operator)
            self._node_operator_names.append(DepotSplit.__name__)
        for operator in params.route_ops:
            if operator.supports(self._data):
                self._local_search.add_route_operator(operator(self._data))
                self._route_operator_names.append(operator.__name__)
        penalty_manager = PenaltyManager.init_from(
            self._data,
            params.penalty,
        )
        self._penalty_manager = penalty_manager
        self._cost_evaluator = penalty_manager.booster_cost_evaluator()
        self.source_id = (
            "setp_hgs_kernel-0.12.2-local-search-unique-duty-slots-v4:"
            + (
                "half-load-propulsion:"
                if self.include_propulsion_proxy
                else "route-only:"
            )
            + (
                "depot-split:"
                if self.depot_assignment_operator_enabled
                else ""
            )
            + (
                "volume-capacity:"
                if self.rebuilt_volume_capacity_enabled
                else ""
            )
            + (
                "same-shift-neighbours:"
                if self.rebuilt_shift_neighbours_only
                else ""
            )
            + ("cross-depot-off:" if not self.cross_depot_enabled else "")
            + ("multi-trip-off:" if not self.multi_trip_enabled else "")
            + ("type-exchange-off:" if not self.type_exchange_enabled else "")
            + (
                "shift-aware-ev-price:"
                if self.shift_aware_ev_unit_cost_enabled
                else ""
            )
            + self.stream_role
        )
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
            "stream_role": self.stream_role,
            "node_operators": self._node_operator_names,
            "route_operators": self._route_operator_names,
            "neighbours": self._local_search.neighbours,
            "route_cost_scale": _ROUTE_COST_SCALE,
            "route_cost_scope": (
                "vehicle-fixed-plus-half-load-propulsion-carbon-distance-time"
                if self.include_propulsion_proxy
                else "vehicle-fixed-plus-non-energy-distance-time"
            ),
            "dynamic_state": dynamic_identity,
            "rebuilt_volume_capacity_enabled": (
                self.rebuilt_volume_capacity_enabled
            ),
            "rebuilt_shift_neighbours_only": (
                self.rebuilt_shift_neighbours_only
            ),
        }
        if not self.cross_depot_enabled:
            identity["cross_depot_enabled"] = False
        if not self.multi_trip_enabled:
            identity["multi_trip_enabled"] = False
        if not self.type_exchange_enabled:
            identity["type_exchange_enabled"] = False
        if self.shift_aware_ev_unit_cost_enabled:
            identity["shift_aware_ev_proxy"] = self._shift_aware_ev_proxy
        if self.depot_assignment_operator_enabled:
            identity["depot_assignment_operator"] = {
                "name": "DepotSplit",
                "compatible_vehicle_groups": (
                    self._compatible_vehicle_groups()
                ),
                "scope": (
                    "same-vehicle-class-cross-depot-trip-prefix-or-suffix-"
                    "to-empty-duty"
                ),
            }
        self.identity_sha256 = hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @property
    def data(self):
        """Return the independently compiled native routing problem."""

        return self._data

    @property
    def rng(self):
        """Return the copied HGS random stream owned by this engine."""

        return self._rng

    @property
    def local_search(self):
        """Return the copied HGS local-search engine."""

        return self._local_search

    @property
    def penalty_manager(self):
        """Return the copied HGS native routing penalty manager."""

        return self._penalty_manager

    @property
    def depot_assignment_statistics(self) -> dict[str, int | bool]:
        """Return cumulative native DepotSplit work for this engine."""

        return {
            "enabled": self.depot_assignment_operator_enabled,
            "evaluations": self._depot_split_evaluations,
            "applications": self._depot_split_applications,
        }

    @property
    def depot_assignment_compatible_vehicle_groups(self) -> tuple[int, ...]:
        """Group unique duty slots by their canonical vehicle class."""

        return tuple(self._compatible_vehicle_groups())

    @property
    def node_operator_names(self) -> tuple[str, ...]:
        """Return the enabled native node operators for closure evidence."""

        return tuple(self._node_operator_names)

    @property
    def shift_aware_ev_proxy(self) -> dict[str, object]:
        """Return the exact private-side shift-rate inputs used by the proxy."""

        return dict(self._shift_aware_ev_proxy)

    @property
    def native_initialization_statistics(self) -> dict[str, int]:
        """Return lineage-only counters for native population construction."""

        return {
            "rng_stream_count": self._initialization_rng_stream_count,
            "make_random_call_count": self._native_random_solution_calls,
            "greedy_repair_call_count": self._greedy_repair_calls,
            "prepopulation_local_search_call_count": (
                self._initialization_prepopulation_local_search_calls
            ),
        }

    def _compatible_vehicle_groups(self) -> list[int]:
        labels = sorted(
            {
                vehicle_type
                for _duty_id, vehicle_type, _depot in self._fleet_registry
            }
        )
        group_by_label = {label: index for index, label in enumerate(labels)}
        groups = [0] * self._data.num_vehicle_types
        for duty_id, vehicle_type, _depot in self._fleet_registry:
            groups[
                self._vehicle_type_by_duty_id[duty_id]
            ] = group_by_label[vehicle_type]
        return groups

    def _record_depot_split_statistics(self) -> None:
        if self._depot_split_operator is None:
            return
        statistics = self._depot_split_operator.statistics
        self._depot_split_evaluations += int(statistics.num_evaluations)
        self._depot_split_applications += int(statistics.num_applications)

    def _restrict_neighbours_to_rebuilt_shift(self, params) -> list[list[int]]:
        contract = self._context.rebuilt_route_constraints
        if contract is None:
            raise ValueError(
                "same-shift neighbours require rebuilt route constraints"
            )
        shifts = {
            customer_id: shift_id
            for customer_id, shift_id in contract.customer_shift_by_id.items()
            if customer_id in self._location_by_node_id
        }
        neighbours = compute_neighbours(
            self._data,
            replace(params, num_neighbours=self._data.num_clients - 1),
        )
        for customer_id, shift_id in shifts.items():
            location = self._location_by_node_id[customer_id]
            neighbours[location] = [
                other
                for other in neighbours[location]
                if self._node_id_by_location.get(other) in shifts
                and shifts[self._node_id_by_location[other]] == shift_id
            ][: params.num_neighbours]
        return neighbours

    def project(
        self,
        individual: DutyIndividual,
    ) -> IndependentKernelSolution:
        """Project a complete Duty candidate onto its native route skeleton."""

        if _fleet_registry(individual) != self._fleet_registry:
            raise ValueError("route projection fleet registry changed")
        return self._project(individual)

    def decode_replacements(
        self,
        reference: DutyIndividual,
        solution: IndependentKernelSolution,
    ) -> tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]:
        """Decode one native skeleton against a fixed physical fleet."""

        if _fleet_registry(reference) != self._fleet_registry:
            raise ValueError("route decoding fleet registry changed")
        return self._decode_changes(reference, solution)

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
        self._record_depot_split_statistics()
        replacements = self._decode_changes(individual, improved)
        if not self._mechanism_locks_preserved(individual, replacements):
            return ()
        components = _migration_components(individual, replacements)
        if not components:
            return ()
        proposal_sets = (
            (replacements, *components)
            if len(components) > 1
            else components
        )
        proposal_sets = tuple(
            component
            for component in proposal_sets
            if self._shift_safe_replacements(component)
        )
        return tuple(
            DutySkeletonMove(
                action_id=(
                    "setp_hgs_kernel-ls-skeleton:"
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
        draw_index: int,
    ) -> DutySkeletonMove | None:
        """Draw once from the engine-owned native initialization stream."""

        if _fleet_registry(individual) != self._fleet_registry:
            raise ValueError("route proposal fleet registry changed")
        self._native_random_solution_calls += 1
        random_solution = IndependentKernelSolution.make_random(
            self._data,
            self._rng,
        )
        self._initialization_prepopulation_local_search_calls += 1
        educated_solution = self._local_search(
            random_solution,
            self._cost_evaluator,
        )
        self._record_depot_split_statistics()
        replacements = self._decode_changes(individual, educated_solution)
        if not self._mechanism_locks_preserved(individual, replacements):
            return None
        if not replacements:
            return None
        if not self._shift_safe_replacements(replacements):
            return None
        return DutySkeletonMove(
            action_id=f"setp_hgs_kernel-random-native-skeleton:{int(draw_index)}",
            channel="initial_population",
            replacements=replacements,
            dynamic_future_only=self._context.dynamic_state is not None,
        )

    def greedy_repair_skeleton_move(
        self,
        individual: DutyIndividual,
        *,
        draw_index: int,
    ) -> DutySkeletonMove | None:
        """Insert one random customer order into all physical vehicle slots."""

        if _fleet_registry(individual) != self._fleet_registry:
            raise ValueError("route proposal fleet registry changed")
        self._native_random_solution_calls += 1
        random_solution = IndependentKernelSolution.make_random(
            self._data,
            self._rng,
        )
        customer_order = [
            int(location)
            for route in random_solution.routes()
            for location in route.visits()
        ]
        empty_routes = [
            IndependentKernelRoute(self._data, [], vehicle_type)
            for vehicle_type in self._vehicle_type_by_duty_id.values()
        ]
        self._greedy_repair_calls += 1
        repaired_routes = greedy_repair(
            empty_routes,
            customer_order,
            self._data,
            self._cost_evaluator,
        )
        repaired_solution = IndependentKernelSolution(
            self._data,
            [route for route in repaired_routes if route.visits()],
        )
        self._initialization_prepopulation_local_search_calls += 1
        educated_solution = self._local_search(
            repaired_solution,
            self._cost_evaluator,
        )
        self._record_depot_split_statistics()
        replacements = self._decode_changes(individual, educated_solution)
        if not self._mechanism_locks_preserved(individual, replacements):
            return None
        if not replacements:
            return None
        if not self._shift_safe_replacements(replacements):
            return None
        return DutySkeletonMove(
            action_id=(
                "setp_hgs_kernel-greedy-repair-skeleton:"
                f"{int(draw_index)}"
            ),
            channel="initial_population",
            replacements=replacements,
            dynamic_future_only=self._context.dynamic_state is not None,
        )

    def _mechanism_locks_preserved(
        self,
        individual: DutyIndividual,
        replacements: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...],
    ) -> bool:
        chains = {
            duty.physical_vehicle_id: tuple(
                tuple(trip.customer_ids) for trip in duty.trips
            )
            for duty in individual.duties
        }
        chains.update(dict(replacements))
        duty_by_id = {
            duty.physical_vehicle_id: duty for duty in individual.duties
        }
        for duty_id, trips in chains.items():
            duty = duty_by_id[duty_id]
            if not self.multi_trip_enabled and len(trips) > 1:
                return False
            for customer in (item for trip in trips for item in trip):
                if (
                    not self.cross_depot_enabled
                    and self._customer_home_depot_by_id.get(customer)
                    != duty.home_depot_id
                ):
                    return False
                if (
                    not self.type_exchange_enabled
                    and self._customer_vehicle_type_by_id.get(customer)
                    != duty.vehicle_type
                ):
                    return False
        return True

    def _shift_safe_replacements(
        self,
        replacements: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...],
    ) -> bool:
        """Keep mixed-shift route chains out of the materialization boundary."""

        if self._context.rebuilt_route_constraints is None:
            return True
        shifts_by_customer = (
            self._context.rebuilt_route_constraints.customer_shift_by_id
        )
        for _duty_id, chain in replacements:
            for customers in chain:
                try:
                    shifts = {
                        str(shifts_by_customer[customer])
                        for customer in customers
                    }
                except KeyError:
                    return False
                if len(shifts) > 1:
                    return False
        return True

    def _project(self, individual: DutyIndividual) -> IndependentKernelSolution:
        routes: list[IndependentKernelRoute] = []
        for duty in individual.duties:
            vehicle_type = self._vehicle_type_by_duty_id[
                duty.physical_vehicle_id
            ]
            depot = self._location_by_node_id[duty.home_depot_id]
            trips = [
                IndependentKernelTrip(
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
                    IndependentKernelRoute(self._data, trips, vehicle_type)
                )
        return IndependentKernelSolution(self._data, routes)

    def _decode_changes(
        self,
        individual: DutyIndividual,
        solution: IndependentKernelSolution,
    ) -> tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]:
        output: dict[str, tuple[tuple[str, ...], ...]] = {
            duty_id: () for duty_id, _vehicle_type, _depot in self._fleet_registry
        }
        for route in solution.routes():
            duty_id = self._duty_id_by_vehicle_type[int(route.vehicle_type())]
            if output[duty_id]:
                raise ValueError("IndependentKernel returned two routes for one physical asset")
            raw_chain = tuple(
                tuple(
                    self._node_id_by_location[int(location)]
                    for location in trip.visits()
                )
                for trip in route.trips()
                if trip.visits()
            )
            output[duty_id] = raw_chain
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
    *,
    include_propulsion_proxy: bool = True,
    include_rebuilt_volume_capacity: bool = False,
    cross_depot_enabled: bool = True,
    multi_trip_enabled: bool = True,
    type_exchange_enabled: bool = True,
    shift_aware_ev_unit_cost_enabled: bool = False,
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
    volume_by_customer = None
    volume_scale = 1
    volume_capacity = None
    if include_rebuilt_volume_capacity:
        contract = context.rebuilt_route_constraints
        if contract is None:
            raise ValueError(
                "rebuilt volume capacity requires a registered route contract"
            )
        volume_by_customer = contract.customer_volume_m3_by_id
        if not {node.node_id for node in customers}.issubset(
            volume_by_customer
        ):
            raise ValueError(
                "rebuilt volume capacity does not cover dynamic customers"
            )
        volume_values = [
            *volume_by_customer.values(),
            contract.vehicle_volume_capacity_m3,
        ]
        volume_scale = 10 ** max(
            (
                max(0, -Decimal(str(value)).as_tuple().exponent)
                for value in volume_values
            ),
            default=0,
        )
        volume_capacity = round(
            float(contract.vehicle_volume_capacity_m3) * volume_scale
        )
    baseline_depot_by_customer = {
        customer: duty.home_depot_id
        for duty in fleet_template.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    baseline_type_by_customer = {
        customer: duty.vehicle_type
        for duty in fleet_template.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    locked_depots = (
        ()
        if cross_depot_enabled
        else tuple(sorted({duty.home_depot_id for duty in fleet_template.duties}))
    )
    locked_vehicle_types = (
        ()
        if type_exchange_enabled
        else tuple(sorted({duty.vehicle_type for duty in fleet_template.duties}))
    )
    location_object = {}
    location_by_node_id: dict[str, int] = {}
    node_id_by_location: dict[int, str] = {}
    shift_contract = context.rebuilt_route_constraints
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
            release_time = 0
            if shift_contract is not None:
                shift_id = str(shift_contract.customer_shift_by_id[node.node_id])
                release_time = round(
                    shift_contract.shift_window_second_by_id[shift_id][0]
                )
            delivery = round(float(node.demand) * load_scale)
            if volume_by_customer is not None or locked_depots or locked_vehicle_types:
                delivery = [delivery]
                if volume_by_customer is not None:
                    delivery.append(
                        round(
                            float(volume_by_customer[node.node_id])
                            * volume_scale
                        )
                    )
                delivery.extend(
                    int(baseline_depot_by_customer[node.node_id] == depot_id)
                    for depot_id in locked_depots
                )
                delivery.extend(
                    int(baseline_type_by_customer[node.node_id] == vehicle_type)
                    for vehicle_type in locked_vehicle_types
                )
            location_object[node.node_id] = model.add_client(
                node.x,
                node.y,
                delivery=delivery,
                service_duration=round(node.service_time),
                tw_early=round(node.ready_time),
                tw_late=round(node.due_time),
                release_time=release_time,
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
    ev_unit_cost_by_depot: dict[str, float] = {}
    shift_aware_ev_proxy: dict[str, object] = {}
    ev_unit_cost_by_depot_and_shift: dict[tuple[str, str], float] = {}
    for vehicle_type, depot_id in profiles:
        if not include_propulsion_proxy:
            continue
        if vehicle_type != "ev" or depot_id in ev_unit_cost_by_depot:
            continue
        rows = time_profile_rows_for_node(
            instance,
            depot_id,
            bundle.time_profile,
        )
        if not rows:
            raise ValueError("EV route proxy has no depot time-profile rows")
        ev_unit_cost_by_depot[depot_id] = sum(
            float(row["depot_energy_cny_per_kwh"])
            + (
                float(row["actual_gco2_per_kwh"])
                / 1_000.0
                * float(bundle.prices.carbon_price)
            )
            for row in rows
        ) / len(rows)
        if shift_aware_ev_unit_cost_enabled:
            rates = _rebuilt_shift_aware_ev_unit_costs(context, rows)
            for shift_id, row in rates.items():
                ev_unit_cost_by_depot_and_shift[(depot_id, shift_id)] = (
                    float(row["proxy_cny_per_kwh"])
                )
            shift_aware_ev_proxy[depot_id] = rates
    for left in (*depots, *customers):
        for right in (*depots, *customers):
            if left.node_id == right.node_id:
                continue
            for (vehicle_type, depot_id), profile in profiles.items():
                _distance_m, duration_s, _ = instance.arc_metrics(
                    left.node_id,
                    right.node_id,
                    vehicle_type,
                    fallback_speed_mps=float(bundle.prices.v_speed_ms),
                )
                model.add_edge(
                    location_object[left.node_id],
                    location_object[right.node_id],
                    distance=_route_proxy_cost_units(
                        context,
                        left.node_id,
                        right.node_id,
                        vehicle_type=vehicle_type,
                        depot_id=depot_id,
                        ev_unit_cost=ev_unit_cost_by_depot.get(depot_id),
                        ev_unit_cost_by_shift=(
                            {
                                shift_id: unit_cost
                                for (candidate_depot, shift_id), unit_cost in (
                                    ev_unit_cost_by_depot_and_shift.items()
                                )
                                if candidate_depot == depot_id
                            }
                            if shift_aware_ev_unit_cost_enabled
                            else None
                        ),
                        include_propulsion_proxy=include_propulsion_proxy,
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
        capacity = round(float(vehicle.payload_capacity_kg) * load_scale)
        if volume_capacity is not None or locked_depots or locked_vehicle_types:
            capacity = [capacity]
            if volume_capacity is not None:
                capacity.append(volume_capacity)
            capacity.extend(
                len(customers) if duty.home_depot_id == depot_id else 0
                for depot_id in locked_depots
            )
            capacity.extend(
                len(customers) if duty.vehicle_type == vehicle_type else 0
                for vehicle_type in locked_vehicle_types
            )
        model.add_vehicle_type(
            num_available=1,
            capacity=capacity,
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
            unit_duration_cost=_money_units(
                float(bundle.prices.route_time_cost_per_hour) / 3_600.0
            ),
            profile=profiles[(duty.vehicle_type, duty.home_depot_id)],
            name=duty.physical_vehicle_id,
            reload_depots=[depot] if multi_trip_enabled else [],
            max_reloads=max_reloads if multi_trip_enabled else 0,
        )
        vehicle_type_by_duty_id[duty.physical_vehicle_id] = vehicle_type_index
        duty_id_by_vehicle_type[vehicle_type_index] = duty.physical_vehicle_id
    return (
        model.data(),
        location_by_node_id,
        node_id_by_location,
        vehicle_type_by_duty_id,
        duty_id_by_vehicle_type,
        shift_aware_ev_proxy,
    )


def _money_units(value: float | Decimal) -> int:
    """Encode one model-currency amount on the route-kernel integer scale."""

    scaled = Decimal(str(value)) * _ROUTE_COST_SCALE
    return max(0, int(scaled.to_integral_value(rounding=ROUND_HALF_UP)))


def _rebuilt_shift_aware_ev_unit_costs(
    context: DutyEvaluationContext,
    rows,
) -> dict[str, dict[str, float | int]]:
    """Select the lowest-carbon half-hour in each causal charging window."""

    contract = context.rebuilt_route_constraints
    if contract is None:
        raise ValueError("shift-aware EV price requires rebuilt route constraints")
    ordered = sorted(
        contract.shift_window_second_by_id.items(),
        key=lambda item: (float(item[1][0]), item[0]),
    )
    selected: dict[str, dict[str, float | int]] = {}
    previous_end = 0.0
    for shift_id, (shift_start, shift_end) in ordered:
        window_start = previous_end
        window_end = float(shift_start)
        available = tuple(
            row
            for row in rows
            if window_start
            <= float(row["horizon_second_start"])
            < window_end
        )
        if not available:
            raise ValueError(
                f"shift {shift_id!r} has no causal depot charging slot"
            )
        row = min(
            available,
            key=lambda item: (
                float(item["actual_gco2_per_kwh"]),
                float(item["depot_energy_cny_per_kwh"]),
                -float(item["horizon_second_start"]),
            ),
        )
        electricity = float(row["depot_energy_cny_per_kwh"])
        carbon = float(row["actual_gco2_per_kwh"])
        selected[str(shift_id)] = {
            "window_start_second": float(window_start),
            "window_end_second": float(window_end),
            "selected_slot": calendar_row_number(row),
            "selected_slot_start_second": float(
                row["horizon_second_start"]
            ),
            "electricity_cny_per_kwh": electricity,
            "actual_gco2_per_kwh": carbon,
            "proxy_cny_per_kwh": electricity
            + carbon / 1_000.0 * float(context.bundle.prices.carbon_price),
        }
        previous_end = float(shift_end)
    return selected


def _route_proxy_cost_units(
    context: DutyEvaluationContext,
    left_node_id: str,
    right_node_id: str,
    *,
    vehicle_type: str,
    depot_id: str,
    ev_unit_cost: float | None = None,
    ev_unit_cost_by_shift: dict[str, float] | None = None,
    include_propulsion_proxy: bool = True,
) -> int:
    """Return a neutral static gradient; complete Duty truth remains final."""

    bundle = context.bundle
    instance = bundle.instance
    prices = bundle.prices
    vehicle = instance.vehicle_profile(vehicle_type)
    proxy_load_kg = 0.5 * float(vehicle.payload_capacity_kg)
    distance_m, _duration_s, _sum_v2d = instance.arc_metrics(
        left_node_id,
        right_node_id,
        vehicle_type,
        fallback_speed_mps=float(prices.v_speed_ms),
    )
    non_energy = (
        float(distance_m)
        / 1_000.0
        * instance.non_energy_distance_cost_per_km(
            vehicle_type,
            fallback=float(prices.c_km),
        )
    )
    if not include_propulsion_proxy:
        return _money_units(non_energy)
    if vehicle_type == "cv":
        fuel_liters = cv_instance_arc_fuel_liters(
            instance,
            left_node_id,
            right_node_id,
            proxy_load_kg,
            prices,
        )
        dummy_route = Route(
            vehicle_id="CV-ROUTE-PROXY",
            vehicle_type="cv",
            home_depot_id=depot_id,
            node_sequence=[depot_id, depot_id],
        )
        propulsion = fuel_liters * (
            diesel_price_for_route(dummy_route, instance, prices)
            + float(prices.diesel_ef) * float(prices.carbon_price)
        )
    elif vehicle_type == "ev":
        energy_kwh = ev_instance_arc_energy_kwh(
            instance,
            left_node_id,
            right_node_id,
            proxy_load_kg,
            prices,
        )
        if ev_unit_cost is None:
            raise ValueError("EV route proxy unit cost was not prepared")
        active_ev_unit_cost = ev_unit_cost
        if ev_unit_cost_by_shift:
            contract = context.rebuilt_route_constraints
            if contract is None:
                raise ValueError(
                    "shift-aware EV price requires rebuilt route constraints"
                )
            shifts = {
                contract.customer_shift_by_id[node_id]
                for node_id in (left_node_id, right_node_id)
                if node_id in contract.customer_shift_by_id
            }
            if shifts:
                active_ev_unit_cost = sum(
                    ev_unit_cost_by_shift[shift_id] for shift_id in shifts
                ) / len(shifts)
        propulsion = energy_kwh * active_ev_unit_cost
    else:
        raise ValueError(f"unsupported route proxy vehicle type {vehicle_type!r}")
    return _money_units(non_energy + propulsion)


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
