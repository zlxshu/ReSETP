from __future__ import annotations

from pathlib import Path

from baselines.china_e3_e7.e7_o1_replanning_20260801 import run_low_cost
from baselines.china_e3_e7.e7_o1_replanning_20260801.policy import (
    COUNT_POLICIES,
    FIXED_30_MINUTES,
    HYBRID_COUNT_10_PERCENT_OR_30_MINUTES,
    HYBRID_COUNT_20_PERCENT_OR_30_MINUTES,
    HYBRID_TWO_MEAN_ORDERS_OR_30_MINUTES,
    MASS_POLICIES,
    PER_ORDER,
    POLICIES,
    build_o1_batches,
    build_o1_stream,
    demand_threshold_kg,
    order_count_threshold,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801.trigger_policies import (
    DynamicOrder,
)
from setp_solver.china81 import load_china81_bundle

REPO = Path(__file__).resolve().parents[3]


def _order(name: str, minute: int, demand: float) -> DynamicOrder:
    return DynamicOrder(
        event_id=name,
        customer_id=name,
        appearance_second=6 * 3600 + minute * 60,
        demand_kg=demand,
        x=0.0,
        y=0.0,
        ready_second=12 * 3600,
        due_second=13 * 3600,
        service_second=60.0,
        city=None,
    )


def test_three_policies_consume_every_order_and_hybrid_uses_both_causes() -> None:
    events = (_order("A", 5, 300), _order("B", 10, 250), _order("C", 50, 100))
    per_order = build_o1_batches(events, PER_ORDER, threshold_kg=500)
    fixed = build_o1_batches(events, FIXED_30_MINUTES, threshold_kg=500)
    hybrid = build_o1_batches(
        events, HYBRID_TWO_MEAN_ORDERS_OR_30_MINUTES, threshold_kg=500
    )
    assert len(per_order) == 3
    assert [batch.trigger_second for batch in fixed] == [6.5 * 3600, 7.0 * 3600]
    assert [batch.cause for batch in hybrid] == ["demand_threshold", "maximum_wait"]
    assert sorted(event for batch in hybrid for event in batch.event_ids) == ["A", "B", "C"]


def test_real_h0_g2_stream_and_threshold_are_deterministic() -> None:
    instance_id = "cn-prd-50c-01-V2-LOCATIONS"
    instance = load_china81_bundle(REPO, instance_id).instance
    first = build_o1_stream(instance, instance_id=instance_id, stream_seed=1)
    replay = build_o1_stream(instance, instance_id=instance_id, stream_seed=1)
    assert first == replay
    assert len(first.events) == 10
    assert abs(demand_threshold_kg(instance) - 488.92) < 1e-9


def test_literature_count_thresholds_scale_with_dynamic_orders() -> None:
    assert [
        order_count_threshold(count, HYBRID_COUNT_10_PERCENT_OR_30_MINUTES)
        for count in (10, 20, 30)
    ] == [1, 2, 3]
    assert [
        order_count_threshold(count, HYBRID_COUNT_20_PERCENT_OR_30_MINUTES)
        for count in (10, 20, 30)
    ] == [2, 4, 6]


def test_count_threshold_combines_early_release_with_30_minute_limit() -> None:
    events = (
        _order("A", 5, 10),
        _order("B", 10, 10),
        _order("C", 50, 10),
        _order("D", 90, 10),
        _order("E", 91, 10),
        _order("F", 92, 10),
        _order("G", 93, 10),
        _order("H", 94, 10),
        _order("I", 95, 10),
        _order("J", 96, 10),
    )
    batches = build_o1_batches(
        events, HYBRID_COUNT_20_PERCENT_OR_30_MINUTES
    )
    assert [batch.cause for batch in batches] == [
        "order_count_threshold",
        "maximum_wait",
        "order_count_threshold",
        "order_count_threshold",
        "order_count_threshold",
        "maximum_wait",
    ]
    assert sorted(event for batch in batches for event in batch.event_ids) == [
        event.event_id for event in events
    ]


def test_cli_selects_count_policies_without_changing_mass_entry(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[tuple[Path, tuple[int, ...], str]] = []

    def record_run(out: Path, seeds: tuple[int, ...], *, policy_set: str) -> None:
        calls.append((out, seeds, policy_set))

    monkeypatch.setattr(run_low_cost, "run", record_run)
    count_output = tmp_path / "count-output"
    run_low_cost.main(
        ["--policy-set", "count", "--output", str(count_output), "--seeds", "2"]
    )
    mass_output = tmp_path / "mass-output"
    run_low_cost.main(["--output", str(mass_output), "--seeds", "3"])

    assert calls == [
        (count_output.resolve(), (2,), "count"),
        (mass_output.resolve(), (3,), "mass"),
    ]
    count_policies, count_pairings, count_name = run_low_cost.run_configuration(
        "count"
    )
    mass_policies, mass_pairings, mass_name = run_low_cost.run_configuration("mass")
    assert count_policies == COUNT_POLICIES
    assert len(count_pairings) == 6
    assert {policy for pair in count_pairings for policy in pair} == set(COUNT_POLICIES)
    assert "count" in count_name
    assert mass_policies == POLICIES == MASS_POLICIES
    assert mass_pairings == run_low_cost.PAIRINGS
    assert mass_name == run_low_cost.OUTPUT_NAME


def test_count_pair_table_retains_all_six_pairs_and_failure_text() -> None:
    rows = []
    for index, policy in enumerate(COUNT_POLICIES):
        failed = policy == HYBRID_COUNT_20_PERCENT_OR_30_MINUTES
        rows.append(
            {
                "instance_id": run_low_cost.INSTANCES[0],
                "stream_seed": 1,
                "policy": policy,
                "status": "LEGAL_INFEASIBLE" if failed else "PASS_ACCEPT_ALL",
                "failure_reason": "original failure text" if failed else "",
                "final_delivery_cost_cny": "NA" if failed else 100.0 + index,
                "distance_total_m": "NA" if failed else 1000.0 + index,
                "total_emissions_kg": "NA" if failed else 10.0 + index,
                "actual_vehicle_count": 2 + index,
                "actual_route_adjustment_count": 3 + index,
                "scheduled_trigger_count": 4 + index,
                "threshold_trigger_count": 1 + index,
                "time_trigger_count": 2 + index,
                "mean_information_wait_minutes": 5.0 + index,
                "failure_stage": 7 if failed else None,
            }
        )

    pairs = run_low_cost.paired_rows(
        rows,
        policies=COUNT_POLICIES,
        pairings=run_low_cost.COUNT_PAIRINGS,
        retain_failures=True,
    )

    assert len(pairs) == 6
    failed_pairs = [row for row in pairs if row["pair_status"] != "PASS_PAIRED"]
    assert len(failed_pairs) == 3
    assert all(
        "original failure text"
        in {row["left_failure_reason"], row["right_failure_reason"]}
        for row in failed_pairs
    )
    report = run_low_cost._report(
        rows,
        pairs,
        policies=COUNT_POLICIES,
        pairings=run_low_cost.COUNT_PAIRINGS,
        policy_set="count",
    )
    assert all(run_low_cost.LABELS[policy] in report for policy in COUNT_POLICIES)
    assert "original failure text" in report
    assert "实际改路线" in report
    assert "平均等待" in report
