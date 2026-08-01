from __future__ import annotations

import math

from setp_solver.charging_curve import curve_from_parameters
from setp_solver.china81 import load_china81_bundle

from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.run_montoya_fs_approximations import (
    APPROXIMATIONS,
    FS_PUBLIC_SOC_CAP,
    L1_POWER_KW,
    L2_POWER_KW,
    M17_POINTS_H_KWH,
    _bundle_for,
    _public_station_cap_kwh,
)


def test_montoya_slopes_are_derived_from_the_registered_points() -> None:
    assert M17_POINTS_H_KWH == (
        (0.0, 0.0),
        (0.62, 13.6),
        (0.77, 15.2),
        (1.01, 16.0),
    )
    assert math.isclose(L1_POWER_KW, 13.6 / 0.62, rel_tol=0.0, abs_tol=1e-15)
    assert math.isclose(L2_POWER_KW, 16.0 / 1.01, rel_tol=0.0, abs_tol=1e-15)


def test_all_four_montoya_approximations_are_executed() -> None:
    assert tuple(APPROXIMATIONS) == ("FS", "L1", "L2", "PL")
    assert FS_PUBLIC_SOC_CAP == 0.85


def test_fs_public_cap_scales_from_the_published_16_kwh_breakpoint() -> None:
    assert math.isclose(_public_station_cap_kwh(16.0, "FS"), 13.6)
    assert math.isclose(_public_station_cap_kwh(20.0, "FS"), 17.0)
    assert math.isclose(_public_station_cap_kwh(32.0, "FS"), 27.2)
    assert _public_station_cap_kwh(20.0, "L1") == 20.0


def test_l2_and_pl_share_full_charge_time_but_not_intermediate_shape() -> None:
    repo = __import__(
        "baselines.china_e3_e7.e5_enroute_nonlinear_20260801.run_montoya_fs_approximations",
        fromlist=["REPO"],
    ).REPO
    base = load_china81_bundle(repo, "cn-prd-50c-01-V2-LOCATIONS")
    l2 = _bundle_for(base, capacity_kwh=16.0, approximation="L2")
    pl = _bundle_for(base, capacity_kwh=16.0, approximation="PL")
    l2_curve = curve_from_parameters(
        l2.prices, capacity_kwh=16.0, reference_power_kw=22.0
    )
    pl_curve = curve_from_parameters(
        pl.prices, capacity_kwh=16.0, reference_power_kw=22.0
    )
    assert math.isclose(l2_curve.duration_seconds(0.0, 16.0), 1.01 * 3600.0)
    assert math.isclose(pl_curve.duration_seconds(0.0, 16.0), 1.01 * 3600.0)
    assert l2_curve.duration_seconds(0.0, 13.6) > pl_curve.duration_seconds(0.0, 13.6)


def test_overlay_preserves_full_departure_and_nominal_capacity() -> None:
    repo = __import__(
        "baselines.china_e3_e7.e5_enroute_nonlinear_20260801.run_montoya_fs_approximations",
        fromlist=["REPO"],
    ).REPO
    base = load_china81_bundle(repo, "cn-prd-50c-01-V2-LOCATIONS")
    for approximation in APPROXIMATIONS:
        bundle = _bundle_for(base, capacity_kwh=16.0, approximation=approximation)
        assert bundle.prices.B_battery_kwh == 16.0
        assert bundle.prices.initial_ev_battery_kwh == 16.0
        assert bundle.instance.battery_capacity_kwh(fallback=-1.0) == 16.0
        assert bundle.prices.charging_curve_id == APPROXIMATIONS[approximation].curve_id


def test_fs_overlay_keeps_full_departure_and_first_segment_station_cap() -> None:
    repo = __import__(
        "baselines.china_e3_e7.e5_enroute_nonlinear_20260801.run_montoya_fs_approximations",
        fromlist=["REPO"],
    ).REPO
    base = load_china81_bundle(repo, "cn-prd-50c-01-V2-LOCATIONS")
    bundle = _bundle_for(base, capacity_kwh=16.0, approximation="FS")
    assert bundle.prices.initial_ev_battery_kwh == 16.0
    assert bundle.instance.battery_capacity_kwh(fallback=-1.0) == 16.0
    assert _public_station_cap_kwh(16.0, "FS") == 13.6
