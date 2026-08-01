from __future__ import annotations

from baselines.china_e3_e7.e3_scattered_ownership_20260801 import (
    run_e3_capacity_rank_aligned as runner,
)


def test_alignment_only_renames_source_labels() -> None:
    bundle, info = runner.prepare()
    customers = sorted(bundle.customer_home_depot)
    source = runner.base.sequences()[(runner.SOURCE_FAMILY, "01")][:150]
    depot_to_label = {depot: label for label, depot in info["label_to_depot"].items()}
    recovered = tuple(depot_to_label[bundle.customer_home_depot[c]] for c in customers)

    assert recovered == source
    assert [source.count(label) for label in range(4)] == [60, 59, 17, 14]


def test_capacity_rank_rule_is_deterministic() -> None:
    _, first = runner.prepare()
    _, second = runner.prepare()

    assert (
        first["label_to_depot"]
        == second["label_to_depot"]
        == {
            0: "D_shenzhen",
            1: "D_guangzhou",
            2: "D_dongguan",
            3: "D_foshan",
        }
    )
    assert first["mapping_sha256"] == second["mapping_sha256"]


def test_150c01_capacity_lower_bound_is_feasible_without_fleet_changes() -> None:
    original = runner.base.load_bundle(runner.INSTANCE)
    aligned, info = runner.prepare()

    assert all(
        row["capacity_shortfall_kg"] == 0 for row in info["depot_stats"].values()
    )
    assert aligned.instance.num_cv == original.instance.num_cv
    assert aligned.instance.num_ev == original.instance.num_ev
    assert {
        depot: dict(caps) for depot, caps in aligned.fleet_caps_by_depot.items()
    } == {depot: dict(caps) for depot, caps in original.fleet_caps_by_depot.items()}


def test_common_initial_is_legal_under_original_caps() -> None:
    bundle, _ = runner.prepare()
    initial, route_counts = runner.base.build_common_initial(bundle)
    _, _, violations = runner.base.exact_china81_score(initial, bundle)

    assert not violations
    assert not initial.cross_site_services
    assert all(
        route_counts[depot] <= caps["total_fleet_cap"]
        for depot, caps in bundle.fleet_caps_by_depot.items()
    )
