from __future__ import annotations

import hashlib
import json
from pathlib import Path

from baselines.china_instances.validate_china_parameter_lock_v2_20260718 import LOCK, validate_lock


def test_china_parameter_lock_is_machine_readable_and_not_formal() -> None:
    data = json.loads(LOCK.read_text(encoding="utf-8"))
    assert data["schema"] == "resetp.china.parameter-lock.v2"
    assert data["formal_search_allowed"] is False
    assert data["units"]["currency"] == "CNY"
    assert data["price_contract"]["tou_slots_per_day"] == 48
    assert data["scope"]["target_instances"] == 81
    assert data["scope"]["customer_sizes"] == [10, 15, 20, 25, 50, 75, 100, 150, 200]
    assert data["scope"]["instances_per_region_size"] == 3
    assert data["scope"]["mutual_exclusivity_required"] is True


def test_china_vehicle_source_captures_exist() -> None:
    data = json.loads(LOCK.read_text(encoding="utf-8"))
    for spec in data["vehicle_contract"].values():
        capture = Path(__file__).resolve().parents[1] / spec["source_capture"]
        assert capture.is_file(), capture


def test_china_order_attribute_contract_is_locked_and_result_independent() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    contract_path = Path(__file__).resolve().parents[1] / lock["customer_contract"]["order_attribute_contract"]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["status"] == "LOCKED_DESIGN_NOT_APPLIED"
    assert contract["formal_search_allowed"] is False
    assert contract["observed_chinese_orders_claim_allowed"] is False
    assert contract["units"] == {
        "demand": "kg",
        "time": "minute_from_local_midnight",
        "service_time": "minute",
    }
    assert sum(row["probability"] for row in contract["demand_mixture"]) == 1.0
    assert max(row["integer_uniform_kg"][1] for row in contract["demand_mixture"]) < 1300
    assert contract["witness_contract"]["route_load_limit_kg"] == 1040
    assert contract["witness_contract"]["algorithm_search_evaluations"] == 0
    assert contract["witness_contract"]["regeneration_after_failure_allowed"] is False
    assert contract["seed_rule"]["independent_of_algorithm_results"] is True
    assert set(contract["variants"]) == {"01", "02", "03"}
    assert {variant["window_profile"] for variant in contract["variants"].values()} == {"base_balanced"}
    assert {variant["replicate_index"] for variant in contract["variants"].values()} == {1, 2, 3}
    exclusivity = contract["mutual_exclusivity_contract"]
    assert exclusivity["customer_map_identity_overlap_allowed"] is False
    assert exclusivity["same_instance_with_changed_label_allowed"] is False
    assert exclusivity["post_result_customer_replacement_allowed"] is False
    assert exclusivity["cross_size_disjointness_required"] is False
    profiles = contract["time_window_profiles"]
    assert set(profiles) == {"base_balanced", "sensitivity_wide", "sensitivity_tight"}
    for profile in profiles.values():
        assert len(set(profile["window_width_minutes"])) > 1
        assert sum(profile["window_width_weights"]) == 1.0


def test_china_customer_location_contract_is_27_cells_with_three_disjoint_replicates() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    contract_path = Path(__file__).resolve().parents[1] / lock["customer_contract"]["customer_location_contract"]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["status"] == "LOCKED_DESIGN_POOL_SUFFICIENCY_PASSED_NOT_BUILT"
    assert contract["replicates_per_region_size"] == 3
    assert contract["replicate_labels"] == ["01", "02", "03"]
    assert contract["within_cell_identity_overlap_allowed"] is False
    assert contract["cross_size_identity_overlap_allowed"] is True
    assert contract["post_result_replacement_allowed"] is False
    assert set(contract["city_quotas"]) == {"jjj", "prd", "cy"}
    assert sum(len(table) for table in contract["city_quotas"].values()) == 27
    for table in contract["city_quotas"].values():
        assert sorted(int(size) for size in table) == contract["customer_sizes"]
        for size, quotas in table.items():
            assert sum(quotas.values()) == int(size)
    gate = contract["sufficiency_gate"]
    decision = json.loads((Path(__file__).resolve().parents[1] / gate["evidence_package"] / "decision.json").read_text(encoding="utf-8"))
    assert decision["verdict"] == "PASS_81_MUTUAL_EXCLUSIVITY_POOL_GATE"
    assert decision["region_size_cells_passed"] == 27
    assignment_decision = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "data/ChinaInstances/china81_customer_location_assignments_v2_20260718/decision.json"
        ).read_text(encoding="utf-8")
    )
    assert assignment_decision["verdict"] == "PASS_81_DISJOINT_LOCATION_ASSIGNMENTS_BUILT"
    assert assignment_decision["instances"] == 81
    assert assignment_decision["within_cell_overlap_violations"] == []


def test_china_road_matrix_contract_blocks_shortcuts_and_result_tuning() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    contract_path = Path(__file__).resolve().parents[1] / lock["distance_contract"]["road_matrix_contract"]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["status"] == "LOCKED_DESIGN_WAITING_FOR_VERIFIED_WGS84_ENTRANCES"
    assert contract["formal_search_allowed"] is False
    assert contract["coordinate_contract"]["formal_crs"] == "WGS84"
    assert contract["coordinate_contract"]["raw_baidu_crs"] == "BD09MC"
    assert contract["coordinate_contract"]["raw_baidu_values_may_enter_formal_lat_lon"] is False
    assert contract["router_contract"]["euclidean_multiplier_allowed"] is False
    assert contract["router_contract"]["straight_line_fallback_allowed"] is False
    assert contract["matrix_invariants"]["unreachable_node_policy"] == "HALT_INSTANCE_NO_REPLACEMENT_AFTER_RESULTS"
    assert contract["matrix_invariants"]["symmetry_required"] is False


def test_named_facility_candidate_manifest_covers_nine_cities_but_is_not_formal() -> None:
    manifest = Path(__file__).resolve().parents[1] / "docs/handoff/china_facility_manifest_v2_20260718.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["formal_search_allowed"] is False
    assert len(data["records"]) == 9
    assert {record["city"] for record in data["records"]} == {
        "beijing",
        "tianjin",
        "shijiazhuang",
        "guangzhou",
        "shenzhen",
        "dongguan",
        "foshan",
        "chengdu",
        "chongqing",
    }
    assert sum(record["source_capture"] is not None for record in data["records"]) == 9
    for record in data["records"]:
        capture = Path(__file__).resolve().parents[1] / record["source_capture"]
        assert capture.is_file(), record["facility_id"]
        assert hashlib.sha256(capture.read_bytes()).hexdigest() == record["source_capture_sha256"]
    assert sum(record["source_capture"] is None for record in data["records"]) == 0


def test_nine_city_operational_sites_do_not_cross_cities_or_fake_wgs84() -> None:
    manifest = Path(__file__).resolve().parents[1] / "docs/handoff/china_facility_manifest_v2_20260718.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    expected_uids = {
        "beijing": "07dc236824a0e3ba49fc8d2b",
        "tianjin": "0aa45c3b9adf9a5e6e20b930",
        "shijiazhuang": "f13a67f3eea2123a82a12e5e",
        "guangzhou": "f5141d94db59caa1c356ac61",
        "shenzhen": "6421a1c69b1aeab68a36eef1",
        "dongguan": "ee7fc367b5165e7f22f017f0",
        "foshan": "b3de3ceec4a5b371b31e3674",
        "chengdu": "85880009b61de98646572689",
        "chongqing": "6e699d1ad3a23e9b260bd089",
    }
    assert len(data["records"]) == len(expected_uids)
    for record in data["records"]:
        preferred = record["preferred_operational_site"]
        assert preferred["map_uid"] == expected_uids[record["city"]]
        raw = preferred["map_coordinate_original"]
        assert raw["crs"] == "BD09MC"
        assert raw["x"] > 1_000_000
        assert raw["y"] > 1_000_000
        assert record["coordinates"] == {"latitude": None, "longitude": None}
        assert preferred["official_operation_sources"]
        assert preferred["hard_parameter_sources"]
        hard = preferred["hard_parameter_audit"]
        assert hard["formal_depot_parameter_lock"] is False
        assert "operational_truck_parking_spaces" in hard
        assert "operational_vehicle_charger_count" in hard
        assert "operational_connector_count" in hard
        assert "operational_rated_power_kw" in hard


def test_facility_validator_recognises_all_candidates_but_keeps_formal_gate_closed() -> None:
    result = validate_lock()
    assert result["facility_manifest"]["preferred_site_count"] == 9
    assert result["facility_manifest"]["hard_parameter_audit_count"] == 9
    assert result["facility_manifest"]["preferred_coordinate_crs"] == "BD09MC"
    assert result["pass"] is False
    codes = {item["code"] for item in result["errors"]}
    assert "FACILITY_COORDINATES_PENDING" in codes
    assert "LEGACY_BRITISH_CORE_STILL_ACTIVE" in codes


def test_current_core_is_still_blocked_until_the_single_localisation_transition() -> None:
    result = validate_lock()
    codes = {item["code"] for item in result["errors"]}
    assert "LEGACY_BRITISH_CORE_STILL_ACTIVE" in codes
    assert result["formal_search_allowed"] is False
