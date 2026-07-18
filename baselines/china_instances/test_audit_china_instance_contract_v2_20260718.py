from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("audit_china_instance_contract_v2_20260718.py")
SPEC = importlib.util.spec_from_file_location("instance_audit", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def minimal_payload() -> dict:
    return {
        "formal_experiment_authorized": False,
        "draft_only": True,
        "demand_unit": "kg",
        "distance_unit": "meter",
        "metadata": {
            "price_contract": {"currency": "CNY"},
            "vehicle_contract": {"minimum_payload_capacity_kg": 1000},
            "customer_contract": {"service_window_mode": "city_06_22"},
            "distance_rule": "road_network shortest path",
            "distance_contract": {"router_name": "OSRM 26.7.3"},
            "carbon_curve": {
                "data_nature": "projected",
                "source_sha256": "a",
                "column": "value",
            },
        },
    }


def nodes() -> list[dict]:
    return [
        {
            "node_id": "D1",
            "node_type": "d",
            "facility_id": "d",
            "facility_name_zh": "场",
            "source_url": "u",
            "source_capture_sha256": "a",
            "operating_status": "scenario",
        },
        {
            "node_id": "C1",
            "node_type": "c",
            "demand": 10,
            "ready_time": 21600,
            "due_time": 30000,
            "service_time": 600,
        },
        {
            "node_id": "F1",
            "node_type": "f",
            "charge_power_kw": 60,
            "station_chargers": 1,
            "charger_count_provenance": "operator",
            "station_name_zh": "站",
            "source_url": "u",
            "source_capture_sha256": "a",
            "operator": "o",
        },
    ]


def test_directed_asymmetric_matrix_is_allowed() -> None:
    matrix = np.array([[0.0, 2.0, 3.0], [4.0, 0.0, 5.0], [6.0, 7.0, 0.0]])
    carbon = [{"value": 1.0} for _ in range(48)]
    result = MODULE.audit_instance(
        minimal_payload(), nodes(), matrix, carbon, matrix * 2, matrix * 3
    )
    codes = {error["code"] for error in result["errors"]}
    assert "DISTANCE_MATRIX_BASIC_INVARIANT_FAILED" not in codes
    assert "DISTANCE_MATRIX_OFF_DIAGONAL_NOT_POSITIVE" not in codes
    assert not any(code.startswith("DURATION_MATRIX") for code in codes)
    assert not any(code.startswith("SUM_V2D_MATRIX") for code in codes)


def test_draft_flag_contract() -> None:
    payload = minimal_payload()
    result = MODULE.audit_instance(payload, nodes(), None, None)
    assert "FORMAL_FLAG_NOT_CLOSED" not in {
        error["code"] for error in result["errors"]
    }
