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
    DynamicInsertionOperator,
    PublicStandbyScenario,
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
            source_certificate_sha256="0" * 64,
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




def test_operator_module_has_no_file_read_path() -> None:
    source = inspect.getsource(dynamic_insertion)

    assert "Path(" not in source
    assert ".open(" not in source
    assert ".read_text(" not in source
    assert "json.load(" not in source
