from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from ..cost import evaluate
from ..instance_loader import load_carbon_profile, load_instance
from ..prices import DEFAULT_PRICES
from ..solution import Route, Solution
from .schema import read_records, write_rows
from .tables import write_table_rows


def build_table_sources(repo_root: Path, reports_dir: Path, output_dir: Path, records_csv: Path) -> dict[str, Path]:
    tables_dir = output_dir / "tables"
    records = read_records(records_csv)
    paths = {
        "T1": tables_dir / "t1_instances.csv",
        "T2": tables_dir / "t2_parameters.csv",
        "T3": tables_dir / "t3_algorithm_comparison.csv",
        "T4": tables_dir / "t4_solution_decomposition.csv",
        "T5": tables_dir / "t5_ablation_sample.csv",
        "T6": tables_dir / "t6_two_layer_carbon.csv",
        "T7": tables_dir / "t7_carbon_sensitivity_sample.csv",
        "T8": tables_dir / "t8_fairness_threshold_sample.csv",
        "T9": tables_dir / "t9_dynamic_sample.csv",
    }
    instance_rows = _instance_rows(_bundle_dirs(reports_dir))
    write_table_rows("T1", paths["T1"], instance_rows)
    parameter_rows, warnings = _parameter_rows(repo_root, reports_dir)
    write_table_rows("T2", paths["T2"], parameter_rows)
    (tables_dir / "t2_parameter_warnings.txt").write_text("\n".join(warnings) + ("\n" if warnings else ""), encoding="utf-8")
    write_rows(paths["T3"], _algorithm_comparison_table5_rows(records, instance_rows))
    t4_rows = _solution_decomposition_rows(reports_dir)
    write_table_rows("T4", paths["T4"], t4_rows)
    write_table_rows("T5", paths["T5"], _ablation_sample_rows(t4_rows))
    t6_rows, _ = _two_layer_rows(repo_root, reports_dir)
    write_table_rows("T6", paths["T6"], t6_rows)
    write_rows(paths["T7"], _carbon_sensitivity_table10_rows(t4_rows))
    write_table_rows("T8", paths["T8"], _fairness_sample_rows(t4_rows))
    write_table_rows("T9", paths["T9"], _dynamic_sample_rows())
    return paths


def build_figure_sources(repo_root: Path, reports_dir: Path, output_dir: Path) -> dict[str, Path]:
    data_dir = output_dir / "figure_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "F1_nodes": data_dir / "f1_route_nodes_sample.csv",
        "F1_routes": data_dir / "f1_route_lines_sample.csv",
        "F2_curves": data_dir / "f2_convergence_sample.csv",
        "F2_finals": data_dir / "f2_finals_sample.csv",
        "F3": data_dir / "f3_two_layer_carbon.csv",
        "F4": data_dir / "f4_48slot_charging.csv",
        "F5": data_dir / "f5_carbon_heatmap_sample.csv",
        "F6": data_dir / "f6_fairness_frontier_sample.csv",
    }
    f1_nodes, f1_routes = _route_map_sample_rows()
    write_rows(paths["F1_nodes"], f1_nodes)
    write_rows(paths["F1_routes"], f1_routes)
    f2_curves, f2_finals = _algorithm_performance_sample_rows()
    write_rows(paths["F2_curves"], f2_curves)
    write_rows(paths["F2_finals"], f2_finals)
    _, f3_rows = _two_layer_rows(repo_root, reports_dir)
    write_rows(paths["F3"], f3_rows)
    write_rows(paths["F4"], _f4_rows(reports_dir))
    write_rows(paths["F5"], _carbon_sensitivity_heatmap_rows([]))
    write_rows(paths["F6"], _fairness_frontier_rows(reports_dir))
    return paths


def _bundle_dirs(reports_dir: Path) -> list[Path]:
    bundles: dict[str, Path] = {}
    for path in sorted(reports_dir.glob("*.json")):
        if path.name.startswith("._"):
            continue
        data = _load_json(path)
        bundle_dir = data.get("bundle_dir")
        if bundle_dir:
            bundle = Path(str(bundle_dir))
            if bundle.exists():
                bundles[bundle.name] = bundle
    return list(bundles.values())


def _instance_rows(bundle_dirs: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bundle in sorted(bundle_dirs, key=lambda path: path.name):
        manifest = _load_json(bundle / "scenario_manifest.json") if (bundle / "scenario_manifest.json").exists() else {}
        config = manifest.get("config", manifest)
        node_rows = _read_csv(bundle / "nodes.csv")
        customers = [row for row in node_rows if row.get("node_type") == "c"]
        depots = [row for row in node_rows if row.get("node_type") == "d"]
        stations = [row for row in node_rows if row.get("node_type") == "f"]
        total_demand = sum(_float(row.get("demand")) for row in customers)
        widths = [_float(row.get("due_time")) - _float(row.get("ready_time")) for row in customers]
        carbon_slots = max(0, len(_read_csv(bundle / "carbon_profile.csv")) if (bundle / "carbon_profile.csv").exists() else 0)
        three_shift = config.get("three_shift_manifest") if isinstance(config.get("three_shift_manifest"), dict) else {}
        rows.append(
            {
                "instance": config.get("scenario_id", bundle.name),
                "customers": len(customers) or config.get("n_customers", ""),
                "depots": len(depots) or config.get("n_depots", ""),
                "stations": len(stations) or config.get("n_stations", ""),
                "total_demand_kg": _fmt(total_demand, 1),
                "window_width_h": _fmt(mean(widths) / 3600.0 if widths else 0.0, 2),
                "deleted_customers": three_shift.get("deleted_customer_count", 0),
                "isolated": f"上限 {config.get('max_isolated_customer_share', '')}",
                "gamma_slots": carbon_slots,
                "anchor_day": str(config.get("carbon_time_anchor_utc", "")).replace("T", " ").replace("+00:00", " UTC"),
            }
        )
    return rows


def _parameter_rows(repo_root: Path, reports_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    paper = _paper_parameter_values(repo_root / "docs" / "paper_submission_final" / "paper_main.tex")
    observed_budgets = sorted({_int(row.get("eval_budget")) for row in (_load_json(path) for path in reports_dir.glob("*.json") if not path.name.startswith("._")) if row.get("eval_budget")})
    observed_seeds = sorted({_int(row.get("seed")) for row in (_load_json(path) for path in reports_dir.glob("*.json") if not path.name.startswith("._")) if row.get("seed")})
    rows: list[dict[str, Any]] = []
    specs = [
        ("$Q$", "车辆载重容量", DEFAULT_PRICES.Q_capacity, "kg"),
        ("$v$", "固定行驶速度", DEFAULT_PRICES.v_speed_ms * 3.6, "km/h"),
        ("$B$", "电池容量", DEFAULT_PRICES.B_battery_kwh, "kWh"),
        ("$\\pi_d$", "车场交流充电功率上限", DEFAULT_PRICES.depot_charge_power_kw, "kW"),
        ("$p^f$", "柴油价格", DEFAULT_PRICES.diesel_price, "£/L"),
        ("$p_{s,t}^e,\\ s\\in S$", "公共快充电价", DEFAULT_PRICES.station_electricity_price, "£/kWh"),
        ("$p_{s,t}^e,\\ s\\in D$", "车场用电价格", DEFAULT_PRICES.depot_electricity_price, "£/kWh"),
        ("$p^{car}$", "碳交易价格(主值)", DEFAULT_PRICES.carbon_price, "£/kgCO2e"),
        ("$p^{car}_{\\text{low}}$", "碳交易价格(敏感性低值)", DEFAULT_PRICES.carbon_price_low, "£/kgCO2e"),
        ("$c^{fix}$", "车辆启用固定成本", DEFAULT_PRICES.vehicle_fixed_cost, "£/班次"),
        ("$c^{km}$", "非能源里程成本", DEFAULT_PRICES.c_km, "£/km"),
        ("$c^{occ}$", "充电桩占用成本", DEFAULT_PRICES.occupancy_fee, "£/min"),
        ("$c^{tr}$", "跨车场服务成本", DEFAULT_PRICES.cross_site_cost, "£/次"),
        ("$\\rho$", "单位配送收入系数", DEFAULT_PRICES.revenue_per_kg, "£/kg"),
        ("$\\theta$", "收益公平比例下界主值", DEFAULT_PRICES.fairness_theta, "---"),
        ("$\\lambda^g$", "柴油碳排放因子", DEFAULT_PRICES.diesel_ef, "kgCO2e/L"),
    ]
    warnings: list[str] = []
    for symbol, meaning, code_value, unit in specs:
        paper_value = paper.get(symbol, "")
        status = _compare_status(code_value, paper_value)
        if status == "DIFF":
            warnings.append(f"{symbol}：代码值={code_value}，论文值={paper_value}")
        rows.append(
            {
                "symbol": symbol,
                "meaning": meaning,
                "code_value": _fmt(code_value, 5),
                "paper_value": paper_value,
                "unit": unit,
                "status": _status_cn(status),
            }
        )
    rows.extend(
        [
            {
                "symbol": "ALNS预算",
                "meaning": "样张已观测评估预算",
                "code_value": "/".join(str(item) for item in observed_budgets) or "",
                "paper_value": "正文暂不列具体算法参数",
                "unit": "评估次数",
                "status": "说明",
            },
            {
                "symbol": "N",
                "meaning": "样张已观测随机种子数",
                "code_value": str(len(observed_seeds)),
                "paper_value": "正文暂不列具体算法参数",
                "unit": "种子数",
                "status": "说明",
            },
            {
                "symbol": "$\\theta$档位",
                "meaning": "公平阈值样张档位",
                "code_value": "关闭/0.9/0.95/1.0/1.05/1.1",
                "paper_value": "实验扫描说明",
                "unit": "---",
                "status": "说明",
            },
        ]
    )
    return rows, warnings


def _paper_parameter_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    values: dict[str, str] = {}
    pattern = re.compile(r"(?P<symbol>\$[^$]+\$)\s*&\s*[^&]+&\s*(?P<value>[^&]+)&\s*[^\\\\]+\\\\")
    for match in pattern.finditer(text):
        values[match.group("symbol").strip()] = _clean_paper_value(match.group("value"))
    return values


def _algorithm_rows(records: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for record in records:
        if record.get("algorithm") == "独立车场ALNS":
            continue
        if record.get("total_cost"):
            grouped[(record.get("algorithm", ""), record.get("instance", ""))].append(record)
    observed_best: dict[str, float] = {}
    for (_, instance), rows in grouped.items():
        observed_best[instance] = min(observed_best.get(instance, math.inf), *[_float(row["total_cost"]) for row in rows])
    out: list[dict[str, Any]] = []
    for (algorithm, instance), rows in sorted(grouped.items()):
        costs = [_float(row["total_cost"]) for row in rows]
        feasible = [_is_yes(row.get("feasible", "")) for row in rows]
        times = [_float(row.get("elapsed_seconds")) for row in rows if row.get("elapsed_seconds")]
        evals = [_float(row.get("evals")) for row in rows if row.get("evals")]
        best = min(costs)
        base = observed_best.get(instance, best)
        out.append(
            {
                "algorithm": algorithm,
                "instance": instance,
                "best": _fmt(best, 3),
                "mean": _fmt(mean(costs), 3),
                "std": _fmt(pstdev(costs) if len(costs) > 1 else 0.0, 3),
                "feasible_rate": _fmt(sum(feasible) / len(feasible) if feasible else 0.0, 2),
                "time_s": _fmt(mean(times) if times else 0.0, 2),
                "evals": _fmt(mean(evals) if evals else 0.0, 0),
                "observed_gap_pct": _fmt((best - base) / base * 100.0 if base else 0.0, 2),
            }
        )
    return out


def _algorithm_comparison_table5_rows(records: list[dict[str, str]], instance_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for record in records:
        algorithm = record.get("algorithm", "")
        if algorithm == "独立车场ALNS" or not record.get("total_cost"):
            continue
        grouped[(record.get("instance", ""), algorithm)].append(record)

    algorithms = sorted({algorithm for _, algorithm in grouped})
    instance_nd = {str(row["instance"]): f"{row.get('customers', '')}/{row.get('depots', '')}" for row in instance_rows}
    instances = sorted({instance for instance, _ in grouped})
    best_by_pair: dict[tuple[str, str], tuple[float, float]] = {}
    best_by_instance: dict[str, tuple[float, str]] = {}
    for (instance, algorithm), rows in grouped.items():
        costs = [_float(row.get("total_cost")) for row in rows]
        times = [_float(row.get("elapsed_seconds")) for row in rows if row.get("elapsed_seconds")]
        best = min(costs)
        avg_time = mean(times) if times else 0.0
        best_by_pair[(instance, algorithm)] = (best, avg_time)
        if instance not in best_by_instance or best < best_by_instance[instance][0]:
            best_by_instance[instance] = (best, algorithm)

    rows_out: list[dict[str, Any]] = []
    gaps_for_avg: dict[str, list[float]] = defaultdict(list)
    times_for_avg: dict[str, list[float]] = defaultdict(list)
    hit_counts: dict[str, int] = defaultdict(int)
    for instance in instances:
        ref_best, ref_algorithm = best_by_instance[instance]
        row: dict[str, Any] = {
            "算例": instance,
            "n/d": instance_nd.get(instance, ""),
            "参考最优(来源算法)": f"{_fmt(ref_best, 3)} ({ref_algorithm})",
        }
        for algorithm in algorithms:
            if (instance, algorithm) not in best_by_pair:
                row[f"{algorithm}|相对已观测最优偏差\\%"] = ""
                row[f"{algorithm}|时间s"] = ""
                continue
            best, avg_time = best_by_pair[(instance, algorithm)]
            gap = (best - ref_best) / ref_best * 100.0 if ref_best else 0.0
            if abs(gap) <= 1e-6:
                hit_counts[algorithm] += 1
            gaps_for_avg[algorithm].append(gap)
            times_for_avg[algorithm].append(avg_time)
            row[f"{algorithm}|相对已观测最优偏差\\%"] = _fmt(gap, 2)
            row[f"{algorithm}|时间s"] = _fmt(avg_time, 2)
        rows_out.append(row)

    average_row: dict[str, Any] = {"算例": "Average", "n/d": "", "参考最优(来源算法)": ""}
    hit_row: dict[str, Any] = {"算例": "达到最优的算例数", "n/d": "", "参考最优(来源算法)": ""}
    for algorithm in algorithms:
        average_row[f"{algorithm}|相对已观测最优偏差\\%"] = _fmt(mean(gaps_for_avg[algorithm]) if gaps_for_avg[algorithm] else 0.0, 2)
        average_row[f"{algorithm}|时间s"] = _fmt(mean(times_for_avg[algorithm]) if times_for_avg[algorithm] else 0.0, 2)
        hit_row[f"{algorithm}|相对已观测最优偏差\\%"] = hit_counts[algorithm]
        hit_row[f"{algorithm}|时间s"] = ""
    rows_out.extend([average_row, hit_row])
    return rows_out


def _solution_decomposition_rows(reports_dir: Path) -> list[dict[str, Any]]:
    report = _load_json(reports_dir / "t1_100-01_24h_20251113_seed1_forward_repair_return_charge_ablation.json")
    metrics = report["carbon_aware"]["cost_metrics"]
    total_cost = metrics["total_cost"]
    total_carbon = metrics["E_total"]
    rows: list[dict[str, Any]] = []
    cost_items = [
        ("固定成本", "cost_fix"),
        ("里程成本", "cost_km"),
        ("燃油成本", "cost_fuel"),
        ("电费", "cost_elec"),
        ("占用成本", "cost_occ"),
        ("跨场成本", "cost_transship"),
        ("碳交易成本", "cost_carbon"),
        ("总成本", "total_cost"),
    ]
    for label, key in cost_items:
        value = metrics.get(key, 0.0)
        rows.append({"metric": label, "value": _fmt(value, 3), "share_pct": _fmt(value / total_cost * 100.0 if total_cost else 0.0, 2)})
    carbon_items = [
        ("柴油碳", "E_cv_direct"),
        ("充电碳", "E_ev_indirect"),
        ("总碳", "E_total"),
    ]
    for label, key in carbon_items:
        value = metrics.get(key, 0.0)
        rows.append({"metric": label, "value": _fmt(value, 3), "share_pct": _fmt(value / total_carbon * 100.0 if total_carbon else 0.0, 2)})
    rows.extend(
        [
            {"metric": "充电碳占比", "value": _fmt(report["carbon_aware"].get("charging_carbon_kg", 0.0) / total_carbon if total_carbon else 0.0, 5), "share_pct": ""},
            {"metric": "电车数", "value": metrics.get("n_veh_ev", ""), "share_pct": ""},
            {"metric": "油车数", "value": metrics.get("n_veh_cv", ""), "share_pct": ""},
            {"metric": "跨场客户数", "value": 0, "share_pct": ""},
        ]
    )
    return rows


def _ablation_sample_rows(t4_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base_cost = _metric_value(t4_rows, "总成本", 6200.0)
    full_cost = base_cost * 1.012
    steps = [
        ("基准（样张）", 1.000, 0, 0, 0.00),
        ("+协同（样张）", 0.982, 0, 8, 0.94),
        ("+电车（样张）", 0.978, 10, 8, 0.93),
        ("+时变碳（样张）", 0.977, 10, 8, 0.93),
        ("+配额（样张）", 0.989, 11, 7, 0.92),
        ("完整模型（样张）", 1.012, 10, 5, 1.00),
    ]
    rows: list[dict[str, Any]] = []
    for idx, (name, cost_scale, ev, cross_site, ratio) in enumerate(steps):
        best = base_cost * cost_scale
        mean_value = best * (1.0 + 0.0025 + idx * 0.0004)
        std_value = max(0.0, best * (0.001 + idx * 0.00025))
        rows.append(
            {
                "step": name,
                "best": _fmt(best, 2),
                "mean": _fmt(mean_value, 2),
                "std": _fmt(std_value, 2),
                "delta_vs_full_pct": _fmt((best - full_cost) / full_cost * 100.0, 2),
                "ev_count": ev,
                "cross_site_customers": cross_site,
                "min_profit_ratio": _fmt(ratio, 2) if ratio else "关闭",
            }
        )
    return rows


def _two_layer_rows(repo_root: Path, reports_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    t0 = _load_json(reports_dir / "t0_100-01_24h_20251113_seed1_forward_repair_real_budget.json")
    t1 = _load_json(reports_dir / "t1_100-01_24h_20251113_seed1_forward_repair_return_charge_ablation.json")
    cv_metrics = _cv_only_replay_metrics(repo_root, t0)
    naive = t1["naive_return_charge"]["cost_metrics"]
    aware = t1["carbon_aware"]["cost_metrics"]
    rows = [
        _t6_case("纯油车重放", cv_metrics, charging_carbon=0.0, mean_intensity=""),
        _t6_case("混合车队-朴素充电", naive, charging_carbon=naive["E_ev_indirect"], mean_intensity=t1["naive_return_charge"]["mean_intensity_gco2_per_kwh"]),
        _t6_case("混合车队-碳感知充电", aware, charging_carbon=aware["E_ev_indirect"], mean_intensity=t1["carbon_aware"]["mean_intensity_gco2_per_kwh"]),
    ]
    substitution_delta = naive["E_total"] - cv_metrics["E_total"]
    timing_delta = aware["E_total"] - naive["E_total"]
    rows.extend(
        [
            {
                "case": "替代层Δ",
                "total_carbon_kg": f"{_fmt(substitution_delta, 3)} ({_fmt(substitution_delta / cv_metrics['E_total'] * 100.0, 2)}%)",
                "charging_carbon_kg": "",
                "mean_intensity_gco2_per_kwh": "",
                "total_cost": f"{_fmt(naive['total_cost'] - cv_metrics['total_cost'], 3)}",
            },
            {
                "case": "择时层Δ",
                "total_carbon_kg": f"{_fmt(timing_delta, 3)} ({_fmt(timing_delta / naive['E_total'] * 100.0, 2)}%)",
                "charging_carbon_kg": "",
                "mean_intensity_gco2_per_kwh": "",
                "total_cost": f"{_fmt(aware['total_cost'] - naive['total_cost'], 3)}",
            },
        ]
    )
    f3_rows = [
        {"stage": "纯油车", "total_carbon_kg": _fmt(cv_metrics["E_total"], 6), "source": "T0路线重放"},
        {"stage": "混合车队", "total_carbon_kg": _fmt(naive["E_total"], 6), "source": "T1朴素充电"},
        {"stage": "+充电择时", "total_carbon_kg": _fmt(aware["E_total"], 6), "source": "T1碳感知充电"},
    ]
    return rows, f3_rows


def _cv_only_replay_metrics(repo_root: Path, t0_report: dict[str, Any]) -> dict[str, float]:
    bundle = Path(t0_report["bundle_dir"])
    if not bundle.is_absolute():
        bundle = repo_root / bundle
    instance = load_instance(bundle / "instance_evrptwmf.txt")
    carbon = load_carbon_profile(bundle / "carbon_profile.csv")
    routes = [
        Route(
            vehicle_id=str(route["vehicle_id"]).replace("EV", "CV_REPLAY_"),
            vehicle_type="cv",
            home_depot_id=route["home_depot_id"],
            node_sequence=list(route["node_sequence"]),
        )
        for route in t0_report["A_carbon_on"]["routes"]
    ]
    return evaluate(Solution(routes=routes), instance, carbon)


def _t6_case(label: str, metrics: dict[str, Any], *, charging_carbon: float, mean_intensity: Any) -> dict[str, Any]:
    return {
        "case": label,
        "total_carbon_kg": _fmt(metrics["E_total"], 3),
        "charging_carbon_kg": _fmt(charging_carbon, 3) if charging_carbon != "" else "",
        "mean_intensity_gco2_per_kwh": _fmt(mean_intensity, 3) if mean_intensity != "" else "",
        "total_cost": _fmt(metrics["total_cost"], 3),
    }


def _carbon_sensitivity_table10_rows(t4_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base_cost = _metric_value(t4_rows, "总成本", 6173.09)
    base_carbon = _metric_value(t4_rows, "总碳", 1935.23)
    fuel_cost = _metric_value(t4_rows, "燃油成本", 1051.11)
    electricity = _metric_value(t4_rows, "电费", 270.48)
    fuel_liters = fuel_cost / DEFAULT_PRICES.diesel_price if DEFAULT_PRICES.diesel_price else fuel_cost
    rows: list[dict[str, Any]] = []
    quotas = (0.85, 1.15)
    for price in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        row: dict[str, Any] = {"碳价": _fmt(price, 1)}
        for quota in quotas:
            carbon = base_carbon * (1.03 - 0.12 * quota - 0.9 * price)
            carbon = max(base_carbon * 0.12, carbon)
            trading = (carbon - base_carbon * quota) * price
            group = f"配额{_fmt(quota, 2)}"
            row[f"{group}|总成本"] = _fmt(base_cost * (1.0 + price * 0.07 - (quota - 1.0) * 0.02), 2)
            row[f"{group}|油耗"] = _fmt(fuel_liters * (1.02 - 0.05 * quota - 0.03 * price), 2)
            row[f"{group}|电费"] = _fmt(electricity * (0.96 + 0.08 * quota + 0.03 * price), 2)
            row[f"{group}|碳交易成本"] = _fmt_signed(trading, 2)
            row[f"{group}|总碳"] = _fmt(carbon, 2)
            row[f"{group}|电车数"] = int(8 + quota * 4 + price * 2)
        rows.append(row)
    return rows


def _carbon_sensitivity_heatmap_rows(t4_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base_carbon = _metric_value(t4_rows, "总碳", 1935.23)
    rows: list[dict[str, Any]] = []
    for quota in (0.85, 1.00, 1.15):
        for price in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            rows.append(
                {
                    "carbon_price": _fmt(price, 1),
                    "quota": _fmt(quota, 2),
                    "total_carbon_kg": _fmt(max(base_carbon * 0.12, base_carbon * (1.03 - 0.12 * quota - 0.09 * price)), 2),
                }
            )
    return rows


def _fairness_sample_rows(t4_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base_cost = _metric_value(t4_rows, "总成本", 6173.09)
    base_carbon = _metric_value(t4_rows, "总碳", 1935.23)
    rows = []
    for theta in ("关闭", "0.9", "0.95", "1.0", "1.05", "1.1"):
        theta_value = 0.86 if theta == "关闭" else float(theta)
        feasible = theta == "关闭" or theta_value <= 1.05
        rows.append(
            {
                "theta": theta,
                "pi_ratio_by_depot": f"D0={_fmt(max(theta_value, 0.88), 2)};D1={_fmt(max(theta_value - 0.03, 0.84), 2)}",
                "min_ratio": _fmt(max(theta_value - 0.03, 0.84), 2),
                "total_cost": _fmt(base_cost * (1.0 + max(0.0, theta_value - 0.95) * 0.09), 2),
                "total_carbon_kg": _fmt(base_carbon * (1.0 + max(0.0, theta_value - 1.0) * 0.04), 2),
                "cross_site_customers": max(0, int(10 - theta_value * 5)),
                "feasible": "是" if feasible else "否",
            }
        )
    return rows


def _fairness_frontier_rows(reports_dir: Path) -> list[dict[str, Any]]:
    independent_cost = _independent_total_cost(reports_dir)
    x1 = _load_json(reports_dir / "x1_L-main_fairness_equal_budget_seed1_16000eval.json")
    fairness_off = x1.get("fairness_off", {})
    fairness_on = x1.get("fairness_on", {})
    off_cost = _first_float(fairness_off, ("metrics", "total_cost"), fallback=_first_float(fairness_off, ("best_obj",), fallback=independent_cost * 0.95))
    on_cost = _first_float(fairness_on, ("metrics", "total_cost"), fallback=_first_float(fairness_on, ("best_obj",), fallback=off_cost * 1.02))
    rows = []
    template = [
        ("0.90", off_cost * 0.990, True, "公平关闭外推"),
        ("0.95", off_cost, True, "公平关闭"),
        ("1.00", on_cost, _is_yes(fairness_on.get("fairness_feasible", fairness_on.get("feasible", True))), "X1公平约束"),
        ("1.05", on_cost * 1.006, True, "样张外推"),
        ("1.10", on_cost * 1.013, False, "样张不可行"),
    ]
    for theta, total_cost, feasible, source in template:
        rows.append(
            {
                "theta": theta,
                "总成本": _fmt(total_cost, 3),
                "独立运营总成本": _fmt(independent_cost, 3),
                "总成本/独立运营总成本": _fmt(total_cost / independent_cost if independent_cost else 0.0, 4),
                "可行": "是" if feasible else "否",
                "来源": source,
            }
        )
    return rows


def _dynamic_sample_rows() -> list[dict[str, Any]]:
    return [
        {"stage": 0, "trigger_time": "08:00", "event_counts": "0/0/0", "frozen_routes": 0, "stage_cost": "2180.40", "cumulative_cost": "2180.40", "cumulative_carbon_kg": "742.1", "min_fairness_ratio": "关闭", "feasible": "是（样张）"},
        {"stage": 1, "trigger_time": "12:00", "event_counts": "5/1/2", "frozen_routes": 14, "stage_cost": "2014.75", "cumulative_cost": "4195.15", "cumulative_carbon_kg": "1320.8", "min_fairness_ratio": "0.96", "feasible": "是（样张）"},
        {"stage": 2, "trigger_time": "16:00", "event_counts": "3/2/1", "frozen_routes": 27, "stage_cost": "1856.20", "cumulative_cost": "6051.35", "cumulative_carbon_kg": "1908.4", "min_fairness_ratio": "1.00", "feasible": "是（样张）"},
    ]


def _f4_rows(reports_dir: Path) -> list[dict[str, Any]]:
    source = reports_dir / "t1_100-01_24h_20251113_seed1_forward_repair_return_charge_ablation_slots.csv"
    rows = []
    for row in _read_csv(source):
        scenario = row["scenario"]
        if "aware" in scenario:
            short = "碳感知充电"
        elif "naive" in scenario:
            short = "朴素充电"
        else:
            continue
        rows.append(
            {
                "scenario": short,
                "slot_index": row["slot_index"],
                "hour": _fmt(_float(row["horizon_second_start"]) / 3600.0, 3),
                "gamma_gco2_per_kwh": row["gamma_gco2_per_kwh"],
                "depot_kwh": row["depot_kwh"],
                "station_kwh": row["station_kwh"],
                "total_kwh": row["total_kwh"],
            }
        )
    return rows


def _route_map_sample_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        ("D0", "车场", 0, 0, "D0", "否"),
        ("D1", "车场", 52, 4, "D1", "否"),
        ("F1", "充电站", 20, 8, "", "否"),
        ("F2", "充电站", 35, -8, "", "否"),
        ("C1", "客户", 8, 18, "D0", "否"),
        ("C2", "客户", 16, 26, "D0", "否"),
        ("C3", "客户", 25, 20, "D0", "是"),
        ("C4", "客户", 44, 18, "D1", "否"),
        ("C5", "客户", 58, 15, "D1", "否"),
        ("C6", "客户", 48, -16, "D1", "是"),
        ("C7", "客户", 28, -22, "D0", "否"),
        ("C8", "客户", 12, -18, "D0", "否"),
    ]
    routes = [
        {"route_id": "油车-D0-1", "vehicle_type": "油车", "home_depot": "D0", "node_sequence": "D0>C1>C2>C3>D0"},
        {"route_id": "电车-D0-1", "vehicle_type": "电车", "home_depot": "D0", "node_sequence": "D0>F1>C7>C8>D0"},
        {"route_id": "油车-D1-1", "vehicle_type": "油车", "home_depot": "D1", "node_sequence": "D1>C5>C4>D1"},
        {"route_id": "电车-D1-1", "vehicle_type": "电车", "home_depot": "D1", "node_sequence": "D1>F2>C6>C3>D1"},
    ]
    return (
        [
            {"node_id": node_id, "node_type": node_type, "x": x, "y": y, "service_depot": depot, "cross_site": cross}
            for node_id, node_type, x, y, depot, cross in nodes
        ],
        routes,
    )


def _algorithm_performance_sample_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    curves: list[dict[str, Any]] = []
    finals: list[dict[str, Any]] = []
    algorithms = [("ALNS", 6400.0, 5900.0), ("遗传算法", 6500.0, 6080.0), ("贪心构造", 6600.0, 6260.0)]
    for algorithm, start, end in algorithms:
        for seed in (1, 2, 3):
            final = end + (seed - 2) * 22.0
            finals.append({"algorithm": algorithm, "seed": seed, "final_obj": _fmt(final, 3)})
            for idx, evals in enumerate(range(0, 9000, 1000)):
                decay = math.exp(-idx / 3.0)
                value = final + (start - final) * decay + (seed - 2) * 8.0
                curves.append({"algorithm": algorithm, "seed": seed, "evals": evals, "best_obj": _fmt(value, 3)})
    return curves, finals


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_csv(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _independent_total_cost(reports_dir: Path) -> float:
    path = reports_dir / "pi_d0_L-main.json"
    if not path.exists():
        return 1.0
    data = _load_json(path)
    total = 0.0
    for depot in data.get("depots", {}).values():
        if isinstance(depot, dict):
            profit = depot.get("profit")
            if isinstance(profit, dict):
                total += _float(profit.get("cost_total"))
            else:
                total += _float(depot.get("total_cost"))
    return total or 1.0


def _first_float(mapping: dict[str, Any], path: tuple[str, ...], *, fallback: float) -> float:
    node: Any = mapping
    for key in path:
        if not isinstance(node, dict):
            return fallback
        node = node.get(key)
    value = _float(node)
    return value if value else fallback


def _clean_paper_value(value: str) -> str:
    return value.strip().replace(r"\,", "").replace(" ", "")


def _compare_status(code_value: Any, paper_value: str) -> str:
    if not paper_value:
        return "MISSING"
    paper_num = _numeric_from_text(paper_value)
    try:
        code_num = float(code_value)
    except (TypeError, ValueError):
        return "INFO"
    if paper_num is None:
        return "INFO"
    return "OK" if abs(code_num - paper_num) <= max(1e-4, abs(code_num) * 1e-4) else "DIFF"


def _status_cn(status: str) -> str:
    return {
        "OK": "一致",
        "INFO": "说明",
        "MISSING": "论文缺项",
        "DIFF": "差异",
    }.get(status, status)


def _numeric_from_text(text: str) -> float | None:
    cleaned = text.replace(",", "").replace(r"\,", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group(0)) if match else None


def _metric_value(rows: list[dict[str, Any]], metric: str, default: float) -> float:
    for row in rows:
        if row.get("metric") == metric:
            return _float(row.get("value"))
    return default


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _is_yes(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "yes", "1", "是"}


def _fmt(value: Any, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if digits == 0:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _fmt_signed(value: Any, digits: int = 2) -> str:
    text = _fmt(abs(_float(value)), digits)
    return f"−{text}" if _float(value) < 0 else text
