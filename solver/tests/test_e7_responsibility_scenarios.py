from __future__ import annotations

import csv
import json

from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as gate
from baselines.e7_dynamic import e7_responsibility_scenario_design_20260714 as design


def _owners(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["customer_id"]: row["owner_depot_id"]
            for row in csv.DictReader(handle)
        }


def test_frozen_responsibility_scenarios_reuse_e3_maps_without_resampling() -> None:
    base_geo = _owners(
        design.E3_OWNERS / "L-main-threeshift-100c-01__geographic.csv"
    )
    base_mixed = _owners(
        design.E3_OWNERS / "L-main-threeshift-100c-01__mixed.csv"
    )
    donor_mixed = _owners(
        design.E3_OWNERS / "L-main-threeshift-200c-01__mixed.csv"
    )
    events = json.loads(
        (design.EVENT_ROOT / "stream_seed1.events.json").read_text(encoding="utf-8")
    )
    geographic = _owners(
        design.OUT / "ownership_maps/stream_seed1__geographic.csv"
    )
    historical = _owners(
        design.OUT / "ownership_maps/stream_seed1__historical_mixed.csv"
    )

    assert all(geographic[customer] == owner for customer, owner in base_geo.items())
    assert all(historical[customer] == owner for customer, owner in base_mixed.items())
    for event in events:
        if event["event_type"] == "add":
            assert (
                historical[event["customer_id"]]
                == donor_mixed[event["donor_customer_id"]]
            )


def test_both_conditions_have_valid_independent_starts() -> None:
    for condition in gate.CONDITIONS:
        sources, _profiles = gate._sources_for_day(condition)
        _events, owners, _event_path, _owner_path = gate._stream_for_condition(
            1, condition
        )
        prepared, certificate = gate.prepare_multitrip_solution(
            sources["solution"],
            sources["bundle"].instance,
            sources["prices"],
        )
        gate.validate_multitrip_certificate(
            certificate,
            list(prepared.routes),
            sources["prices"],
        )
        assert not gate.base._cross_site_ids_for_routes(
            prepared.routes,
            sources["bundle"].instance,
            owners,
        )
