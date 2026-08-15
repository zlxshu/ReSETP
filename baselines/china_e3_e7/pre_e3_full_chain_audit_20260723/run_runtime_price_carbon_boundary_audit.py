#!/usr/bin/env python3
"""Zero-search runtime boundary and fault-injection audit for China81.

The script calls the production loader and production charging settlement
functions. It never invokes an optimiser. Positive checks independently
recompute slot, price, service-fee, and carbon arithmetic. Negative checks
record whether malformed formal inputs are rejected or silently accepted.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[3]
OUT = SCRIPT.parent
CORRECTED_AUTHORITY = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v3_20260723"
)
sys.path.insert(0, str(REPO / "solver/src"))

from setp_solver.charging_curve import spec_from_parameters  # noqa: E402
from setp_solver.china81 import (  # noqa: E402
    _load_time_profile,
    load_china81_bundle,
)
from setp_solver.cost import (  # noqa: E402
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    time_profile_rows_for_node,
)
from setp_solver.solution import ChargingAction  # noqa: E402


@dataclass(frozen=True)
class RuntimeCheck:
    check_id: str
    severity: str
    status: str
    subject: str
    observed: str
    expected: str
    evidence: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add(
    checks: list[RuntimeCheck],
    *,
    check_id: str,
    severity: str,
    status: str,
    subject: str,
    observed: Any,
    expected: Any,
    evidence: str,
) -> None:
    checks.append(
        RuntimeCheck(
            check_id=check_id,
            severity=severity,
            status=status,
            subject=subject,
            observed=str(observed),
            expected=str(expected),
            evidence=evidence,
        )
    )


def make_action(
    bundle: Any,
    node_id: str,
    *,
    start_second: float,
    energy_kwh: float,
) -> ChargingAction:
    node = bundle.instance.nodes[bundle.instance.node_index[node_id]]
    reference_power = (
        float(bundle.prices.depot_charge_power_kw)
        if node.node_type.lower() == "d"
        else float(node.charge_power_kw)
    )
    curve = spec_from_parameters(bundle.prices).scale(
        capacity_kwh=bundle.instance.battery_capacity_kwh(
            fallback=float(bundle.prices.B_battery_kwh)
        ),
        reference_power_kw=reference_power,
    )
    end_energy = float(energy_kwh)
    duration = curve.duration_seconds(0.0, end_energy)
    return ChargingAction(
        vehicle_id="EV_AUDIT",
        station_id=node_id,
        energy_kwh=end_energy,
        occupancy_minutes=duration / 60.0,
        charge_start_second=float(start_second),
        charge_day_offset=0,
        start_energy_kwh=0.0,
        end_energy_kwh=end_energy,
        charging_curve_id=curve.curve_id,
    )


def city_facility(bundle: Any, city: str, node_type: str) -> str:
    matches = [
        node.node_id
        for node in bundle.instance.nodes
        if str(node.city).lower() == city
        and node.node_type.lower() == node_type
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one {node_type} node for {city}, found {matches}"
        )
    return matches[0]


def main() -> int:
    checks: list[RuntimeCheck] = []
    legacy_chengdu_rejected = False
    legacy_chengdu_error = ""
    try:
        load_china81_bundle(
            REPO,
            "cn-cy-50c-01-V2-LOCATIONS",
        )
    except ValueError as exc:
        legacy_chengdu_error = str(exc)
        legacy_chengdu_rejected = (
            "city-carbon mapping disagrees" in legacy_chengdu_error
        )
    add(
        checks,
        check_id="A4R-LEGACY-01",
        severity="P0",
        status="PASS" if legacy_chengdu_rejected else "FAIL",
        subject="legacy Chengdu-to-Chongqing carbon contamination is rejected",
        observed=legacy_chengdu_error or "legacy bundle accepted",
        expected="production loader fails closed on the frozen v1 mismatch",
        evidence="china81.py::_load_time_profile",
    )
    bundles = [
        load_china81_bundle(
            REPO,
            "cn-jjj-50c-01-V2-LOCATIONS",
            runtime_parameter_authority=CORRECTED_AUTHORITY,
        ),
        load_china81_bundle(
            REPO,
            "cn-prd-50c-01-V2-LOCATIONS",
            runtime_parameter_authority=CORRECTED_AUTHORITY,
        ),
        load_china81_bundle(
            REPO,
            "cn-cy-50c-01-V2-LOCATIONS",
            runtime_parameter_authority=CORRECTED_AUTHORITY,
        ),
    ]
    bundle_by_city: dict[str, Any] = {}
    for bundle in bundles:
        for node in bundle.instance.nodes:
            if node.node_type.lower() in {"d", "f"}:
                bundle_by_city[str(node.city).lower()] = bundle

    positive_errors: list[str] = []
    cross_slot_errors: list[str] = []
    midnight_errors: list[str] = []
    service_fee_errors: list[str] = []

    for city, bundle in sorted(bundle_by_city.items()):
        station_id = city_facility(bundle, city, "f")
        depot_id = city_facility(bundle, city, "d")
        station_profile = time_profile_rows_for_node(
            bundle.instance,
            station_id,
            bundle.time_profile,
        )
        canonical_starts = [
            float(row["horizon_second_start"]) for row in station_profile
        ]
        canonical_slots = [int(row["hourly_calendar_row"]) for row in station_profile]
        if canonical_starts != [slot * 1800.0 for slot in range(48)]:
            positive_errors.append(f"{city}:noncanonical_starts")
        if canonical_slots != list(range(1, 49)):
            positive_errors.append(f"{city}:noncanonical_slots")

        # A small action remains inside each half-hour slot. This checks exact
        # boundary assignment at every slot start, including 06:00 and 22:00.
        for index, row in enumerate(station_profile):
            action = make_action(
                bundle,
                station_id,
                start_second=index * 1800.0,
                energy_kwh=0.1,
            )
            actual_cost = charging_action_electricity_cost(
                action,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
            )
            expected_cost = 0.1 * float(row["public_total_cny_per_kwh"])
            actual_emissions = charging_action_emissions_kg(
                action,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
            )
            expected_emissions = (
                0.1 * float(row["actual_gco2_per_kwh"]) / 1000.0
            )
            if not math.isclose(
                actual_cost, expected_cost, rel_tol=1e-11, abs_tol=1e-11
            ):
                positive_errors.append(
                    f"{city}:slot{index + 1}:cost:"
                    f"{actual_cost}!={expected_cost}"
                )
            if not math.isclose(
                actual_emissions,
                expected_emissions,
                rel_tol=1e-11,
                abs_tol=1e-11,
            ):
                positive_errors.append(
                    f"{city}:slot{index + 1}:carbon:"
                    f"{actual_emissions}!={expected_emissions}"
                )

        # Split one 1 kWh / 60 s public action equally across the first price
        # transition in the day and recompute both price and carbon manually.
        transition_index = next(
            index
            for index in range(1, 48)
            if float(
                station_profile[index - 1]["public_total_cny_per_kwh"]
            )
            != float(station_profile[index]["public_total_cny_per_kwh"])
        )
        transition = transition_index * 1800.0
        crossing_action = make_action(
            bundle,
            station_id,
            start_second=transition - 30.0,
            energy_kwh=1.0,
        )
        actual_cross_cost = charging_action_electricity_cost(
            crossing_action,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )
        expected_cross_cost = 0.5 * (
            float(
                station_profile[transition_index - 1][
                    "public_total_cny_per_kwh"
                ]
            )
            + float(
                station_profile[transition_index][
                    "public_total_cny_per_kwh"
                ]
            )
        )
        actual_cross_carbon = charging_action_emissions_kg(
            crossing_action,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )
        expected_cross_carbon = (
            0.5
            * (
                float(
                    station_profile[transition_index - 1][
                        "actual_gco2_per_kwh"
                    ]
                )
                + float(
                    station_profile[transition_index][
                        "actual_gco2_per_kwh"
                    ]
                )
            )
            / 1000.0
        )
        if not math.isclose(
            actual_cross_cost,
            expected_cross_cost,
            rel_tol=1e-11,
            abs_tol=1e-11,
        ):
            cross_slot_errors.append(f"{city}:price")
        if not math.isclose(
            actual_cross_carbon,
            expected_cross_carbon,
            rel_tol=1e-11,
            abs_tol=1e-11,
        ):
            cross_slot_errors.append(f"{city}:carbon")

        midnight_action = make_action(
            bundle,
            station_id,
            start_second=86_370.0,
            energy_kwh=1.0,
        )
        actual_midnight_cost = charging_action_electricity_cost(
            midnight_action,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )
        expected_midnight_cost = 0.5 * (
            float(station_profile[47]["public_total_cny_per_kwh"])
            + float(station_profile[0]["public_total_cny_per_kwh"])
        )
        actual_midnight_carbon = charging_action_emissions_kg(
            midnight_action,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )
        expected_midnight_carbon = (
            0.5
            * (
                float(station_profile[47]["actual_gco2_per_kwh"])
                + float(station_profile[0]["actual_gco2_per_kwh"])
            )
            / 1000.0
        )
        if not math.isclose(
            actual_midnight_cost,
            expected_midnight_cost,
            rel_tol=1e-11,
            abs_tol=1e-11,
        ):
            midnight_errors.append(f"{city}:price")
        if not math.isclose(
            actual_midnight_carbon,
            expected_midnight_carbon,
            rel_tol=1e-11,
            abs_tol=1e-11,
        ):
            midnight_errors.append(f"{city}:carbon")

        station_action = make_action(
            bundle,
            station_id,
            start_second=21_600.0,
            energy_kwh=0.1,
        )
        depot_action = make_action(
            bundle,
            depot_id,
            start_second=21_600.0,
            energy_kwh=0.1,
        )
        station_cost = charging_action_electricity_cost(
            station_action,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )
        depot_cost = charging_action_electricity_cost(
            depot_action,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )
        if not math.isclose(
            station_cost - depot_cost,
            0.1 * 0.4,
            rel_tol=1e-11,
            abs_tol=1e-11,
        ):
            service_fee_errors.append(
                f"{city}:{station_cost - depot_cost}"
            )

    add(
        checks,
        check_id="A4R-01",
        severity="P0",
        status="PASS" if not positive_errors else "FAIL",
        subject="48-slot city-specific exact-boundary price/carbon readback",
        observed=f"errors={len(positive_errors)}",
        expected="9 cities x 48 slots match independent one-slot arithmetic",
        evidence="production China81 loader and cost.py functions",
    )
    add(
        checks,
        check_id="A4R-02",
        severity="P0",
        status="PASS" if not cross_slot_errors else "FAIL",
        subject="charging action crossing a TOU/carbon boundary",
        observed=f"errors={cross_slot_errors}",
        expected="energy-weighted settlement closes across both slots",
        evidence="one 1 kWh action per city, starting 30 seconds before transition",
    )
    add(
        checks,
        check_id="A4R-03",
        severity="P0",
        status="PASS" if not midnight_errors else "FAIL",
        subject="charging action crossing 24:00",
        observed=f"errors={midnight_errors}",
        expected="23:59:30--00:00:30 splits exactly over slots 48 and 1",
        evidence="one 1 kWh cyclic action per city",
    )
    add(
        checks,
        check_id="A4R-04",
        severity="P0",
        status="PASS" if not service_fee_errors else "FAIL",
        subject="depot/public price-field selection",
        observed=f"errors={service_fee_errors}",
        expected="same-city public minus depot cost equals 0.4 CNY/kWh proxy",
        evidence="one 0.1 kWh depot/public pair per city at 06:00",
    )

    reference_bundle = bundle_by_city["shenzhen"]
    station_id = city_facility(reference_bundle, "shenzhen", "f")
    action = make_action(
        reference_bundle,
        station_id,
        start_second=36_000.0,
        energy_kwh=0.1,
    )

    raw_calendar_path = (
        REPO
        / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718/"
        "tariff_carbon_hourly_calendar.csv"
    )
    with raw_calendar_path.open(
        newline="", encoding="utf-8-sig"
    ) as handle:
        raw_calendar = list(csv.DictReader(handle))
    raw_fields = list(raw_calendar[0])

    def formal_loader_accepts(rows: list[dict[str, str]]) -> bool:
        with tempfile.TemporaryDirectory(prefix="resetp-a4r-") as temp:
            path = Path(temp) / "calendar.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=raw_fields)
                writer.writeheader()
                writer.writerows(rows)
            try:
                _load_time_profile(
                    path,
                    cities={"shenzhen"},
                    date="2025-02-12",
                )
            except (KeyError, TypeError, ValueError):
                return False
        return True

    malformed_missing_price = [dict(row) for row in raw_calendar]
    for row in malformed_missing_price:
        if (
            row["city"] == "shenzhen"
            and row["date"] == "2025-02-12"
            and row["hourly_calendar_row"] == "21"
        ):
            row["public_total_cny_per_kwh"] = ""
            break
    missing_price_rejected = not formal_loader_accepts(
        malformed_missing_price
    )
    add(
        checks,
        check_id="A4R-FI-01",
        severity="P0",
        status="PASS" if missing_price_rejected else "FAIL",
        subject="fault injection: one missing time-varying price field",
        observed=(
            "rejected"
            if missing_price_rejected
            else "silently accepted through mean-price fallback"
        ),
        expected="formal China81 settlement fails closed",
        evidence="china81.py::_load_time_profile on a temporary malformed calendar",
    )

    cityless_profile = [dict(row) for row in raw_calendar]
    for row in cityless_profile:
        if (
            row["city"] == "shenzhen"
            and row["date"] == "2025-02-12"
            and row["hourly_calendar_row"] == "21"
        ):
            row["city"] = ""
            break
    cityless_rejected = not formal_loader_accepts(cityless_profile)
    add(
        checks,
        check_id="A4R-FI-02",
        severity="P0",
        status="PASS" if cityless_rejected else "FAIL",
        subject="fault injection: city labels removed from formal profile",
        observed=(
            "rejected"
            if cityless_rejected
            else "silently accepted as a historical shared profile"
        ),
        expected="formal China81 profile cannot downgrade to shared-profile mode",
        evidence="china81.py::_load_time_profile on a temporary malformed calendar",
    )

    shifted_profile = [dict(row) for row in raw_calendar]
    for row in shifted_profile:
        if (
            row["city"] == "shenzhen"
            and row["date"] == "2025-02-12"
            and row["hourly_calendar_row"] == "21"
        ):
            row["minute_of_day"] = "610"
            break
    shifted_rejected = not formal_loader_accepts(shifted_profile)
    add(
        checks,
        check_id="A4R-FI-03",
        severity="P0",
        status="PASS" if shifted_rejected else "FAIL",
        subject="fault injection: slot id and local-time start disagree",
        observed=(
            "rejected"
            if shifted_rejected
            else "accepted without canonical-grid validation"
        ),
        expected="hourly_calendar_row s starts at exactly (s-1)*1800 seconds",
        evidence="china81.py::_load_time_profile; cost.py profile lookup",
    )

    low_level_profile = [
        dict(row) for row in reference_bundle.time_profile
    ]
    for row in low_level_profile:
        if row["city"] == "shenzhen":
            row.pop("public_total_cny_per_kwh", None)
            break
    low_level_rejected = False
    try:
        charging_action_electricity_cost(
            action,
            reference_bundle.instance,
            low_level_profile,
            reference_bundle.prices,
        )
    except (KeyError, ValueError):
        low_level_rejected = True
    add(
        checks,
        check_id="A4R-HARD-01",
        severity="P2",
        status="PASS" if low_level_rejected else "FAIL",
        subject="hardening: low-level settlement receives partial price rows",
        observed=(
            "rejected"
            if low_level_rejected
            else "mean-price compatibility fallback used"
        ),
        expected=(
            "formal caller must validate first; preferably expose an explicit "
            "strict mode instead of silently using the historical fallback"
        ),
        evidence="cost.py::charging_action_electricity_cost",
    )

    missing_date_rejected = False
    try:
        load_china81_bundle(
            REPO,
            "cn-prd-50c-01-V2-LOCATIONS",
            date="1900-01-01",
        )
    except ValueError:
        missing_date_rejected = True
    add(
        checks,
        check_id="A4R-FI-04",
        severity="P0",
        status="PASS" if missing_date_rejected else "FAIL",
        subject="fault injection: requested date absent from calendar",
        observed="rejected" if missing_date_rejected else "accepted",
        expected="loader fails closed",
        evidence="china81.py::_load_time_profile",
    )

    statuses: dict[str, int] = {}
    for check in checks:
        statuses[check.status] = statuses.get(check.status, 0) + 1
    with (OUT / "runtime_boundary_checks.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(asdict(checks[0]))
        )
        writer.writeheader()
        writer.writerows(asdict(check) for check in checks)
    payload = {
        "schema": "resetp.pre-e3-runtime-boundary-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": str(SCRIPT.relative_to(REPO)),
        "script_sha256": sha256(SCRIPT),
        "search_evaluations": 0,
        "formal_search_allowed": False,
        "checks": len(checks),
        "statuses": statuses,
        "verdict": (
            "PASS_RUNTIME_BOUNDARIES"
            if statuses.get("FAIL", 0) == 0
            else "HOLD_RUNTIME_FAULT_INJECTIONS_ACCEPTED"
        ),
        "results": [asdict(check) for check in checks],
    }
    (OUT / "runtime_boundary_findings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if statuses.get("FAIL", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
