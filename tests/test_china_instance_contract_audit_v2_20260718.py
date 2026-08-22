from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from baselines.china_instances.audit_china_instance_contract_v2_20260718 import audit_instance


def _valid_payload() -> dict:
    return {
        "draft_only": False,
        "formal_experiment_authorized": False,
        "demand_unit": "kg",
        "distance_unit": "meter",
        "metadata": {
            "price_contract": {"currency": "CNY"},
            "vehicle_contract": {"minimum_payload_capacity_kg": 1300},
            "customer_contract": {"service_window_mode": "city_06_22"},
            "distance_rule": "road_network_shortest_path",
            "distance_contract": {"router_name": "test-router"},
            "carbon_curve": {"column": "Beijing", "data_nature": "China projected TVCI", "source_sha256": "abc"},
        },
    }


def _valid_nodes() -> list[dict]:
    return [
        {"node_id": "D0", "node_type": "d", "facility_id": "f0", "facility_name_zh": "测试物流枢纽", "source_url": "https://example.gov.cn/f0", "source_capture_sha256": "d0", "operating_status": "operating"},
        {"node_id": "C1", "node_type": "c", "demand": 400, "ready_time": 21600, "due_time": 30000, "service_time": 600},
        {"node_id": "C2", "node_type": "c", "demand": 500, "ready_time": 32000, "due_time": 43000, "service_time": 600},
        {"node_id": "F1", "node_type": "f", "charge_power_kw": 60, "station_chargers": 1, "charger_count_provenance": "official_station_field", "station_name_zh": "测试快充站", "source_url": "https://example.gov.cn/f1", "source_capture_sha256": "f1", "operator": "测试运营方"},
    ]




def test_historical_draft_is_rejected_for_the_relevant_reasons() -> None:
    repo = Path(__file__).resolve().parents[1]
    bundle = next((repo / "data/ChinaInstances/CHINA81_DRAFT_20260717_source_bound").glob("cn-jjj-10c-1d-01-24h-DRAFT"))
    payload = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
    nodes = payload["nodes"]
    matrix = np.load(bundle / "distance_matrix.npy", allow_pickle=False)
    with (bundle / "carbon_profile.csv").open(encoding="utf-8") as handle:
        import csv

        carbon = list(csv.DictReader(handle))
    result = audit_instance(payload, nodes, matrix, carbon)
    codes = {item["code"] for item in result["errors"]}
    assert "LEGACY_FOREIGN_PARAMETER_MARKER" in codes
    assert "DEPOT_IS_GENERIC_INDUSTRIAL_CANDIDATE" in codes
    assert "ROAD_DISTANCE_CONTRACT_MISSING" in codes
    assert "STATION_GUN_COUNT_UNSUPPORTED_DEFAULT" in codes
    assert "TIME_WINDOW_MODE_UNDECLARED" in codes
