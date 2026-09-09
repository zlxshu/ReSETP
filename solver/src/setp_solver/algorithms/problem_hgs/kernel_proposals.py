"""Independent foundation-kernel proposals with exact physical-asset identity.

The copied compiled local search proposes a changed route skeleton.  It never
writes a Duty individual and never accepts a candidate.  Each kernel vehicle
type owns the physical assets whose parameter vectors are identical (one each
until 2026-09-05, four groups of 3/7/3/7 on the delivered static batch), and
``_decode_changes`` seats the returned routes back on those assets with the
fewest changes, so a route still maps back without guessing from route order.
Charging, carbon, collaboration, profit participation, and complete
feasibility remain in Duty evaluation.
"""

from __future__ import annotations

import bisect

from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from random import SystemRandom

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
from setp_solver.charge_timing import validate_charge_timing_policy
from setp_solver.instance_loader import Instance
from setp_solver.search.multitrip_schedule import (
    STATIC_PREHORIZON_SECONDS,
    _curve_for_prices,
)
from setp_solver.solution import Route
from setp_solver.field_rename_compat import calendar_row_number

from .charging import (
    FIRST_TRIP_WINDOW_PREV_RETURN,
    FIRST_TRIP_WINDOW_SAME_DAY,
    validate_first_trip_window,
)
from .evaluation import (
    DutyEvaluationContext,
    FullEvaluation,
)
from .model import DutyIndividual
from .operators import DutyMove, DutySkeletonMove

_ROUTE_COST_SCALE = 100_000


class _LockPinnedPenaltyManager(PenaltyManager):
    """Upstream penalty manager whose mechanism-lock dimensions never adapt."""

    pinned_dimensions: tuple[int, ...] = ()
    # Raw (pre-booster) penalty written into the pinned dimensions.  None --
    # the historical behaviour and every caller that does not ask for another
    # value -- keeps ``params.max_penalty``, so the pinned dimensions carry
    # exactly the value they carried before this knob existed.
    pinned_penalty: float | None = None

    def pin_dimensions(
        self,
        dimensions: tuple[int, ...],
        *,
        penalty: float | None = None,
    ) -> None:
        for index in dimensions:
            if index < 0 or index >= len(self._penalties) - 2:
                raise ValueError("pinned dimension must be a load dimension")
        if penalty is not None and not float(penalty) > 0.0:
            raise ValueError("pinned penalty must be positive")
        self.pinned_dimensions = tuple(dimensions)
        self.pinned_penalty = None if penalty is None else float(penalty)
        self._repin()

    def _repin(self) -> None:
        value = (
            self._params.max_penalty
            if self.pinned_penalty is None
            else self.pinned_penalty
        )
        for index in self.pinned_dimensions:
            self._penalties[index] = value

    def register(self, sol) -> None:
        super().register(sol)
        self._repin()


class IndependentKernelDutyRouteProposalEngine:
    """Use the copied local-search kernel as a proposal generator."""

    def __init__(
        self,
        context: DutyEvaluationContext,
        fleet_template: DutyIndividual,
        *,
        stream_role: str = "main_route",
        include_propulsion_proxy: bool = True,
        depot_assignment_operator_enabled: bool = False,
        rebuilt_volume_capacity_enabled: bool = False,
        rebuilt_shift_neighbours_only: bool = False,
        cross_depot_enabled: bool = True,
        multi_trip_enabled: bool = True,
        type_exchange_enabled: bool = True,
        shift_aware_ev_unit_cost_enabled: bool = False,
        charge_timing_policy_for_proxy: str | None = None,
        proxy_feasible_slots_only: bool = False,
        first_trip_window: str = FIRST_TRIP_WINDOW_SAME_DAY,
        first_trip_window_open_second: float | None = None,
        ev_charge_time_proxy_enabled: bool = True,
        ev_unit_cost_cny_per_kwh: float | None = None,
        ev_departure_gap_proxy_enabled: bool = False,
        ev_departure_gap_reference: str = "max",
        ev_departure_gap_reference_kwh: float | None = None,
        ev_reload_gap_proxy_enabled: bool = False,
        ev_reload_gap_reference_kwh: float | None = None,
        ev_reload_gap_seconds: float | None = None,
        vehicle_fixed_cost_in_proxy: bool = True,
        max_reloads_per_vehicle: int | None = None,
        vehicle_type_dedup_enabled: bool = True,
        mechanism_lock_penalty: float | None = None,
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
        # 2026-09-05 (A2): the arm's charge-timing policy, so the shift-aware
        # EV price is the one THIS arm's exact settlement would pay.  None
        # (the default, and every caller that does not declare a policy)
        # keeps the historical selection key bit-for-bit.
        self.charge_timing_policy_for_proxy = (
            None
            if charge_timing_policy_for_proxy is None
            else validate_charge_timing_policy(
                str(charge_timing_policy_for_proxy)
            )
        )
        # 2026-09-10: when True the shift-aware EV price may only be taken
        # from calendar rows that can actually HOST the reference charge
        # before the window closes (start + reference duration <= window
        # end).  Off by default: every existing run is bit-for-bit unchanged.
        # Measured 2026-09-10 (midday x 1.0, 40 runs): the historical key let
        # ``carbon_min`` price its first-trip charge at the 08:00 row (the
        # cleanest row of the merged window, which cannot fit a charge before
        # the 08:00 departure), proxy 0.873 vs 1.355 CNY/kWh actually paid,
        # so that arm dispatched the MOST EVs while paying the most.
        self.proxy_feasible_slots_only = bool(proxy_feasible_slots_only)
        # 2026-09-06: the exact repair's first-trip window rule, so the
        # shift-aware EV price prices the SAME window the settlement will use.
        self.first_trip_window = validate_first_trip_window(
            str(first_trip_window)
        )
        # 2026-09-06: when the FIRST shift's causal charging window opens under
        # ``first_trip_window="prev_return"``, as a local second of the
        # preceding day.  The route proxy is built before any route exists, so
        # it cannot know a vehicle's own return; the caller measures the
        # median last return of the initial population (the same
        # take-a-quantile-from-the-population device the reload reservation
        # uses) and hands it here.  None keeps the route-independent fallback:
        # the contract's last shift end, which is also the exact repair's
        # fallback for a single-trip duty.  Ignored under ``same_day``.
        self.first_trip_window_open_second = (
            None
            if first_trip_window_open_second is None
            else float(first_trip_window_open_second)
        )
        self.ev_charge_time_proxy_enabled = bool(ev_charge_time_proxy_enabled)
        self.ev_departure_gap_proxy_enabled = bool(ev_departure_gap_proxy_enabled)
        self.ev_departure_gap_reference = str(ev_departure_gap_reference)
        # Trip energy behind the departure gap; None derives it from the
        # reference solution's trips (empty under fleet overrides whose
        # slots cannot hold the all-CV witness, hence the explicit value).
        self.ev_departure_gap_reference_kwh = (
            None
            if ev_departure_gap_reference_kwh is None
            else float(ev_departure_gap_reference_kwh)
        )
        # Reload-gap proxy (2026-09-03, fleet-composition experiment only):
        # every depot gets a reload copy in the kernel; EV arcs leaving the
        # copy carry the between-trip depot charging time, arcs leaving the
        # real depot carry none (the first trip charges from midnight, see
        # charging.py same_day_predeparture).  ``ev_reload_gap_seconds`` is
        # the value fed back from the exact best's actual sessions in later
        # rounds; None derives round one from the mean reference trip.
        self.ev_reload_gap_proxy_enabled = bool(ev_reload_gap_proxy_enabled)
        if self.ev_reload_gap_proxy_enabled and self.ev_departure_gap_proxy_enabled:
            raise ValueError(
                "ev_reload_gap_proxy and ev_departure_gap_proxy are exclusive"
            )
        self.ev_reload_gap_reference_kwh = (
            None
            if ev_reload_gap_reference_kwh is None
            else float(ev_reload_gap_reference_kwh)
        )
        self.ev_reload_gap_seconds = (
            None if ev_reload_gap_seconds is None else float(ev_reload_gap_seconds)
        )
        # Fixed-composition experiment (2026-09-03): the fleet is owned in
        # full, so its daily fixed cost is a constant and the kernel must not
        # be rewarded for parking a vehicle (the exact model requires every
        # configured vehicle to be dispatched).
        self.vehicle_fixed_cost_in_proxy = bool(vehicle_fixed_cost_in_proxy)
        # Reload slots per vehicle in the kernel model; None keeps the
        # historic ``len(customers) - 1`` bound.  See ``max_reloads`` in
        # ``_build_unique_asset_problem``.
        self.max_reloads_per_vehicle = (
            None
            if max_reloads_per_vehicle is None
            else max(0, int(max_reloads_per_vehicle))
        )
        # 2026-09-05: one kernel vehicle type per *parameter vector* instead of
        # one per physical vehicle.  The per-vehicle type only ever existed so
        # a returned route could be mapped back to its physical asset (see
        # ``name=duty.physical_vehicle_id`` in ``_build_unique_asset_problem``);
        # ``_decode_changes`` now recovers that mapping inside the group.  The
        # kernel's local search probes empty routes once per vehicle type for
        # every customer and every step (``LocalSearch.cpp`` applyEmptyRouteMoves,
        # which carries no incremental cache), and 14-15 of the 20 kernel routes
        # sit empty in every dumped plan, so the type count is a real per-
        # iteration cost: measured 3.451 -> 3.140 ms/iteration on this instance
        # (docs/handoff/per_iteration_cost_design_20260905.md sections 1.2/2.1).
        # The merge is by full parameter vector, never by a hard-coded count:
        # under a dynamic cut ``tw_early`` differs per physical vehicle and the
        # dedup falls back to one type per vehicle on its own.  False restores
        # the historic 1:1 model bit for bit.
        self.vehicle_type_dedup_enabled = bool(vehicle_type_dedup_enabled)
        # 2026-09-09: per-unit penalty the local search pays for breaking a
        # mechanism lock (the pinned load dimensions built below), stated in
        # the units the local search actually sees, i.e. AFTER the repair
        # booster.  None keeps the historical value bit for bit:
        # ``params.penalty.max_penalty`` (100,000) x ``repair_booster`` (12)
        # = 1,200,000 per unit.  The pinned dimensions cover whichever locks
        # exist -- depot locks when ``cross_depot`` is off, vehicle-type locks
        # when ``type_exchange`` is off -- so this knob moves both.
        self.mechanism_lock_penalty = (
            None
            if mechanism_lock_penalty is None
            else float(mechanism_lock_penalty)
        )
        if (
            self.mechanism_lock_penalty is not None
            and not self.mechanism_lock_penalty > 0.0
        ):
            raise ValueError("mechanism_lock_penalty must be positive")
        # Realised electricity + carbon price per kWh fed back from an exact
        # evaluation (kernel-native search rounds); None keeps the calendar
        # estimate.
        self.ev_unit_cost_cny_per_kwh = (
            None if ev_unit_cost_cny_per_kwh is None else float(ev_unit_cost_cny_per_kwh)
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
            self._duty_ids_by_vehicle_type,
            self._shift_aware_ev_proxy,
            self.ev_charge_time_proxy,
            self._reload_location_by_depot_id,
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
            charge_timing_policy_for_proxy=(
                self.charge_timing_policy_for_proxy
            ),
            proxy_feasible_slots_only=self.proxy_feasible_slots_only,
            first_trip_window=self.first_trip_window,
            first_trip_window_open_second=self.first_trip_window_open_second,
            ev_charge_time_proxy_enabled=self.ev_charge_time_proxy_enabled,
            ev_unit_cost_override=self.ev_unit_cost_cny_per_kwh,
            ev_departure_gap_proxy_enabled=self.ev_departure_gap_proxy_enabled,
            ev_departure_gap_reference=self.ev_departure_gap_reference,
            ev_departure_gap_reference_kwh=self.ev_departure_gap_reference_kwh,
            ev_reload_gap_proxy_enabled=self.ev_reload_gap_proxy_enabled,
            ev_reload_gap_reference_kwh=self.ev_reload_gap_reference_kwh,
            ev_reload_gap_seconds=self.ev_reload_gap_seconds,
            vehicle_fixed_cost_in_proxy=self.vehicle_fixed_cost_in_proxy,
            max_reloads_per_vehicle=self.max_reloads_per_vehicle,
            vehicle_type_dedup_enabled=self.vehicle_type_dedup_enabled,
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
        rng = RandomNumberGenerator(
            seed=SystemRandom().randrange(1, 2**31)
        )
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
        penalty_manager = _LockPinnedPenaltyManager.init_from(
            self._data,
            params.penalty,
        )
        # Load dimensions after payload (and volume) encode the disabled
        # mechanisms as hard locks: one 0/1 delivery per locked depot or
        # vehicle type against a capacity of 0 on every other asset.  They are
        # not soft HGS constraints -- the exact evaluator does not re-check
        # vehicle-type membership -- so their penalties must never adapt.
        # (2026-09-02: with adaptive penalties the type lock eroded to the
        # minimum within a run and the no-type-exchange arm ended up with EVs.)
        first_lock_dimension = 1 + int(self.rebuilt_volume_capacity_enabled)
        # ``mechanism_lock_penalty`` is quoted in the units the local search
        # sees, and ``_cost_evaluator`` is the BOOSTED evaluator, so divide
        # the booster out before writing the raw pinned value.  None leaves
        # the pin at ``params.penalty.max_penalty`` exactly as before.
        self.mechanism_lock_penalty_repair_booster = int(
            params.penalty.repair_booster
        )
        requested_raw_pin = (
            None
            if self.mechanism_lock_penalty is None
            else self.mechanism_lock_penalty
            / float(self.mechanism_lock_penalty_repair_booster)
        )
        # Always-valued mirrors, so an artefact can record what the pin
        # actually carried without re-deriving the upstream default.
        self.mechanism_lock_penalty_raw = float(
            params.penalty.max_penalty
            if requested_raw_pin is None
            else requested_raw_pin
        )
        self.mechanism_lock_penalty_effective = (
            self.mechanism_lock_penalty_raw
            * float(self.mechanism_lock_penalty_repair_booster)
        )
        penalty_manager.pin_dimensions(
            tuple(range(first_lock_dimension, self._data.num_load_dimensions)),
            penalty=requested_raw_pin,
        )
        self.locked_load_dimensions = penalty_manager.pinned_dimensions
        self._penalty_manager = penalty_manager
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
            + (
                f"policy-proxy-{self.charge_timing_policy_for_proxy}:"
                if self.charge_timing_policy_for_proxy
                else ""
            )
            + (
                f"first-trip-window-{self.first_trip_window}:"
                if self.first_trip_window != FIRST_TRIP_WINDOW_SAME_DAY
                else ""
            )
            # Tagged only where it can change a price: the opening is read
            # by the shift-aware proxy's first window and by nothing else, so
            # an engine without that proxy keeps its old lineage string.
            + (
                f"first-trip-open-{self.first_trip_window_open_second:g}:"
                if (
                    self.first_trip_window_open_second is not None
                    and self.first_trip_window != FIRST_TRIP_WINDOW_SAME_DAY
                    and self.shift_aware_ev_unit_cost_enabled
                )
                else ""
            )
            + (
                "ev-charge-time:"
                if self.ev_charge_time_proxy is not None
                else ""
            )
            + ("ev-departure-gap:" if self.ev_departure_gap_proxy_enabled else "")
            + ("ev-reload-gap:" if self.ev_reload_gap_proxy_enabled else "")
            + (
                f"max-reloads-{self.max_reloads_per_vehicle}:"
                if self.max_reloads_per_vehicle is not None
                else ""
            )
            # Tagged only when enabled, like every other deviation flag above:
            # a dedup-off engine keeps the pre-2026-09-05 lineage string.
            + (
                "vtype-dedup:"
                if self.vehicle_type_dedup_enabled
                else ""
            )
            # Tagged only where it can change a search, like the first-trip
            # opening above: the knob writes into the pinned lock dimensions,
            # and an arm that keeps its mechanisms open has none, so its
            # lineage string stays bit for bit what it was before this knob
            # existed even when the flag is passed to both arms at once.
            + (
                f"lock-penalty-{self.mechanism_lock_penalty:g}:"
                if (
                    self.mechanism_lock_penalty is not None
                    and self.locked_load_dimensions
                )
                else ""
            )
            + self.stream_role
        )
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
    def _cost_evaluator(self):
        """Boosted evaluator at the penalty manager's *current* penalties.

        2026-09-02: the manager now adapts (``register`` in ``breed``), so the
        boosted evaluator must be rebuilt per call instead of frozen at init.
        """

        return self._penalty_manager.booster_cost_evaluator()

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
        changed_duty_ids: frozenset[str] | None = None,
    ) -> tuple[DutyMove, ...]:
        del evaluation, include_whole_duty_type_exchange, changed_duty_ids
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
                    + "+".join(
                        duty_id for duty_id, _trips in component
                    )
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
            # With reload copies every between-trip depot visit is the copy:
            # trip 1 leaves the real depot, later trips leave the copy, the
            # last trip returns to the real depot (kernel Route validation
            # requires trip i's end depot == trip i+1's start depot).
            reload = self._reload_location_by_depot_id.get(
                duty.home_depot_id, depot
            )
            loaded_trips = [trip for trip in duty.trips if trip.customer_ids]
            last = len(loaded_trips) - 1
            trips = [
                IndependentKernelTrip(
                    self._data,
                    [
                        self._location_by_node_id[customer]
                        for customer in trip.customer_ids
                    ],
                    vehicle_type,
                    start_depot=depot if index == 0 else reload,
                    end_depot=depot if index == last else reload,
                )
                for index, trip in enumerate(loaded_trips)
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
        chains_by_vehicle_type: dict[
            int, list[tuple[tuple[str, ...], ...]]
        ] = {}
        for route in solution.routes():
            raw_chain = tuple(
                tuple(
                    self._node_id_by_location[int(location)]
                    for location in trip.visits()
                )
                for trip in route.trips()
                if trip.visits()
            )
            chains_by_vehicle_type.setdefault(
                int(route.vehicle_type()), []
            ).append(raw_chain)
        current = {
            duty.physical_vehicle_id: tuple(
                tuple(trip.customer_ids) for trip in duty.trips
            )
            for duty in individual.duties
        }
        # The kernel never returns an empty trip, so a duty's *loaded* chain is
        # what a returned chain can be equal to.  ``current`` itself keeps the
        # empty trips: the returned diff must stay exactly what the 1:1 decoder
        # produced, and dropping an empty trip has always counted as a change.
        loaded = {
            duty_id: tuple(trip for trip in chain if trip)
            for duty_id, chain in current.items()
        }
        locked_prefixes = {
            duty.physical_vehicle_id: frozenset(
                customer
                for trip in duty.trips
                for customer in trip.locked_customer_prefix
            )
            for duty in individual.duties
            if _duty_locked(duty)
        }
        for vehicle_type, chains in chains_by_vehicle_type.items():
            slots = self._duty_ids_by_vehicle_type[int(vehicle_type)]
            if len(chains) > len(slots):
                raise ValueError(
                    "IndependentKernel returned more routes than this "
                    "physical asset group owns"
                )
            output.update(
                _least_churn_match(slots, chains, loaded, locked_prefixes)
            )
        return tuple(
            (duty_id, chain)
            for duty_id, chain in output.items()
            if chain != current[duty_id]
        )


# Reload-gap reservation quantile (2026-09-05, internal calibration -- NOT a
# literature value).  Measured on this instance, this machine, this batch:
# the 101 real between-trip charging sessions of the 20 P=0.2 midday-valley
# solutions have p50 = 1348 s, p75 = 1875 s, p90 = 2614 s (evidence:
# ``docs/handoff/second_root_cause_reload_gap_20260905.md`` section 3.2).
# Reserving the maximum (the pre-2026-09-05 behaviour, quantile 1.0) booked
# 2031.7 s in round one and 2380-2642 s afterwards; at 2614.1 s, 25 of 33
# exactly-feasible solutions were infeasible inside the kernel, where
# ``GeneticAlgorithm._best`` can never reach them.  0.75 feeds back 1875.3 s
# instead, at which 4 of the 33 are infeasible: still above the bulk of real
# sessions -- and above the p50 floor the 2026-09-03 mean-reservation crash
# established (see ``inter_trip_reload_seconds``) -- without pricing out as
# many EV-dense structures.
#
# Both rounds, since 2026-09-05 (A).  Round one used to take its reservation
# from the witness's *trip energies*, a much coarser distribution (16 trips)
# whose 0.75 order statistic converts to 1177.20 s -- below the floor below --
# with neighbouring rungs at 1240.80 s (also below) and 1692.94 s, so no rung
# of that grid lands in the [1348, ~1560) s window that is both at or above
# the floor and 0/33 infeasible.  ``population_inter_trip_reload_seconds``
# replaces that grid with the *initial population's own* between-trip
# sessions: 25 exactly evaluated plans pool 38-66 sessions (measured over 20
# draws) instead of one witness's 16 trip energies, so the same 0.75 level
# now has a distribution fine enough to land inside the window.  A quantile
# of exactly 1.0 still takes the witness maximum in round one, so
# ``--reload-gap-quantile 1.0`` reproduces the pre-2026-09-05 round one bit
# for bit (2031.6707043430688 s on the P=0.2 midday-valley batch).
RELOAD_GAP_QUANTILE = 0.75

# Floor under the round-one reservation (2026-09-05, internal calibration --
# NOT a literature value): the median of the same 101 real between-trip
# sessions.  The initial population is randomly constructed rather than
# optimised, so its 0.75 order statistic is noisier than the batch's and does
# dip under the median (measured: 1233.26 s and 1250.62 s in 2 of 20 draws).
# Reserving less than the median is the failure mode the 2026-09-03 crash
# recorded in ``inter_trip_reload_seconds`` -- the kernel packs chains no
# exact repair can charge -- so the round-one value is raised to this floor
# when the draw lands below it.
RELOAD_GAP_FLOOR_SECONDS = 1348.0


def _order_statistic(values: list[float], quantile: float) -> float:
    """``quantile``-th value of sorted ``values`` (1.0 is the maximum).

    Nearest-rank order statistic: index ``ceil(q * n) - 1``, clamped into
    range.  ``q = 1.0`` selects ``values[n - 1]``, i.e. exactly ``max``, so a
    caller passing 1.0 reproduces the pre-2026-09-05 behaviour bit for bit.
    """

    ordered = sorted(values)
    index = ceil(float(quantile) * len(ordered)) - 1
    return ordered[max(0, min(len(ordered) - 1, index))]


def reference_trip_energy_kwh(
    instance: Instance,
    prices,
    duties,
    *,
    reference: str = "max",
    quantile: float | None = None,
) -> float:
    """Half-load EV energy of a reference trip in ``duties``.

    ``reference`` picks the statistic: ``"max"`` (the largest trip),
    ``"mean"``, ``"p75"`` (the 0.75 order statistic) or ``"quantile"``, which
    reads the level from ``quantile``.  The quantile path uses the same
    nearest-rank rule as ``inter_trip_reload_seconds``, so ``quantile=1.0``
    returns the maximum unchanged.  See ``RELOAD_GAP_QUANTILE`` for why the
    reload-gap caller no longer reserves the maximum.
    """
    half_load = 0.5 * float(instance.vehicle_profile("ev").payload_capacity_kg)
    trip_energies = [
        sum(
            ev_instance_arc_energy_kwh(instance, a, b, half_load, prices)
            for a, b in zip(
                (duty.home_depot_id, *trip.customer_ids),
                (*trip.customer_ids, duty.home_depot_id),
            )
        )
        for duty in duties
        for trip in duty.trips
        if trip.customer_ids
    ]
    if reference == "mean":
        return sum(trip_energies) / len(trip_energies) if trip_energies else 0.0
    if reference == "max":
        return max(trip_energies, default=0.0)
    if reference in ("p75", "quantile"):
        if not trip_energies:
            return 0.0
        level = RELOAD_GAP_QUANTILE if reference == "p75" else quantile
        if level is None:
            raise ValueError("reference='quantile' needs a quantile")
        return _order_statistic(trip_energies, level)
    raise ValueError(
        "departure gap reference must be max, mean, p75 or quantile"
    )


_RELOAD_COPY_SUFFIX = "#reload"


def _reload_copy_id(depot_id: str) -> str:
    """Kernel-only node id of a depot's reload copy."""

    return f"{depot_id}{_RELOAD_COPY_SUFFIX}"


def _metric_node_id(node_id: str) -> str:
    """Instance node id behind a kernel location (reload copies map back)."""

    if node_id.endswith(_RELOAD_COPY_SUFFIX):
        return node_id[: -len(_RELOAD_COPY_SUFFIX)]
    return node_id


def inter_trip_reload_seconds(
    individual,
    *,
    quantile: float = RELOAD_GAP_QUANTILE,
) -> float | None:
    """``quantile``-th depot charging occupancy before trips 2.. in ``individual``.

    Feeds the reload-gap proxy from an exact plan: only sessions attached to
    a trip after the first count (the first trip charges before the day
    starts).  None when the plan has no between-trip session.

    Not the mean: a reservation below what most trips actually need is
    exploited by the kernel, whose population then packs chains no exact
    repair can charge (measured 2026-09-03: a mean reservation left a
    free-fleet round with no repairable EV member and an 8-CV best).  That
    crash sets the floor -- any level chosen here must stay at or above the
    batch's median session (1348 s on the P=0.2 midday-valley batch).

    And no longer the maximum either (``quantile=1.0``, the behaviour up to
    2026-09-05): the longest single session of the previous round's exact
    best measured 2380-2642 s, and at 2614.1 s the kernel judged 25 of 33
    exactly-feasible solutions infeasible, so ``GeneticAlgorithm._best``
    could not reach them and round two searched for nothing.  See
    ``RELOAD_GAP_QUANTILE`` for the measured distribution behind the default.
    """

    seconds = [
        float(session.occupancy_minutes) * 60.0
        for duty in individual.duties
        for session in duty.charging_sessions
        if int(session.trip_index) >= 2
    ]
    if not seconds:
        return None
    return _order_statistic(seconds, quantile)


def max_inter_trip_reload_seconds(individual) -> float | None:
    """Longest depot charging occupancy before trips 2.. in ``individual``.

    The pre-2026-09-05 reservation, kept for callers and tests that want the
    maximum explicitly; ``inter_trip_reload_seconds`` with ``quantile=1.0``
    is the same value.
    """

    return inter_trip_reload_seconds(individual, quantile=1.0)


def population_inter_trip_reload_seconds(
    individuals,
    *,
    quantile: float = RELOAD_GAP_QUANTILE,
    floor_seconds: float = RELOAD_GAP_FLOOR_SECONDS,
) -> float | None:
    """Round-one reload reservation from a whole initial population.

    Pools the between-trip charging sessions of every plan in ``individuals``
    -- the same ``trip_index >= 2`` rule ``inter_trip_reload_seconds`` uses on
    one plan -- and returns their ``quantile``-th order statistic, raised to
    ``floor_seconds`` when the draw lands below it.  None when no plan has a
    between-trip session, which is the idle-start case (a written-down fleet
    the witness cannot seat carries no trips at all); the caller then keeps
    the witness's largest trip.

    Why the population and not the witness (2026-09-05): round one used to
    convert the *largest trip energy* of the single unconstrained witness,
    booking 2031.67 s where the batch's real sessions have a 1348 s median.
    A witness has 16 trips, so its order statistics are a grid too coarse to
    land in the admissible window; 25 exactly evaluated plans pool 38-66
    sessions (measured over 20 draws per arm on the P=0.2 midday-valley
    batch), which is fine enough.  The population is randomly constructed,
    so this value is per-run rather than a constant of the instance.
    """

    seconds = [
        float(session.occupancy_minutes) * 60.0
        for individual in individuals
        for duty in individual.duties
        for session in duty.charging_sessions
        if int(session.trip_index) >= 2
    ]
    if not seconds:
        return None
    return max(float(floor_seconds), _order_statistic(seconds, quantile))


FIRST_TRIP_WINDOW_OPEN_QUANTILE = 0.50


def population_first_trip_window_open_second(
    evaluations,
    *,
    quantile: float = FIRST_TRIP_WINDOW_OPEN_QUANTILE,
) -> float | None:
    """Round-one first-trip window opening from a whole initial population.

    Under ``first_trip_window="prev_return"`` each vehicle's first-trip depot
    charge may start when that vehicle came back the preceding evening.  The
    route proxy is built before any route exists, so it cannot know a
    vehicle's own return; this pools the LAST return of every electric duty in
    every exactly evaluated plan of the initial population and returns their
    ``quantile``-th order statistic -- the same device
    ``population_inter_trip_reload_seconds`` uses for the reload reservation,
    and the same ``_order_statistic`` nearest-rank rule.

    The median rather than an extreme: the value is a PRICE anchor, not a
    feasibility reservation, so neither tail is safe -- an early anchor prices
    the afternoon rows the settlement will not reach, a late one hides the
    clean afternoon the settlement does reach.

    Reads ``FullEvaluation.certificate.trips``, which carries every trip's
    ``return_second``; ``DutyIndividual`` itself does not (``duty.schedule``
    is ``None`` on a charge-repaired candidate).  Returns None when no plan
    has an electric trip, and the caller then keeps the route-independent
    fallback (the contract's last shift end).
    """

    returns: list[float] = []
    for evaluation in evaluations:
        certificate = getattr(evaluation, "certificate", None)
        if certificate is None:
            continue
        last_by_vehicle: dict[str, float] = {}
        for trip in certificate.trips:
            if str(trip.vehicle_type).lower() != "ev":
                continue
            vehicle = str(trip.physical_vehicle_id)
            last_by_vehicle[vehicle] = max(
                last_by_vehicle.get(vehicle, float("-inf")),
                float(trip.return_second),
            )
        returns.extend(last_by_vehicle.values())
    if not returns:
        return None
    return _order_statistic(returns, quantile) % STATIC_PREHORIZON_SECONDS


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
    charge_timing_policy_for_proxy: str | None = None,
    proxy_feasible_slots_only: bool = False,
    first_trip_window: str = FIRST_TRIP_WINDOW_SAME_DAY,
    first_trip_window_open_second: float | None = None,
    ev_charge_time_proxy_enabled: bool = True,
    ev_unit_cost_override: float | None = None,
    ev_departure_gap_proxy_enabled: bool = False,
    ev_departure_gap_reference: str = "max",
    ev_departure_gap_reference_kwh: float | None = None,
    ev_reload_gap_proxy_enabled: bool = False,
    ev_reload_gap_reference_kwh: float | None = None,
    ev_reload_gap_seconds: float | None = None,
    vehicle_fixed_cost_in_proxy: bool = True,
    max_reloads_per_vehicle: int | None = None,
    vehicle_type_dedup_enabled: bool = True,
):
    bundle = context.bundle
    instance = bundle.instance
    model = Model()
    depots = [
        node for node in instance.nodes if node.node_type.lower() == "d"
    ]
    # Reload copies (2026-09-03): one extra kernel depot per real depot that
    # only serves as the between-trip reload location.  It shares the real
    # depot's coordinates, window and arc metrics; the EV profile adds the
    # between-trip charging time to arcs leaving the copy and nothing to arcs
    # leaving the real depot, since the first trip charges from midnight.
    reload_copies = (
        [
            replace(node, node_id=_reload_copy_id(node.node_id))
            for node in depots
        ]
        if (
            include_propulsion_proxy
            and ev_reload_gap_proxy_enabled
            and any(duty.vehicle_type == "ev" for duty in fleet_template.duties)
        )
        else []
    )
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
    for location, node in enumerate((*depots, *reload_copies, *customers)):
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
    reload_location_by_depot_id = {
        node.node_id: location_by_node_id[_reload_copy_id(node.node_id)]
        for node in depots
        if reload_copies
    }
    reload_object = {
        node.node_id: location_object[_reload_copy_id(node.node_id)]
        for node in depots
        if reload_copies
    }

    # One arc table per (vehicle type, depot).  The kernel profiles are only
    # registered after the tables are known, so identical tables can share one
    # profile (2026-09-05); the keys themselves stay one per pair, because the
    # arc costs below are computed per pair.
    profile_keys = sorted(
        {
            (duty.vehicle_type, duty.home_depot_id)
            for duty in fleet_template.duties
        }
    )
    ev_unit_cost_by_depot: dict[str, float] = {}
    shift_aware_ev_proxy: dict[str, object] = {}
    # 2026-09-10: reference charge duration for the feasible-slot filter of
    # the shift-aware EV price (same reference the departure-gap proxy uses).
    proxy_reference_seconds: float | None = None
    if (
        proxy_feasible_slots_only
        and include_propulsion_proxy
        and any(vehicle_type == "ev" for vehicle_type, _depot in profile_keys)
    ):
        _ref_curve = _curve_for_prices(bundle.prices, instance)
        _ref_kwh = (
            reference_trip_energy_kwh(
                instance,
                bundle.prices,
                fleet_template.duties,
                reference=ev_departure_gap_reference,
            )
            if ev_departure_gap_reference_kwh is None
            else float(ev_departure_gap_reference_kwh)
        )
        _ref_kwh = min(_ref_kwh, float(_ref_curve.capacity_kwh))
        proxy_reference_seconds = float(_ref_curve.duration_seconds(0.0, _ref_kwh))
        shift_aware_ev_proxy["feasible_slots_reference_seconds"] = proxy_reference_seconds
    # 2026-09-05 (A3): how the scalar restart feedback was folded into the
    # per-shift prices, per depot.  Metadata only; keyed off the depot map so
    # it rides the existing ledger instead of opening a second channel.
    override_accounting: dict[str, object] = {}
    ev_unit_cost_by_depot_and_shift: dict[tuple[str, str], float] = {}
    for vehicle_type, depot_id in profile_keys:
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
            rates = _rebuilt_shift_aware_ev_unit_costs(
                context,
                rows,
                charge_timing_policy=charge_timing_policy_for_proxy,
                first_trip_window=first_trip_window,
                first_trip_window_open_second=first_trip_window_open_second,
                feasible_slots_only=proxy_feasible_slots_only,
                reference_charge_seconds=proxy_reference_seconds,
            )
            for shift_id, row in rates.items():
                ev_unit_cost_by_depot_and_shift[(depot_id, shift_id)] = (
                    float(row["proxy_cny_per_kwh"])
                )
            shift_aware_ev_proxy[depot_id] = rates
        if ev_unit_cost_override is not None:
            # 2026-09-05 (A3): the restart feedback is ONE scalar (last round's
            # exact cost_elec + carbon per kWh), and overwriting every shift
            # with it flattened the per-shift/per-policy structure the proxy
            # had just built -- from restart 2 on, the search saw no calendar
            # at all.  Rescale instead: the scalar sets the LEVEL, the windows
            # keep their RATIOS.  The base is an unweighted mean over shifts
            # because per-shift kWh is not known at build time; that is an
            # explicit convention, not an estimate of the true split.
            ev_unit_cost_by_depot[depot_id] = float(ev_unit_cost_override)
            keys = [
                key
                for key in ev_unit_cost_by_depot_and_shift
                if key[0] == depot_id
            ]
            if keys:
                base = sum(
                    ev_unit_cost_by_depot_and_shift[key] for key in keys
                ) / len(keys)
                factor = (
                    float(ev_unit_cost_override) / base if base > 0.0 else 1.0
                )
                if abs(factor - 1.0) > 0.25:
                    # A correction this large means the scalar and the window
                    # prices disagree about more than the level; scaling would
                    # amplify rather than calibrate.  Leave the structural
                    # prices alone this round and record why.
                    override_accounting[depot_id] = {
                        "applied": "none",
                        "reason": "factor deviates from 1 by more than 25%",
                        "factor": float(factor),
                        "unweighted_shift_mean": float(base),
                        "override_cny_per_kwh": float(ev_unit_cost_override),
                    }
                else:
                    for key in keys:
                        ev_unit_cost_by_depot_and_shift[key] *= factor
                    override_accounting[depot_id] = {
                        "applied": "proportional",
                        "factor": float(factor),
                        "unweighted_shift_mean": float(base),
                        "override_cny_per_kwh": float(ev_unit_cost_override),
                    }
    if override_accounting:
        shift_aware_ev_proxy["ev_unit_cost_override_accounting"] = (
            override_accounting
        )
    # 2026-09-02 (A): the kernel is the only place routes are searched, and
    # until now its EV profile carried travel time only, so 86% of its children
    # died in charging repair on time it could not see (between-trip depot
    # charging).  With an empty morning battery and just-enough charging,
    # every kWh driven must be bought back at the depot charger before the
    # next departure, so EV arc durations now carry travel + energy / P_eff,
    # P_eff read from the depot charging curve (average power from empty to
    # half the battery).  Exact charging repair remains the final judge.
    ev_charge_time_proxy: dict[str, float] | None = None
    if (
        include_propulsion_proxy
        and ev_charge_time_proxy_enabled
        and any(vehicle_type == "ev" for vehicle_type, _depot in profile_keys)
    ):
        curve = _curve_for_prices(bundle.prices, instance)
        reference_energy_kwh = 0.5 * float(curve.capacity_kwh)
        reference_seconds = float(
            curve.duration_seconds(0.0, reference_energy_kwh)
        )
        if reference_energy_kwh <= 0.0 or reference_seconds <= 0.0:
            raise ValueError("EV charge-time proxy needs a positive charging curve")
        ev_charge_time_proxy = {
            "curve_id": str(curve.curve_id),
            "reference_energy_kwh": reference_energy_kwh,
            "effective_power_kw": reference_energy_kwh
            / (reference_seconds / 3600.0),
            "seconds_per_kwh": reference_seconds / reference_energy_kwh,
            "ev_half_load_kg": 0.5
            * float(instance.vehicle_profile("ev").payload_capacity_kg),
        }
    # Departure-gap proxy (2026-09-03): the exact ledger sizes every depot
    # charge for the *next* trip from an empty battery, a requirement no
    # per-arc amortisation can express (it can only carry the trip's own
    # energy).  Instead every EV arc leaving a depot carries the charge time
    # of the largest trip in the reference construction, so a chain the
    # kernel calls on time always leaves a gap the exact repair can fill.
    ev_departure_gap_seconds = 0.0
    if (
        include_propulsion_proxy
        and ev_departure_gap_proxy_enabled
        and any(vehicle_type == "ev" for vehicle_type, _depot in profile_keys)
    ):
        curve = _curve_for_prices(bundle.prices, instance)
        reference_energy = (
            reference_trip_energy_kwh(
                instance,
                bundle.prices,
                fleet_template.duties,
                reference=ev_departure_gap_reference,
            )
            if ev_departure_gap_reference_kwh is None
            else float(ev_departure_gap_reference_kwh)
        )
        reference_energy = min(reference_energy, float(curve.capacity_kwh))
        ev_departure_gap_seconds = float(curve.duration_seconds(0.0, reference_energy))
        ev_charge_time_proxy = {
            **(ev_charge_time_proxy or {}),
            "departure_gap_seconds": ev_departure_gap_seconds,
            "departure_gap_reference_kwh": reference_energy,
        }
    # Reload-gap proxy: between-trip depot charging time on EV arcs into a
    # reload copy.  Round one reserves the charge of the *largest* reference
    # trip (a sufficient reservation: a smaller one is exploited by the
    # kernel, whose population then packs chains no exact repair can charge).
    # Later rounds pass the between-trip charge the exact best actually
    # needed, at ``RELOAD_GAP_QUANTILE`` since 2026-09-05 -- the maximum put
    # 25 of 33 exactly-feasible solutions outside the kernel's reach.  The
    # first trip of the day reserves nothing.
    reload_gap_seconds = 0.0
    if reload_copies:
        curve = _curve_for_prices(bundle.prices, instance)
        if ev_reload_gap_seconds is not None:
            reload_gap_seconds = max(0.0, float(ev_reload_gap_seconds))
            reload_reference_kwh = None
        else:
            reload_reference_kwh = (
                reference_trip_energy_kwh(
                    instance,
                    bundle.prices,
                    fleet_template.duties,
                    reference="max",
                )
                if ev_reload_gap_reference_kwh is None
                else float(ev_reload_gap_reference_kwh)
            )
            reload_reference_kwh = min(
                reload_reference_kwh, float(curve.capacity_kwh)
            )
            reload_gap_seconds = float(
                curve.duration_seconds(0.0, reload_reference_kwh)
            )
        ev_charge_time_proxy = {
            **(ev_charge_time_proxy or {}),
            "reload_gap_seconds": reload_gap_seconds,
            "reload_gap_reference_kwh": reload_reference_kwh,
            "reload_copy_depots": len(reload_copies),
        }
    depot_ids = {node.node_id for node in depots}
    reload_ids = {node.node_id for node in reload_copies}
    arc_rows: dict[tuple[str, str], list[tuple[str, str, int, int]]] = {
        key: [] for key in profile_keys
    }
    for left in (*depots, *reload_copies, *customers):
        left_id = _metric_node_id(left.node_id)
        for right in (*depots, *reload_copies, *customers):
            if left.node_id == right.node_id:
                continue
            right_id = _metric_node_id(right.node_id)
            for (vehicle_type, depot_id) in profile_keys:
                _distance_m, duration_s, _ = instance.arc_metrics(
                    left_id,
                    right_id,
                    vehicle_type,
                    fallback_speed_mps=float(bundle.prices.v_speed_ms),
                )
                if (
                    vehicle_type == "ev"
                    and ev_charge_time_proxy is not None
                    and "seconds_per_kwh" in ev_charge_time_proxy
                ):
                    arc_energy_kwh = ev_instance_arc_energy_kwh(
                        instance,
                        left_id,
                        right_id,
                        ev_charge_time_proxy["ev_half_load_kg"],
                        bundle.prices,
                    )
                    duration_s = float(duration_s) + (
                        float(arc_energy_kwh)
                        * ev_charge_time_proxy["seconds_per_kwh"]
                    )
                if vehicle_type == "ev" and left.node_id in depot_ids:
                    duration_s = float(duration_s) + ev_departure_gap_seconds
                if (
                    vehicle_type == "ev"
                    and right.node_id in reload_ids
                    and left.node_id not in depot_ids
                    and left.node_id not in reload_ids
                ):
                    # The between-trip charge is booked on the customer ->
                    # reload-copy arc (the return that precedes it).  Booking
                    # it on the copy's outgoing arcs instead makes the
                    # copied kernel's local search cycle forever (measured
                    # 2026-09-03: DepotSplit + RelocateWithDepot with
                    # asymmetric depot-leaving durations); arriving-side
                    # booking keeps every depot-leaving arc symmetric.
                    duration_s = float(duration_s) + reload_gap_seconds
                arc_rows[(vehicle_type, depot_id)].append(
                    (
                        left.node_id,
                        right.node_id,
                        _route_proxy_cost_units(
                            context,
                            left_id,
                            right_id,
                            vehicle_type=vehicle_type,
                            depot_id=depot_id,
                            ev_unit_cost=ev_unit_cost_by_depot.get(depot_id),
                            ev_unit_cost_by_shift=(
                                {
                                    shift_id: unit_cost
                                    for (candidate_depot, shift_id), unit_cost
                                    in (
                                        ev_unit_cost_by_depot_and_shift.items()
                                    )
                                    if candidate_depot == depot_id
                                }
                                if shift_aware_ev_unit_cost_enabled
                                else None
                            ),
                            include_propulsion_proxy=include_propulsion_proxy,
                        ),
                        max(0, round(duration_s)),
                    )
                )

    # Register one kernel profile per *distinct* arc table.  ``profiles`` is
    # built by (vehicle type, depot) because the arc costs are, but the two
    # depots can price diesel and electricity identically -- they do on the
    # delivered instance, where the four tables are two -- and then the copies
    # only cost memory.  The test is the table itself, arc for arc, so a
    # calendar that prices the depots apart keeps its four profiles.
    profiles: dict[tuple[str, str], object] = {}
    profile_groups: list[list[tuple[str, str]]] = []
    if vehicle_type_dedup_enabled:
        group_by_table: dict[tuple, int] = {}
        for key in profile_keys:
            table = tuple(arc_rows[key])
            index = group_by_table.get(table)
            if index is None:
                index = len(profile_groups)
                group_by_table[table] = index
                profile_groups.append([])
            profile_groups[index].append(key)
    else:
        profile_groups = [[key] for key in profile_keys]
    for members in profile_groups:
        profile = model.add_profile(
            name="+".join(
                f"{vehicle_type}@{depot_id}"
                for vehicle_type, depot_id in members
            )
        )
        for left_node, right_node, distance, duration in arc_rows[members[0]]:
            model.add_edge(
                location_object[left_node],
                location_object[right_node],
                distance=distance,
                duration=duration,
                profile=profile,
            )
        for key in members:
            profiles[key] = profile
    profile_group_by_key = {
        key: index
        for index, members in enumerate(profile_groups)
        for key in members
    }

    vehicle_type_by_duty_id: dict[str, int] = {}
    duty_ids_by_vehicle_type: dict[int, list[str]] = {}
    # Reload slots per vehicle.  ``len(customers) - 1`` (49 here) is the
    # theoretical bound -- one trip per customer -- and was the value up to
    # 2026-09-05.  No plan the exact model ever accepted came near it: the
    # largest duty across every dumped ``best_solution.json`` of the
    # 2026-09-04/05 batches runs 5 trips, i.e. 4 reloads.  A caller-supplied
    # cap keeps the kernel's reload dimension honest without changing what
    # any accepted plan can express; ``None`` restores the historic bound.
    max_reloads = (
        max(0, len(customers) - 1)
        if max_reloads_per_vehicle is None
        else max(0, int(max_reloads_per_vehicle))
    )
    vehicle_type_arguments: list[
        tuple[str, tuple, dict[str, object]]
    ] = []
    for duty in fleet_template.duties:
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
        fixed_cost = (
            _money_units(
                instance.vehicle_fixed_cost_per_day(
                    duty.vehicle_type,
                    fallback=bundle.prices.vehicle_fixed_cost,
                )
            )
            if vehicle_fixed_cost_in_proxy
            else 0  # fixed composition: the fleet's fixed cost is a constant
        )
        vehicle_type_arguments.append(
            (
                duty.physical_vehicle_id,
                # Everything that makes two kernel vehicle types
                # interchangeable, i.e. every ``add_vehicle_type`` argument
                # below except ``name``.  ``home_depot_id`` stands in for the
                # depot and reload-copy handles, which are functions of it and
                # need not be hashable.
                (
                    tuple(capacity)
                    if isinstance(capacity, list)
                    else capacity,
                    duty.home_depot_id,
                    fixed_cost,
                    round(vehicle_tw_early),
                    round(depot_open.due_time),
                    profile_group_by_key[
                        (duty.vehicle_type, duty.home_depot_id)
                    ],
                    max_reloads if multi_trip_enabled else 0,
                    bool(multi_trip_enabled),
                ),
                dict(
                    capacity=capacity,
                    start_depot=depot,
                    end_depot=depot,
                    fixed_cost=fixed_cost,
                    tw_early=round(vehicle_tw_early),
                    tw_late=round(depot_open.due_time),
                    unit_distance_cost=1,
                    profile=profiles[
                        (duty.vehicle_type, duty.home_depot_id)
                    ],
                    reload_depots=(
                        [reload_object.get(duty.home_depot_id, depot)]
                        if multi_trip_enabled
                        else []
                    ),
                    max_reloads=max_reloads if multi_trip_enabled else 0,
                ),
            )
        )
    # 2026-09-05: one kernel vehicle type per distinct argument vector rather
    # than one per physical vehicle.  ``name`` is the only field that ever
    # differed on the delivered static batch -- it is the physical vehicle id,
    # and it existed only so ``_decode_changes`` could map a returned route
    # back to its asset, which the group's duty-id list now does instead.
    # Everything else is in the key, so nothing here is hard-coded: under a
    # dynamic cut ``tw_early`` is per vehicle and this loop registers the 20
    # types again by itself.
    index_by_key: dict[tuple, int] = {}
    arguments_by_index: list[dict[str, object]] = []
    for duty_id, key, arguments in vehicle_type_arguments:
        index = index_by_key.get(key) if vehicle_type_dedup_enabled else None
        if index is None:
            index = len(arguments_by_index)
            index_by_key[key] = index
            arguments_by_index.append(arguments)
            duty_ids_by_vehicle_type[index] = []
        duty_ids_by_vehicle_type[index].append(duty_id)
        vehicle_type_by_duty_id[duty_id] = index
    for index, arguments in enumerate(arguments_by_index):
        members = duty_ids_by_vehicle_type[index]
        model.add_vehicle_type(
            # Identical argument vectors, so the merged type owns exactly as
            # many vehicles as the group has members.
            num_available=len(members),
            name="+".join(members),
            **arguments,
        )
    return (
        model.data(),
        location_by_node_id,
        node_id_by_location,
        vehicle_type_by_duty_id,
        duty_ids_by_vehicle_type,
        shift_aware_ev_proxy,
        ev_charge_time_proxy,
        reload_location_by_depot_id,
    )


def _money_units(value: float | Decimal) -> int:
    """Encode one model-currency amount on the route-kernel integer scale."""

    scaled = Decimal(str(value)) * _ROUTE_COST_SCALE
    return max(0, int(scaled.to_integral_value(rounding=ROUND_HALF_UP)))


def _calendar_span_pricer(rows, duration: float):
    """Return ``start -> (electricity, gco2)`` averaged over ``[start, start +
    duration]`` on the daily calendar ``rows`` (absolute starts may be
    negative for the previous evening; each instant maps to its day row)."""

    day_rows = sorted(rows, key=lambda row: float(row["horizon_second_start"]))
    starts = [float(row["horizon_second_start"]) for row in day_rows]

    def _price(start: float) -> tuple[float, float]:
        remaining = float(duration)
        instant = float(start)
        electricity = 0.0
        gco2 = 0.0
        if remaining <= 0.0:
            row = day_rows[max(bisect.bisect_right(starts, instant % STATIC_PREHORIZON_SECONDS) - 1, 0)]
            return (
                float(row["depot_energy_cny_per_kwh"]),
                float(row["actual_gco2_per_kwh"]),
            )
        while remaining > 1e-9:
            day_second = instant % STATIC_PREHORIZON_SECONDS
            index = max(bisect.bisect_right(starts, day_second) - 1, 0)
            row_end = (
                starts[index + 1]
                if index + 1 < len(starts)
                else STATIC_PREHORIZON_SECONDS
            )
            segment = min(remaining, max(row_end - day_second, 1e-9))
            electricity += segment * float(day_rows[index]["depot_energy_cny_per_kwh"])
            gco2 += segment * float(day_rows[index]["actual_gco2_per_kwh"])
            instant += segment
            remaining -= segment
        return electricity / float(duration), gco2 / float(duration)

    return _price


def _rebuilt_shift_aware_ev_unit_costs(
    context: DutyEvaluationContext,
    rows,
    *,
    charge_timing_policy: str | None = None,
    first_trip_window: str = FIRST_TRIP_WINDOW_SAME_DAY,
    first_trip_window_open_second: float | None = None,
    feasible_slots_only: bool = False,
    reference_charge_seconds: float | None = None,
) -> dict[str, dict[str, float | int]]:
    """Price each causal charging window at what THIS arm's policy would pay.

    2026-09-05 (A1/A4): the window used to be priced by one fixed key
    (lowest carbon, then cheapest, ties to the LATEST slot) regardless of the
    arm's charge-timing policy, so both arms searched routes against an
    identical EV price and the timing mechanism could not express itself in
    the route proxy.  The selection key is now the arm's own policy, which is
    what the exact charge-timing settlement will actually pay.

    ``charge_timing_policy=None`` keeps the historical key verbatim, so every
    caller that does not declare a policy is bit-for-bit unchanged.

    Ties break to the EARLIEST slot, matching the exact timer
    (``charge_timing.select_charge_timing_start`` ends in
    ``min(scored, key=lambda item: (item[0], item[1]))`` with ``item[1]`` the
    start instant).  Under the beijing/uniform calendars this moves
    ``cost_plus_carbon``'s recorded slot (390 -> 360 min) while leaving
    ``proxy_cny_per_kwh`` bit-identical: the tied slots have equal price and
    equal carbon.

    2026-09-06: under ``first_trip_window="prev_return"`` the FIRST shift's
    causal window no longer opens at the simulation day's 00:00 but at the
    depot return of the preceding evening, so it wraps across midnight and
    also covers the evening calendar rows.  The route proxy is built before
    any route exists, so it cannot read a vehicle's own return;
    ``first_trip_window_open_second`` carries the caller's route-independent
    estimate of it -- the MEDIAN last return of the initial population, taken
    with the same order statistic the reload reservation uses.  None keeps the
    fallback the exact repair itself uses for a single-trip duty: the
    contract's last shift end (19:00 on this instance).

    The opening instant almost never lands on a calendar boundary, so the
    window's first priced row is the row that CONTAINS it, not the first row
    after it (measured 2026-09-06: with a 16:20 opening, filtering on
    ``start >= opening`` skipped the 16:00-16:30 row the exact settlement
    actually pays and priced ``asap`` at 16:30).  That containing row is
    ordered at the opening instant itself, since that is when ``asap`` starts
    charging.  Slots are ordered by their ABSOLUTE instant (an evening row
    counts as ``start - 86400``), so ``asap`` takes the evening return instead
    of the day's midnight valley while every cost-driven key still ranks the
    whole merged window on price and carbon.  Later shifts keep their same-day
    inter-shift windows unchanged.
    """

    if charge_timing_policy is not None:
        charge_timing_policy = validate_charge_timing_policy(
            str(charge_timing_policy)
        )
    validate_first_trip_window(first_trip_window)
    carbon_price = float(context.bundle.prices.carbon_price)

    def _selection_key(item):
        row, start = item
        return _key_values(
            float(row["depot_energy_cny_per_kwh"]),
            float(row["actual_gco2_per_kwh"]),
            start,
        )

    def _key_values(electricity, gco2, start):
        if charge_timing_policy is None:
            return (gco2, electricity, -start)
        policy = charge_timing_policy
        # Same degeneration as the exact timer: with no carbon price the
        # carbon term vanishes, so cost_plus_carbon IS cost_min.
        if policy == "cost_plus_carbon" and carbon_price == 0.0:
            policy = "cost_min"
        if policy == "asap":
            return (start,)
        if policy == "cost_min":
            return (electricity, start)
        if policy == "carbon_min":
            return (gco2, start)
        if policy == "cost_plus_carbon":
            return (electricity + gco2 / 1_000.0 * carbon_price, start)
        raise ValueError(
            f"unknown charge timing policy {charge_timing_policy!r}"
        )

    contract = context.rebuilt_route_constraints
    if contract is None:
        raise ValueError("shift-aware EV price requires rebuilt route constraints")
    ordered = sorted(
        contract.shift_window_second_by_id.items(),
        key=lambda item: (float(item[1][0]), item[0]),
    )
    last_shift_end = max(
        float(window[1])
        for window in contract.shift_window_second_by_id.values()
    )
    selected: dict[str, dict[str, float | int]] = {}
    previous_end = 0.0
    for position, (shift_id, (shift_start, shift_end)) in enumerate(ordered):
        window_start = previous_end
        window_end = float(shift_start)
        wraps_to_previous_evening = (
            position == 0
            and first_trip_window == FIRST_TRIP_WINDOW_PREV_RETURN
        )
        if wraps_to_previous_evening:
            opening = (
                last_shift_end
                if first_trip_window_open_second is None
                else float(first_trip_window_open_second)
            )
            if not 0.0 <= opening < STATIC_PREHORIZON_SECONDS:
                raise ValueError(
                    "the first-trip window opening must be a local second of "
                    f"one representative day, got {opening!r}"
                )
            starts_at_or_before = [
                float(row["horizon_second_start"])
                for row in rows
                if float(row["horizon_second_start"]) <= opening
            ]
            # The row that CONTAINS the opening is the last one starting at or
            # before it; that row's price is what a charge beginning at the
            # opening pays.
            evening_floor = (
                max(starts_at_or_before) if starts_at_or_before else opening
            )
            window_start = opening - STATIC_PREHORIZON_SECONDS
            merged: dict[int, tuple[dict, float]] = {}
            for position_in_day, row in enumerate(rows):
                start = float(row["horizon_second_start"])
                if start >= evening_floor:
                    merged[position_in_day] = (
                        row,
                        max(start, opening) - STATIC_PREHORIZON_SECONDS,
                    )
                elif start < window_end:
                    merged[position_in_day] = (row, start)
            available = tuple(merged[key] for key in sorted(merged))
        else:
            available = tuple(
                (row, float(row["horizon_second_start"]))
                for row in rows
                if window_start
                <= float(row["horizon_second_start"])
                < window_end
            )
        if not available:
            raise ValueError(
                f"shift {shift_id!r} has no causal depot charging slot"
            )
        priced_start: float | None = None
        if feasible_slots_only and reference_charge_seconds:
            # 2026-09-10: price the window the way the exact timer settles it.
            # A candidate start is a row's first instant inside the window
            # (the opening itself for the row that contains it); it is kept
            # only when the reference charge can finish before the shift
            # departs, and it is priced by the time-weighted electricity and
            # carbon over the whole charge span, not by the single row it
            # starts in.  Measured 2026-09-10 (midday calendar, 1.0 CNY/kg):
            # the single-row key priced ``carbon_min`` at the 15:30 row of the
            # previous evening (182.5 g) although a charge opening at 15:47
            # runs into the 16:00 row and later returns land in the 17:00
            # peak, so that arm's route search saw the cheapest EV of the four
            # arms while its settlement paid the most.
            duration = float(reference_charge_seconds)
            span = _calendar_span_pricer(rows, duration)
            candidates = tuple(
                (row, max(start, window_start))
                for row, start in available
                if max(start, window_start) + duration <= window_end
            )
            if candidates:
                priced = tuple(
                    (row, start, *span(start)) for row, start in candidates
                )
                row, priced_start, electricity, carbon = min(
                    priced,
                    key=lambda item: _key_values(item[2], item[3], item[1]),
                )
        if priced_start is None:
            row, _absolute_start = min(available, key=_selection_key)
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
            **(
                {}
                if priced_start is None
                else {
                    "priced_start_second": float(priced_start),
                    "reference_charge_seconds": float(
                        reference_charge_seconds
                    ),
                }
            ),
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


def _least_churn_match(
    slots: list[str],
    chains: list[tuple[tuple[str, ...], ...]],
    loaded: dict[str, tuple[tuple[str, ...], ...]],
    locked_prefixes: dict[str, frozenset[str]],
) -> dict[str, tuple[tuple[str, ...], ...]]:
    """Seat one vehicle type's returned routes on its own physical slots.

    Merging parameter-identical vehicles into one kernel vehicle type makes the
    route -> physical asset map many-to-one, so the decoder has to choose which
    slot of the group each returned chain belongs to.  Inside a group the
    choice is free -- the members' parameter vectors are identical field for
    field, so any seating prices out the same -- but it is *not* free
    downstream: ``_decode_changes`` only reports the duties whose chain
    changed, and the exact stage re-decodes, charge-repairs and fully evaluates
    one duty per reported change.  Seating arbitrarily would report all 20
    vehicles as changed on every iteration and hand the per-iteration saving
    straight back to the exact stage, so the seating is the one that changes
    the fewest duties: locked duties first, then whoever already owns the
    chain, then by shared customers.
    """

    assigned: dict[str, tuple[tuple[str, ...], ...]] = {}
    free = list(slots)
    rest = list(chains)

    def take(duty_id: str, chain: tuple[tuple[str, ...], ...]) -> None:
        assigned[duty_id] = chain
        free.remove(duty_id)
        rest.remove(chain)

    # (1) A locked duty cannot move: it keeps its own chain when the kernel
    # returned it unchanged, and otherwise the chain that carries its locked
    # prefix.  (Static runs never get here -- ``propose`` bails out on any
    # locked duty -- but the dynamic path can, and the group is the only place
    # a lock could silently change hands.)
    for duty_id in [slot for slot in slots if slot in locked_prefixes]:
        if not rest:
            break
        own = loaded[duty_id]
        if own and own in rest:
            take(duty_id, own)
            continue
        locked_customers = locked_prefixes[duty_id]
        if not locked_customers:
            continue
        carrier = next(
            (
                chain
                for chain in rest
                if locked_customers.issubset(
                    {customer for trip in chain for customer in trip}
                )
            ),
            None,
        )
        if carrier is not None:
            take(duty_id, carrier)
    # (2) Whatever came back unchanged stays where it was: zero churn.
    for duty_id in list(free):
        own = loaded[duty_id]
        if own and own in rest:
            take(duty_id, own)
    # (3) The rest go to the slot they share the most customers with; ties keep
    # the earliest free slot, so the seating is deterministic.
    while rest and free:
        chain = rest[0]
        customers = {customer for trip in chain for customer in trip}
        duty_id = max(
            free,
            key=lambda slot: len(
                customers
                & {customer for trip in loaded[slot] for customer in trip}
            ),
        )
        take(duty_id, chain)
    for duty_id in free:
        assigned[duty_id] = ()
    return assigned


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
