from __future__ import annotations

import csv
from pathlib import Path

from .schema import read_rows, write_rows


ColumnSpec = tuple[str, str]


ALGORITHM_DISPLAY_LABELS = {
    "ALNS-Wouda": "ALNS",
    "ALNS@wangqianlongucas": "ALNS",
    "ALNS-WQL": "ALNS",
    "PyGAD": "GA",
    "NSGA-II@haris989": "NSGA-II",
    "VNS@Valdecy": "VNS",
    "scikit-opt-GA": "GA",
    "scikit-opt-SA": "SA",
    "winner kernel": "ALNS",
}


TABLE_SPECS: dict[str, list[ColumnSpec]] = {
    "T1": [
        ("instance", "算例"),
        ("customers", "客户数"),
        ("depots", "车场数"),
        ("stations", "充电站数"),
        ("total_demand_kg", "总需求/kg"),
        ("window_width_h", "平均时间窗宽/h"),
        ("isolated_customer_share_pct", "孤立客户占比/\\%"),
        ("gamma_slots", "$\\gamma$槽数"),
        ("anchor_day", "碳强度锚定日"),
    ],
    "T2": [
        ("symbol", "符号"),
        ("meaning", "含义"),
        ("code_value", "代码值"),
        ("paper_value", "论文值"),
        ("unit", "单位"),
        ("status", "核对"),
    ],
    "T3": [
        ("instance", "算例"),
        ("algorithm", "算法"),
        ("best", "最优/£"),
        ("mean", "均值/£"),
        ("std", "标准差"),
        ("observed_gap_pct", "相对已观测最优偏差/\\%"),
        ("feasible_rate_pct", "可行率/\\%"),
        ("equal_eval_time_s", "等eval耗时/s"),
        ("equal_wallclock_score", "等墙钟成绩"),
        ("significance", "显著性"),
    ],
    "T4": [
        ("metric", "指标"),
        ("cv_only", "仅油车"),
        ("ev_only", "仅电车"),
        ("mixed", "混合"),
    ],
    "T5": [
        ("step", "消融层级"),
        ("mean_std_cost", "成本均值±std/£"),
        ("delta_vs_full_pct", "相对完整模型Δ/\\%"),
        ("significance", "显著性"),
        ("total_carbon_kg", "总排放/kgCO$_2$e"),
        ("ev_routes", "电车路线数"),
        ("cross_site_customers", "跨场服务数"),
        ("min_fairness_ratio", "最小公平比"),
    ],
    "T6": [
        ("case", "方案"),
        ("total_cost", "总成本/£"),
        ("diesel_carbon_kg", "直接排放（燃油）/kgCO$_2$e"),
        ("charging_carbon_kg", "充电间接排放/kgCO$_2$e"),
        ("total_carbon_kg", "总排放/kgCO$_2$e"),
        ("mean_intensity_gco2_per_kwh", "充电加权碳强度/(gCO$_2$/kWh)"),
        ("delta_emission_prev_pct", "相对上一行Δ排放/\\%"),
    ],
    "T7": [
        ("carbon_price_level", "碳价档"),
        ("total_cost", "总成本/£"),
        ("fuel_liters", "燃油量/L"),
        ("charging_kwh", "充电量/kWh"),
        ("charging_centroid_h", "充电时段重心/h"),
        ("carbon_trading_cost", "碳交易成本/£"),
        ("diesel_carbon_kg", "直接排放（燃油）/kgCO$_2$e"),
        ("charging_carbon_kg", "充电间接排放/kgCO$_2$e"),
        ("total_carbon_kg", "总排放/kgCO$_2$e"),
        ("ev_routes", "电车路线数"),
    ],
    "T8": [
        ("theta", "$\\theta$"),
        ("pi_ratio_by_depot", "各场$\\Pi_d/\\Pi_d^0$"),
        ("min_ratio", "最小比值"),
        ("total_cost", "总成本/£"),
        ("total_carbon_kg", "总排放/kgCO$_2$e"),
        ("cross_site_customers", "跨场服务数"),
        ("feasible", "可行"),
    ],
    "T9": [
        ("event_flow", "事件流"),
        ("event_counts", "事件数(新增/取消/变更)"),
        ("replans", "重规划次数"),
        ("final_cost", "最终成本/£"),
        ("hindsight_cost", "静态后见基线/£"),
        ("information_cost", "信息成本"),
        ("total_carbon_kg", "总排放/kgCO$_2$e"),
        ("cross_site_customers", "跨场服务数"),
        ("min_fairness_ratio", "公平比最低值"),
        ("low_carbon_charge_share_pct", "低碳时段充电占比/\\%"),
        ("conservation_audit", "守恒审计"),
    ],
}


def table_t1_instances(csv_path: str | Path) -> str:
    return csv_to_booktabs(csv_path, TABLE_SPECS["T1"], col_format=r"@{}lrrrrrrrl@{}")


def table_t2_parameters(csv_path: str | Path) -> str:
    return csv_to_booktabs(csv_path, TABLE_SPECS["T2"])


def table_t3_algorithm_comparison(csv_path: str | Path) -> str:
    fieldnames, _ = _read_rows_with_fieldnames(csv_path)
    if not any("|" in field for field in fieldnames):
        return csv_to_booktabs(csv_path, TABLE_SPECS["T3"], col_format=r"@{}llrrrrrrll@{}", table_id="T3")
    return grouped_csv_to_long_booktabs(
        csv_path,
        # v2026-06-13: Formal CSV stores base columns as field names; labels are
        # rendered via _base_header_label so values are not blanked.
        base_headers=["instance", "n_d", "reference_best"],
        group_metric_headers=["相对已观测最优偏差\\%", "时间s", "实际评估次数"],
    )


def table_t4_solution_decomposition(csv_path: str | Path) -> str:
    return csv_to_booktabs(csv_path, TABLE_SPECS["T4"], col_format=r"@{}lrrr@{}", table_id="T4")


def table_t5_ablation(csv_path: str | Path) -> str:
    return csv_to_booktabs(
        csv_path,
        TABLE_SPECS["T5"],
        col_format=(
            r"@{}>{\RaggedRight\arraybackslash}p{0.22\linewidth}"
            r">{\centering\arraybackslash}p{0.12\linewidth}"
            r">{\centering\arraybackslash}p{0.11\linewidth}"
            r">{\centering\arraybackslash}p{0.07\linewidth}"
            r">{\centering\arraybackslash}p{0.13\linewidth}"
            r">{\centering\arraybackslash}p{0.09\linewidth}"
            r">{\centering\arraybackslash}p{0.09\linewidth}"
            r">{\centering\arraybackslash}p{0.09\linewidth}@{}"
        ),
        table_id="T5",
    )


def table_t6_two_layer_carbon(csv_path: str | Path) -> str:
    return csv_to_booktabs(
        csv_path,
        TABLE_SPECS["T6"],
        col_format=(
            r"@{}>{\RaggedRight\arraybackslash}p{0.18\linewidth}"
            r">{\centering\arraybackslash}p{0.09\linewidth}"
            r">{\centering\arraybackslash}p{0.13\linewidth}"
            r">{\centering\arraybackslash}p{0.13\linewidth}"
            r">{\centering\arraybackslash}p{0.11\linewidth}"
            r">{\centering\arraybackslash}p{0.14\linewidth}"
            r">{\centering\arraybackslash}p{0.10\linewidth}@{}"
        ),
        table_id="T6",
    )


def table_t7_carbon_sensitivity(csv_path: str | Path) -> str:
    fieldnames, _ = _read_rows_with_fieldnames(csv_path)
    if any("|" in field for field in fieldnames):
        return grouped_csv_to_booktabs(
            csv_path,
            base_headers=["碳价"],
            group_metric_headers=["总成本", "油耗", "电费", "碳交易成本", "总碳", "电车数"],
        )
    return csv_to_booktabs(
        csv_path,
        TABLE_SPECS["T7"],
        col_format=(
            r"@{}>{\RaggedRight\arraybackslash}p{0.105\linewidth}"
            r">{\centering\arraybackslash}p{0.08\linewidth}"
            r">{\centering\arraybackslash}p{0.07\linewidth}"
            r">{\centering\arraybackslash}p{0.07\linewidth}"
            r">{\centering\arraybackslash}p{0.085\linewidth}"
            r">{\centering\arraybackslash}p{0.09\linewidth}"
            r">{\centering\arraybackslash}p{0.11\linewidth}"
            r">{\centering\arraybackslash}p{0.11\linewidth}"
            r">{\centering\arraybackslash}p{0.09\linewidth}"
            r">{\centering\arraybackslash}p{0.06\linewidth}@{}"
        ),
        table_id="T7",
    )


def table_t8_fairness_threshold(csv_path: str | Path) -> str:
    return csv_to_booktabs(csv_path, TABLE_SPECS["T8"], col_format=r"@{}rp{0.23\linewidth}rrrrc@{}", table_id="T8")


def table_t9_dynamic(csv_path: str | Path) -> str:
    return csv_to_booktabs(
        csv_path,
        TABLE_SPECS["T9"],
        col_format=(
            r"@{}>{\centering\arraybackslash}p{0.055\linewidth}"
            r">{\centering\arraybackslash}p{0.09\linewidth}"
            r">{\centering\arraybackslash}p{0.07\linewidth}"
            r">{\centering\arraybackslash}p{0.08\linewidth}"
            r">{\centering\arraybackslash}p{0.09\linewidth}"
            r">{\centering\arraybackslash}p{0.095\linewidth}"
            r">{\centering\arraybackslash}p{0.09\linewidth}"
            r">{\centering\arraybackslash}p{0.07\linewidth}"
            r">{\centering\arraybackslash}p{0.08\linewidth}"
            r">{\centering\arraybackslash}p{0.085\linewidth}"
            r">{\centering\arraybackslash}p{0.06\linewidth}@{}"
        ),
        table_id="T9",
    )


TABLE_BUILDERS = {
    "T1": table_t1_instances,
    "T2": table_t2_parameters,
    "T3": table_t3_algorithm_comparison,
    "T4": table_t4_solution_decomposition,
    "T5": table_t5_ablation,
    "T6": table_t6_two_layer_carbon,
    "T7": table_t7_carbon_sensitivity,
    "T8": table_t8_fairness_threshold,
    "T9": table_t9_dynamic,
}


def csv_to_booktabs(csv_path: str | Path, columns: list[ColumnSpec], *, col_format: str | None = None, table_id: str | None = None) -> str:
    rows = read_rows(csv_path)
    col_format = col_format or "@{}" + "l" * len(columns) + "@{}"
    lines = [f"\\begin{{tabular}}{{{col_format}}}", "\\toprule"]
    lines.append(" & ".join(header for _, header in columns) + r"\\")
    lines.append("\\midrule")
    if not rows:
        lines.append(r"\multicolumn{" + str(len(columns)) + r"}{l}{无可用行}\\")
    for row in rows:
        lines.append(" & ".join(_latex_cell(_display_value(table_id, field, _cell_value(row, field, header))) for field, header in columns) + r"\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    return "\n".join(lines)


def grouped_csv_to_long_booktabs(csv_path: str | Path, *, base_headers: list[str], group_metric_headers: list[str]) -> str:
    fieldnames, rows = _read_rows_with_fieldnames(csv_path)
    groups = _grouped_headers(fieldnames, base_headers)
    metric_headers = [metric for metric in group_metric_headers if any(f"{group}|{metric}" in fieldnames for group, _ in groups)]
    lines = [
        r"\begin{tabular}{@{}lllp{0.18\linewidth}rrr@{}}",
        r"\toprule",
        "算例 & n/d & 算法 & 参考最优 & 偏差\\% & 时间s & 评估次数\\\\",
        r"\midrule",
    ]
    if not rows:
        lines.append(r"\multicolumn{7}{l}{无可用行}\\")
    for row in rows:
        instance = _base_header_value(row, "instance")
        for group, _ in groups:
            values = {
                "相对已观测最优偏差\\%": row.get(f"{group}|相对已观测最优偏差\\%", ""),
                "时间s": row.get(f"{group}|时间s", ""),
                "实际评估次数": row.get(f"{group}|实际评估次数", ""),
            }
            if not any(values.get(metric, "") for metric in metric_headers):
                continue
            lines.append(
                " & ".join(
                    [
                        _latex_cell(instance),
                        _latex_cell(_base_header_value(row, "n_d")),
                        _latex_cell(_algorithm_label(group)),
                        _latex_cell(_display_value("T3", "reference_best", _base_header_value(row, "reference_best"))),
                        _latex_cell(_display_value("T3", "gap", values["相对已观测最优偏差\\%"])),
                        _latex_cell(_display_value("T3", "time", values["时间s"])),
                        _latex_cell(_display_value("T3", "evals", values["实际评估次数"])),
                    ]
                )
                + r"\\"
            )
        if instance not in {"", "Average", "达优次数", "达到最优的算例数"}:
            lines.append(r"\addlinespace[1pt]")
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    return "\n".join(lines)


def grouped_csv_to_booktabs(csv_path: str | Path, *, base_headers: list[str], group_metric_headers: list[str]) -> str:
    fieldnames, rows = _read_rows_with_fieldnames(csv_path)
    groups = _grouped_headers(fieldnames, base_headers)
    col_count = len(base_headers) + sum(len(metrics) for _, metrics in groups)
    col_format = "@{}" + "l" * col_count + "@{}"
    lines = [f"\\begin{{tabular}}{{{col_format}}}", "\\toprule"]

    first_header = [_base_header_label(header) for header in base_headers]
    for group, metrics in groups:
        first_header.append(f"\\multicolumn{{{len(metrics)}}}{{c}}{{{_latex_cell(_algorithm_label(group))}}}")
    lines.append(" & ".join(first_header) + r"\\")

    cmidrules: list[str] = []
    start = len(base_headers) + 1
    for _, metrics in groups:
        end = start + len(metrics) - 1
        cmidrules.append(f"\\cmidrule(lr){{{start}-{end}}}")
        start = end + 1
    if cmidrules:
        lines.append(" ".join(cmidrules))

    second_header = [""] * len(base_headers)
    for _, metrics in groups:
        second_header.extend(_latex_cell(metric) for metric in metrics)
    lines.append(" & ".join(second_header) + r"\\")
    lines.append("\\midrule")

    if not rows:
        lines.append(r"\multicolumn{" + str(col_count) + r"}{l}{无可用行}\\")
    for row in rows:
        values: list[str] = []
        values.extend(_latex_cell(_base_header_value(row, header)) for header in base_headers)
        for group, metrics in groups:
            values.extend(_latex_cell(row.get(f"{group}|{metric}", "")) for metric in metrics)
        lines.append(" & ".join(values) + r"\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    return "\n".join(lines)


def write_table_rows(table_id: str, csv_path: str | Path, rows: list[dict[str, object]]) -> None:
    if table_id not in TABLE_SPECS:
        raise KeyError(f"未知表编号：{table_id}")
    columns = TABLE_SPECS[table_id]
    localized = [
        {header: row.get(field, "") for field, header in columns}
        for row in rows
    ]
    write_rows(csv_path, localized, [header for _, header in columns])


def write_table_fragment(table_id: str, csv_path: str | Path, tex_path: str | Path) -> None:
    if table_id not in TABLE_BUILDERS:
        raise KeyError(f"未知表编号：{table_id}")
    path = Path(tex_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TABLE_BUILDERS[table_id](csv_path), encoding="utf-8")


def _latex_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith("$") or "\\" in text:
        return text
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _display_value(table_id: str | None, field: str, value: object) -> str:
    text = "" if value is None else str(value).strip()
    if text == "":
        return ""
    if table_id == "T5" and field == "step":
        return _compact_ablation_label(text)
    if field in {"total_cost", "best", "mean", "std", "equal_eval_time_s", "final_cost", "hindsight_cost"}:
        return _format_number(text, digits=1)
    if field in {"observed_gap_pct", "feasible_rate_pct", "delta_vs_full_pct", "delta_emission_prev_pct", "low_carbon_charge_share_pct"}:
        return _format_number(text, digits=1)
    if field in {"min_ratio", "min_fairness_ratio", "charging_centroid_h"}:
        return _format_number(text, digits=3)
    if field in {"diesel_carbon_kg", "charging_carbon_kg", "total_carbon_kg", "mean_intensity_gco2_per_kwh", "fuel_liters", "charging_kwh", "carbon_trading_cost"}:
        return _format_number(text, digits=1)
    if table_id in {"T3", "T7", "T8"} and field not in {"algorithm", "carbon_price_level", "pi_ratio_by_depot", "feasible", "equal_wallclock_score", "significance"}:
        return _format_number(text, digits=1)
    if field == "feasible":
        return {"True": "是", "False": "否"}.get(text, text)
    return text


def _algorithm_label(name: str) -> str:
    return ALGORITHM_DISPLAY_LABELS.get(name, name)


def _format_number(text: str, *, digits: int) -> str:
    try:
        value = float(text)
    except ValueError:
        return text
    if abs(value) >= 10000:
        return f"{value:.1f}"
    formatted = f"{value:.{digits}f}"
    return formatted.rstrip("0").rstrip(".")


def _compact_ablation_label(text: str) -> str:
    if " " in text:
        code, detail = text.split(" ", 1)
    elif "_" in text:
        code, detail = text.split("_", 1)
    else:
        return text
    compact = detail.replace("_", " ")
    return f"{code} {compact}"


def _cell_value(row: dict[str, str], field: str, header: str) -> str:
    return row.get(field, row.get(header, ""))


def _read_rows_with_fieldnames(csv_path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    with Path(csv_path).open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _grouped_headers(fieldnames: list[str], base_headers: list[str]) -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = []
    for header in fieldnames:
        if header in base_headers or "|" not in header:
            continue
        group, metric = header.split("|", 1)
        if not any(group == existing for existing, _ in groups):
            groups.append((group, []))
        for existing, metrics in groups:
            if existing == group and metric not in metrics:
                metrics.append(metric)
                break
    for _, metrics in groups:
        metrics.sort(key=lambda item: group_metric_order(item))
    return groups


def group_metric_order(metric: str) -> tuple[int, str]:
    preferred = {
        "相对已观测最优偏差\\%": 0,
        "时间s": 1,
        "实际评估次数": 2,
        "总成本": 0,
        "油耗": 1,
        "电费": 2,
        "碳交易成本": 3,
        "总碳": 4,
        "电车数": 5,
    }
    return preferred.get(metric, 99), metric


def _base_header_label(field: str) -> str:
    # v2026-06-13: Keep grouped table readers on CSV field names while preserving
    # paper-facing labels in formal-backfill output.
    return {
        "instance": "算例",
        "n_d": "n/d",
        "reference_best": "参考最优(来源算法)",
        "carbon_price": "碳价",
    }.get(field, field)


def _base_header_value(row: dict[str, str], field: str) -> str:
    return row.get(field, row.get(_base_header_label(field), ""))
