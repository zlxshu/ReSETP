"""Dynamic insertion operator contract and full-ruler tests."""

from __future__ import annotations

import inspect
import sys
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import _build_context, _policy  # noqa: E402
from setp_solver.algorithms.problem_hgs import dynamic_insertion  # noqa: E402
from setp_solver.algorithms.problem_hgs.dynamic import (  # noqa: E402
    DutyDynamicState,
    future_individual_from_cut,
)
from setp_solver.algorithms.problem_hgs.dynamic_insertion import (  # noqa: E402
    DynamicInsertionOperator,
    PublicStandbyScenario,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
)
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS  # noqa: E402
from setp_solver.search.dynamic_multitrip_schedule import (  # noqa: E402
    DynamicAssetState,
    cut_certificate_at_trigger,
)
from setp_solver.search.multitrip_schedule import (  # noqa: E402
    prepare_multitrip_solution,
)


INSTANCE_ID = "cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS"


def _build_dynamic_fixture(trigger: float):
    repo = Path(__file__).parents[2]
    bundle, initial, _neutral, base_context = _build_context(
        repo,
        INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    rebuilt = []
    revealed = None
    for duty in initial.duties:
        if duty.physical_vehicle_id == "CV_D_guangzhou_4":
            trip = duty.trips[0]
            revealed = trip.customer_ids[-1]
            rebuilt.append(
                replace(
                    duty,
                    trips=(
                        replace(
                            trip,
                            customer_ids=trip.customer_ids[:-1],
                        ),
                    ),
                )
            )
        else:
            rebuilt.append(duty)
    assert revealed is not None
    partial = replace(
        initial,
        duties=tuple(rebuilt),
        unserved_customers=(revealed,),
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
    committed_route_ids = {
        *cut.completed_route_ids,
        *cut.in_progress_route_ids,
    }
    committed_customers = {
        node_id
        for route in source_solution.routes
        if route.vehicle_id in committed_route_ids
        for node_id in route.node_sequence[1:-1]
        if node_id in customer_ids
    }
    state = DutyDynamicState(
        source_solution=source_solution,
        cut=cut,
        asset_states=MappingProxyType(assets),
        future_customer_ids=frozenset(
            customer_ids.difference(committed_customers)
        ),
        customer_appearance_second={
            customer_id: trigger if customer_id == revealed else 0.0
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
        incremental_full_truth_sentinel_enabled=False,
    )
    return bundle, future, context, revealed, committed_customers


@pytest.fixture(scope="module")
def dynamic_fixture():
    return _build_dynamic_fixture(46_800.0)


@pytest.fixture(scope="module")
def in_progress_dynamic_fixture():
    return _build_dynamic_fixture(30_000.0)


def test_disabled_operator_is_exact_noop(dynamic_fixture) -> None:
    _bundle, future, context, revealed, _committed = dynamic_fixture
    evaluator = DutyFullEvaluator(context)

    result = DynamicInsertionOperator(enabled=False, random_seed=11).apply(
        future,
        evaluator=evaluator,
        charging_policy=_policy(evaluator),
        newly_revealed_customer_ids=(revealed,),
    )

    assert result.individual is future
    assert result.evaluation is None
    assert evaluator.full_calls == 0
    assert result.accounting.complete_evaluations == 0
    assert (
        result.accounting.committed_sha256_before
        == result.accounting.committed_sha256_after
    )


def test_revealed_order_is_inserted_without_changing_commitment_and_passes_ruler(
    dynamic_fixture,
) -> None:
    bundle, future, context, revealed, committed_customers = dynamic_fixture
    evaluator = DutyFullEvaluator(context)

    result = DynamicInsertionOperator(enabled=True, random_seed=11).apply(
        future,
        evaluator=evaluator,
        charging_policy=_policy(evaluator),
        newly_revealed_customer_ids=(revealed,),
    )

    assert result.evaluation is not None and result.evaluation.feasible
    assert revealed not in result.individual.unserved_customers
    assert result.accounting.newly_revealed_count == 1
    assert result.accounting.kernel_updates >= 1
    assert (
        result.accounting.committed_sha256_before
        == result.accounting.committed_sha256_after
    )
    customers = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served = {
        node_id
        for route in result.evaluation.prepared_solution.routes
        for node_id in route.node_sequence[1:-1]
        if node_id in customers
    }
    assert served == set(customers)
    assert committed_customers.issubset(served)
    assert sum(customers[item].demand for item in served) == pytest.approx(
        sum(node.demand for node in customers.values())
    )


def test_in_progress_trips_are_frozen_as_whole_routes(
    in_progress_dynamic_fixture,
) -> None:
    _bundle, future, context, revealed, _committed = in_progress_dynamic_fixture
    assert context.dynamic_state.cut.in_progress_route_ids
    evaluator = DutyFullEvaluator(context)

    result = DynamicInsertionOperator(enabled=True, random_seed=11).apply(
        future,
        evaluator=evaluator,
        charging_policy=_policy(evaluator),
        newly_revealed_customer_ids=(revealed,),
    )

    assert result.evaluation is not None and result.evaluation.feasible
    assert (
        result.accounting.committed_sha256_before
        == result.accounting.committed_sha256_after
    )


def test_standby_scenario_interface_rejects_non_public_artifacts() -> None:
    context = SimpleNamespace(
        dynamic_state=SimpleNamespace(
            cut=SimpleNamespace(trigger_second=28_800.0)
        )
    )
    individual = SimpleNamespace()

    with pytest.raises(ValueError, match="public 08:00 manifest"):
        PublicStandbyScenario(
            context=context,
            initial_future=individual,
            source_artifacts=(
                "public/algorithm_visible_at_0800.json",
                "private/true_dynamic_events.csv",
            ),
            decision_horizon_second=30_600.0,
        )


def test_public_standby_scenario_is_scored_by_complete_evaluator(
    dynamic_fixture,
) -> None:
    _bundle, future, context, revealed, _committed = dynamic_fixture
    evaluator = DutyFullEvaluator(context)
    scenario = PublicStandbyScenario(
        context=context,
        initial_future=future,
        source_artifacts=(
            "public/algorithm_visible_at_0800.json",
            "public/algorithm_scenario_seed_3.csv",
        ),
        decision_horizon_second=48_600.0,
    )

    result = DynamicInsertionOperator(enabled=True, random_seed=11).apply(
        future,
        evaluator=evaluator,
        charging_policy=_policy(evaluator),
        newly_revealed_customer_ids=(revealed,),
        standby_scenario=scenario,
    )

    assert result.standby is not None
    assert result.standby.scenario_evaluation.feasible
    assert result.standby.source_artifacts == scenario.source_artifacts
    assert result.standby.no_charge_selected == (
        not result.standby.charging_actions
    )


def test_operator_module_has_no_file_read_path() -> None:
    source = inspect.getsource(dynamic_insertion)

    assert "Path(" not in source
    assert ".open(" not in source
    assert ".read_text(" not in source
    assert "json.load(" not in source
