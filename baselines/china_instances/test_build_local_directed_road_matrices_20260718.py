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


def test_zero_duration_terminal_segment_is_coalesced() -> None:
    payload = response(1000.0, 100.0)
    annotation = payload["routes"][0]["legs"][0]["annotation"]
    annotation["distance"] = [500.0, 499.9, 0.1]
    annotation["duration"] = [50.0, 50.0, 0.0]
    value = MODULE.parse_response(payload)
    assert value.zero_duration_positive_distance_segments == 1
    assert value.distance_m == 1000.0
    assert value.sum_v2d_m3_s2 > 0


def test_distinct_inputs_snapped_to_same_point_are_explicit_colocated_pair() -> None:
    payload = response(0.0, 0.0)
    payload["routes"][0]["duration"] = 0.0
    payload["routes"][0]["legs"][0]["annotation"]["distance"] = [0.0]
    payload["routes"][0]["legs"][0]["annotation"]["duration"] = [0.0]
    payload["waypoints"][1]["location"] = payload["waypoints"][0]["location"]
    value = MODULE.parse_response(payload)
    assert value.colocated_snapped_pair == 1
    assert value.distance_m == 0
    assert value.duration_s == 0
    assert value.sum_v2d_m3_s2 == 0


def test_subresolution_positive_distance_zero_duration_is_explicit() -> None:
    payload = response(0.2, 0.0)
    payload["routes"][0]["duration"] = 0.0
    payload["routes"][0]["legs"][0]["annotation"]["distance"] = [0.222]
    payload["routes"][0]["legs"][0]["annotation"]["duration"] = [0.0]
    value = MODULE.parse_response(payload)
    assert value.subresolution_zero_duration_pair == 1
    assert value.distance_m == 0.222
    assert value.duration_s == 0
    assert value.sum_v2d_m3_s2 == 0


def test_one_via_combines_two_leg_annotations() -> None:
    payload = response(300.0, 30.0)
    payload["routes"][0]["legs"] = [
        {"annotation": {"distance": [100.0], "duration": [10.0]}},
        {"annotation": {"distance": [200.0], "duration": [20.0]}},
    ]
    payload["waypoints"].insert(1, {"location": [116.05, 40.05]})
    value = MODULE.parse_response(payload)
    assert value.via_repair == 1
    assert value.via_matched_lon == 116.05
    assert value.distance_m == 300.0
    assert value.annotation_segments == 2


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
