from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for path in (HERE, REPO / "solver/src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from pyvrp_adapter import _distance_only_arc_cost
from setp_solver.china81 import load_china81_bundle


def test_distance_only_is_raw_directed_distance() -> None:
    bundle = load_china81_bundle(REPO, "cn-jjj-25c-01-V2-LOCATIONS")
    depot = next(
        node for node in bundle.instance.nodes if node.node_type.lower() == "d"
    )
    customer = next(
        node for node in bundle.instance.nodes if node.node_type.lower() == "c"
    )
    expected, _, _ = bundle.instance.arc_metrics(
        depot.node_id,
        customer.node_id,
        "cv",
        fallback_speed_mps=float(bundle.prices.v_speed_ms),
    )
    observed = _distance_only_arc_cost(
        bundle,
        depot.node_id,
        customer.node_id,
        1234.5,
        vehicle_type="cv",
        fueling_depot_id=depot.node_id,
    )
    assert observed == round(expected)


def test_runner_module_loads_and_development_scope_is_frozen() -> None:
    spec = importlib.util.spec_from_file_location(
        "comparison_runner_under_test",
        HERE / "run_comparison.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    instances, seeds = module._scope(False)
    assert len(instances) == 9
    assert seeds == (1, 2, 3)
    rows = module._archive_rows(instances, seeds)
    assert len(rows) == 108
    assert {row["arm"] for row in rows} == {"F", "E", "M", "MV"}
