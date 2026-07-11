from __future__ import annotations


def test_route_signature_ignores_vehicle_id_but_keeps_structure() -> None:
    from baselines.e2_alns.e2_route_block_headroom_audit import structural_route_signature
    from setp_solver.solution import Route

    left = Route("EV1#T1", "ev", "D0", ["D0", "C1", "D0"])
    right = Route("OTHER", "EV", "D0", ["D0", "C1", "D0"])
    changed = Route("OTHER", "EV", "D0", ["D0", "C2", "D0"])
    assert structural_route_signature(left) == structural_route_signature(right)
    assert structural_route_signature(left) != structural_route_signature(changed)


def test_route_block_headroom_requires_broad_feasible_and_material_conversions() -> None:
    from baselines.e2_alns.e2_route_block_headroom_audit import classify_headroom

    rows = []
    for index in range(6):
        rows.append(
            {
                "pair_role": "development",
                "feasible_mixed_partitions": 1 if index < 3 else 0,
                "best_mixed_gain_vs_best_parent_pct": 0.5 if index < 2 else 0.0,
                "best_mixed_cost": 99.0 if index < 2 else 101.0,
                "lns_cost": 100.0,
            }
        )
    assert classify_headroom(rows, parents_clean=True) == "ROUTE_BLOCK_HEADROOM_SUPPORTED"
    rows[1]["best_mixed_cost"] = 101.0
    assert classify_headroom(rows, parents_clean=True) == "ROUTE_BLOCK_HEADROOM_NOT_SUPPORTED"
    assert classify_headroom(rows, parents_clean=False) == "ROUTE_BLOCK_HEADROOM_NOT_SUPPORTED"
