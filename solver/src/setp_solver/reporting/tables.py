from __future__ import annotations

import csv
from pathlib import Path

from .schema import read_rows, write_rows


ColumnSpec = tuple[str, str]


TABLE_SPECS: dict[str, list[ColumnSpec]] = {
    "T1": [
        ("instance", "算例"),
        ("customers", "客户数"),
        ("depots", "车场"),
        ("stations", "站点"),
        ("total_demand_kg", "总需求kg"),
        ("window_width_h", "窗宽h"),
        ("deleted_customers", "删除客户数"),
        ("isolated", "孤立客户"),
        ("gamma_slots", "$\\gamma$槽"),
        ("anchor_day", "锚定日"),
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
        ("n_d", "n/d"),
        ("reference_best", "参考最优(来源算法)"),
    ],
    "T4": [
        ("metric", "指标"),
        ("value", "数值"),
        ("share_pct", "占比\\%"),
    ],
    "T5": [
        ("step", "消融层级"),
        ("best", "最优"),
        ("mean", "均值"),
        ("std", "std"),
        ("E_total_kg", "总碳kg"),
        ("delta_vs_full_pct", "相对完整模型变化\\%"),
        ("ev_count", "电车数"),
        ("cross_site_customers", "跨场数"),
        ("min_profit_ratio", "$\\min\\Pi/\\Pi^0$"),
    ],
    "T6": [
        ("case", "方案"),
        ("total_carbon_kg", "总碳"),
        ("charging_carbon_kg", "充电碳"),
        ("mean_intensity_gco2_per_kwh", "均强度"),
        ("total_cost", "总成本"),
    ],
    "T7": [
        ("carbon_price", "碳价"),
        ("quota", "配额"),
        ("total_cost", "总成本"),
        ("fuel_liters", "油耗"),
        ("electricity_cost", "电费"),
        ("carbon_trading_cost", "碳交易成本"),
        ("total_carbon_kg", "总碳"),
        ("ev_count", "电车数"),
        ("feasible", "可行"),
    ],
    "T8": [
        ("theta", "$\\theta$"),
        ("pi_ratio_by_depot", "各场$\\Pi_d/\\Pi_d^0$"),
        ("min_ratio", "最小比值"),
        ("total_cost", "总成本"),
        ("total_carbon_kg", "总碳"),
        ("cross_site_customers", "跨场数"),
        ("feasible", "可行"),
    ],
    "T9": [
        ("stage", "阶段$\\tau$"),
        ("trigger_time", "触发时刻"),
        ("event_counts", "新增/取消/变更数"),
        ("frozen_routes", "冻结路线"),
        ("stage_cost", "阶段成本"),
        ("cumulative_cost", "累计成本"),
        ("cumulative_carbon_kg", "累计碳"),
        ("min_fairness_ratio", "最小公平比"),
        ("feasible", "可行"),
    ],
}


def table_t1_instances(csv_path: str | Path) -> str:
    return csv_to_booktabs(csv_path, TABLE_SPECS["T1"])


def table_t2_parameters(csv_path: str | Path) -> str:
    return csv_to_booktabs(csv_path, TABLE_SPECS["T2"])


def table_t3_algorithm_comparison(csv_path: str | Path) -> str:
    return grouped_csv_to_booktabs(
        csv_path,
        # v2026-06-13: Formal CSV stores base columns as field names; labels are
        # rendered via _base_header_label so values are not blanked.
        base_headers=["instance", "n_d", "reference_best"],
        group_metric_headers=["相对已观测最优偏差\\%", "时间s", "实际评估次数"],
    )


def table_t4_solution_decomposition(csv_path: str | Path) -> str:
    return csv_to_booktabs(csv_path, TABLE_SPECS["T4"])


def table_t5_ablation(csv_path: str | Path) -> str:
    return csv_to_booktabs(csv_path, TABLE_SPECS["T5"])


def table_t6_two_layer_carbon(csv_path: str | Path) -> str:
    return csv_to_booktabs(csv_path, TABLE_SPECS["T6"])


def table_t7_carbon_sensitivity(csv_path: str | Path) -> str:
    fieldnames, _ = _read_rows_with_fieldnames(csv_path)
    if any("|" in field for field in fieldnames):
        return grouped_csv_to_booktabs(
            csv_path,
            base_headers=["碳价"],
            group_metric_headers=["总成本", "油耗", "电费", "碳交易成本", "总碳", "电车数"],
        )
    return csv_to_booktabs(csv_path, TABLE_SPECS["T7"])


def table_t8_fairness_threshold(csv_path: str | Path) -> str:
    return csv_to_booktabs(csv_path, TABLE_SPECS["T8"])


def table_t9_dynamic(csv_path: str | Path) -> str:
    return csv_to_booktabs(csv_path, TABLE_SPECS["T9"])


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


def csv_to_booktabs(csv_path: str | Path, columns: list[ColumnSpec]) -> str:
    rows = read_rows(csv_path)
    col_format = "@{}" + "l" * len(columns) + "@{}"
    lines = [f"\\begin{{tabular}}{{{col_format}}}", "\\toprule"]
    lines.append(" & ".join(header for _, header in columns) + r"\\")
    lines.append("\\midrule")
    if not rows:
        lines.append(r"\multicolumn{" + str(len(columns)) + r"}{l}{无可用行}\\")
    for row in rows:
        lines.append(" & ".join(_latex_cell(_cell_value(row, field, header)) for field, header in columns) + r"\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    return "\n".join(lines)


def grouped_csv_to_booktabs(csv_path: str | Path, *, base_headers: list[str], group_metric_headers: list[str]) -> str:
    fieldnames, rows = _read_rows_with_fieldnames(csv_path)
    groups = _grouped_headers(fieldnames, base_headers)
    col_count = len(base_headers) + sum(len(metrics) for _, metrics in groups)
    col_format = "@{}" + "l" * col_count + "@{}"
    lines = [f"\\begin{{tabular}}{{{col_format}}}", "\\toprule"]

    first_header = [_base_header_label(header) for header in base_headers]
    for group, metrics in groups:
        first_header.append(f"\\multicolumn{{{len(metrics)}}}{{c}}{{{_latex_cell(group)}}}")
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
