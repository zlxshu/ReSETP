from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pytest

from setp_solver.algorithms.problem_hgs.fleet_registry import (
    register_all_vehicle_slots,
)
from setp_solver.algorithms.problem_hgs.model import DutyIndividual
from setp_solver.china81 import (
    ENDOGENOUS_FLEET_PARAMETERS,
    FIXED_25_PERCENT_FLEET_PARAMETERS,
    load_china81_bundle,
)
from setp_solver.cost import evaluate


REPO = Path(__file__).resolve().parents[2]
FLEET_CAPS = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v3_20260802/fleet_caps.csv"
)
TARGETS = (
    "cn-cy-50c-01-V2-LOCATIONS",
    "cn-jjj-50c-01-V2-LOCATIONS",
    "cn-prd-50c-01-V2-LOCATIONS",
)


def _authority_rows(instance_id: str) -> dict[str, dict[str, str]]:
    with FLEET_CAPS.open(newline="", encoding="utf-8") as handle:
        return {
            row["depot_id"]: row
            for row in csv.DictReader(handle)
            if row["instance_id"] == instance_id
        }


def test_existing_fixed_25_percent_loader_path_is_unchanged() -> None:
    implicit = load_china81_bundle(REPO, TARGETS[0])
    explicit = load_china81_bundle(
        REPO,
        TARGETS[0],
        fleet_parameters=FIXED_25_PERCENT_FLEET_PARAMETERS,
    )

    assert {
        depot: dict(caps)
        for depot, caps in implicit.fleet_caps_by_depot.items()
    } == {
        depot: dict(caps)
        for depot, caps in explicit.fleet_caps_by_depot.items()
    }
    assert implicit.instance.num_cv == explicit.instance.num_cv
    assert implicit.instance.num_ev == explicit.instance.num_ev
    assert implicit.has_additional_total_fleet_cap is True


def test_china81_carbon_profile_uses_24_hourly_values() -> None:
    bundle = load_china81_bundle(REPO, TARGETS[1])
    beijing_rows = [
        row
        for row in bundle.time_profile
        if row["city"] == "beijing"
    ]

    assert len(beijing_rows) == 48
    assert sorted({row["hourly_calendar_row"] for row in beijing_rows}) == list(
        range(1, 25)
    )
    for hour in range(1, 25):
        rows = [
            row
            for row in beijing_rows
            if row["hourly_calendar_row"] == hour
        ]
        assert len(rows) == 2
        assert rows[0]["actual_gco2_per_kwh"] == pytest.approx(
            rows[1]["actual_gco2_per_kwh"]
        )


@pytest.mark.parametrize("instance_id", TARGETS)
def test_endogenous_caps_are_exactly_rd_re_with_unchanged_depot_chargers(
    instance_id: str,
) -> None:
    rows = _authority_rows(instance_id)
    bundle = load_china81_bundle(
        REPO,
        instance_id,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )

    assert bundle.has_additional_total_fleet_cap is False
    assert set(bundle.fleet_caps_by_depot) == set(rows)
    for depot_id, caps in bundle.fleet_caps_by_depot.items():
        row = rows[depot_id]
        assert caps["num_cv"] == int(row["base_all_cv_routes_Rd"])
        assert caps["num_ev"] == int(row["base_all_ev_routes_Re"])
        assert caps["total_fleet_cap"] == caps["num_cv"] + caps["num_ev"]
        charger = bundle.charger_scenario_by_node[depot_id]
        assert charger["charger_count"] == 2
        assert charger["charge_power_kw"] == pytest.approx(22.0)
    assert bundle.instance.num_cv == sum(
        int(row["base_all_cv_routes_Rd"])
        for row in rows.values()
    )
    assert bundle.instance.num_ev == sum(
        int(row["base_all_ev_routes_Re"])
        for row in rows.values()
    )


def test_endogenous_registry_pads_every_idle_vehicle_and_idle_cost_is_zero() -> None:
    bundle = load_china81_bundle(
        REPO,
        TARGETS[0],
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    registered = register_all_vehicle_slots(
        DutyIndividual((), source="endogenous-registry-sanity"),
        bundle,
    )

    counts = Counter(
        (duty.home_depot_id, duty.vehicle_type)
        for duty in registered.duties
    )
    for depot_id, caps in bundle.fleet_caps_by_depot.items():
        assert counts[(depot_id, "cv")] == caps["num_cv"]
        assert counts[(depot_id, "ev")] == caps["num_ev"]
    assert all(duty.trips == () for duty in registered.duties)

    breakdown = evaluate(
        registered.to_solution(),
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    assert breakdown["n_veh_cv"] == 0
    assert breakdown["n_veh_ev"] == 0
    assert breakdown["cost_fix"] == pytest.approx(0.0)
