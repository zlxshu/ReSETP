"""Kernel vehicle-type / profile dedup (2026-09-05).

Up to 2026-09-05 the route kernel got one vehicle type per physical vehicle.
That was never a modelling statement -- the 20 types carry the same parameter
vector in four equivalence classes, and the per-vehicle type existed only so a
returned route could be mapped back to its asset through ``name``.  It is,
however, a per-iteration cost: ``LocalSearch``'s empty-route probe runs once
per vehicle type for every customer and every step with no incremental cache,
and 14 to 15 of the 20 kernel routes sit empty in every dumped plan.

These tests pin the three properties the merge has to keep:

* the compiled model is the same model -- every cost field of a projected plan
  reads identically with the dedup on and off (V1);
* decoding is churn-free -- projecting a plan and decoding it back reports no
  changed duty, whatever order the group's routes come back in (V2), because a
  spurious "changed" duty costs a full exact re-evaluation downstream;
* the merge is data-driven, never a hard-coded count, and it preserves the
  fixed-composition experiment's (vehicle type, depot) multiset (V3, V5).

The per-iteration measurement itself is not a test (it is a timing, and it is
recorded in ``docs/handoff/per_iteration_cost_design_20260905.md``).
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    FLEET_PARAMETER_CLASSES,
    _build_context,
)
from setp_hgs_kernel import Route as KernelRoute  # noqa: E402
from setp_hgs_kernel import Solution as KernelSolution  # noqa: E402
from setp_hgs_kernel import Trip as KernelTrip  # noqa: E402
from setp_solver.algorithms.problem_hgs.kernel_proposals import (  # noqa: E402
    IndependentKernelDutyRouteProposalEngine,
    _least_churn_match,
)
from setp_solver.algorithms.problem_hgs.model import (  # noqa: E402
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)


REPO = Path(__file__).parents[2]

# Every field of the kernel reading that a route skeleton can move.
COST_FIELDS = (
    "distance",
    "distance_cost",
    "duration",
    "duration_cost",
    "fixed_vehicle_cost",
    "time_warp",
    "excess_distance",
    "is_feasible",
    "num_routes",
    "num_trips",
    "num_clients",
)

# Batches whose fleet is the unconstrained 20-vehicle one this module builds.
DUMP_BATCHES = (
    "ideal_construction_20260904/P=0.2/MT-HGS",
    "ideal_construction_20260904/P=0.2/MTC-HGS",
    "reload_fix_shortrun_20260905/MT-HGS",
    "reload_fix_shortrun_20260905/MTC-HGS",
    "policy_proxy_shortrun_20260905/MTC-HGS",
    "ablation_formal_10x_v5_20260904/MT-HGS",
    "ablation_formal_10x_v5_20260904/MTC-HGS",
)


def _engine(context, fleet_template, **extra):
    return IndependentKernelDutyRouteProposalEngine(
        context,
        fleet_template,
        stream_role="main_route",
        depot_assignment_operator_enabled=True,
        rebuilt_volume_capacity_enabled=True,
        rebuilt_shift_neighbours_only=True,
        ev_charge_time_proxy_enabled=False,
        ev_reload_gap_proxy_enabled=True,
        max_reloads_per_vehicle=8,
        **extra,
    )


@pytest.fixture(scope="module")
def pair():
    """The delivered engine with the dedup on and off, on one context."""

    _bundle, initial, _neutral, context = _build_context(
        REPO,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=FLEET_PARAMETER_CLASSES["endogenous"],
    )
    return (
        _engine(context, initial, vehicle_type_dedup_enabled=True),
        _engine(context, initial, vehicle_type_dedup_enabled=False),
        initial,
    )


def _project(engine, individual):
    """``engine._project`` for a plan whose duties are plain dictionaries."""

    data = engine.data
    location = engine._location_by_node_id
    reload_location = engine._reload_location_by_depot_id
    routes = []
    for duty in individual.duties:
        chains = [trip.customer_ids for trip in duty.trips if trip.customer_ids]
        if not chains:
            continue
        vehicle_type = engine._vehicle_type_by_duty_id[duty.physical_vehicle_id]
        depot = location[duty.home_depot_id]
        reload_copy = reload_location.get(duty.home_depot_id, depot)
        last = len(chains) - 1
        trips = [
            KernelTrip(
                data,
                [location[customer] for customer in chain],
                vehicle_type,
                start_depot=depot if index == 0 else reload_copy,
                end_depot=depot if index == last else reload_copy,
            )
            for index, chain in enumerate(chains)
        ]
        routes.append(KernelRoute(data, trips, vehicle_type))
    return KernelSolution(data, routes)


def _readings(solution):
    values = {field: getattr(solution, field)() for field in COST_FIELDS}
    values["excess_load"] = list(solution.excess_load())
    return values


def _individual_from_dump(path: Path) -> DutyIndividual:
    payload = json.loads(path.read_text())["individual"]
    duties = tuple(
        PhysicalVehicleDuty(
            physical_vehicle_id=duty["physical_vehicle_id"],
            vehicle_type=duty["vehicle_type"],
            home_depot_id=duty["home_depot_id"],
            trips=tuple(
                DutyTrip(
                    trip_index=int(trip["trip_index"]),
                    customer_ids=tuple(trip["customer_ids"]),
                    locked_customer_prefix=tuple(
                        trip.get("locked_customer_prefix", ())
                    ),
                    route_visits=tuple(trip.get("route_visits", ())),
                )
                for trip in duty["trips"]
            ),
        )
        for duty in payload["duties"]
    )
    return DutyIndividual(duties=duties, source="dump")


def _reindexed(trips) -> tuple[DutyTrip, ...]:
    return tuple(
        replace(trip, trip_index=index)
        for index, trip in enumerate(trips, start=1)
    )


def _synthetic_plans(initial: DutyIndividual) -> list[DutyIndividual]:
    """Plans that exercise the many-to-one map without needing the dumps.

    Each one puts at least two loaded routes inside one merged vehicle type,
    which is exactly the case the 1:1 decoder used to reject.
    """

    by_id = {duty.physical_vehicle_id: duty for duty in initial.duties}
    plans = [initial]

    def rebuild(changed):
        return DutyIndividual(
            duties=tuple(
                changed.get(duty.physical_vehicle_id, duty)
                for duty in initial.duties
            ),
            source="synthetic",
        )

    groups: dict[tuple[str, str], list[str]] = {}
    for duty in initial.duties:
        groups.setdefault((duty.vehicle_type, duty.home_depot_id), []).append(
            duty.physical_vehicle_id
        )
    # A group whose first member carries more than one trip, so the moves below
    # actually have something to move.
    donor_id, receiver_id = next(
        (members[0], members[-1])
        for members in groups.values()
        if len(members) > 1 and len(by_id[members[0]].trips) > 1
    )
    donor, receiver = by_id[donor_id], by_id[receiver_id]

    # (a) two members of one group swap their whole day.
    plans.append(
        rebuild(
            {
                donor_id: replace(donor, trips=receiver.trips),
                receiver_id: replace(receiver, trips=donor.trips),
            }
        )
    )
    # (b) the donor's last trip moves onto another slot of the same group.
    plans.append(
        rebuild(
            {
                donor_id: replace(donor, trips=_reindexed(donor.trips[:-1])),
                receiver_id: replace(
                    receiver,
                    trips=_reindexed((*receiver.trips, donor.trips[-1])),
                ),
            }
        )
    )
    # (c) the donor's day is emptied outright.
    plans.append(rebuild({donor_id: replace(donor, trips=())}))
    return plans


def _dumped_plans(initial: DutyIndividual, limit: int = 48):
    registry = tuple(
        (duty.physical_vehicle_id, duty.vehicle_type, duty.home_depot_id)
        for duty in initial.duties
    )
    plans = []
    for batch in DUMP_BATCHES:
        for path in sorted(
            (REPO / "solver/reports" / batch).glob("run_*/best_solution.json")
        ):
            plan = _individual_from_dump(path)
            if (
                tuple(
                    (
                        duty.physical_vehicle_id,
                        duty.vehicle_type,
                        duty.home_depot_id,
                    )
                    for duty in plan.duties
                )
                != registry
            ):
                continue
            plans.append((path, plan))
            if len(plans) >= limit:
                return plans
    return plans


def test_dedup_merges_by_parameter_vector_not_by_a_hard_coded_count(pair):
    """V3: 20 types -> 4 and 4 profiles -> 2, with the fleet size untouched."""

    merged, historic, initial = pair
    assert historic.data.num_vehicle_types == len(initial.duties) == 20
    assert historic.data.num_profiles == 4
    assert merged.data.num_vehicle_types == 4
    assert merged.data.num_profiles == 2
    # The fleet itself does not shrink: the merged types own the same vehicles.
    assert merged.data.num_vehicles == historic.data.num_vehicles == 20
    assert (
        sum(
            vehicle_type.num_available
            for vehicle_type in merged.data.vehicle_types()
        )
        == 20
    )
    # One group per (vehicle type, depot); every physical vehicle in exactly one.
    assert sorted(
        len(members) for members in merged._duty_ids_by_vehicle_type.values()
    ) == [3, 3, 7, 7]
    seated = [
        duty_id
        for members in merged._duty_ids_by_vehicle_type.values()
        for duty_id in members
    ]
    assert sorted(seated) == sorted(
        duty.physical_vehicle_id for duty in initial.duties
    )
    for index, members in merged._duty_ids_by_vehicle_type.items():
        assert merged.data.vehicle_type(index).num_available == len(members)
        assert merged.data.vehicle_type(index).name == "+".join(members)
        for duty_id in members:
            assert merged._vehicle_type_by_duty_id[duty_id] == index
    # Merging vehicle types must not disturb the DepotSplit grouping.
    assert merged.depot_assignment_compatible_vehicle_groups == (0, 0, 1, 1)
    assert historic.depot_assignment_compatible_vehicle_groups == (
        (0,) * 10 + (1,) * 10
    )
    # The lineage string marks the deviation, like every other switch.
    assert "vtype-dedup:" in merged.source_id
    assert "vtype-dedup:" not in historic.source_id


def test_projected_plans_read_identically_with_and_without_the_dedup(pair):
    """V1: the merged model is the same model, field for field."""

    merged, historic, initial = pair
    plans = _synthetic_plans(initial)
    plans.extend(plan for _path, plan in _dumped_plans(initial))
    assert len(plans) >= 4
    for plan in plans:
        assert _readings(_project(merged, plan)) == _readings(
            _project(historic, plan)
        )


def test_dumped_plans_read_identically_with_and_without_the_dedup(pair):
    """V1 on the real corpus, when the (git-ignored) run dumps are present."""

    merged, historic, initial = pair
    plans = _dumped_plans(initial)
    if not plans:
        pytest.skip("no dumped best_solution.json under solver/reports")
    for path, plan in plans:
        assert _readings(_project(merged, plan)) == _readings(
            _project(historic, plan)
        ), path


def test_decoding_a_projected_plan_reports_no_change(pair):
    """V2: project -> decode is a round trip, in any group route order.

    Without the least-churn seating the merged model would report every
    vehicle of a group as changed and hand the per-iteration saving straight
    back to the exact stage.
    """

    merged, _historic, initial = pair
    plans = _synthetic_plans(initial)
    plans.extend(plan for _path, plan in _dumped_plans(initial))
    for plan in plans:
        solution = _project(merged, plan)
        assert merged._decode_changes(plan, solution) == ()
        reversed_routes = KernelSolution(
            merged.data, list(reversed(list(solution.routes())))
        )
        assert merged._decode_changes(plan, reversed_routes) == ()


def test_an_empty_trip_still_counts_as_a_change(pair):
    """The kernel drops empty trips, and that has always been a change.

    The dedup matches on the loaded chains, but the reported diff must stay
    exactly what the 1:1 decoder produced, empty trips included.
    """

    merged, historic, initial = pair
    donor = next(duty for duty in initial.duties if duty.trips)
    with_empty = replace(
        donor,
        trips=_reindexed((*donor.trips, DutyTrip(trip_index=1, customer_ids=()))),
    )
    plan = DutyIndividual(
        duties=tuple(
            with_empty if duty.physical_vehicle_id == donor.physical_vehicle_id
            else duty
            for duty in initial.duties
        ),
        source="synthetic",
    )
    # The empty trip disappears, so the duty is reported as changed -- with
    # and without the dedup, exactly as the 1:1 decoder did.
    expected = (
        (
            donor.physical_vehicle_id,
            tuple(trip.customer_ids for trip in donor.trips),
        ),
    )
    assert merged._decode_changes(plan, _project(merged, plan)) == expected
    assert historic._decode_changes(plan, _project(historic, plan)) == expected


def test_a_locked_duty_keeps_its_own_slot(pair):
    """A locked duty cannot change hands inside its group."""

    merged, _historic, initial = pair
    groups: dict[tuple[str, str], list] = {}
    for duty in initial.duties:
        groups.setdefault((duty.vehicle_type, duty.home_depot_id), []).append(
            duty
        )
    loaded_pair = next(
        [duty for duty in members if duty.trips][:2]
        for members in groups.values()
        if len([duty for duty in members if duty.trips]) >= 2
    )
    locked_duty, other = loaded_pair
    locked = replace(
        locked_duty,
        trips=_reindexed(
            (
                replace(
                    locked_duty.trips[0],
                    locked_customer_prefix=locked_duty.trips[0].customer_ids[:1],
                ),
                *locked_duty.trips[1:],
            )
        ),
    )
    plan = DutyIndividual(
        duties=tuple(
            locked if duty.physical_vehicle_id == locked.physical_vehicle_id
            else duty
            for duty in initial.duties
        ),
        source="synthetic",
    )
    solution = _project(merged, plan)
    assert merged._decode_changes(plan, solution) == ()
    reversed_routes = KernelSolution(
        merged.data, list(reversed(list(solution.routes())))
    )
    assert merged._decode_changes(plan, reversed_routes) == ()
    assert locked.physical_vehicle_id != other.physical_vehicle_id


def test_least_churn_match_pins_a_locked_prefix_before_anything_else():
    """The locked duty follows its locked customers, not its old chain."""

    slots = ["CV_1", "CV_2", "CV_3"]
    loaded = {
        "CV_1": (("a", "b"),),
        "CV_2": (("c", "d"),),
        "CV_3": (),
    }
    locked_prefixes = {"CV_1": frozenset({"a"})}
    # The kernel moved "a" onto a longer chain and left CV_2's day alone.
    chains = [(("c", "d"),), (("a", "b", "e"),)]
    seated = _least_churn_match(slots, chains, loaded, locked_prefixes)
    assert seated["CV_1"] == (("a", "b", "e"),)
    assert seated["CV_2"] == (("c", "d"),)
    assert seated["CV_3"] == ()


def test_least_churn_match_leaves_untouched_chains_where_they_were():
    slots = ["EV_1", "EV_2", "EV_3"]
    loaded = {
        "EV_1": (("a",),),
        "EV_2": (("b",), ("c",)),
        "EV_3": (),
    }
    # Same two chains, handed back in the opposite order plus a new third one.
    chains = [(("b",), ("c",)), (("a",),), (("d",),)]
    seated = _least_churn_match(slots, chains, loaded, {})
    assert seated["EV_1"] == (("a",),)
    assert seated["EV_2"] == (("b",), ("c",))
    assert seated["EV_3"] == (("d",),)


def test_least_churn_match_seats_the_rest_by_shared_customers():
    slots = ["CV_1", "CV_2"]
    loaded = {"CV_1": (("a", "b"),), "CV_2": (("c", "d"),)}
    chains = [(("c", "d", "e"),), (("a", "b", "f"),)]
    seated = _least_churn_match(slots, chains, loaded, {})
    assert seated["CV_1"] == (("a", "b", "f"),)
    assert seated["CV_2"] == (("c", "d", "e"),)


def test_a_group_can_never_be_handed_more_routes_than_it_owns(pair):
    """The decoder's group-overflow guard is belt and braces.

    ``num_available`` is what makes the merge safe: the kernel refuses to build
    a solution that seats more routes on a merged type than the group has
    physical vehicles, so the many-to-one map can never run out of slots.
    """

    merged, _historic, _initial = pair
    vehicle_type, members = next(
        (index, members)
        for index, members in merged._duty_ids_by_vehicle_type.items()
        if len(members) == 3
    )
    assert merged.data.vehicle_type(vehicle_type).num_available == len(members)
    first_client = merged.data.num_depots
    routes = [
        KernelRoute(merged.data, [first_client + offset], vehicle_type)
        for offset in range(len(members) + 1)
    ]
    with pytest.raises(RuntimeError, match="more than"):
        KernelSolution(merged.data, routes)


def test_fixed_composition_multiset_survives_the_merge():
    """V5: --fleet-mix-override keeps its (vehicle type, depot) counts."""

    mix = {
        "D_OSM_WAY_1003511503": (2, 1),
        "D_OSM_WAY_1071205721": (1, 2),
    }
    _bundle, initial, _neutral, context = _build_context(
        REPO,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=FLEET_PARAMETER_CLASSES["endogenous"],
        ev_cap_override=mix,
    )
    context = replace(context, fleet_exact_composition=True)
    configured: dict[tuple[str, str], int] = {}
    for duty in initial.duties:
        key = (duty.vehicle_type, duty.home_depot_id)
        configured[key] = configured.get(key, 0) + 1
    assert configured == {
        ("cv", "D_OSM_WAY_1003511503"): 2,
        ("ev", "D_OSM_WAY_1003511503"): 1,
        ("cv", "D_OSM_WAY_1071205721"): 1,
        ("ev", "D_OSM_WAY_1071205721"): 2,
    }
    by_id = {
        duty.physical_vehicle_id: (duty.vehicle_type, duty.home_depot_id)
        for duty in initial.duties
    }
    for dedup in (True, False):
        engine = _engine(
            context,
            initial,
            vehicle_fixed_cost_in_proxy=False,
            vehicle_type_dedup_enabled=dedup,
        )
        seated: dict[tuple[str, str], int] = {}
        for index, members in engine._duty_ids_by_vehicle_type.items():
            assert engine.data.vehicle_type(index).num_available == len(members)
            for duty_id in members:
                seated[by_id[duty_id]] = seated.get(by_id[duty_id], 0) + 1
        assert seated == configured
        assert engine.data.num_vehicles == len(initial.duties)
    merged = _engine(
        context,
        initial,
        vehicle_fixed_cost_in_proxy=False,
        vehicle_type_dedup_enabled=True,
    )
    historic = _engine(
        context,
        initial,
        vehicle_fixed_cost_in_proxy=False,
        vehicle_type_dedup_enabled=False,
    )
    assert merged.data.num_vehicle_types == 4
    assert historic.data.num_vehicle_types == len(initial.duties)
