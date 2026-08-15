from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "solver/scripts/build_china81_suite_rebuild_20260812.py"
SPEC = importlib.util.spec_from_file_location("suite_rebuild_20260812", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_catalog_is_three_regions_nine_sizes_three_replicates() -> None:
    identities = MODULE.catalog_identities()
    assert len(identities) == 81
    assert {item.region for item in identities} == {"cy", "jjj", "prd"}
    assert {item.size for item in identities} == {
        10,
        15,
        20,
        25,
        50,
        75,
        100,
        150,
        200,
    }
    assert all("-V3-TWO-SHIFT-FS" in item.new_instance_id for item in identities)


def test_shift_assignment_is_deterministic_one_to_two_and_preserves_widths() -> None:
    tasks = [
        {
            "customer_id": f"C{index:03d}",
            "time_window_early_minute": str(700 + index * 3),
            "time_window_late_minute": str(730 + index * 3 + index % 4),
            "time_window_width_minute": str(30 + index % 4),
        }
        for index in range(1, 51)
    ]
    first = MODULE.assign_shift_windows(tasks)
    second = MODULE.assign_shift_windows(list(reversed(tasks)))
    assert first == second
    assert sum(row["shift_id"] == "AM" for row in first.values()) == 17
    assert sum(row["shift_id"] == "PM" for row in first.values()) == 33
    for customer_id, shifted in first.items():
        assert math.isclose(
            float(shifted["late"]) - float(shifted["early"]),
            float(shifted["width"]),
            abs_tol=1.0e-9,
        ), customer_id


def test_shift_assignment_switches_only_when_frozen_road_preferred_is_unreachable() -> None:
    tasks = [
        {
            "customer_id": f"C{index + 1:03d}",
            "time_window_early_minute": str(index * 10),
            "time_window_late_minute": str(index * 10 + 30),
            "time_window_width_minute": "30",
        }
        for index in range(9)
    ]
    travel = {row["customer_id"]: 0.0 for row in tasks}
    travel["C004"] = 110.0 * 60.0
    travel["C001"] = 400.0 * 60.0

    shifted = MODULE.assign_shift_windows(
        tasks,
        travel_seconds_by_customer=travel,
    )

    assert shifted["C004"]["preferred_shift_id"] == "AM"
    assert shifted["C004"]["shift_id"] == "PM"
    assert (
        shifted["C004"]["reachability_status"]
        == "SWITCHED_TO_REACHABLE_ALTERNATIVE"
    )
    assert shifted["C001"]["shift_id"] == "AM"
    assert (
        shifted["C001"]["reachability_status"]
        == "FLAG_BOTH_SHIFTS_UNREACHABLE"
    )


def test_gate_selector_enters_registered_range_without_changing_threshold() -> None:
    facts = []
    for index in range(20):
        facts.append(
            MODULE.LocationFact(
                source_node_id=f"C{index:03d}",
                city="x",
                nearest_depot="D_a",
                second_depot="D_b",
                nearest_cost_cny=float(index + 1),
                second_cost_cny=float(index + 1) * (1.1 if index >= 10 else 2.0),
                relative_gap=0.1 if index >= 10 else 1.0,
            )
        )
    selected, success, _ = MODULE.select_locations_for_gate(facts, 10)
    assert success
    count = sum(row.relative_gap < 0.25 for row in selected)
    assert 3 <= count <= 4


def test_closest_real_facility_pairs_are_source_derived() -> None:
    pairs = MODULE.closest_facility_pair_by_region()
    assert pairs["prd"] == ("D_foshan", "D_guangzhou")
    assert pairs["jjj"] == ("D_beijing", "D_tianjin")
    assert pairs["cy"] == ("D_chengdu", "D_chongqing")


def test_closest_pair_reanchor_does_not_borrow_a_third_city() -> None:
    identity = next(
        item
        for item in MODULE.catalog_identities()
        if item.source_instance_id == "cn-jjj-10c-01-V2-LOCATIONS"
    )
    cache = MODULE.SourceBundleCache()
    geometry = MODULE.choose_geometry(
        identity,
        cache.get(identity.source_instance_id),
        cache,
        MODULE.closest_facility_pair_by_region(),
    )
    assert geometry.mode == "ORIGINAL_GEOMETRY"
    assert geometry.attempted_rebuild
    assert not geometry.rebuild_succeeded
