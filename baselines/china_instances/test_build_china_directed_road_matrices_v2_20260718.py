from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parent
    / "build_china_directed_road_matrices_v2_20260718.py"
)
SPEC = importlib.util.spec_from_file_location("china_road_probe", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def node(node_id: str, latitude: float, longitude: float):
    return MODULE.ProbeNode(node_id, latitude, longitude, "node", node_id, node_id)


def valid_payload() -> dict:
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": 300.0,
                "duration": 30.0,
                "legs": [
                    {
                        "annotation": {
                            "distance": [100.0, 200.0],
                            "duration": [20.0, 10.0],
                        }
                    }
                ],
            }
        ],
        "waypoints": [
            {"location": [116.0, 39.0]},
            {"location": [116.1, 39.1]},
        ],
    }


def test_same_annotation_drives_all_three_metrics() -> None:
    metrics = MODULE.parse_route_response(
        valid_payload(), node("A", 39.0, 116.0), node("B", 39.1, 116.1)
    )
    assert metrics.distance_m == pytest.approx(300.0)
    assert metrics.duration_s == pytest.approx(30.0)
    assert metrics.annotation_duration_s == pytest.approx(30.0)
    assert metrics.routing_delay_s == pytest.approx(0.0)
    expected = (100.0 / 20.0) ** 2 * 100.0 + (200.0 / 10.0) ** 2 * 200.0
    assert metrics.sum_v2d_m3_s2 == pytest.approx(expected)
    assert metrics.annotation_segments == 2


def test_positive_distance_with_zero_duration_is_hard_failure() -> None:
    payload = valid_payload()
    payload["routes"][0]["legs"][0]["annotation"]["duration"][0] = 0.0
    with pytest.raises(MODULE.ProbeError, match="zero duration"):
        MODULE.parse_route_response(
            payload, node("A", 39.0, 116.0), node("B", 39.1, 116.1)
        )


def test_route_total_may_include_same_route_turn_delay() -> None:
    payload = valid_payload()
    payload["routes"][0]["duration"] = 35.0
    metrics = MODULE.parse_route_response(
        payload, node("A", 39.0, 116.0), node("B", 39.1, 116.1)
    )
    assert metrics.duration_s == pytest.approx(35.0)
    assert metrics.annotation_duration_s == pytest.approx(30.0)
    assert metrics.routing_delay_s == pytest.approx(5.0)


def test_missing_annotation_is_hard_failure_not_fallback() -> None:
    payload = valid_payload()
    payload["routes"][0]["legs"][0].pop("annotation")
    with pytest.raises(MODULE.ProbeError, match="annotation is missing"):
        MODULE.parse_route_response(
            payload, node("A", 39.0, 116.0), node("B", 39.1, 116.1)
        )


def test_route_url_requests_ordered_route_annotations() -> None:
    source = node("A", 39.0, 116.0)
    target = node("B", 39.1, 116.1)
    url = MODULE.route_url("https://example.test/", source, target)
    assert "/route/v1/driving/116.0000000,39.0000000;116.1000000,39.1000000" in url
    assert "annotations=distance%2Cduration" in url
    reverse = MODULE.route_url("https://example.test/", target, source)
    assert reverse != url


def test_asymmetry_is_measured_but_not_required() -> None:
    symmetric = [[0.0, 1.0], [1.0, 0.0]]
    asymmetric = [[0.0, 1.0], [2.0, 0.0]]
    assert MODULE.count_asymmetric_pairs(symmetric) == 0
    assert MODULE.count_asymmetric_pairs(asymmetric) == 1
    assert math.isfinite(asymmetric[1][0])


def test_user_approval_decision_is_fixed() -> None:
    assert (
        MODULE.DECISION
        == "EVIDENCE_OR_PROBE_READY_ROAD_METHOD_AWAITING_USER_APPROVAL"
    )
