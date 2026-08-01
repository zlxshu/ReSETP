from __future__ import annotations

from dataclasses import replace

from baselines.china_e3_e7.e7_trigger_policies_20260801.aggregate_seeds import (
    ALL_DYNAMIC_PAIRS,
    _report as aggregate_report,
    comparison_rows,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801.run_pilot import (
    _report as seed_report,
    default_output,
)
from setp_solver.check import CHARGING_START, check_solution
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.dynamic_multitrip_schedule import (
    DynamicAssetState,
    prepare_dynamic_multitrip_solution,
    validate_dynamic_multitrip_certificate,
)
from setp_solver.solution import Route, Solution


def test_seed_selects_its_own_sibling_output() -> None:
    assert default_output(1).name == "pilot_50c_seed1_eval8_v1_20260801"
    assert default_output(3).name == "pilot_50c_seed3_eval8_v1_20260801"
    assert default_output(10).name == "pilot_50c_seed10_eval8_v1_20260801"


def test_report_uses_actual_seed_subset_count_and_evaluation_budget() -> None:
    text = seed_report(
        [],
        "stream-hash",
        "PASS",
        stream_seed=9,
        addition_count=3,
        static_subset_count=7,
        stage_evaluations=11,
    )

    assert "订单流种子 9" in text
    assert "对 3 个新订单的全部 7 种取舍" in text
    assert "每个候选均使用 11 次完整评价" in text
    assert "全信息一次性静态参照" in text
    assert "邱莹莹式一次启发式排程" in text
    assert "不是数学最优或理论上界" in text


def test_aggregate_report_replaces_the_historical_static_label() -> None:
    text = aggregate_report(
        [
            {
                "stream_seed": 1,
                "arm": "full_information_static_reference",
                "total_cost_with_lost_revenue_cny": 100.0,
                "completion_rate_pct": 90.0,
                "rejected_customer_count": 1,
                "evaluation_count": 8,
                "legal": True,
            }
        ],
        [],
        False,
    )

    assert "| 1 | 全信息一次性静态参照 |" in text
    assert "旧单种子报告作为历史产物保留" in text
    assert "邱莹莹式一次启发式排程" in text
    assert "不是数学最优或理论上界" in text


def test_aggregate_report_supports_the_approved_ten_seed_extension() -> None:
    text = aggregate_report([], [], True, tuple(range(1, 11)))

    assert "# E7 10个订单流种子汇总" in text
    assert "seed 1、2、3、4、5、6、7、8、9、10" in text
    assert "原车型上限" in text
    assert "10个种子的低成本小试事实表" in text


def test_seed_comparison_keeps_signed_differences_and_win_loss() -> None:
    rows = []
    for seed, per_cost, fixed_cost, hybrid_cost in (
        (1, 90.0, 100.0, 80.0),
        (2, 100.0, 100.0, 120.0),
        (3, 130.0, 110.0, 140.0),
    ):
        for arm, cost, completion, rejected, evaluations in (
            ("per_order", per_cost, 92.0, 4, 100),
            ("fixed_30_minutes", fixed_cost, 90.0, 5, 120),
            ("hybrid_500kg_or_30_minutes", hybrid_cost, 94.0, 3, 80),
        ):
            rows.append(
                {
                    "stream_seed": seed,
                    "arm": arm,
                    "total_cost_with_lost_revenue_cny": cost,
                    "completion_rate_pct": completion,
                    "rejected_customer_count": rejected,
                    "evaluation_count": evaluations,
                }
            )

    compared = comparison_rows(rows, ALL_DYNAMIC_PAIRS)
    by_key = {
        (row["stream_seed"], row["left_arm"], row["right_arm"]): row
        for row in compared
    }

    assert by_key[(1, "per_order", "fixed_30_minutes")][
        "total_cost_delta_cny"
    ] == -10.0
    assert by_key[(1, "per_order", "fixed_30_minutes")][
        "left_cost_outcome"
    ] == "win"
    assert by_key[(2, "per_order", "fixed_30_minutes")][
        "left_cost_outcome"
    ] == "tie"
    assert by_key[(3, "per_order", "fixed_30_minutes")][
        "left_cost_outcome"
    ] == "loss"
    assert by_key[(1, "per_order", "hybrid_500kg_or_30_minutes")][
        "completion_rate_delta_percentage_points"
    ] == -2.0
    assert by_key[(1, "per_order", "hybrid_500kg_or_30_minutes")][
        "evaluation_count_delta"
    ] == 20
    assert by_key[
        (1, "hybrid_500kg_or_30_minutes", "fixed_30_minutes")
    ]["total_cost_delta_cny"] == -20.0


def test_dynamic_certificate_clock_is_not_replaced_by_natural_route_clock() -> None:
    prices = replace(DEFAULT_PRICES, initial_ev_battery_kwh=0.0)
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=30_000.0),
            Node(
                "C1",
                "c",
                1.0,
                0.0,
                demand=10.0,
                ready_time=2_500.0,
                due_time=10_000.0,
                service_time=300.0,
            ),
        ],
        distance_matrix=[[0.0, 10_000.0], [10_000.0, 0.0]],
        num_cv=0,
        num_ev=1,
    )
    states = {
        "EV_D0_1": DynamicAssetState("EV_D0_1", "ev", "D0", 3_000.0, 0.0, 1)
    }
    source = Solution(
        routes=[Route("open", "ev", "D0", ["D0", "C1", "D0"])]
    )

    prepared, certificate = prepare_dynamic_multitrip_solution(
        source,
        instance,
        prices,
        asset_states=states,
        stage_start_second=3_000.0,
    )
    validate_dynamic_multitrip_certificate(
        prepared,
        certificate,
        instance,
        prices,
        asset_states=states,
        stage_start_second=3_000.0,
    )

    assert any(
        item.type == CHARGING_START
        for item in check_solution(prepared, instance, prices)
    )
    action = prepared.charging_actions[0]
    assert action.charge_start_second > 2_100.0
    assert abs(
        action.charge_start_second
        + action.occupancy_minutes * 60.0
        - certificate.trips[0].departure_second
    ) < 1.0e-9
