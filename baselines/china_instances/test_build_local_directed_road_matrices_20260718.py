from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).with_name(
    "build_local_directed_road_matrices_20260718.py"
)
SPEC = importlib.util.spec_from_file_location("local_matrix", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def response(distance: float, duration: float) -> dict:
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": distance,
                "duration": duration + 2,
                "legs": [
                    {
                        "annotation": {
                            "distance": [distance / 2, distance / 2],
                            "duration": [duration / 2, duration / 2],
                        }
                    }
                ],
            }
        ],
        "waypoints": [{"location": [116.0, 40.0]}, {"location": [116.1, 40.1]}],
    }


def test_same_route_metrics() -> None:
    value = MODULE.parse_response(response(1000.0, 100.0))
    assert value.distance_m == 1000.0
    assert value.duration_s == 102.0
    assert value.routing_delay_s == 2.0
    assert math.isclose(value.sum_v2d_m3_s2, 100000.0)


def test_route_url_preserves_direction() -> None:
    left = MODULE.Node("A", "depot", 40.0, 116.0)
    right = MODULE.Node("B", "customer", 40.1, 116.1)
    forward = MODULE.route_url("http://127.0.0.1:5000", "driving", left, right)
    reverse = MODULE.route_url("http://127.0.0.1:5000", "driving", right, left)
    assert forward != reverse
    assert "116.0000000,40.0000000;116.1000000,40.1000000" in forward


def test_no_route_halts() -> None:
    try:
        MODULE.parse_response({"code": "NoRoute"})
    except MODULE.MatrixBuildError:
        return
    raise AssertionError("NoRoute must halt")


def test_customer_only_node_set_halts(tmp_path: Path) -> None:
    path = tmp_path / "nodes.csv"
    path.write_text(
        "node_id,node_type,latitude,longitude\n"
        "C1,customer,40.0,116.0\n"
        "C2,customer,40.1,116.1\n",
        encoding="utf-8",
    )
    try:
        MODULE.load_nodes(path)
    except MODULE.MatrixBuildError:
        return
    raise AssertionError("formal matrix nodes require depot and station")
