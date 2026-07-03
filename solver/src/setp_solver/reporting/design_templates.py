from __future__ import annotations

from pathlib import Path
from typing import Any

from .figures import (
    figure_f1_route_map,
    figure_f2_algorithm_performance,
    figure_f3_two_layer_waterfall,
    figure_f4_48slot_charging,
    figure_f5_carbon_response,
    figure_f6_fairness_frontier,
    figure_f7_dynamic_timeline,
)
from .schema import write_rows
from .tables import TABLE_SPECS, write_table_fragment


TABLE_SLUGS = {
    "T1": "instances",
    "T3": "algorithm_comparison",
    "T4": "solution_decomposition",
    "T5": "ablation",
    "T6": "two_layer_carbon",
    "T7": "carbon_sensitivity",
    "T8": "fairness_threshold",
    "T9": "dynamic",
}

TABLE_CSV_NAMES = {
    "T1": "t1_instances.csv",
    "T3": "t3_algorithm_comparison.csv",
    "T4": "t4_solution_decomposition.csv",
    "T5": "t5_ablation.csv",
    "T6": "t6_two_layer_carbon.csv",
    "T7": "t7_carbon_sensitivity.csv",
    "T8": "t8_fairness_threshold.csv",
    "T9": "t9_dynamic.csv",
}

TABLE_NOTES = {
    "T1": "样例数据/非实验结果，仅用于锁定论文图表样板；正式数值以后续实验 CSV 为准。口径：数据来源为 scenario manifest；客户、车场、充电站、需求、时间窗和碳强度锚定日均按 manifest 与导出校验器逐项核验。",
    "T3": "样例数据/非实验结果，仅用于锁定论文图表样板；正式数值以后续实验 CSV 为准。口径：参考最优定义为本轮全部可行解的已观测最优值，并注明来源算法；显著性为相对主算法逐 seed Wilcoxon 配对检验，p<0.05 记 *；样板预算占位为 10 seed、16000 eval 或 900 s 先到为准。",
    "T4": "样例数据/非实验结果，仅用于锁定论文图表样板；正式数值以后续实验 CSV 为准。口径：仅油车、仅电车、混合三方案均为同预算独立重优化，非同一路线的动力替换。",
    "T5": "样例数据/非实验结果，仅用于锁定论文图表样板；正式数值以后续实验 CSV 为准。口径：Δ\\% 与显著性的对照基准均为完整模型；若真实重跑显示机制无效应，属实验设计问题需回炉，不得靠表格掩饰。",
    "T6": "样例数据/非实验结果，仅用于锁定论文图表样板；正式数值以后续实验 CSV 为准。口径链：仅油车重优化基线 → 混合+朴素即充 → 混合+碳感知择时；总排放=直接排放（燃油）+充电间接排放。",
    "T7": "样例数据/非实验结果，仅用于锁定论文图表样板；正式数值以后续实验 CSV 为准。口径：配额在线性可买卖碳交易下为目标函数常数项，故不设配额轴；硬配额情景见附录。",
    "T8": "样例数据/非实验结果，仅用于锁定论文图表样板；正式数值以后续实验 CSV 为准。口径：θ 网格需覆盖各场自然比值附近的 binding 区间，并同时标记可行段、自然比值线与不可行区。",
    "T9": "样例数据/非实验结果，仅用于锁定论文图表样板；正式数值以后续实验 CSV 为准。口径：信息成本=动态最终成本−同流静态后见基线成本；守恒审计=冻结段不可变+状态继承逐阶段核验。",
    "T9_APPENDIX": "样例数据/非实验结果，仅用于锁定论文图表样板；正式数值以后续实验 CSV 为准。口径：附录仅展开 1 条代表事件流的逐阶段明细，用于核验正文 T9 的信息成本、守恒审计和三机制阶段指标。",
}


def build_design_templates(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    mock_dir = output_dir / "mock_data"
    tables_dir = output_dir / "tables"
    figures_dir = output_dir / "figures"
    for path in (mock_dir, tables_dir, figures_dir):
        path.mkdir(parents=True, exist_ok=True)

    mock_data = _write_mock_data(mock_dir)
    table_tex = _write_tables(mock_data, tables_dir)
    figure_outputs = _write_figures(mock_data, figures_dir)
    contract = output_dir / "DATA_CONTRACT.md"
    contract.write_text(_data_contract_markdown(), encoding="utf-8")
    preview = output_dir / "design_preview.tex"
    preview.write_text(_preview_tex(), encoding="utf-8")
    report = output_dir / "design_template_report.md"
    report.write_text(_report_markdown(mock_data, table_tex, figure_outputs), encoding="utf-8")
    _cleanup_appledouble(output_dir)
    return {
        "mock_data": mock_data,
        "tables": table_tex,
        "figures": figure_outputs,
        "contract": contract,
        "preview": preview,
        "report": report,
        "repo_root": repo_root,
    }


def _write_mock_data(mock_dir: Path) -> dict[str, Path]:
    paths = {
        "T1": mock_dir / "t1_instances.csv",
        "T3": mock_dir / "t3_algorithm_comparison.csv",
        "T4": mock_dir / "t4_solution_decomposition.csv",
        "T5": mock_dir / "t5_ablation.csv",
        "T6": mock_dir / "t6_two_layer_carbon.csv",
        "T7": mock_dir / "t7_carbon_sensitivity.csv",
        "T8": mock_dir / "t8_fairness_threshold.csv",
        "T9": mock_dir / "t9_dynamic.csv",
        "F1_nodes": mock_dir / "f1_route_nodes.csv",
        "F1_routes": mock_dir / "f1_route_lines.csv",
        "F2_curves": mock_dir / "f2_algorithm_curves.csv",
        "F2_finals": mock_dir / "f2_algorithm_finals.csv",
        "F3": mock_dir / "f3_two_layer_carbon.csv",
        "F4": mock_dir / "f4_48slot_charging.csv",
        "F5": mock_dir / "f5_carbon_response.csv",
        "F6": mock_dir / "f6_fairness_frontier.csv",
        "F7": mock_dir / "f7_dynamic_timeline.csv",
        "T9_APPENDIX": mock_dir / "t9_appendix_stage_detail.csv",
    }
    _write_mock_rows(paths["T1"], _t1_rows())
    _write_mock_rows(paths["T3"], _t3_rows())
    _write_mock_rows(paths["T4"], _t4_rows())
    _write_mock_rows(paths["T5"], _t5_rows())
    _write_mock_rows(paths["T6"], _t6_rows())
    _write_mock_rows(paths["T7"], _t7_rows())
    _write_mock_rows(paths["T8"], _t8_rows())
    _write_mock_rows(paths["T9"], _t9_rows())
    f1_nodes, f1_routes = _f1_rows()
    _write_mock_rows(paths["F1_nodes"], f1_nodes)
    _write_mock_rows(paths["F1_routes"], f1_routes)
    f2_curves, f2_finals = _f2_rows()
    _write_mock_rows(paths["F2_curves"], f2_curves)
    _write_mock_rows(paths["F2_finals"], f2_finals)
    _write_mock_rows(paths["F3"], _f3_rows())
    _write_mock_rows(paths["F4"], _f4_rows())
    _write_mock_rows(paths["F5"], _f5_rows())
    _write_mock_rows(paths["F6"], _f6_rows())
    _write_mock_rows(paths["F7"], _f7_rows())
    _write_mock_rows(paths["T9_APPENDIX"], _t9_appendix_stage_detail_rows())
    return paths


def _write_mock_rows(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    write_rows(csv_path, [{field: _format_mock_value(value) for field, value in row.items()} for row in rows])


def _format_mock_value(value: Any) -> Any:
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return "0" if text == "-0" else text
    return value


def _write_tables(mock_data: dict[str, Path], tables_dir: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for table_id, slug in TABLE_SLUGS.items():
        tex = tables_dir / f"{table_id.lower()}_{slug}.tex"
        write_table_fragment(table_id, mock_data[table_id], tex)
        _append_table_note(tex, table_id)
        out[table_id] = tex
    appendix = tables_dir / "t9_appendix_stage_detail.tex"
    write_table_fragment("T9_APPENDIX", mock_data["T9_APPENDIX"], appendix)
    _append_table_note(appendix, "T9_APPENDIX")
    out["T9_APPENDIX"] = appendix
    return out


def _append_table_note(tex: Path, table_id: str) -> None:
    text = tex.read_text(encoding="utf-8").rstrip()
    text += f"\n\\par\\footnotesize 注：{TABLE_NOTES[table_id]}\n"
    tex.write_text(text, encoding="utf-8")


def _write_figures(mock_data: dict[str, Path], figures_dir: Path) -> dict[str, tuple[Path, Path]]:
    return {
        "F1": figure_f1_route_map(mock_data["F1_nodes"], mock_data["F1_routes"], figures_dir / "figure_f1_route_map"),
        "F2": figure_f2_algorithm_performance(mock_data["F2_curves"], mock_data["F2_finals"], figures_dir / "figure_f2_algorithm_performance"),
        "F3": figure_f3_two_layer_waterfall(mock_data["F3"], figures_dir / "figure_f3_two_layer_carbon", watermark=True),
        "F4": figure_f4_48slot_charging(mock_data["F4"], figures_dir / "figure_f4_48slot_charging"),
        "F5": figure_f5_carbon_response(mock_data["F5"], figures_dir / "figure_f5_carbon_response"),
        "F6": figure_f6_fairness_frontier(mock_data["F6"], figures_dir / "figure_f6_fairness_frontier"),
        "F7": figure_f7_dynamic_timeline(mock_data["F7"], figures_dir / "figure_f7_dynamic_timeline"),
    }


def _t1_rows() -> list[dict[str, Any]]:
    return [
        {"instance": "L-main", "customers": 100, "depots": 2, "stations": 10, "total_demand_kg": 12345.6, "window_width_h": 3.5, "isolated_customer_share_pct": 1.2, "gamma_slots": 48, "anchor_day": "2025-11-13 UTC"},
        {"instance": "XL-dynamic", "customers": 219, "depots": 2, "stations": 23, "total_demand_kg": 23456.7, "window_width_h": 4.0, "isolated_customer_share_pct": 0.8, "gamma_slots": 48, "anchor_day": "2025-11-13 UTC"},
    ]


def _t3_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    win_counts: dict[str, int] = {}
    gap_totals: dict[str, list[float]] = {}
    for instance, ref in (("L-main", 1200.0), ("XL-dynamic", 2400.0)):
        for algorithm, scale, sig in (("ALNS", 1.000, "--"), ("GA", 1.083, "*"), ("PSO", 1.117, "*"), ("VNS", 1.052, "*")):
            best = ref * scale
            gap = (scale - 1.0) * 100.0
            win_counts[algorithm] = win_counts.get(algorithm, 0) + (1 if scale == 1.0 else 0)
            gap_totals.setdefault(algorithm, []).append(gap)
            rows.append(
                {
                    "instance": instance,
                    "algorithm": algorithm,
                    "best": best,
                    "mean": best * 1.012,
                    "std": best * 0.018,
                    "observed_gap_pct": gap,
                    "feasible_rate_pct": 100.0,
                    "equal_eval_time_s": 210.0 * scale,
                    "equal_wallclock_score": "占位",
                    "significance": sig,
                }
            )
    for algorithm in ("ALNS", "GA", "PSO", "VNS"):
        rows.append(
            {
                "instance": "达优次数",
                "algorithm": algorithm,
                "best": f"{win_counts.get(algorithm, 0)}/2",
                "mean": "",
                "std": "",
                "observed_gap_pct": "",
                "feasible_rate_pct": "",
                "equal_eval_time_s": "",
                "equal_wallclock_score": "",
                "significance": "",
            }
        )
    for algorithm in ("ALNS", "GA", "PSO", "VNS"):
        gaps = gap_totals.get(algorithm, [0.0])
        rows.append(
            {
                "instance": "平均偏差",
                "algorithm": algorithm,
                "best": "",
                "mean": "",
                "std": "",
                "observed_gap_pct": round(sum(gaps) / len(gaps), 1),
                "feasible_rate_pct": "",
                "equal_eval_time_s": "",
                "equal_wallclock_score": "",
                "significance": "",
            }
        )
    return rows


def _t4_rows() -> list[dict[str, Any]]:
    return [
        {"metric": "固定成本/£", "cv_only": 640.0, "ev_only": 720.0, "mixed": 680.0},
        {"metric": "里程成本/£", "cv_only": 1234.5, "ev_only": 1188.8, "mixed": 1199.9},
        {"metric": "燃油成本/£", "cv_only": 1333.3, "ev_only": 0.0, "mixed": 512.4},
        {"metric": "电费/£", "cv_only": 0.0, "ev_only": 455.6, "mixed": 288.8},
        {"metric": "充电占用/£", "cv_only": 0.0, "ev_only": 244.4, "mixed": 144.4},
        {"metric": "跨场成本/£", "cv_only": 95.0, "ev_only": 190.0, "mixed": 285.0},
        {"metric": "碳交易成本/£", "cv_only": 132.1, "ev_only": 43.2, "mixed": 78.9},
        {"metric": "总成本/£", "cv_only": 3434.9, "ev_only": 2842.0, "mixed": 3189.4},
        {"metric": "直接排放（燃油）/kgCO$_2$e", "cv_only": 1888.8, "ev_only": 0.0, "mixed": 722.2},
        {"metric": "充电间接排放/kgCO$_2$e", "cv_only": 0.0, "ev_only": 388.8, "mixed": 166.6},
        {"metric": "总排放/kgCO$_2$e", "cv_only": 1888.8, "ev_only": 388.8, "mixed": 888.8},
        {"metric": "油车/电车路线数", "cv_only": "36/0", "ev_only": "0/34", "mixed": "16/22"},
        {"metric": "车场/站充电kWh", "cv_only": "0/0", "ev_only": "1888.8/222.2", "mixed": "1111.1/123.4"},
        {"metric": "跨场服务客户数", "cv_only": 1, "ev_only": 2, "mixed": 6},
    ]


def _t5_rows() -> list[dict[str, Any]]:
    return [
        {"step": "M0 无协同基线", "mean_std_cost": "3388.8±88.8", "delta_vs_full_pct": 6.4, "significance": "*", "total_carbon_kg": 1111.1, "ev_routes": 12, "cross_site_customers": 0, "min_fairness_ratio": 0.932},
        {"step": "M1 加入多车场协同", "mean_std_cost": "3277.7±77.7", "delta_vs_full_pct": 2.9, "significance": "*", "total_carbon_kg": 1044.4, "ev_routes": 15, "cross_site_customers": 5, "min_fairness_ratio": 0.948},
        {"step": "M2 加入EV间接排放", "mean_std_cost": "3244.4±70.1", "delta_vs_full_pct": 1.9, "significance": "*", "total_carbon_kg": 999.9, "ev_routes": 18, "cross_site_customers": 5, "min_fairness_ratio": 0.956},
        {"step": "M3 加入时变碳强度", "mean_std_cost": "3222.2±66.6", "delta_vs_full_pct": 1.2, "significance": "*", "total_carbon_kg": 944.4, "ev_routes": 19, "cross_site_customers": 6, "min_fairness_ratio": 0.966},
        {"step": "M4 加入碳交易", "mean_std_cost": "3205.5±62.2", "delta_vs_full_pct": 0.7, "significance": "*", "total_carbon_kg": 911.1, "ev_routes": 20, "cross_site_customers": 6, "min_fairness_ratio": 0.978},
        {"step": "M5 完整模型", "mean_std_cost": "3183.0±60.0", "delta_vs_full_pct": 0.0, "significance": "--", "total_carbon_kg": 888.8, "ev_routes": 22, "cross_site_customers": 6, "min_fairness_ratio": 1.003},
    ]


def _t6_rows() -> list[dict[str, Any]]:
    return [
        {"case": "仅油车重优化基线", "total_cost": 3434.9, "diesel_carbon_kg": 1888.8, "charging_carbon_kg": 0.0, "total_carbon_kg": 1888.8, "mean_intensity_gco2_per_kwh": "", "delta_emission_prev_pct": ""},
        {"case": "混合车队+朴素即充", "total_cost": 3211.1, "diesel_carbon_kg": 800.0, "charging_carbon_kg": 222.2, "total_carbon_kg": 1022.2, "mean_intensity_gco2_per_kwh": 142.0, "delta_emission_prev_pct": -45.9},
        {"case": "混合车队+碳感知择时", "total_cost": 3189.4, "diesel_carbon_kg": 722.2, "charging_carbon_kg": 166.6, "total_carbon_kg": 888.8, "mean_intensity_gco2_per_kwh": 86.0, "delta_emission_prev_pct": -13.0},
    ]


def _t7_rows() -> list[dict[str, Any]]:
    return [
        {"carbon_price_level": "0.8×现实值", "total_cost": 3166.6, "fuel_liters": 300.0, "charging_kwh": 1500.0, "charging_centroid_h": 16.0, "carbon_trading_cost": 35.5, "diesel_carbon_kg": 770.0, "charging_carbon_kg": 188.8, "total_carbon_kg": 958.8, "ev_routes": 20},
        {"carbon_price_level": "1.0×现实值", "total_cost": 3189.4, "fuel_liters": 281.0, "charging_kwh": 1560.0, "charging_centroid_h": 14.2, "carbon_trading_cost": 44.8, "diesel_carbon_kg": 722.2, "charging_carbon_kg": 166.6, "total_carbon_kg": 888.8, "ev_routes": 22},
        {"carbon_price_level": "1.2×现实值", "total_cost": 3202.2, "fuel_liters": 276.0, "charging_kwh": 1598.0, "charging_centroid_h": 12.7, "carbon_trading_cost": 55.2, "diesel_carbon_kg": 709.4, "charging_carbon_kg": 150.0, "total_carbon_kg": 859.4, "ev_routes": 23},
        {"carbon_price_level": "1.5×现实值", "total_cost": 3233.3, "fuel_liters": 260.0, "charging_kwh": 1666.0, "charging_centroid_h": 10.8, "carbon_trading_cost": 70.1, "diesel_carbon_kg": 668.4, "charging_carbon_kg": 133.3, "total_carbon_kg": 801.7, "ev_routes": 24},
    ]


def _t8_rows() -> list[dict[str, Any]]:
    rows = []
    for theta, min_ratio, cost, cross_site, feasible in (
        (0.80, 0.965, 3150.0, 8, "是"),
        (0.90, 0.982, 3166.6, 7, "是"),
        (0.95, 0.995, 3175.5, 7, "是"),
        (1.00, 1.003, 3189.4, 6, "是"),
        (1.01, 1.012, 3201.0, 5, "是"),
        (1.02, 1.021, 3222.2, 4, "是"),
        (1.03, 1.030, 3266.6, 3, "是"),
        (1.04, 1.041, 3333.3, 2, "是"),
        (1.05, "", "", "", "否"),
        (1.10, "", "", "", "否"),
    ):
        rows.append({"theta": theta, "pi_ratio_by_depot": f"D0={min_ratio or '--'};D1={min_ratio or '--'}", "min_ratio": min_ratio, "total_cost": cost, "total_carbon_kg": 888.8 if feasible == "是" else "", "cross_site_customers": cross_site, "feasible": feasible})
    return rows


def _t9_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    flows = [
        ("s1", "8/3/5", 4, 3444.4, 3322.2, 999.9, 7, 1.012, 68.0),
        ("s2", "6/2/4", 3, 3333.3, 3244.4, 955.5, 6, 1.005, 72.0),
        ("s3", "10/4/6", 5, 3666.6, 3499.9, 1055.5, 9, 1.018, 65.0),
        ("s4", "7/1/5", 4, 3408.8, 3290.0, 982.4, 7, 1.009, 70.0),
        ("s5", "9/2/3", 4, 3511.2, 3380.5, 1008.6, 8, 1.014, 67.5),
        ("s6", "5/4/4", 3, 3360.6, 3268.8, 940.2, 5, 1.002, 74.0),
        ("s7", "11/3/7", 5, 3718.5, 3542.0, 1088.3, 10, 1.021, 63.0),
        ("s8", "6/3/6", 4, 3462.0, 3340.4, 990.1, 7, 1.011, 69.0),
        ("s9", "8/2/8", 5, 3602.6, 3455.9, 1033.7, 8, 1.017, 66.0),
        ("s10", "7/4/5", 4, 3538.1, 3401.4, 1012.5, 9, 1.016, 71.0),
    ]
    for event_flow, counts, replans, final_cost, hindsight, carbon, cross_site, fairness, low_carbon in flows:
        info = final_cost - hindsight
        pct = info / hindsight * 100.0
        rows.append(
            {
                "event_flow": event_flow,
                "event_counts": counts,
                "replans": replans,
                "final_cost": final_cost,
                "hindsight_cost": hindsight,
                "information_cost": f"{info:.1f} ({pct:.1f}%)",
                "total_carbon_kg": carbon,
                "cross_site_customers": cross_site,
                "min_fairness_ratio": fairness,
                "low_carbon_charge_share_pct": low_carbon,
                "conservation_audit": "通过",
            }
        )
    return rows


def _f1_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        ("D0", "车场", 0, 0, "D0", "否"),
        ("D1", "车场", 52, 4, "D1", "否"),
        ("F1", "充电站", 20, 8, "", "否"),
        ("F2", "充电站", 35, -8, "", "否"),
        ("C1", "客户", 8, 18, "D0", "否"),
        ("C2", "客户", 16, 26, "D0", "否"),
        ("C3", "客户", 25, 20, "D1", "是"),
        ("C4", "客户", 44, 18, "D1", "否"),
        ("C5", "客户", 58, 15, "D1", "否"),
        ("C6", "客户", 48, -16, "D0", "是"),
        ("C7", "客户", 28, -22, "D0", "否"),
        ("C8", "客户", 12, -18, "D0", "否"),
    ]
    routes = [
        {"route_id": "CV-D0-1", "vehicle_type": "油车", "home_depot": "D0", "node_sequence": "D0>C1>C2>C3>D0"},
        {"route_id": "EV-D0-1", "vehicle_type": "电车", "home_depot": "D0", "node_sequence": "D0>F1>C7>C8>D0"},
        {"route_id": "CV-D1-1", "vehicle_type": "油车", "home_depot": "D1", "node_sequence": "D1>C5>C4>D1"},
        {"route_id": "EV-D1-1", "vehicle_type": "电车", "home_depot": "D1", "node_sequence": "D1>F2>C6>C3>D1"},
    ]
    return ([{"node_id": n, "node_type": t, "x": x, "y": y, "service_depot": d, "cross_site": c} for n, t, x, y, d, c in nodes], routes)


def _f2_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    curves: list[dict[str, Any]] = []
    finals: list[dict[str, Any]] = []
    for instance, ref in (("L-main", 1200.0), ("XL-dynamic", 2400.0)):
        for algorithm, gap in (("ALNS", 0.0), ("GA", 0.08), ("PSO", 0.12), ("VNS", 0.05)):
            for seed in (1, 2, 3):
                final = ref * (1.0 + gap) + (seed - 2) * 8.0
                finals.append({"instance": instance, "algorithm": algorithm, "seed": seed, "final_obj": final})
                for idx, evals in enumerate(range(0, 16001, 2000)):
                    decay = 0.55 ** idx
                    value = final + ref * (0.35 + gap) * decay
                    curves.append({"instance": instance, "algorithm": algorithm, "seed": seed, "evals": evals, "best_obj": value, "reference_best": ref})
    return curves, finals


def _f3_rows() -> list[dict[str, Any]]:
    return [
        {"stage": "仅油车重优化", "total_carbon_kg": 1888.8},
        {"stage": "混合朴素充电", "total_carbon_kg": 1022.2},
        {"stage": "混合碳感知择时", "total_carbon_kg": 888.8},
    ]


def _f4_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in ("naive_return_charge", "carbon_aware"):
        for slot in range(48):
            hour = slot * 0.5
            gamma = 170.0 - 90.0 * max(0.0, 1.0 - abs(hour - 12.0) / 8.0)
            naive_kwh = 26.0 if 17 <= hour <= 20 else 3.0
            aware_kwh = 24.0 if 10 <= hour <= 14 else 2.0
            rows.append({"scenario": scenario, "slot_index": slot, "horizon_second_start": slot * 1800, "gamma_gco2_per_kwh": gamma, "depot_kwh": 0.0, "station_kwh": 0.0, "other_kwh": 0.0, "total_kwh": naive_kwh if scenario == "naive_return_charge" else aware_kwh})
    return rows


def _f5_rows() -> list[dict[str, Any]]:
    return [
        {"panel": "现实邻域", "price_gbp_per_tonne": 42.0, "total_carbon_mean": 980.0, "total_carbon_std": 22.0, "ev_routes": 20},
        {"panel": "现实邻域", "price_gbp_per_tonne": 50.3, "total_carbon_mean": 888.8, "total_carbon_std": 18.0, "ev_routes": 22},
        {"panel": "现实邻域", "price_gbp_per_tonne": 60.0, "total_carbon_mean": 858.0, "total_carbon_std": 16.0, "ev_routes": 23},
        {"panel": "现实邻域", "price_gbp_per_tonne": 75.0, "total_carbon_mean": 822.0, "total_carbon_std": 14.0, "ev_routes": 24},
        {"panel": "宽域压力", "price_gbp_per_tonne": 42.0, "total_carbon_mean": 980.0, "total_carbon_std": 22.0, "ev_routes": 20},
        {"panel": "宽域压力", "price_gbp_per_tonne": 100.0, "total_carbon_mean": 790.0, "total_carbon_std": 18.0, "ev_routes": 25},
        {"panel": "宽域压力", "price_gbp_per_tonne": 400.0, "total_carbon_mean": 710.0, "total_carbon_std": 20.0, "ev_routes": 28},
        {"panel": "宽域压力", "price_gbp_per_tonne": 1600.0, "total_carbon_mean": 566.6, "total_carbon_std": 36.0, "ev_routes": 34},
        {"panel": "宽域压力", "price_gbp_per_tonne": 3200.0, "total_carbon_mean": 555.5, "total_carbon_std": 55.0, "ev_routes": 35},
    ]


def _f6_rows() -> list[dict[str, Any]]:
    return _t8_rows()


def _f7_rows() -> list[dict[str, Any]]:
    vehicles = ["CV1", "CV2", "EV1", "EV2", "EV3"]
    stage_metrics = [
        (0.0, 2.0, "冻结段", "新增", 0.8, 640.0, 620.0, 188.0, 2, 56.0, 1.000),
        (2.0, 5.0, "重规划段", "变更", 2.0, 1260.0, 1198.0, 356.0, 4, 64.0, 1.006),
        (5.0, 8.0, "冻结段", "取消", 5.0, 2038.0, 1930.0, 590.0, 5, 70.0, 1.014),
        (8.0, 12.0, "重规划段", "新增", 8.0, 2888.8, 2744.4, 800.0, 7, 76.0, 1.020),
    ]
    rows: list[dict[str, Any]] = []
    for vehicle_index, vehicle in enumerate(vehicles):
        offset = 0.08 * vehicle_index
        for stage_index, (start, end, segment, event_type, event_time, cost, hindsight, carbon, cross_site, low_carbon, fairness) in enumerate(stage_metrics):
            rows.append(
                {
                    "vehicle_id": vehicle,
                    "stage_start_h": start + offset,
                    "stage_end_h": end - 0.04 * vehicle_index,
                    "segment_type": segment,
                    "event_type": event_type if vehicle_index == 0 else "",
                    "event_time_h": event_time if vehicle_index == 0 else "",
                    "cumulative_cost": cost if vehicle_index == 0 else "",
                    "hindsight_cost": hindsight if vehicle_index == 0 else "",
                    "cumulative_carbon_kg": carbon if vehicle_index == 0 else "",
                    "cross_site_customers": cross_site if vehicle_index == 0 else "",
                    "low_carbon_charge_share_pct": low_carbon if vehicle_index == 0 else "",
                    "min_fairness_ratio": fairness if vehicle_index == 0 else "",
                    "theta": 1.000 if vehicle_index == 0 else "",
                }
            )
    return rows


def _t9_appendix_stage_detail_rows() -> list[dict[str, Any]]:
    return [
        {"stage": "S0", "trigger_time_h": 0.0, "event_counts": "0/0/0", "frozen_route_count": 0, "stage_cost": 640.0, "cumulative_cost": 640.0, "cumulative_carbon_kg": 188.0, "stage_min_fairness_ratio": 1.000, "stage_cross_site_customers": 2, "stage_low_carbon_charge_share_pct": 56.0},
        {"stage": "S1", "trigger_time_h": 0.8, "event_counts": "3/0/1", "frozen_route_count": 3, "stage_cost": 620.0, "cumulative_cost": 1260.0, "cumulative_carbon_kg": 356.0, "stage_min_fairness_ratio": 1.006, "stage_cross_site_customers": 4, "stage_low_carbon_charge_share_pct": 64.0},
        {"stage": "S2", "trigger_time_h": 5.0, "event_counts": "0/2/1", "frozen_route_count": 5, "stage_cost": 778.0, "cumulative_cost": 2038.0, "cumulative_carbon_kg": 590.0, "stage_min_fairness_ratio": 1.014, "stage_cross_site_customers": 5, "stage_low_carbon_charge_share_pct": 70.0},
        {"stage": "S3", "trigger_time_h": 8.0, "event_counts": "5/1/3", "frozen_route_count": 6, "stage_cost": 850.8, "cumulative_cost": 2888.8, "cumulative_carbon_kg": 800.0, "stage_min_fairness_ratio": 1.020, "stage_cross_site_customers": 7, "stage_low_carbon_charge_share_pct": 76.0},
    ]


def _data_contract_markdown() -> str:
    lines = [
        "# ReSETP 图表样板数据契约",
        "",
        "所有 mock 数值均为样例数据/非实验结果。正式重跑只能按本契约灌入 CSV，不得在表图层修改结论。全文碳口径只使用：直接排放（燃油）、充电间接排放、总排放（=两者之和）。",
        "",
    ]
    table_claims = {
        "T1": "本表证明：算例规模、碳强度槽和数据锚点可核验。",
        "T3": "本表证明：主算法在相同预算下相对文献基线更优且有统计标记。",
        "T4": "本表证明：混合车队在成本与两类排放之间形成可解释折中。",
        "T5": "本表证明：每个建模层都有可见边际贡献。",
        "T6": "本表证明：减排来自车队电动化与充电择时两层。",
        "T7": "本表证明：现实邻域碳价只产生边际响应。",
        "T8": "本表证明：公平约束有代价曲线和可行边界。",
        "T9": "本表证明：动态重规划状态闭合且三机制持续参与。",
    }
    for table_id in TABLE_SLUGS:
        lines.extend([f"## {table_id}", "", table_claims[table_id], "", f"CSV：`mock_data/{TABLE_CSV_NAMES[table_id]}`", "", f"表注模板：{TABLE_NOTES[table_id]}", ""])
        lines.append("字段：")
        for field, header in TABLE_SPECS[table_id]:
            lines.append(f"- `{field}`：{header}")
        lines.append("")
    lines.extend(["## T9 附录阶段明细", "", "本表证明：正文 T9 的代表事件流可追溯到逐阶段状态继承、信息成本和三机制指标。", "", "CSV：`mock_data/t9_appendix_stage_detail.csv`", "", f"表注模板：{TABLE_NOTES['T9_APPENDIX']}", ""])
    lines.append("字段：")
    for field, header in TABLE_SPECS["T9_APPENDIX"]:
        lines.append(f"- `{field}`：{header}")
    lines.append("")
    lines.extend(
        [
            "## F1 主解路线图",
            "本图证明：混合车队分工与跨场协同的空间形态。CSV：`f1_route_nodes.csv`, `f1_route_lines.csv`。路线编码固定为燃油车同色实线、电动车同色虚线；跨场服务客户使用黑色描边。",
            "",
            "## F2 算法性能",
            "本图证明：主算法收敛更快、终值更优更稳。样板固定为按算例分面的收敛曲线+终值箱线图；重跑硬要求：逐 eval 收敛日志、seed、参考已观测最优、等墙钟账本。",
            "",
            "## F3 两层减碳",
            "本图证明：同 T6 的三行链条能分解动力替换与充电择时的贡献。",
            "",
            "## F4 48槽碳强度与充电负荷",
            "本图证明：碳感知充电把充电量移向低碳时段。",
            "",
            "## F5 碳价响应",
            "本图证明：现实邻域边际起效，宽域压力下才出现明显阈值。",
            "",
            "## F6 公平前沿",
            "本图证明：公平收紧会压缩协同空间并提高成本；重跑硬要求：θ 细网格覆盖 binding 区间。",
            "",
            "## F7 动态时间线",
            "本图证明：事件到达触发重规划，同时协同、公平和低碳充电在阶段间持续活跃；重跑硬要求：事件、冻结段、静态后见基线、阶段公平比、跨场服务数、低碳时段充电占比。",
            "",
            "若真实数据中协同≈0、公平不 binding 或动态三交互缺列，结论应为实验设计回炉，不得靠表格掩饰。",
            "",
        ]
    )
    return "\n".join(lines)


def _preview_tex() -> str:
    table_blocks = "\n".join(
        [
            f"\\begin{{table}}[H]\\centering\\caption{{{table_id} 样板}}\\setptabsetup\\input{{tables/{table_id.lower()}_{slug}.tex}}\\end{{table}}"
            for table_id, slug in TABLE_SLUGS.items()
        ]
    )
    figures = [
        ("F1 主解路线图", "figure_f1_route_map.pdf"),
        ("F2 算法性能", "figure_f2_algorithm_performance.pdf"),
        ("F3 两层减碳", "figure_f3_two_layer_carbon.pdf"),
        ("F4 48槽碳强度与充电负荷", "figure_f4_48slot_charging.pdf"),
        ("F5 碳价响应", "figure_f5_carbon_response.pdf"),
        ("F6 公平前沿", "figure_f6_fairness_frontier.pdf"),
        ("F7 动态时间线", "figure_f7_dynamic_timeline.pdf"),
    ]
    figure_blocks = "\n".join(
        [f"\\begin{{figure}}[H]\\centering\\includegraphics[width=0.92\\linewidth]{{figures/{filename}}}\\caption{{{caption}（样例数据/非实验结果）}}\\end{{figure}}" for caption, filename in figures]
    )
    appendix_block = "\\appendix\n\\section*{附录：动态阶段明细样板}\n\\begin{table}[H]\\centering\\caption{T9 附录：代表事件流逐阶段明细}\\setptabsetup\\input{tables/t9_appendix_stage_detail.tex}\\end{table}"
    return rf"""\documentclass{{setp-new}}
\usepackage{{fontspec}}
\setmainfont{{Times New Roman}}
\setsansfont{{Arial}}
\IfFontExistsTF{{Songti SC}}{{\newcommand{{\setpSongFont}}{{Songti SC}}}}{{\newcommand{{\setpSongFont}}{{SimSun}}}}
\IfFontExistsTF{{Heiti SC}}{{\newcommand{{\setpHeiFont}}{{Heiti SC}}}}{{\newcommand{{\setpHeiFont}}{{SimHei}}}}
\IfFontExistsTF{{Songti SC}}{{\newcommand{{\setpFangSongFont}}{{Songti SC}}}}{{\newcommand{{\setpFangSongFont}}{{FangSong}}}}
\setCJKmainfont[BoldFont=\setpHeiFont]{{\setpSongFont}}
\setCJKsansfont{{\setpHeiFont}}
\setCJKmonofont{{\setpSongFont}}
\setCJKfamilyfont{{zhsong}}[BoldFont=\setpHeiFont]{{\setpSongFont}}
\setCJKfamilyfont{{zhhei}}{{\setpHeiFont}}
\setCJKfamilyfont{{zhfs}}{{\setpFangSongFont}}
\providecommand{{\songti}}{{}}
\providecommand{{\heiti}}{{}}
\providecommand{{\fangsong}}{{}}
\renewcommand{{\songti}}{{\CJKfamily{{zhsong}}}}
\renewcommand{{\heiti}}{{\CJKfamily{{zhhei}}}}
\renewcommand{{\fangsong}}{{\CJKfamily{{zhfs}}}}
\usepackage{{graphicx}}
\usepackage{{booktabs}}
\usepackage{{array}}
\usepackage{{float}}
\usepackage{{ragged2e}}
\newcommand{{\setptabsetup}}{{\scriptsize\renewcommand{{\arraystretch}}{{0.90}}\setlength{{\tabcolsep}}{{2.2pt}}\setlength{{\aboverulesep}}{{0.4pt}}\setlength{{\belowrulesep}}{{0.4pt}}\hbadness=10000}}
\jolname{{系统工程理论与实践}}{{Systems Engineering --- Theory \& Practice}}
\Title{{ReSETP 论文图表样板预览}}
\Author{{样例}}{{样例}}
\Abstract{{本文件仅用于预览图表样板，所有数值均为样例数据。}}
\Keywords{{样板；图表契约；非实验结果}}
\ETitle{{Preview of ReSETP Table and Figure Templates}}
\EAuthor{{Sample}}{{Sample}}
\EAbstract{{This file previews table and figure templates only. All values are mock data.}}
\EKeywords{{template; data contract; mock result}}
\begin{{document}}
\maketitle
\section*{{说明}}
本文件仅用于预览图表样板。所有表图均为样例数据/非实验结果。
{table_blocks}
{figure_blocks}
{appendix_block}
\end{{document}}
"""


def _report_markdown(mock_data: dict[str, Path], table_tex: dict[str, Path], figure_outputs: dict[str, tuple[Path, Path]]) -> str:
    lines = ["# ReSETP 图表样板生成报告", "", "本轮未运行 solver，未读取 formal fallback，未覆盖正式 generated 目录。", "", "## Mock CSV"]
    lines.extend(f"- {key}: `{path}`" for key, path in sorted(mock_data.items()))
    lines.extend(["", "## Tables"])
    lines.extend(f"- {key}: `{path}`" for key, path in sorted(table_tex.items()))
    lines.extend(["", "## Figures"])
    lines.extend(f"- {key}: `{paths[0]}` / `{paths[1]}`" for key, paths in sorted(figure_outputs.items()))
    lines.append("")
    return "\n".join(lines)


def _cleanup_appledouble(output_dir: Path) -> None:
    for path in output_dir.rglob("._*"):
        if path.is_file() or path.is_symlink():
            path.unlink()
