"""``--public-station-power-kw``：公共站参考功率开关（2026-09-08 尝试性）。

要测的两件事：

1. **不给开关时什么都不发生。** 位级不变性是结构性的——``main()`` 里的
   ``if args.public_station_power_kw is not None:`` 在不给值时一行都不执行，
   所以这里只钉住"算例自带口径"这个前提：97 个公共站与 2 个车场都是 60 kW，
   ``charger_scenario_by_node`` 同值，``prices`` 的公共站曲线三元组就是
   ``M17_FAST_SHAPE_SCALED_60KW_PWL``。前提一旦被改，这条测试先响。
2. **给 120 时只有站功率动。** 97 个站的 ``charge_power_kw`` 与台账都变成
   120，两个车场仍是 60，``prices`` 一个字段都不动（曲线**形状**共用，
   只有缩放用的参考功率换了），站曲线的分段功率整体翻倍、充满时间减半。

曲线 id 仍写着 ``M17_FAST_SHAPE_SCALED_60KW_PWL``：名字里的 60KW 指形状的
出处（Montoya 等 2017 快充形状按 44→60 kW 归一化），不是本轮生效的功率。
``cost.py`` 的证书校验按 id 比对，所以 id 必须保持不变。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    _build_context,
    _with_public_station_power,
)
from setp_solver.charging_curve import (  # noqa: E402
    M17_FAST_SHAPE_SCALED_60KW_PWL,
    spec_for_charging_node,
)
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS  # noqa: E402


REPO = Path(__file__).resolve().parents[2]
INSTANCE_ID = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
INSTANCE_STATION_POWER_KW = 60.0
INSTANCE_DEPOT_POWER_KW = 60.0
EXPECTED_STATIONS = 97
EXPECTED_DEPOTS = 2


@pytest.fixture(scope="module")
def bundle():
    built, _initial, _neutral, _context = _build_context(
        REPO,
        INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    return built


def _by_type(bundle, node_type: str):
    return [
        node
        for node in bundle.instance.nodes
        if node.node_type.lower() == node_type
    ]


def _station_curve(bundle, node):
    spec = spec_for_charging_node(bundle.prices, node_type="f")
    return spec.scale(
        capacity_kwh=bundle.instance.battery_capacity_kwh(fallback=0.0),
        reference_power_kw=float(node.charge_power_kw),
    )


def test_default_bundle_keeps_the_instance_60_kw_station_scenario(bundle):
    stations = _by_type(bundle, "f")
    depots = _by_type(bundle, "d")
    assert len(stations) == EXPECTED_STATIONS
    assert len(depots) == EXPECTED_DEPOTS
    assert {node.charge_power_kw for node in stations} == {
        INSTANCE_STATION_POWER_KW
    }
    assert {node.charge_power_kw for node in depots} == {
        INSTANCE_DEPOT_POWER_KW
    }
    ledger = bundle.charger_scenario_by_node
    assert {
        float(ledger[node.node_id]["charge_power_kw"]) for node in stations
    } == {INSTANCE_STATION_POWER_KW}
    assert (
        bundle.prices.public_charging_curve_id
        == M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id
    )
    assert (
        bundle.prices.public_charging_soc_breakpoints
        == M17_FAST_SHAPE_SCALED_60KW_PWL.soc_breakpoints
    )
    assert (
        bundle.prices.public_charging_relative_powers
        == M17_FAST_SHAPE_SCALED_60KW_PWL.relative_powers
    )
    assert bundle.prices.depot_charge_power_kw == INSTANCE_DEPOT_POWER_KW


def test_switch_moves_every_station_and_nothing_else(bundle):
    scaled = _with_public_station_power(bundle, 120.0)

    stations = _by_type(scaled, "f")
    depots = _by_type(scaled, "d")
    assert len(stations) == EXPECTED_STATIONS
    assert {node.charge_power_kw for node in stations} == {120.0}
    assert {node.charge_power_kw for node in depots} == {
        INSTANCE_DEPOT_POWER_KW
    }
    ledger = scaled.charger_scenario_by_node
    assert {
        float(ledger[node.node_id]["charge_power_kw"]) for node in stations
    } == {120.0}
    assert {
        float(ledger[node.node_id]["charge_power_kw"]) for node in depots
    } == {INSTANCE_DEPOT_POWER_KW}
    # 枪数是另一件事，本开关不碰。
    assert {node.station_chargers for node in stations} == {
        node.station_chargers for node in _by_type(bundle, "f")
    }

    # prices 一个字段都没动：曲线形状、曲线 id、车场功率、站点电价。
    assert scaled.prices == bundle.prices
    assert (
        scaled.prices.public_charging_curve_id
        == M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id
    )
    assert (
        scaled.prices.station_electricity_price
        == bundle.prices.station_electricity_price
    )

    # 客户与车场节点原样传递，节点顺序与数量不变。
    assert [node.node_id for node in scaled.instance.nodes] == [
        node.node_id for node in bundle.instance.nodes
    ]
    assert all(
        new is old
        for new, old in zip(scaled.instance.nodes, bundle.instance.nodes)
        if old.node_type.lower() != "f"
    )

    # 原 bundle 不被就地改写。
    assert {node.charge_power_kw for node in _by_type(bundle, "f")} == {
        INSTANCE_STATION_POWER_KW
    }


def test_station_curve_scales_but_keeps_its_shape(bundle):
    scaled = _with_public_station_power(bundle, 120.0)
    base_curve = _station_curve(bundle, _by_type(bundle, "f")[0])
    fast_curve = _station_curve(scaled, _by_type(scaled, "f")[0])

    assert fast_curve.curve_id == base_curve.curve_id
    assert fast_curve.energy_breakpoints_kwh == base_curve.energy_breakpoints_kwh
    for fast, base in zip(
        fast_curve.segment_powers_kw,
        base_curve.segment_powers_kw,
        strict=True,
    ):
        assert fast == pytest.approx(2.0 * base, rel=1e-12)
    for fast, base in zip(
        fast_curve.cumulative_seconds,
        base_curve.cumulative_seconds,
        strict=True,
    ):
        assert fast == pytest.approx(0.5 * base, rel=1e-12)


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_switch_rejects_nonpositive_or_nonfinite_power(bundle, value):
    with pytest.raises(ValueError):
        _with_public_station_power(bundle, value)
