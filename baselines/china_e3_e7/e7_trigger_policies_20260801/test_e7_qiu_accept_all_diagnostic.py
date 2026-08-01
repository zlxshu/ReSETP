from __future__ import annotations

import pytest

from baselines.china_e3_e7.e7_trigger_policies_20260801.dynamic_adapter import (
    PlanAttempt,
    accept_new_orders_as_full_batch,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801.run_qiu_accept_all_diagnostic import (
    route_plan_signature,
)
from setp_solver.instance_loader import Instance, Node
from setp_solver.solution import Route


def test_full_batch_admission_calls_planner_once_and_accepts_every_order() -> None:
    calls: list[tuple[str, ...]] = []

    def planner(customer_ids, _asset_states):
        calls.append(customer_ids)
        return PlanAttempt(True, payload="plan", delivery_cost=12.5)

    result = accept_new_orders_as_full_batch(("B", "A"), {}, planner)

    assert calls == [("A", "B")]
    assert result.accepted_customer_ids == ("A", "B")
    assert result.rejected_customer_ids == ()
    assert result.rejected_revenue == 0.0
    assert result.planner_call_count == 1


def test_full_batch_admission_preserves_the_planner_failure_text() -> None:
    def planner(_customer_ids, _asset_states):
        return PlanAttempt(False, reason="NoExecutableContinuation: exact failure")

    with pytest.raises(RuntimeError, match="^NoExecutableContinuation: exact failure$"):
        accept_new_orders_as_full_batch(("A",), {}, planner)


def test_route_signature_tracks_vehicle_assignment_and_customer_order() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0),
            Node("S0", "s", 0.5, 0.0),
            Node("C1", "c", 1.0, 0.0),
            Node("C2", "c", 2.0, 0.0),
        ],
        distance_matrix=[[0.0] * 4 for _ in range(4)],
    )
    before = [Route("CV_D0_1#T2", "cv", "D0", ["D0", "S0", "C1", "C2", "D0"])]
    same = [Route("CV_D0_1#T9", "cv", "D0", ["D0", "C1", "S0", "C2", "D0"])]
    changed = [Route("CV_D0_1#T2", "cv", "D0", ["D0", "C2", "C1", "D0"])]

    assert route_plan_signature(before, instance) == route_plan_signature(same, instance)
    assert route_plan_signature(before, instance) != route_plan_signature(changed, instance)
