#!/usr/bin/env python3
"""Frozen physical and tariff overlay for the E5 fast-charge probe."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for path in (REPO / "solver/src",):
    if str(path) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(path))

from setp_solver.charging_curve import ChargingCurveSpec, L100_CONTROL
from setp_solver.china81 import China81Bundle, load_china81_bundle

TASK_ID = "E5-FASTCHARGE-PROBE-20260731"
OUT = REPO / "baselines/china_e3_e7/e5_fastcharge_20260731"
PREREG = OUT / "pre_registration.json"
RUNNER = REPO / "baselines/china_e3_e7/run_e5_fastcharge_20260731.py"
CHECKER = REPO / "baselines/china_e3_e7/check_e5_fastcharge_20260731.py"

FAST_CURVE = ChargingCurveSpec(
    "M17_FAST_SHAPE_SCALED_120KW_PWL",
    (0.0, 0.85, 0.95, 1.0),
    (
        43.87096774193549 / 44.0,
        20.0 / 44.0,
        (20.0 / 3.0) / 44.0,
    ),
)
ARMS = (L100_CONTROL.curve_id, FAST_CURVE.curve_id)
DEPOT_POWER_KW = 120.0
PUBLIC_POWER_KW = 60.0
TAPER_SOC = 0.85
BUDGET_CAP = 400
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

INSTANCE_SPECS = (
    {
        "instance_id": "cn-prd-50c-01-V2-LOCATIONS",
        "sample_role": "MAIN_EXHIBIT",
        "seeds": tuple(range(1, 11)),
    },
    {
        "instance_id": "cn-prd-100c-02-V2-LOCATIONS",
        "sample_role": "ROBUSTNESS",
        "seeds": tuple(range(1, 11)),
    },
)

TWO_PART_DEPOT_ENERGY_CNY_PER_KWH: dict[str, dict[str, float]] = {
    "guangzhou": {
        "sharp_peak": 1.49606875,
        "peak": 1.20236875,
        "flat": 0.71866875,
        "valley": 0.29026875,
    },
    "shenzhen": {
        "sharp_peak": 1.43716875,
        "peak": 1.15526875,
        "flat": 0.75776875,
        "valley": 0.25716875,
    },
}


def curve_spec(arm: str) -> ChargingCurveSpec:
    if arm == L100_CONTROL.curve_id:
        return L100_CONTROL
    if arm == FAST_CURVE.curve_id:
        return FAST_CURVE
    raise ValueError(f"unknown E5 fast-charge arm: {arm}")


def apply_fastcharge_overlay(
    bundle: China81Bundle,
    arm: str,
) -> China81Bundle:
    """Return the frozen power, curve, and two-part depot-tariff scenario."""

    spec = curve_spec(arm)
    profile: list[dict[str, Any]] = []
    for original in bundle.time_profile:
        row = dict(original)
        city = str(row["city"]).strip().lower()
        period = str(row["tariff_period"]).strip().lower()
        if city not in TWO_PART_DEPOT_ENERGY_CNY_PER_KWH:
            raise ValueError(f"fast-charge tariff has no city row: {city}")
        tariff = TWO_PART_DEPOT_ENERGY_CNY_PER_KWH[city]
        if period not in tariff:
            raise ValueError(
                f"fast-charge tariff has no {city}/{period} period"
            )
        row["depot_energy_cny_per_kwh"] = float(tariff[period])
        row["tariff_row_class"] = (
            "E5_FASTCHARGE_TWO_PART_OR_EV_FACILITY_SCENARIO_ROW"
        )
        row["e5_fastcharge_tariff_overlay"] = True
        profile.append(row)
    depot_mean = sum(
        float(row["depot_energy_cny_per_kwh"]) for row in profile
    ) / len(profile)
    prices = replace(
        bundle.prices,
        depot_electricity_price=depot_mean,
        depot_charge_power_kw=DEPOT_POWER_KW,
        charging_curve_id=spec.curve_id,
        charging_soc_breakpoints=spec.soc_breakpoints,
        charging_relative_powers=spec.relative_powers,
    )
    return replace(bundle, prices=prices, time_profile=profile)


def load_fastcharge_bundle(instance_id: str, arm: str) -> China81Bundle:
    return apply_fastcharge_overlay(
        load_china81_bundle(REPO, instance_id),
        arm,
    )

