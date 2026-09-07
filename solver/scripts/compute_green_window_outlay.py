#!/usr/bin/env python3
"""核算「绿色充电窗口补贴」这根杠杆的财政支出（表11 新增行）。

杠杆本身：北京现行分时电价的时段结构一个字不动，只把 **12:00--15:00** 六个
半小时槽的电度价按谷价（0.56328575 元/kWh）计，差价由财政补贴。反事实日历由
``solver/scripts/build_counterfactual_tariff_calendar.py`` 的 ``midday_discount``
布局生成，见 ``data/ChinaInstances/china81_cf_calendar_midday_discount_v1_20260904/README.md``。

## 电量怎么分进半小时槽

**不是**按时长均摊，也**不是**图 3 生成器 ``generate_carbon_charging_figure.py``
里 ``_sessions_by_slot`` 那种「整场电量记在它开始的那个槽」。本脚本直接调用
``setp_solver.cost.charging_action_slot_breakdown(..., n_slots=48, cyclic=True)``
——那是求解器**自己结算电费时用的同一个函数**（见 ``cost.charging_action_electricity_cost``
第 1385--1409 行），它按充电动作的分段线性充电曲线（``slot_energy_kwh``）
把电量精确切进各个半小时槽，充电功率非匀速这件事已经在里面了。
因此本脚本报的窗口内电量是**曲线精确值**，没有均摊近似。

## 三条对账（任何一条不过就退出）

1. **本币对账**：把每个解的充电动作在**它自己求解时那份日历**下逐槽计价，
   总额必须与 ``best_solution.json`` 的 ``evaluation.breakdown.cost_elec``
   相符（容差 1e-9）。这条抓得住日历接错、槽索引偏一位、节点类型判错。
2. **两种算法对账**：财政支出既按「原日历电费 − 补贴日历电费」算一遍，
   又按「Σ 窗口内逐槽电量 × 该槽差价」算一遍，两者必须相符（容差 1e-9）。
3. **窗口外零差价**：窗口外任何一个槽的两份日历价格必须逐位相同（否则退出）。

## 基准列是事后算的

对 ``ablation_formal_10x_v5_20260904``（北京原日历、当时没有补贴）也算一遍
「若当时有此补贴、按其**实际**充电时刻能领多少」。那批解是在**没有**补贴的
价格信号下搜出来的，所以这一列只是参考：它回答「补贴不改变行为时能领多少」，
不是那批解在补贴下会变成什么样。报告里必须标明是事后算。

用法（仓库根）::

    export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src:solver/scripts'
    .public-hgs-venv/bin/python3 solver/scripts/compute_green_window_outlay.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[2]
INSTANCE_ID = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
SLOTS_PER_DAY = 48
# 12:00-15:00：``ChargingSlot.slot_index`` 是 **0 起**的，故窗口是 24..29；
# 日历 CSV 的 ``hourly_calendar_row`` 是 **1 起**的，同一个窗口在那边写作 25..30。
WINDOW_SLOTS = tuple(range(24, 30))
DEFAULT_SOURCE_AUTHORITY = (
    "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
)
DEFAULT_DISCOUNT_AUTHORITY = (
    "data/ChinaInstances/china81_cf_calendar_midday_discount_v1_20260904"
)
DEFAULT_LEVER_DIR = "solver/reports/lever_green_window_20260904/MTC-HGS"
DEFAULT_BASELINE_DIR = "solver/reports/ablation_formal_10x_v5_20260904/MTC-HGS"
TOLERANCE = 1e-9


def _load_runtime(repo: Path):
    """按 build_charge_timing_comparison.py 的同一套办法加载私有 runner。"""

    path = repo / "solver/scripts/run_problem_hgs_private_technical.py"
    spec = importlib.util.spec_from_file_location(
        "_green_window_runtime", path
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise SystemExit(f"cannot load the private runner from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _price_field(instance, station_id: str) -> str:
    node = instance.node_lookup.get(station_id)
    if node is None:
        raise SystemExit(f"charging action at unknown node {station_id!r}")
    return (
        "depot_energy_cny_per_kwh"
        if node.node_type == "d"
        else "public_total_cny_per_kwh"
    )


def _slot_price(cost_mod, node_profile, slot_index: int, field: str) -> float:
    return float(
        cost_mod.carbon_profile_row_for_slot(node_profile, slot_index)[field]
    )


def _run_dirs(root: Path) -> tuple[list[Path], list[Path]]:
    """返回（有 best_solution.json 的 run 目录, 有目录但没有解的 run 目录）。

    第二项必须被调用方报出来：一个跑挂了却只是让 n 少一，均值会在没人察觉的
    情况下变成两跑平均——这正是「失败停在原地如实报」要防的。
    """

    complete: list[Path] = []
    incomplete: list[Path] = []
    for path in sorted(root.glob("run_*")):
        if not path.is_dir():
            continue
        if (path / "best_solution.json").is_file():
            complete.append(path)
        else:
            incomplete.append(path)
    return complete, incomplete


def analyse_run(
    cost_mod,
    solution_from_dict,
    payload: dict[str, Any],
    *,
    own_bundle,
    other_bundle,
    own_is_discount: bool,
) -> dict[str, Any]:
    """核一个解：本币对账、窗口内电量、财政支出（两种算法互核）。"""

    solution = solution_from_dict(payload["evaluation"]["prepared_solution"])
    breakdown = payload["evaluation"]["breakdown"]

    own_cost = 0.0
    other_cost = 0.0
    window_kwh = 0.0
    outlay_by_slot = 0.0
    per_slot_kwh = {slot: 0.0 for slot in WINDOW_SLOTS}
    total_split_kwh = 0.0

    for action in solution.charging_actions:
        field = _price_field(own_bundle.instance, action.station_id)
        if field != _price_field(other_bundle.instance, action.station_id):
            raise SystemExit("the two bundles disagree on a node's price field")
        own_cost += cost_mod.charging_action_electricity_cost(
            action, own_bundle.instance, own_bundle.time_profile, own_bundle.prices
        )
        other_cost += cost_mod.charging_action_electricity_cost(
            action,
            other_bundle.instance,
            other_bundle.time_profile,
            other_bundle.prices,
        )
        slots = cost_mod.charging_action_slot_breakdown(
            action,
            own_bundle.instance,
            own_bundle.prices,
            n_slots=SLOTS_PER_DAY,
            cyclic=True,
        )
        own_rows = cost_mod.time_profile_rows_for_node(
            own_bundle.instance, action.station_id, own_bundle.time_profile
        )
        other_rows = cost_mod.time_profile_rows_for_node(
            other_bundle.instance, action.station_id, other_bundle.time_profile
        )
        for slot in slots:
            total_split_kwh += float(slot.y_skt_kwh)
            own_price = _slot_price(cost_mod, own_rows, slot.slot_index, field)
            other_price = _slot_price(cost_mod, other_rows, slot.slot_index, field)
            if slot.slot_index not in WINDOW_SLOTS:
                if own_price != other_price:
                    raise SystemExit(
                        f"slot {slot.slot_index} is outside 12:00-15:00 but the "
                        f"two calendars price it differently: "
                        f"{own_price!r} vs {other_price!r}"
                    )
                continue
            window_kwh += float(slot.y_skt_kwh)
            per_slot_kwh[slot.slot_index] += float(slot.y_skt_kwh)
            gap = (other_price - own_price) if own_is_discount else (own_price - other_price)
            if gap <= 0.0:
                raise SystemExit(
                    f"slot {slot.slot_index}: subsidy per kWh is not positive "
                    f"({gap!r})"
                )
            outlay_by_slot += float(slot.y_skt_kwh) * gap

    # 对账 1：本币电费必须与落盘的 cost_elec 相符。
    recorded_elec = float(breakdown["cost_elec"])
    if abs(own_cost - recorded_elec) > TOLERANCE:
        raise SystemExit(
            f"重算电费 {own_cost!r} 与落盘 cost_elec {recorded_elec!r} 不符"
        )
    # 逐槽切分的总电量必须等于 electricity_kwh。
    recorded_kwh = float(breakdown["electricity_kwh"])
    if abs(total_split_kwh - recorded_kwh) > 1e-7:
        raise SystemExit(
            f"逐槽电量之和 {total_split_kwh!r} 与 electricity_kwh {recorded_kwh!r} 不符"
        )
    # 对账 2：两种算法算出的财政支出必须相符。
    outlay_by_cost = (other_cost - own_cost) if own_is_discount else (own_cost - other_cost)
    if abs(outlay_by_cost - outlay_by_slot) > TOLERANCE:
        raise SystemExit(
            f"财政支出两种算法不符：日历差 {outlay_by_cost!r} vs 逐槽差价 {outlay_by_slot!r}"
        )

    return {
        "total_cost": float(breakdown["total_cost"]),
        "cost_elec": recorded_elec,
        "E_total": float(breakdown["E_total"]),
        "n_veh_cv": int(breakdown["n_veh_cv"]),
        "n_veh_ev": int(breakdown["n_veh_ev"]),
        "electricity_kwh": recorded_kwh,
        "window_kwh": window_kwh,
        "window_share": (window_kwh / recorded_kwh) if recorded_kwh else 0.0,
        "outlay_cny": outlay_by_cost,
        "outlay_cny_by_slot": outlay_by_slot,
        "per_slot_kwh": {str(k): v for k, v in per_slot_kwh.items()},
        "elec_cost_original_calendar": (
            other_cost if own_is_discount else own_cost
        ),
        "elec_cost_discount_calendar": (
            own_cost if own_is_discount else other_cost
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--lever-dir", type=Path, default=Path(DEFAULT_LEVER_DIR))
    parser.add_argument(
        "--baseline-dir", type=Path, default=Path(DEFAULT_BASELINE_DIR)
    )
    parser.add_argument(
        "--source-authority", type=Path, default=Path(DEFAULT_SOURCE_AUTHORITY)
    )
    parser.add_argument(
        "--discount-authority", type=Path, default=Path(DEFAULT_DISCOUNT_AUTHORITY)
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--readme", type=Path, default=None)
    parser.add_argument(
        "--expect-lever-runs",
        type=int,
        default=3,
        help="杠杆侧必须拿到几个可用的解；不足即退出（传 0 关掉这条闸）",
    )
    args = parser.parse_args(argv)

    repo = args.repo_root.resolve()
    runtime = _load_runtime(repo)
    from setp_solver import cost as cost_mod
    from setp_solver.search.metaheuristic_baselines import solution_from_dict

    fleet = runtime.FLEET_PARAMETER_CLASSES["endogenous"]
    original_bundle = runtime._build_context(
        repo,
        INSTANCE_ID,
        fleet_parameters=fleet,
        tariff_calendar_authority=args.source_authority,
    )[0]
    discount_bundle = runtime._build_context(
        repo,
        INSTANCE_ID,
        fleet_parameters=fleet,
        tariff_calendar_authority=args.discount_authority,
    )[0]

    report: dict[str, Any] = {
        "instance_id": INSTANCE_ID,
        "window": "12:00-15:00",
        "window_slot_index_0based": list(WINDOW_SLOTS),
        "source_authority": str(args.source_authority),
        "discount_authority": str(args.discount_authority),
        "energy_split_method": (
            "setp_solver.cost.charging_action_slot_breakdown"
            "(n_slots=48, cyclic=True) —— 与求解器结算电费同一函数，按充电曲线精确切分"
        ),
        "lever": {},
        "baseline_counterfactual": {},
    }

    for label, root, own_bundle, other_bundle, own_is_discount, key in (
        (
            "杠杆（补贴日历下重搜）",
            repo / args.lever_dir,
            discount_bundle,
            original_bundle,
            True,
            "lever",
        ),
        (
            "基准（原日历，事后算能领多少）",
            repo / args.baseline_dir,
            original_bundle,
            discount_bundle,
            False,
            "baseline_counterfactual",
        ),
    ):
        runs: dict[str, Any] = {}
        complete, incomplete = _run_dirs(root)
        if incomplete:
            print(
                f"[warn] {label}：以下 run 目录存在但没有 best_solution.json（失败或未跑完）："
                + ", ".join(path.name for path in incomplete)
            )
        for run_dir in complete:
            payload = json.loads(
                (run_dir / "best_solution.json").read_text(encoding="utf-8")
            )
            runs[run_dir.name] = analyse_run(
                cost_mod,
                solution_from_dict,
                payload,
                own_bundle=own_bundle,
                other_bundle=other_bundle,
                own_is_discount=own_is_discount,
            )
        if not runs:
            print(f"[warn] {label}：{root} 下没有可用的 best_solution.json")
        report[key] = {
            "label": label,
            "dir": str(root.relative_to(repo)),
            "n_runs": len(runs),
            "incomplete_runs": [path.name for path in incomplete],
            "runs": runs,
        }
        if runs:
            if len(runs) >= 2:
                import statistics

                report[key]["sd"] = {
                    field: statistics.stdev(
                        [item[field] for item in runs.values()]
                    )
                    for field in ("total_cost", "E_total", "window_kwh", "outlay_cny")
                }
            report[key]["mean"] = {
                field: sum(item[field] for item in runs.values()) / len(runs)
                for field in (
                    "total_cost",
                    "E_total",
                    "electricity_kwh",
                    "window_kwh",
                    "outlay_cny",
                )
            }
            best = min(runs.items(), key=lambda kv: kv[1]["total_cost"])
            report[key]["best_by_cost"] = {"run": best[0], **best[1]}

    if args.expect_lever_runs:
        got = report["lever"]["n_runs"]
        if got != int(args.expect_lever_runs):
            raise SystemExit(
                f"杠杆侧只拿到 {got} 个可用的解，期望 {args.expect_lever_runs} 个；"
                f"缺的 run 目录：{report['lever']['incomplete_runs']}。"
                "先把失败的跑查清楚，不要拿少一跑的均值出报告。"
            )

    # 逐槽电网碳强度（解释方向用）：便宜的窗口把负荷吸过来，排放动不动要看这一列。
    window_rows = []
    for slot in WINDOW_SLOTS:
        row = cost_mod.carbon_profile_row_for_slot(
            original_bundle.time_profile, slot
        )
        window_rows.append(
            {
                "slot_index_0based": slot,
                "clock": f"{slot // 2:02d}:{(slot % 2) * 30:02d}",
                "actual_gco2_per_kwh": float(row["actual_gco2_per_kwh"]),
            }
        )
    day_intensity = [
        float(
            cost_mod.carbon_profile_row_for_slot(
                original_bundle.time_profile, slot
            )["actual_gco2_per_kwh"]
        )
        for slot in range(SLOTS_PER_DAY)
    ]
    report["window_carbon_intensity"] = window_rows
    report["carbon_intensity_gco2_per_kwh"] = {
        "window_mean": sum(item["actual_gco2_per_kwh"] for item in window_rows)
        / len(window_rows),
        "day_mean": sum(day_intensity) / len(day_intensity),
        "day_min": min(day_intensity),
        "day_max": max(day_intensity),
    }

    # 财政每元补贴的减排量（kg/元），分母 0 或减排 <= 0 时写 "—"。
    lever = report["lever"]
    base = report["baseline_counterfactual"]
    ratio: Any = "—"
    if lever.get("mean") and base.get("mean"):
        saved = base["mean"]["E_total"] - lever["mean"]["E_total"]
        spend = lever["mean"]["outlay_cny"]
        ratio = (saved / spend) if (spend > 0.0 and saved > 0.0) else "—"
        report["emission_saved_kg_mean"] = saved
    report["kg_per_cny"] = ratio

    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    print(text)
    if args.out is not None:
        out = repo / args.out if not args.out.is_absolute() else args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"\nwritten -> {out}")
    if args.readme is not None:
        readme = repo / args.readme if not args.readme.is_absolute() else args.readme
        readme.parent.mkdir(parents=True, exist_ok=True)
        readme.write_text(_readme_text(repo, args, report), encoding="utf-8")
        print(f"written -> {readme}")
    return 0


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fmt(value: Any, digits: int = 4) -> str:
    if isinstance(value, str):
        return value
    return f"{float(value):.{digits}f}"


def _run_table(section: dict[str, Any]) -> str:
    lines = [
        "| 跑 | 总成本（元） | 排放 E_total（kg） | 车队 (燃油, 电动) | "
        "总充电量（kWh） | 窗口内电量（kWh） | 窗口占比 | 财政支出（元） |",
        "|---|---:|---:|:--:|---:|---:|---:|---:|",
    ]
    for name, item in section["runs"].items():
        lines.append(
            f"| {name} | {_fmt(item['total_cost'], 2)} | {_fmt(item['E_total'], 2)} | "
            f"({item['n_veh_cv']}, {item['n_veh_ev']}) | "
            f"{_fmt(item['electricity_kwh'], 2)} | {_fmt(item['window_kwh'], 2)} | "
            f"{_fmt(100.0 * item['window_share'], 1)}% | {_fmt(item['outlay_cny'], 2)} |"
        )
    mean = section["mean"]
    best = section["best_by_cost"]
    lines.append(
        f"| **均值 (n={section['n_runs']})** | **{_fmt(mean['total_cost'], 2)}** | "
        f"**{_fmt(mean['E_total'], 2)}** | — | {_fmt(mean['electricity_kwh'], 2)} | "
        f"{_fmt(mean['window_kwh'], 2)} | — | **{_fmt(mean['outlay_cny'], 2)}** |"
    )
    lines.append(
        f"| **最优（成本最小＝{best['run']}）** | **{_fmt(best['total_cost'], 2)}** | "
        f"**{_fmt(best['E_total'], 2)}** | ({best['n_veh_cv']}, {best['n_veh_ev']}) | "
        f"{_fmt(best['electricity_kwh'], 2)} | {_fmt(best['window_kwh'], 2)} | "
        f"{_fmt(100.0 * best['window_share'], 1)}% | {_fmt(best['outlay_cny'], 2)} |"
    )
    return "\n".join(lines)


def _readme_text(repo: Path, args, report: dict[str, Any]) -> str:
    calendar = repo / args.discount_authority / "tariff_carbon_hourly_calendar.csv"
    source = repo / args.source_authority / "tariff_carbon_hourly_calendar.csv"
    lever = report["lever"]
    base = report["baseline_counterfactual"]
    ratio = report["kg_per_cny"]
    ratio_text = "—" if isinstance(ratio, str) else f"{float(ratio):.4f} kg/元"
    if lever.get("mean") and base.get("mean"):
        delta_e = base["mean"]["E_total"] - lever["mean"]["E_total"]
        delta_c = base["mean"]["total_cost"] - lever["mean"]["total_cost"]
        compare = "\n".join(
            (
                f"| 排放均值 | {_fmt(base['mean']['E_total'], 2)} kg | "
                f"{_fmt(lever['mean']['E_total'], 2)} kg | {_fmt(-delta_e, 2)} kg |",
                f"| 总成本均值 | {_fmt(base['mean']['total_cost'], 2)} 元 | "
                f"{_fmt(lever['mean']['total_cost'], 2)} 元 | {_fmt(-delta_c, 2)} 元 |",
                f"| 最优（成本最小那一跑）总成本 | "
                f"{_fmt(base['best_by_cost']['total_cost'], 2)} 元 | "
                f"{_fmt(lever['best_by_cost']['total_cost'], 2)} 元 | "
                f"{_fmt(lever['best_by_cost']['total_cost'] - base['best_by_cost']['total_cost'], 2)} 元 |",
                f"| 最优那一跑的排放 | {_fmt(base['best_by_cost']['E_total'], 2)} kg | "
                f"{_fmt(lever['best_by_cost']['E_total'], 2)} kg | "
                f"{_fmt(lever['best_by_cost']['E_total'] - base['best_by_cost']['E_total'], 2)} kg |",
                f"| 窗口内充电量均值 | {_fmt(base['mean']['window_kwh'], 2)} kWh | "
                f"{_fmt(lever['mean']['window_kwh'], 2)} kWh | "
                f"{_fmt(lever['mean']['window_kwh'] - base['mean']['window_kwh'], 2)} kWh |",
                f"| 财政支出均值 | {_fmt(base['mean']['outlay_cny'], 2)} 元（事后算） | "
                f"{_fmt(lever['mean']['outlay_cny'], 2)} 元 | "
                f"{_fmt(lever['mean']['outlay_cny'] - base['mean']['outlay_cny'], 2)} 元 |",
            )
        )
        saved_line = (
            f"减排量（基准排放均值 {_fmt(base['mean']['E_total'], 4)} kg − 本杠杆排放均值 "
            f"{_fmt(lever['mean']['E_total'], 4)} kg）＝ **{_fmt(delta_e, 4)} kg**；"
            f"财政支出均值 ＝ **{_fmt(lever['mean']['outlay_cny'], 4)} 元**。"
        )
    else:
        compare = "| — | — | — | — |"
        saved_line = "杠杆侧还没有可用的解，无法比较。"

    lever_table = _run_table(lever) if lever.get("mean") else "（暂无）"
    base_table = _run_table(base) if base.get("mean") else "（暂无）"

    def _sd_line(section: dict[str, Any], name: str) -> str:
        sd = section.get("sd")
        if not sd:
            return f"- {name}：不足两跑，算不出标准差。"
        return (
            f"- {name}（n={section['n_runs']}）：总成本 sd {_fmt(sd['total_cost'], 2)} 元、"
            f"排放 sd {_fmt(sd['E_total'], 2)} kg、"
            f"窗口内电量 sd {_fmt(sd['window_kwh'], 2)} kWh、"
            f"财政支出 sd {_fmt(sd['outlay_cny'], 2)} 元。"
        )

    noise = "\n".join(
        (_sd_line(base, "基准"), _sd_line(lever, "本杠杆"))
    )
    intensity = report.get("carbon_intensity_gco2_per_kwh") or {}
    window_rows = report.get("window_carbon_intensity") or []
    intensity_table = "\n".join(
        f"| {item['clock']} | {_fmt(item['actual_gco2_per_kwh'], 2)} |"
        for item in window_rows
    )
    # 「窗口内电量是不是被补贴推上去的」——把两侧的窗口电量取值摊开看。
    def _window_values(section: dict[str, Any]) -> list[float]:
        return [item["window_kwh"] for item in section.get("runs", {}).values()]

    reading = ""
    if lever.get("mean") and base.get("mean"):
        lever_window = _window_values(lever)
        base_window = _window_values(base)
        top = max(base_window + lever_window)
        base_at_top = sum(1 for value in base_window if abs(value - top) < 1e-9)
        lever_at_top = sum(1 for value in lever_window if abs(value - top) < 1e-9)
        base_sd = base.get("sd", {})
        lever_fleets = {
            (item["n_veh_cv"], item["n_veh_ev"]) for item in lever["runs"].values()
        }
        base_fleets: dict[tuple[int, int], list[float]] = {}
        for item in base["runs"].values():
            key = (item["n_veh_cv"], item["n_veh_ev"])
            base_fleets.setdefault(key, []).append(item["window_kwh"])
        fleet_text = "；".join(
            f"{cv} 油 + {ev} 电 共 {len(values)} 跑，其中 "
            f"{sum(1 for value in values if abs(value - top) < 1e-9)} 跑顶到 "
            f"{_fmt(top, 2)} kWh"
            for (cv, ev), values in sorted(base_fleets.items())
        )
        reading = f"""
- **窗口内电量没有被补贴推高，它顶在同一个上限上。** 两侧出现过的最大窗口电量是
  {_fmt(top, 4)} kWh：本杠杆 {lever_at_top}/{lever['n_runs']} 跑就是这个数
  （逐跑一模一样，标准差 {_fmt(lever.get('sd', {}).get('window_kwh', 0.0), 4)}），
  而**没有补贴的基准里已经有 {base_at_top}/{base['n_runs']} 跑达到了同一个数**。
  也就是说这些电量本来就在 12:00–15:00 充，补贴没有把新的电量挪进来，
  只是替企业付了这部分电费——就这批解看，它更像一笔**转移支付**而不是行为改变。
- **窗口电量顶不顶得到上限，和车队里有几辆电动车走得更近。** 本杠杆三跑的车队都是
  {"、".join(f"{cv} 油 + {ev} 电" for cv, ev in sorted(lever_fleets))}；
  基准十跑按车队分：{fleet_text}。
  （这是逐跑事实，不是回归结论——十跑里还有一跑车队相同却没顶到上限。）
- **排放不降反升 {_fmt(lever['mean']['E_total'] - base['mean']['E_total'], 2)} kg，
  而且这个差落在噪声里。** 基准十跑排放的标准差是
  {_fmt(base_sd.get('E_total', 0.0), 2)} kg，两侧均值之差
  {_fmt(abs(base['mean']['E_total'] - lever['mean']['E_total']), 2)} kg 远小于它；
  总成本同理，基准标准差 {_fmt(base_sd.get('total_cost', 0.0), 2)} 元。
  这三跑**不足以**断言这根杠杆改变了排放，只够说「没看出减排」。
  加上窗口内碳强度本就是全天最低的一档（见上），负荷早就被择时策略吸到这里了，
  再用价格补一刀也没有多余的电量可挪。
- **企业省的钱（{_fmt(base['mean']['total_cost'] - lever['mean']['total_cost'], 2)} 元）
  与财政掏的钱（{_fmt(lever['mean']['outlay_cny'], 2)} 元）** 量级相当；
  差出来的部分落在总成本的种子抖动范围内，不能当成补贴带来的额外效率。
"""
    intensity_summary = (
        f"窗口内六个槽的电网碳强度均值 {_fmt(intensity.get('window_mean', 0.0), 2)} gCO2e/kWh，"
        f"全天 48 槽均值 {_fmt(intensity.get('day_mean', 0.0), 2)}，"
        f"全天区间 {_fmt(intensity.get('day_min', 0.0), 2)}--{_fmt(intensity.get('day_max', 0.0), 2)}。"
        if intensity
        else ""
    )

    return f"""# 绿色充电窗口补贴（表11 新增杠杆）· 2026-09-04

北京现行分时电价的时段结构**一个字不动**，只把 **12:00–15:00** 六个半小时槽的
电度价按谷价 0.56328575 元/kWh 计，差价由财政补贴。与「购车补贴」（电动车日固定
溢价 100→50→0）对照：同样是财政出钱，投在**充电时刻**上还是投在**购车**上减排更多。

## 一、怎么跑的

反事实日历（生成器 `solver/scripts/build_counterfactual_tariff_calendar.py` 的
`midday_discount` 布局）：

```
.public-hgs-venv/bin/python3 solver/scripts/build_counterfactual_tariff_calendar.py
```

- 日历目录：`{args.discount_authority}`
- `tariff_carbon_hourly_calendar.csv` sha256：`{_sha256(calendar)}`
- 源日历 `{args.source_authority}` sha256：`{_sha256(source)}`
- 与源日历相比只有 168 行不同（北京 28 个日期 × 窗口内 6 个槽），
  其余 1176 行北京行与全部非北京行逐字节相同。

三跑（MTC-HGS，碳价 0.2，全机制；COMMON 参数与
`run_ideal_construction_one.sh` 的 MTC-HGS 臂逐条相同）：

```
zsh solver/scripts/run_lever_green_window_one.sh \\
    solver/reports/lever_green_window_20260904 01   # 02 / 03 同
```

财政支出核算：

```
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src:solver/scripts'
.public-hgs-venv/bin/python3 solver/scripts/compute_green_window_outlay.py \\
    --out solver/reports/lever_green_window_20260904/outlay.json \\
    --readme solver/reports/lever_green_window_20260904/README.md
```

**电量分槽用的是求解器自己结算电费的那个函数**
（`setp_solver.cost.charging_action_slot_breakdown(n_slots=48, cyclic=True)`），
它按分段线性充电曲线精确切分，充电功率非匀速这件事已经在里面了，**不是按时间均摊**。
核算脚本有三条对账（任一不过即退出）：本币电费 = 落盘 `cost_elec`（容差 1e-9）、
财政支出两种算法互核（日历差 vs 逐槽差价，容差 1e-9）、窗口外两份日历价格逐位相同。

## 二、三跑三大件

{lever_table}

## 三、与基准并排（基准＝`ablation_formal_10x_v5_20260904` 的 MTC-HGS 十次，北京原日历）

| 量 | 基准（n={base.get('n_runs', 0)}） | 本杠杆（n={lever.get('n_runs', 0)}） | 差（杠杆 − 基准） |
|---|---:|---:|---:|
{compare}

基准侧那一列财政支出是「若当时有此补贴、按其**实际**充电时刻能领多少」，
**事后算**：那批解是在没有补贴的价格信号下搜出来的，只作参考。逐跑：

{base_table}

## 四、财政每元补贴的减排量

{saved_line}

**{ratio_text}**

（减排 ≤ 0 或财政支出为 0 时写「—」。）

### 这个比值的噪声底

{noise}

基准十跑的排放本身就有约 8 kg 的抖动，本杠杆只有三跑，
**两侧均值之差在 10 kg 量级以内时分不出是杠杆效应还是种子抖动**，
上面那个 kg/元 的相对误差因此很大，只能当量级看。

### 方向为什么是这个方向：窗口内的电网碳强度

排放不会因为电价变便宜而直接变化，只能通过**行为改变**变化：
充电时刻策略是 `cost_plus_carbon`，把 12:00–15:00 变便宜就会把负荷往这里拉，
于是排放怎么动，取决于这里的电网碳强度比被腾空的时段高还是低。

| 时段（半小时槽起点） | `actual_gco2_per_kwh` |
|---|---:|
{intensity_table}

{intensity_summary}

## 五、怎么读这三跑
{reading}
## 六、口径提醒

- 两侧重复次数不同：基准 10 次、本杠杆 3 次。
- **三跑不是三个固定种子**：内核种子在
  `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py` 第 217 行由
  `SystemRandom().randrange(1, 2**31)` 现取，每个进程一个随机种子，
  所以 run_01/02/03 与基准的 run_01/02/03 **不构成配对**，只能按均值比。
- 「最优」一律指**成本最小的那一跑**，其排放是那一跑自己的排放，不是各跑里排放最小的。
- **补贴窗口有一半是够不着的**：班次合约是上午 08:00–11:00、午休 11:00–13:00、
  下午 13:00–19:00，车辆在 13:00 之后就上路了。基准十跑的窗口内电量**全部**落在
  12:00–13:30 三个槽里，13:30–15:00 那三个槽逐跑都是 0 kWh。
  也就是说这根杠杆的可作用面被排班挡掉了一半，这是它效果的结构性上限，不是求解没搜到。
- **这个算例里所有充电都在车场**（十跑的 `station_charging_kwh` 全为 0），
  所以日历里 `public_energy` / `public_total` 那半边的改动对本算例是空转的，
  真正生效的只有 `depot_energy`。改这两列是为了让日历本身自洽
  （`energy + service == total`），不是因为公共桩在本算例里被用到。
"""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
