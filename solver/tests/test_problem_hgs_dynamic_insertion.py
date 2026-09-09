"""Dynamic insertion operator contract and full-ruler tests."""

from __future__ import annotations

import dataclasses
import inspect
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    _build_context,
    _policy,
)
from setp_solver.algorithms.problem_hgs import (  # noqa: E402
    dynamic_insertion,
    evaluation as problem_hgs_evaluation,
)
from setp_solver.algorithms.problem_hgs.dynamic import (  # noqa: E402
    DutyDynamicState,
    DynamicPrefixAccountingCorrection,
    _merge_execution_history,
    future_individual_from_cut,
    prepare_dynamic_candidate,
)
from setp_solver.algorithms.problem_hgs.dynamic_insertion import (  # noqa: E402
    NOT_INSERTED_SEARCH_EXHAUSTED,
    DirectInsertionScreen,
    DynamicInsertionOperator,
    _build_direct_insertion_screen,
    _direct_insertion_candidates,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
    _aggregate_dynamic_prefix_accounting,
    _validate_dynamic_state_customers,
)
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS  # noqa: E402
from setp_solver.instance_loader import Node  # noqa: E402
from setp_solver.search.dynamic_multitrip_schedule import (  # noqa: E402
    CertificateCut,
    DynamicAssetState,
    cut_certificate_at_trigger,
)
from setp_solver.search.multitrip_schedule import (  # noqa: E402
    prepare_multitrip_solution,
)
from setp_solver.solution import Route, Solution  # noqa: E402


INSTANCE_ID = DEPOT_SEARCH_INSTANCE_ID
DONOR_DUTY_ID = "CV_D_OSM_WAY_1071205721_1"


def _build_dynamic_fixture(
    trigger: float,
    *,
    donor_duty_id: str = DONOR_DUTY_ID,
    withheld_customer_count: int = 1,
):
    """Hide the tail of one planned trip and reveal it again at ``trigger``."""

    repo = Path(__file__).parents[2]
    bundle, initial, _neutral, base_context = _build_context(
        repo,
        INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    rebuilt = []
    revealed: tuple[str, ...] = ()
    for duty in initial.duties:
        if duty.physical_vehicle_id == donor_duty_id:
            trip = duty.trips[-1]
            revealed = tuple(trip.customer_ids[-withheld_customer_count:])
            rebuilt.append(
                replace(
                    duty,
                    trips=(
                        *duty.trips[:-1],
                        replace(
                            trip,
                            customer_ids=trip.customer_ids[
                                :-withheld_customer_count
                            ],
                        ),
                    ),
                )
            )
        else:
            rebuilt.append(duty)
    assert revealed
    partial = replace(
        initial,
        duties=tuple(rebuilt),
        unserved_customers=revealed,
        source="dynamic-insertion-test-partial",
    )
    source_solution, source_certificate = prepare_multitrip_solution(
        partial.to_solution(),
        bundle.instance,
        bundle.prices,
        depot_charge_window_mode=base_context.depot_charge_window_mode,
    )
    cut = cut_certificate_at_trigger(
        source_solution,
        source_certificate,
        bundle.instance,
        bundle.prices,
        trigger_second=trigger,
    )
    battery_capacity = bundle.instance.battery_capacity_kwh(
        fallback=bundle.prices.B_battery_kwh
    )
    assets = {
        duty.physical_vehicle_id: cut.asset_states.get(
            duty.physical_vehicle_id,
            DynamicAssetState(
                duty.physical_vehicle_id,
                duty.vehicle_type,
                duty.home_depot_id,
                trigger,
                battery_capacity if duty.vehicle_type == "ev" else 0.0,
                1,
            ),
        )
        for duty in initial.duties
    }
    customer_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    committed_route_ids = set(cut.completed_route_ids)
    committed_customers = {
        node_id
        for route in source_solution.routes
        if route.vehicle_id in committed_route_ids
        for node_id in route.node_sequence[1:-1]
        if node_id in customer_ids
    }
    committed_customers.update(
        node_id
        for asset in cut.asset_states.values()
        for node_id in tuple(getattr(asset, "executed_prefix", ()))
        if node_id in customer_ids
    )
    state = DutyDynamicState(
        source_solution=source_solution,
        cut=cut,
        asset_states=MappingProxyType(assets),
        future_customer_ids=frozenset(
            customer_ids.difference(committed_customers)
        ),
        customer_appearance_second={
            customer_id: trigger if customer_id in revealed else 0.0
            for customer_id in customer_ids
        },
        charging_strategy="aware",
        charging_intensity_field="forecast_gco2_per_kwh",
    )
    future = future_individual_from_cut(
        state,
        source_certificate,
        bundle.instance,
    )
    context = replace(
        base_context,
        dynamic_state=state,
    )
    return bundle, future, context, revealed, committed_customers


@pytest.fixture(scope="module")
def dynamic_fixture():
    return _build_dynamic_fixture(46_800.0)


@pytest.fixture(scope="module")
def in_progress_dynamic_fixture():
    return _build_dynamic_fixture(30_000.0)


@pytest.fixture(scope="module")
def two_order_dynamic_fixture():
    return _build_dynamic_fixture(
        46_800.0,
        donor_duty_id="CV_D_OSM_WAY_1071205721_2",
        withheld_customer_count=2,
    )


# Recorded on 2026-09-09 from the source as it stood before the eligibility
# pre-filter, the partial fallback and the candidate budget were added.  These
# are the flag-off oracle: every switch defaults to off and must reproduce them.
_FLAG_OFF_ORACLE = {
    "cut": {
        "trigger": 46_800.0,
        "revealed": ("C029",),
        "direct_generator_candidates": 61,
        "screened_generator_candidates": 31,
        "total_cost": 3033.2059767107694,
        "receiving_duty_id": "CV_D_OSM_WAY_1071205721_1",
        "receiving_trip_customers": ("C024", "C023", "C019", "C029"),
    },
    "in_progress": {
        "trigger": 30_000.0,
        "revealed": ("C029",),
        "direct_generator_candidates": 84,
        "screened_generator_candidates": 66,
        "total_cost": 3033.2059767107694,
        "receiving_duty_id": "CV_D_OSM_WAY_1071205721_1",
        "receiving_trip_customers": ("C024", "C023", "C019", "C029"),
    },
    "two_order": {
        "trigger": 46_800.0,
        "revealed": ("C020", "C037"),
        "direct_generator_candidates": 3680,
        "screened_generator_candidates": 950,
        "total_cost": 3033.2059767107694,
        "receiving_duty_id": "CV_D_OSM_WAY_1071205721_2",
        "receiving_trip_customers": ("C048", "C020", "C037"),
    },
}


def _apply(fixture, **operator_kwargs):
    _bundle, future, context, revealed, _committed = fixture
    evaluator = DutyFullEvaluator(context)
    base_evaluation = evaluator.evaluate(future)
    result = DynamicInsertionOperator(enabled=True, **operator_kwargs).apply(
        future,
        evaluator=evaluator,
        charging_policy=_policy(evaluator, frvcpy_enabled=False),
        newly_revealed_customer_ids=tuple(future.unserved_customers),
        current_evaluation=base_evaluation,
    )
    return future, evaluator, revealed, result


def _served_customers(individual) -> frozenset[str]:
    return frozenset(
        customer_id
        for duty in individual.duties
        for trip in duty.trips
        for customer_id in trip.customer_ids
    )


def _trip_customers(individual, duty_id: str) -> tuple[tuple[str, ...], ...]:
    return tuple(
        trip.customer_ids
        for duty in individual.duties
        if duty.physical_vehicle_id == duty_id
        for trip in duty.trips
    )


@pytest.mark.parametrize(
    ("key", "fixture_name"),
    (
        ("cut", "dynamic_fixture"),
        ("in_progress", "in_progress_dynamic_fixture"),
        ("two_order", "two_order_dynamic_fixture"),
    ),
)
def test_every_switch_off_reproduces_the_recorded_result(
    key,
    fixture_name,
    request,
) -> None:
    """A bare enabled operator must still return the pre-change result."""

    expected = _FLAG_OFF_ORACLE[key]
    fixture = request.getfixturevalue(fixture_name)
    future, _evaluator, revealed, result = _apply(fixture)

    assert revealed == expected["revealed"]
    assert result.status == "INSERTED_AND_FULL_EVALUATION_FEASIBLE"
    assert result.individual.unserved_customers == ()
    assert result.evaluation is not None
    assert float(result.evaluation.total_cost) == expected["total_cost"]
    assert result.accounting.candidate_attempt_count == 1
    assert result.accounting.candidate_feasible_count == 1
    assert result.accounting.complete_evaluations == 1
    assert result.accounting.changed_duty_count == 1
    assert result.accounting.charging_candidates_evaluated == 0
    assert expected["receiving_trip_customers"] in _trip_customers(
        result.individual,
        expected["receiving_duty_id"],
    )
    # The direct fallback generator is the part the pre-filter edits, so its
    # unscreened enumeration is pinned separately from the accepted result.
    unscreened = sum(
        1
        for _candidate in _direct_insertion_candidates(
            future,
            tuple(future.unserved_customers),
        )
    )
    assert unscreened == expected["direct_generator_candidates"]


@pytest.mark.parametrize(
    ("key", "fixture_name"),
    (
        ("cut", "dynamic_fixture"),
        ("in_progress", "in_progress_dynamic_fixture"),
        ("two_order", "two_order_dynamic_fixture"),
    ),
)
def test_pre_filter_cuts_candidates_without_losing_placements(
    key,
    fixture_name,
    request,
) -> None:
    """Fewer complete evaluations are attempted and nothing new is dropped."""

    fixture = request.getfixturevalue(fixture_name)
    future, evaluator, _revealed, off_result = _apply(fixture)
    pending = tuple(future.unserved_customers)

    unscreened = {
        candidate.fingerprint
        for candidate, _id, _changed in _direct_insertion_candidates(
            future,
            pending,
        )
    }
    screen = _build_direct_insertion_screen(future, evaluator)
    screened = {
        candidate.fingerprint
        for candidate, _id, _changed in _direct_insertion_candidates(
            future,
            pending,
            screen=screen,
        )
    }

    assert len(unscreened) == _FLAG_OFF_ORACLE[key][
        "direct_generator_candidates"
    ]
    assert len(screened) == _FLAG_OFF_ORACLE[key][
        "screened_generator_candidates"
    ]
    assert len(screened) < len(unscreened)
    assert screened.issubset(unscreened)

    _future, _evaluator, _revealed, on_result = _apply(
        fixture,
        prefilter_ineligible_assets=True,
    )
    assert on_result.status == off_result.status
    assert _served_customers(on_result.individual) >= _served_customers(
        off_result.individual
    )


def test_the_screen_carries_no_asset_availability_rule(dynamic_fixture) -> None:
    """A busy asset must never be screened out.

    The exact scheduler does not reject an asset that is still occupied at
    the cut, it delays the departure
    (``dynamic_multitrip_schedule.py:1059``, ``boundary = max(stage_start,
    asset.available_second)``).  An availability rule in the screen would
    therefore prune placements the complete ruler accepts, so the screen must
    keep every duty enumerable and gate only on load.
    """

    _bundle, future, context, _revealed, _committed = dynamic_fixture
    screen = _build_direct_insertion_screen(future, DutyFullEvaluator(context))

    fields = {field.name for field in dataclasses.fields(DirectInsertionScreen)}
    assert fields == {
        "demand_by_customer",
        "load_ceiling_by_trip",
        "load_ceiling_by_new_trip",
    }
    assert not hasattr(screen, "allows_duty")
    assert not hasattr(screen, "ineligible_duty_ids")
    assert "_asset_is_idle_now" not in inspect.getsource(dynamic_insertion)


def test_load_screen_refuses_more_than_the_inherited_load() -> None:
    screen = DirectInsertionScreen(
        demand_by_customer={"C1": 400.0, "C2": 300.0},
        load_ceiling_by_trip={("CV_D0_1", 1): 500.0, ("CV_D0_1", 2): 3650.0},
        load_ceiling_by_new_trip={"CV_D0_1": 3650.0},
    )

    assert not screen.allows_trip("CV_D0_1", 1, ("C2",), "C1")
    assert screen.allows_trip("CV_D0_1", 2, ("C2",), "C1")
    assert screen.allows_trip("CV_D0_1", 1, (), "C1")


def test_candidate_budget_stops_the_search_deterministically(
    dynamic_fixture,
) -> None:
    """A budget of zero forbids the first complete evaluation and is reported."""

    _future, _evaluator, _revealed, exhausted = _apply(
        dynamic_fixture,
        candidate_budget=0,
    )
    assert exhausted.status == NOT_INSERTED_SEARCH_EXHAUSTED

    _future, _evaluator, _revealed, allowed = _apply(
        dynamic_fixture,
        candidate_budget=8,
    )
    assert allowed.status == "INSERTED_AND_FULL_EVALUATION_FEASIBLE"
    assert allowed.accounting.complete_evaluations == 1
    assert float(allowed.evaluation.total_cost) == _FLAG_OFF_ORACLE["cut"][
        "total_cost"
    ]


def test_the_pruning_comes_from_the_inherited_load_not_from_capacity(
    dynamic_fixture,
) -> None:
    """Attribute the measured reduction to the branch that actually causes it.

    Every vehicle's payload capacity is 3650 kg and no planned trip comes near
    it, so the plain capacity ceiling prunes nothing.  All of the reduction is
    the inherited load a vehicle still carries past the cut, which is what the
    exact scheduler rejects as "exceeds inherited load".
    """

    _bundle, future, context, _revealed, _committed = dynamic_fixture
    evaluator = DutyFullEvaluator(context)
    pending = tuple(future.unserved_customers)
    screen = _build_direct_insertion_screen(future, evaluator)

    inherited = {
        key: value
        for key, value in screen.load_ceiling_by_trip.items()
        if value < screen.load_ceiling_by_new_trip[key[0]]
    }
    assert inherited, "no continuation trip carries an inherited load"
    assert all(key[1] == 1 for key in inherited)

    capacity_only = replace(
        screen,
        load_ceiling_by_trip={
            key: screen.load_ceiling_by_new_trip[key[0]]
            for key in screen.load_ceiling_by_trip
        },
    )
    unscreened = sum(
        1 for _ in _direct_insertion_candidates(future, pending)
    )
    capacity_screened = sum(
        1
        for _ in _direct_insertion_candidates(
            future,
            pending,
            screen=capacity_only,
        )
    )
    full_screened = sum(
        1 for _ in _direct_insertion_candidates(future, pending, screen=screen)
    )

    assert capacity_screened == unscreened
    assert full_screened < unscreened


def test_the_screen_drops_no_candidate_the_complete_ruler_would_accept(
    dynamic_fixture,
) -> None:
    """Necessity, checked exhaustively rather than argued.

    Every candidate the unscreened generator produces is evaluated by the
    complete ruler; not one feasible candidate may be missing from the
    screened enumeration.
    """

    _bundle, future, context, _revealed, _committed = dynamic_fixture
    evaluator = DutyFullEvaluator(context)
    pending = tuple(future.unserved_customers)
    screen = _build_direct_insertion_screen(future, evaluator)
    kept = {
        candidate.fingerprint
        for candidate, _id, _changed in _direct_insertion_candidates(
            future,
            pending,
            screen=screen,
        )
    }

    feasible = 0
    for candidate, _id, _changed in _direct_insertion_candidates(
        future,
        pending,
    ):
        try:
            evaluation = evaluator.evaluate(candidate)
        except (TypeError, ValueError):
            continue
        if not evaluation.feasible:
            continue
        feasible += 1
        assert candidate.fingerprint in kept

    assert feasible == 18








def test_second_cut_keeps_history_before_the_previous_virtual_origin() -> None:
    route_id = "CV_D0_1#T1"
    current = Route(route_id, "cv", "D0", ["V1", "C2", "C3", "D0"])
    full = Route(
        route_id,
        "cv",
        "D0",
        ["D0", "C1", "V1", "C2", "C3", "D0"],
    )
    asset = DynamicAssetState(
        "CV_D0_1",
        "cv",
        "D0",
        20.0,
        0.0,
        1,
        position_node_id="V2",
        remaining_load_kg=3.0,
        continuation_route_id=route_id,
        continuation_trip_index=1,
        executed_prefix=("V1", "C2"),
        editable_suffix=("C3",),
        release_node_id="C3",
        virtual_origin_node_id="V2",
    )
    state = DutyDynamicState(
        source_solution=Solution(routes=[current]),
        source_full_execution_solution=Solution(routes=[full]),
        cut=CertificateCut(
            trigger_second=20.0,
            completed_route_ids=(),
            in_progress_route_ids=(route_id,),
            editable_route_ids=(),
            locked_charging_actions=(),
            asset_states=MappingProxyType({"CV_D0_1": asset}),
        ),
        asset_states=MappingProxyType({"CV_D0_1": asset}),
        future_customer_ids=frozenset({"C3"}),
        customer_appearance_second={"C1": 0.0, "C2": 0.0, "C3": 0.0},
        charging_strategy="aware",
        charging_intensity_field="forecast_gco2_per_kwh",
    )

    merged = _merge_execution_history(
        state,
        Solution(
            routes=[Route(route_id, "cv", "D0", ["V2", "C3", "D0"])]
        ),
    )

    assert merged.routes[0].node_sequence == [
        "D0",
        "C1",
        "V1",
        "C2",
        "V2",
        "C3",
        "D0",
    ]
    _validate_dynamic_state_customers(
        state,
        SimpleNamespace(
            instance=SimpleNamespace(
                nodes=[
                    Node("D0", "d", 0.0, 0.0),
                    Node("C1", "c", 1.0, 0.0),
                    Node("C2", "c", 2.0, 0.0),
                    Node("C3", "c", 3.0, 0.0),
                ]
            )
        ),
    )
    return_asset = replace(
        asset,
        position_node_id="D0",
        continuation_route_id=None,
        continuation_trip_index=None,
        executed_prefix=("V1", "C2", "C3"),
        editable_suffix=(),
        release_node_id="D0",
        virtual_origin_node_id=None,
    )
    return_assets = MappingProxyType({"CV_D0_1": return_asset})
    return_state = replace(
        state,
        cut=replace(state.cut, asset_states=return_assets),
        asset_states=return_assets,
        future_customer_ids=frozenset(),
    )
    _validate_dynamic_state_customers(
        return_state,
        SimpleNamespace(
            instance=SimpleNamespace(
                nodes=[
                    Node("D0", "d", 0.0, 0.0),
                    Node("C1", "c", 1.0, 0.0),
                    Node("C2", "c", 2.0, 0.0),
                    Node("C3", "c", 3.0, 0.0),
                ]
            )
        ),
    )


def test_prefix_accounting_totals_keep_completed_route_corrections() -> None:
    corrections = {
        "CV_D0_1#T1": DynamicPrefixAccountingCorrection(
            home_depot_id="D0",
            fuel_liters=2.0,
            fuel_cost=15.0,
            cv_emissions_kg=5.36,
        ),
        "EV_D1_1#T1": DynamicPrefixAccountingCorrection(
            home_depot_id="D1",
            ev_drive_kwh=4.0,
        ),
    }

    totals = _aggregate_dynamic_prefix_accounting(corrections)

    assert totals.fuel_liters == pytest.approx(2.0)
    assert totals.fuel_cost_by_depot == (("D0", 15.0), ("D1", 0.0))
    assert totals.cv_emissions_by_depot == (("D0", 5.36), ("D1", 0.0))
    assert totals.ev_drive_kwh == pytest.approx(4.0)


def test_active_prefix_accounting_overwrites_prior_cumulative_value(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        problem_hgs_evaluation,
        "_arc_loads",
        lambda *_args: [1.0, 0.0],
    )
    monkeypatch.setattr(
        problem_hgs_evaluation,
        "_prefix_energy_at_terminal_load",
        lambda _route, _prefix, _virtual, load, _bundle: SimpleNamespace(
            fuel_liters=float(load),
            ev_drive_kwh=0.0,
        ),
    )
    monkeypatch.setattr(
        problem_hgs_evaluation,
        "diesel_price_for_route",
        lambda *_args: 1.0,
    )
    route_id = "CV_D0_1#T1"
    prior = DynamicPrefixAccountingCorrection(
        home_depot_id="D0",
        fuel_liters=10.0,
        fuel_cost=10.0,
        cv_emissions_kg=20.0,
    )
    completed = DynamicPrefixAccountingCorrection(
        home_depot_id="D0",
        fuel_liters=5.0,
        fuel_cost=5.0,
        cv_emissions_kg=10.0,
    )
    state = SimpleNamespace(
        prior_prefix_accounting_by_route_id={
            route_id: prior,
            "CV_D0_2#T1": completed,
        },
        asset_states={
            "CV_D0_1": SimpleNamespace(
                continuation_route_id=route_id,
                virtual_origin_node_id="V2",
                remaining_load_kg=3.0,
            )
        },
    )
    bundle = SimpleNamespace(
        instance=SimpleNamespace(nodes=[]),
        prices=SimpleNamespace(diesel_ef=2.0),
    )
    solution = Solution(
        routes=[
            Route(route_id, "cv", "D0", ["D0", "V2", "D0"]),
            Route("CV_D0_2#T1", "cv", "D0", ["D0", "D0"]),
        ]
    )

    corrections = problem_hgs_evaluation._dynamic_prefix_accounting_by_route_id(
        solution,
        state,
        bundle,
    )

    assert corrections[route_id].fuel_liters == pytest.approx(2.0)
    assert corrections[route_id].cv_emissions_kg == pytest.approx(4.0)
    assert corrections["CV_D0_2#T1"] == completed




@dataclass(frozen=True)
class _StubRollingState:
    """Only the fields the per-order fallback loop reads or rewrites."""

    planning_active_customer_ids: frozenset[str]
    stage_index: int = 0
    deferred_customer_ids: tuple[str, ...] = ()
    mechanical_insertion_wall_seconds: float = 0.0


def test_partial_fallback_keeps_the_orders_it_can_place(monkeypatch) -> None:
    """One unplaceable order no longer forces the whole batch to be deferred."""

    from setp_solver import main3b_backend

    unplaceable = "C2"

    def fake_build_stage(self, problem, previous, active, trigger, applied):
        return SimpleNamespace(
            initial_future=SimpleNamespace(unserved_customers=()),
            evaluator=SimpleNamespace(),
            active_customer_ids=active,
        )

    def fake_insert(individual, customer_id, evaluator):
        if customer_id == unplaceable:
            raise main3b_backend.MechanicalInsertionFailure(
                customer_id,
                class_diagnostics={},
                rejected_candidates=(),
            )
        return SimpleNamespace(
            individual=SimpleNamespace(unserved_customers=()),
            evaluation=SimpleNamespace(feasible=True),
            decision=SimpleNamespace(candidate_class="3_dispatch_unused_vehicle"),
        )

    emitted: list[dict] = []

    def fake_successful_state(
        previous,
        frame,
        candidate,
        evaluation,
        *,
        active_customer_ids,
        stage_index,
        diagnostics,
    ):
        emitted.append(dict(diagnostics))
        return replace(
            previous,
            planning_active_customer_ids=frozenset(active_customer_ids),
            stage_index=stage_index,
        )

    monkeypatch.setattr(
        main3b_backend.ProductionBackend,
        "_build_stage",
        fake_build_stage,
    )
    monkeypatch.setattr(main3b_backend, "insert_revealed_customer", fake_insert)
    monkeypatch.setattr(
        main3b_backend,
        "_successful_state",
        fake_successful_state,
    )

    backend = main3b_backend.ProductionBackend(partial_fallback=True)
    work, placed, deferred = backend._rolling_partial_insertions(
        None,
        _StubRollingState(planning_active_customer_ids=frozenset({"C0"})),
        (),
        0.0,
        ("C1", unplaceable, "C3"),
    )

    assert placed == ("C1", "C3")
    assert deferred == (unplaceable,)
    assert work.planning_active_customer_ids == frozenset({"C0", "C1", "C3"})
    # Wall seconds and the count must move together: these seconds land in
    # ``mechanical_insertion_wall_seconds``, and ``_summary`` counts a row
    # only when its ``kind`` is exactly ``mechanical_insertion``.
    assert work.mechanical_insertion_wall_seconds >= 0.0
    assert [row["kind"] for row in emitted] == ["mechanical_insertion"] * 2
    assert {row["source"] for row in emitted} == {"partial_mechanical_fallback"}
    counted = sum(
        row.get("kind") == "mechanical_insertion" for row in emitted
    )
    assert counted == len(placed)


def test_partial_fallback_declares_its_hgs_call_like_any_other_stage(
    monkeypatch,
) -> None:
    """The fallback's Problem-HGS call must be counted by the audit.

    ``_summary`` derives ``actual_hgs_call_count`` by counting diagnostics
    rows whose ``kind`` is exactly ``problem_hgs_stage``, and the declared
    side of the budget/call audit is one call per trigger batch.  A batch
    served through the partial fallback spends exactly one call, so it must
    contribute exactly one such row -- otherwise a correct run reports fewer
    calls than it made and fails the audit.
    """

    from setp_solver import main3b_backend

    unplaceable = "C2"
    hgs_calls: list[dict] = []

    def fake_build_stage(self, problem, previous, active, trigger, applied):
        return SimpleNamespace(
            initial_future=SimpleNamespace(unserved_customers=()),
            evaluator=SimpleNamespace(
                evaluate=lambda individual: SimpleNamespace(feasible=True)
            ),
            context=SimpleNamespace(),
            active_customer_ids=active,
        )

    def fake_insert(individual, customer_id, evaluator):
        if customer_id == unplaceable:
            raise main3b_backend.MechanicalInsertionFailure(
                customer_id,
                class_diagnostics={},
                rejected_candidates=(),
            )
        return SimpleNamespace(
            individual=SimpleNamespace(unserved_customers=()),
            evaluation=SimpleNamespace(feasible=True),
            decision=SimpleNamespace(candidate_class="3_dispatch_unused_vehicle"),
        )

    def fake_run_hgs(self, individual, context, *, arm, stage_index):
        hgs_calls.append({"arm": arm, "stage_index": stage_index})
        return (
            individual,
            SimpleNamespace(feasible=True),
            SimpleNamespace(iterations=7, termination_status="STOPPED_BY_CALLER"),
        )

    emitted: list[dict] = []

    def fake_successful_state(
        previous,
        frame,
        candidate,
        evaluation,
        *,
        active_customer_ids,
        stage_index,
        diagnostics,
    ):
        emitted.append(dict(diagnostics))
        return replace(
            previous,
            planning_active_customer_ids=frozenset(active_customer_ids),
            stage_index=stage_index,
        )

    monkeypatch.setattr(
        main3b_backend.ProductionBackend,
        "_build_stage",
        fake_build_stage,
    )
    monkeypatch.setattr(
        main3b_backend.ProductionBackend,
        "_run_hgs",
        fake_run_hgs,
    )
    monkeypatch.setattr(main3b_backend, "insert_revealed_customer", fake_insert)
    monkeypatch.setattr(
        main3b_backend,
        "_successful_state",
        fake_successful_state,
    )

    backend = main3b_backend.ProductionBackend(partial_fallback=True)
    outcome = backend._rolling_partial_fallback(
        None,
        _StubRollingState(planning_active_customer_ids=frozenset({"C0"})),
        (),
        0.0,
        ("C1", unplaceable, "C3"),
        reason="no_feasible_candidate:NOT_INSERTED_SEARCH_EXHAUSTED",
    )

    assert outcome is not None
    _, detail = outcome
    assert detail == "rolling_partial_mechanical_fallback"

    # One call was made; the audit's counting rule must see exactly one.
    assert len(hgs_calls) == 1
    counted = sum(row.get("kind") == "problem_hgs_stage" for row in emitted)
    assert counted == len(hgs_calls) == 1

    stage_row = next(
        row for row in emitted if row["kind"] == "problem_hgs_stage"
    )
    assert stage_row["source"] == "partial_mechanical_fallback"
    assert stage_row["arm"] == "rolling_dynamic"
    assert stage_row["inserted_customer_ids"] == ["C1", "C3"]
    assert stage_row["deferred_customer_ids"] == [unplaceable]
    assert stage_row["termination_status"] == "STOPPED_BY_CALLER"
    # The per-order rows stay on the mechanical axis and must not be
    # double-counted as HGS calls.
    assert sum(
        row.get("kind") == "mechanical_insertion" for row in emitted
    ) == 2


def test_partial_fallback_halts_instead_of_deferring_a_malformed_cut(
    monkeypatch,
) -> None:
    """Only a MechanicalInsertionFailure defers; a defect must propagate.

    The sequential arm turns TypeError/ValueError out of
    ``insert_revealed_customer`` into a ProductionBackendHalt.  The rolling
    arm's per-order fallback must not silently reclassify the same defect as
    "this customer is undeliverable".
    """

    from setp_solver import main3b_backend

    def fake_build_stage(self, problem, previous, active, trigger, applied):
        return SimpleNamespace(
            initial_future=SimpleNamespace(unserved_customers=()),
            evaluator=SimpleNamespace(),
            active_customer_ids=active,
        )

    def exploding_insert(individual, customer_id, evaluator):
        raise TypeError("cut payload is not a tuple")

    monkeypatch.setattr(
        main3b_backend.ProductionBackend,
        "_build_stage",
        fake_build_stage,
    )
    monkeypatch.setattr(
        main3b_backend,
        "insert_revealed_customer",
        exploding_insert,
    )

    backend = main3b_backend.ProductionBackend(partial_fallback=True)
    with pytest.raises(main3b_backend.ProductionBackendHalt) as raised:
        backend._rolling_partial_insertions(
            None,
            _StubRollingState(planning_active_customer_ids=frozenset()),
            (),
            0.0,
            ("C1",),
        )

    assert "TypeError" in str(raised.value)
    assert isinstance(raised.value.__cause__, TypeError)


def test_partial_fallback_is_off_by_default() -> None:
    from setp_solver import main3b_backend

    default = main3b_backend.ProductionBackend()

    assert default.partial_fallback is False
    assert default.prefilter_ineligible_assets is False
    assert default.insertion_candidate_budget is None
    assert (
        default._rolling_partial_fallback(
            None,
            None,
            (),
            0.0,
            ("C1",),
            reason="test",
        )
        is None
    )


def test_operator_module_has_no_file_read_path() -> None:
    source = inspect.getsource(dynamic_insertion)

    assert "Path(" not in source
    assert ".open(" not in source
    assert ".read_text(" not in source
    assert "json.load(" not in source
