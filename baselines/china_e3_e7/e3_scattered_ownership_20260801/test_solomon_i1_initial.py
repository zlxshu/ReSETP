"""Checks for the E3 fixed-ownership initial route construction."""

from baselines.china_e3_e7.e3_scattered_ownership_20260801.run_e3_capacity_rank_aligned import (
    prepare,
)
from baselines.china_e3_e7.e3_scattered_ownership_20260801.shared_runtime import (
    build_common_initial,
)


def test_solomon_i1_initial_fits_all_six_formal_instances() -> None:
    for size in (150, 200):
        for replicate in (1, 2, 3):
            instance_id = f"cn-prd-{size}c-0{replicate}-V2-LOCATIONS"
            bundle, _ = prepare(instance_id)
            solution, route_counts = build_common_initial(bundle)

            assert solution.routes
            assert all(
                route_counts[depot] <= int(caps["total_fleet_cap"])
                for depot, caps in bundle.fleet_caps_by_depot.items()
            )
