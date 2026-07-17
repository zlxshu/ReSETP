"""MIT cspy cross-check over a finite graph of fully replayed micro plans.

The nonlinear physics is compiled by the clean-room prototype before cspy is
called.  This does not claim that cspy 0.1.2 natively implements ReSETP's
nonlinear charging resource extension.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import networkx as nx
import numpy as np
from cspy import BiDirectional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from micro_cases import conflict_micro_route  # noqa: E402
from prototype import enumerate_action_plans, replay_plan  # noqa: E402


def main() -> int:
    case = conflict_micro_route()
    feasible = []
    for index, actions in enumerate(enumerate_action_plans(case)):
        result = replay_plan(case, actions, plan_index=index)
        if result.feasible:
            feasible.append(result)
    graph = nx.DiGraph(n_res=2)
    for result in feasible:
        node = f"plan_{result.plan_index:03d}"
        graph.add_edge(
            "Source",
            node,
            weight=float(result.objective_value),
            res_cost=np.array(
                [float(result.finish_time_seconds), float(result.total_charge_kwh)]
            ),
        )
        graph.add_edge(
            node,
            "Sink",
            weight=0.0,
            res_cost=np.array([0.0, 0.0]),
        )
    algorithm = BiDirectional(
        graph,
        max_res=[20_000.0, 20.0],
        min_res=[0.0, 0.0],
        direction="forward",
        elementary=True,
    )
    algorithm.run()
    selected = int(str(algorithm.path[1]).split("_")[1])
    expected = min(feasible, key=lambda row: (row.objective_value, row.plan_index))
    payload = {
        "status": "PASS" if selected == expected.plan_index else "FAIL",
        "distribution_version": "0.1.2",
        "module_version": __import__("cspy").__version__,
        "license": "MIT",
        "graph_semantics": "finite_graph_of_clean_room_replayed_feasible_plans",
        "native_nonlinear_resource_claimed": False,
        "feasible_plan_count": len(feasible),
        "selected_plan_index": selected,
        "expected_plan_index": expected.plan_index,
        "objective": float(algorithm.total_cost),
        "path": list(algorithm.path),
        "consumed_resources": [float(value) for value in algorithm.consumed_resources],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

