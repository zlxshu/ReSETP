from __future__ import annotations

import numpy as np

import setp_solver.algorithms.resetp_alns.support.charging as charging_module
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerOperatorAction,
    WinnerOperatorSet,
    _selector_coupling_contract,
    apply_winner_action,
)
from setp_solver.algorithms.resetp_alns.support.carbon_charging import (
    ChargeOption,
    ChargeRequest,
    integrated_charge_carbon_kg,
    schedule_charge_requests_exact,
    select_charge_option,
    select_integrated_carbon_start,
)
from setp_solver.algorithms.resetp_alns.support.charging import (
    charge_amount_target_kwh,
    curve_knee_strategies,
    repair_route_charging,
    repair_route_charging_candidates,
)
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import ChargingAction, Route, Solution


def _instance() -> Instance:
    # Charging-slot accounting does not use the road graph, but retaining a
    # real Instance object keeps the micro-gate on the production cost helper.
    return Instance(nodes=[], distance_matrix=[])


def _profile(*gammas: float) -> list[dict[str, object]]:
    return [
        {
            "time_index": index,
            "horizon_second_start": float(index * 1800),
            "actual_gco2_per_kwh": float(gamma),
            "forecast_gco2_per_kwh": float(gamma),
        }
        for index, gamma in enumerate(gammas)
    ]


def test_curve_knee_amounts_come_from_the_input_curve() -> None:
    prices = PriceParameters(
        charging_curve_id="test_two_knees",
        charging_soc_breakpoints=(0.0, 0.8, 0.9, 1.0),
        charging_relative_powers=(1.0, 0.5, 0.25),
    )

    assert curve_knee_strategies(prices) == ("curve_knee_1", "curve_knee_2")
    assert charge_amount_target_kwh(
        "curve_knee_1",
        just_enough_kwh=30.0,
        max_coverage_kwh=60.0,
        capacity_kwh=80.0,
        curve_soc_breakpoints=prices.charging_soc_breakpoints,
    ) == 64.0
    assert charge_amount_target_kwh(
        "curve_knee_2",
        just_enough_kwh=75.0,
        max_coverage_kwh=75.0,
        capacity_kwh=80.0,
        curve_soc_breakpoints=prices.charging_soc_breakpoints,
    ) == 75.0


def test_full_interval_timing_does_not_confuse_green_start_with_green_charge() -> None:
    profile = _profile(10.0, 1000.0, 20.0, 20.0)

    choice = select_integrated_carbon_start(
        earliest_start_second=0.0,
        latest_start_second=3600.0,
        occupancy_seconds=3600.0,
        energy_kwh=60.0,
        instance=_instance(),
        carbon_profile=profile,
    )

    # Starting at t=0 looks best if only the first slot is inspected, but the
    # one-hour charge then spills into the 1000 g/kWh slot.  Starting at t=3600
    # keeps the complete action in the two 20 g/kWh slots.
    assert choice.start_second == 3600.0
    assert choice.carbon_kg == 1.2
    assert integrated_charge_carbon_kg(0.0, 3600.0, 60.0, _instance(), profile) == 30.3


def test_station_choice_uses_one_monetary_objective_instead_of_carbon_first() -> None:
    profile = _profile(500.0, 500.0, 50.0, 50.0)
    prices = PriceParameters()
    near_dirty = ChargeOption(
        station_id="F_NEAR",
        node_type="f",
        earliest_start_second=0.0,
        latest_start_second=0.0,
        energy_kwh=60.0,
        power_kw=60.0,
        detour_m=0.0,
    )
    far_green = ChargeOption(
        station_id="F_FAR",
        node_type="f",
        earliest_start_second=3600.0,
        latest_start_second=3600.0,
        energy_kwh=60.0,
        power_kw=60.0,
        detour_m=10_000.0,
    )

    normal = select_charge_option(
        [near_dirty, far_green],
        _instance(),
        profile,
        prices,
        carbon_weight=1.0,
    )
    strong_carbon_signal = select_charge_option(
        [near_dirty, far_green],
        _instance(),
        profile,
        prices,
        carbon_weight=4.0,
    )

    # At the paper carbon price, the 10 km detour costs more than the carbon
    # saving, so a carbon-first lexicographic rule would make the wrong choice.
    assert normal.option.station_id == "F_NEAR"
    # Increasing only the carbon weight eventually makes the same green station
    # rational; this proves that the units are combined coherently.
    assert strong_carbon_signal.option.station_id == "F_FAR"


def test_zero_carbon_weight_is_a_real_earliest_feasible_ablation() -> None:
    profile = _profile(900.0, 900.0, 10.0, 10.0)
    option = ChargeOption(
        station_id="F0",
        node_type="f",
        earliest_start_second=0.0,
        latest_start_second=3600.0,
        energy_kwh=30.0,
        power_kw=60.0,
    )

    naive = select_charge_option([option], _instance(), profile, PriceParameters(), carbon_weight=0.0)
    aware = select_charge_option([option], _instance(), profile, PriceParameters(), carbon_weight=1.0)

    assert naive.timing.start_second == 0.0
    assert aware.timing.start_second == 3600.0
    assert aware.timing.carbon_kg < naive.timing.carbon_kg


def test_exact_micro_scheduler_respects_single_charger_capacity() -> None:
    profile = _profile(10.0, 100.0, 200.0)
    requests = [
        ChargeRequest("EV1", "F0", 0.0, 1800.0, 30.0, 1800.0),
        ChargeRequest("EV2", "F0", 0.0, 1800.0, 30.0, 1800.0),
    ]

    schedule = schedule_charge_requests_exact(
        requests,
        _instance(),
        profile,
        station_capacity={"F0": 1},
    )

    assert len(schedule) == 2
    starts = sorted(item.start_second for item in schedule)
    assert starts == [0.0, 1800.0]
    assert schedule[0].end_second <= schedule[1].start_second


def test_integrated_route_repair_inserts_station_and_remains_fully_feasible() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=20_000.0),
            Node("C1", "c", 0.0, 0.0, demand=100.0, due_time=20_000.0),
            Node("F1", "f", 0.0, 0.0, due_time=20_000.0, charge_power_kw=60.0),
        ],
        distance_matrix=[
            [0.0, 100_000.0, 20_000.0],
            [100_000.0, 0.0, 20_000.0],
            [20_000.0, 20_000.0, 0.0],
        ],
    )
    profile = _profile(300.0, 250.0, 200.0, 50.0, 100.0, *([150.0] * 13))
    prices = PriceParameters(B_battery_kwh=80.0)
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])

    repaired, actions = repair_route_charging(
        route,
        instance,
        profile,
        prices,
        strategy="integrated",
    )

    assert "F1" in repaired.node_sequence
    assert {action.station_id for action in actions} == {"D0", "F1"}
    assert check_solution(Solution(routes=[repaired], charging_actions=actions), instance, prices) == []


def test_parallel_repair_keeps_equal_launch_energy_station_alternatives() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=20_000.0),
            Node("C1", "c", 0.0, 0.0, demand=100.0, due_time=20_000.0),
            Node("F1", "f", 0.0, 0.0, due_time=20_000.0, charge_power_kw=60.0),
            Node("F2", "f", 0.0, 0.0, due_time=20_000.0, charge_power_kw=60.0),
        ],
        distance_matrix=[
            [0.0, 100_000.0, 20_000.0, 20_000.0],
            [100_000.0, 0.0, 20_000.0, 20_000.0],
            [20_000.0, 20_000.0, 0.0, 20_000.0],
            [20_000.0, 20_000.0, 20_000.0, 0.0],
        ],
    )
    profile = _profile(300.0, 250.0, 200.0, 50.0, 100.0, *([150.0] * 13))
    prices = PriceParameters(B_battery_kwh=80.0)
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])

    candidates = repair_route_charging_candidates(
        route,
        instance,
        profile,
        prices,
        strategy="integrated",
        public_station_candidate_mode="parallel",
    )
    by_public_station = {
        next(
            action.station_id
            for action in actions
            if action.station_id in {"F1", "F2"}
        ): (candidate_route, actions)
        for _, candidate_route, actions in candidates
        if any(action.station_id in {"F1", "F2"} for action in actions)
    }

    assert set(by_public_station) == {"F1", "F2"}
    for candidate_route, actions in by_public_station.values():
        assert check_solution(
            Solution(routes=[candidate_route], charging_actions=actions),
            instance,
            prices,
        ) == []


def test_parallel_repair_continues_when_default_candidate_fails(
    monkeypatch,
) -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=20_000.0),
            Node("C1", "c", 0.0, 0.0, demand=1.0, due_time=20_000.0),
            Node("F1", "f", 0.0, 0.0, due_time=20_000.0, charge_power_kw=60.0),
        ],
        distance_matrix=[
            [0.0, 1_000.0, 1_000.0],
            [1_000.0, 0.0, 1_000.0],
            [1_000.0, 1_000.0, 0.0],
        ],
    )
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])

    def fake_candidate(*args, forced_station_path=(), **kwargs):
        del args, kwargs
        if not forced_station_path:
            raise ValueError("default path failed")
        station_id = forced_station_path[0]
        return (
            Route("EV1", "ev", "D0", ["D0", station_id, "C1", "D0"]),
            [
                ChargingAction(
                    "EV1",
                    station_id,
                    1.0,
                    1.0,
                    100.0,
                )
            ],
        )

    monkeypatch.setattr(
        charging_module,
        "_repair_route_charging_candidate",
        fake_candidate,
    )

    candidates = repair_route_charging_candidates(
        route,
        instance,
        _profile(100.0),
        PriceParameters(initial_ev_battery_kwh=80.0),
        public_station_candidate_mode="parallel",
    )

    assert [label for label, _, _ in candidates] == ["public_path_F1"]


def test_refined_operator_registry_is_opt_in_and_has_safe_pairing() -> None:
    default_ops = WinnerOperatorSet.create()
    refined_ops = WinnerOperatorSet.create(refined_carbon=True, refined_carbon_weight=2.0)

    default_destroy = [name for name, _ in default_ops.destroy_ops]
    default_repair = [name for name, _ in default_ops.repair_ops]
    refined_destroy = [name for name, _ in refined_ops.destroy_ops]
    refined_repair = [name for name, _ in refined_ops.repair_ops]

    assert "high_carbon_charge_segment_removal" not in default_destroy
    assert "charging_station_reset_destroy" not in default_destroy
    assert "integrated_carbon_reconstruction_repair" not in default_repair
    assert "worst_carbon_removal" not in refined_destroy
    assert "low_carbon_charging_repair" not in refined_repair
    assert refined_ops.refined_carbon_weight == 2.0

    coupling = _selector_coupling_contract(refined_ops)
    refined_repair_idx = refined_repair.index("integrated_carbon_reconstruction_repair")
    for destroy_name in ("high_carbon_charge_segment_removal", "charging_station_reset_destroy"):
        destroy_idx = refined_destroy.index(destroy_name)
        assert int(coupling[destroy_idx].sum()) == 1
        assert bool(coupling[destroy_idx, refined_repair_idx])


def test_refined_reset_and_reconstruction_consumes_one_candidate_evaluation() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=20_000.0),
            Node("C1", "c", 0.0, 0.0, demand=100.0, due_time=20_000.0),
            Node("F1", "f", 0.0, 0.0, due_time=20_000.0, charge_power_kw=60.0),
        ],
        distance_matrix=[
            [0.0, 100_000.0, 20_000.0],
            [100_000.0, 0.0, 20_000.0],
            [20_000.0, 20_000.0, 0.0],
        ],
    )
    profile = _profile(300.0, 250.0, 200.0, 50.0, 100.0, *([150.0] * 13))
    prices = PriceParameters(B_battery_kwh=80.0)
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])
    legacy_route, legacy_actions = repair_route_charging(route, instance, profile, prices, strategy="legacy")
    legacy_solution = Solution(routes=[legacy_route], charging_actions=legacy_actions)
    context = EvaluationContext(instance, profile, prices=prices, budget=EvalBudget(limit=1, target=1))
    operators = WinnerOperatorSet.create(refined_carbon=True, refined_carbon_weight=1.0)

    result = apply_winner_action(
        legacy_solution,
        WinnerOperatorAction("charging_station_reset_destroy", "integrated_carbon_reconstruction_repair"),
        context,
        rng=np.random.default_rng(7),
        operator_set=operators,
        current_obj=float(
            evaluate(
                legacy_solution,
                instance,
                profile,
                prices,
            )["total_cost"]
        ),
    )

    assert result["actual_evals_added"] == 1
    assert context.budget is not None and context.budget.count == 1
    assert result["hard_violation_count"] == 0
    assert check_solution(result["candidate_solution"], instance, prices) == []
