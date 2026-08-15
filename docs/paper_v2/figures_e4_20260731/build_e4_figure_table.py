#!/usr/bin/env python3
"""Build the sealed-data E4 timing-migration figure and main table.

This script reads only the sealed E4 replay and the frozen 48-slot calendar.
It performs no solver call, search, simulation, or experiment.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import subprocess
from collections import defaultdict
from decimal import Decimal, getcontext
from pathlib import Path


getcontext().prec = 40

OUTPUT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = OUTPUT_DIR.parents[2]
E4_DIR = PROJECT_ROOT / "baselines/china_e3_e7/e4_carbon_timing_20260729"
ACTION_CSV = E4_DIR / "action_timing_audit.csv"
RAW_RUNS_CSV = E4_DIR / "raw_runs.csv"
SOURCE_HASHES_JSON = E4_DIR / "artifact_hashes.json"
CALENDAR_CSV = (
    PROJECT_ROOT
    / "data/ChinaInstances/china81_runtime_parameter_authority_v3_20260723"
    / "tariff_carbon_hourly_calendar.csv"
)

TYPICAL_DATE = "2025-02-12"
TYPICAL_DAY_RULE = (
    "固定日历位置：采用冻结日历中的2025-02-12；京津冀、珠三角、成渝分别固定读取"
    "北京、广州（Guangdong源列）、重庆的48个半小时时段，不依据E4结果筛选。"
)
REPRESENTATIVE_GRIDS = (
    ("jjj", "京津冀（北京）", "beijing", "Beijing"),
    ("prd", "珠三角（广东）", "guangzhou", "Guangdong"),
    ("cy", "成渝（重庆）", "chongqing", "Chongqing"),
)

ACTION_REQUIRED = (
    "task_id",
    "instance_id",
    "region",
    "seed",
    "grid_date",
    "action_index",
    "energy_kwh",
    "earliest_start_second",
    "latest_start_second",
    "asap_start_second",
    "carbon_start_second",
    "asap_actual_emissions_kg",
    "carbon_actual_emissions_kg",
)
RAW_REQUIRED = (
    "task_id",
    "instance_id",
    "region",
    "seed",
    "grid_date",
    "charging_action_count",
    "charging_energy_kwh",
    "asap_charging_emissions_kg",
    "carbon_charging_emissions_kg",
    "asap_system_total_emissions_kg",
    "carbon_system_total_emissions_kg",
    "asap_charging_electricity_cost_cny",
    "carbon_charging_electricity_cost_cny",
    "asap_full_model_cost_cny",
    "carbon_full_model_cost_cny",
)
CALENDAR_REQUIRED = (
    "city",
    "region",
    "date",
    "hourly_calendar_row",
    "minute_of_day",
    "carbon_factor_kgco2e_per_kwh",
    "carbon_source_column",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path, required: tuple[str, ...]) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        missing = sorted(set(required) - set(fields))
        if missing:
            raise ValueError(f"{path}: missing fields {missing}")
        rows = list(reader)
    null_rows = [
        index + 2
        for index, row in enumerate(rows)
        if any(not row[field].strip() for field in required)
    ]
    if null_rows:
        raise ValueError(f"{path}: blank required values at rows {null_rows[:10]}")
    return rows, fields


def decimal_sum(rows: list[dict[str, str]], field: str) -> Decimal:
    return sum((Decimal(row[field]) for row in rows), Decimal("0"))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fmt_decimal(value: Decimal, places: int) -> str:
    return f"{value:.{places}f}"


def tex_number(value: Decimal, places: int) -> str:
    rendered = f"{value:,.{places}f}"
    return rendered.replace(",", r"\,")


def validate_hashes() -> dict[str, str]:
    source_hashes = json.loads(SOURCE_HASHES_JSON.read_text(encoding="utf-8"))
    expected = {
        "action_timing_audit.csv": source_hashes["artifacts"]["action_timing_audit.csv"],
        "raw_runs.csv": source_hashes["artifacts"]["raw_runs.csv"],
        "tariff_carbon_hourly_calendar.csv": source_hashes["calendar_sha256"],
    }
    observed = {
        "action_timing_audit.csv": sha256(ACTION_CSV),
        "raw_runs.csv": sha256(RAW_RUNS_CSV),
        "tariff_carbon_hourly_calendar.csv": sha256(CALENDAR_CSV),
    }
    mismatches = {name: (expected[name], digest) for name, digest in observed.items() if digest != expected[name]}
    if mismatches:
        raise ValueError(f"sealed input hash mismatch: {mismatches}")
    return observed


def build_aggregates(
    action_rows: list[dict[str, str]],
    raw_rows: list[dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    action_by_pair: dict[tuple[str, str, str, str], list[Decimal | int]] = defaultdict(
        lambda: [0, Decimal("0")]
    )
    binned = {
        "ASAP": [Decimal("0") for _ in range(48)],
        "CARBON": [Decimal("0") for _ in range(48)],
    }
    window_violations = 0
    boundary_tolerance = Decimal("0.000000001")
    out_of_day = 0
    nonpositive_energy = 0
    unique_action_keys: set[tuple[str, str, str, str, str]] = set()

    for row in action_rows:
        pair_key = (row["task_id"], row["instance_id"], row["seed"], row["grid_date"])
        action_key = (*pair_key, row["action_index"])
        unique_action_keys.add(action_key)
        energy = Decimal(row["energy_kwh"])
        lower = Decimal(row["earliest_start_second"])
        upper = Decimal(row["latest_start_second"])
        starts = {
            "ASAP": Decimal(row["asap_start_second"]),
            "CARBON": Decimal(row["carbon_start_second"]),
        }
        action_by_pair[pair_key][0] += 1
        action_by_pair[pair_key][1] += energy
        if energy <= 0:
            nonpositive_energy += 1
        for strategy, start in starts.items():
            if start < lower - boundary_tolerance or start > upper + boundary_tolerance:
                window_violations += 1
            if not (Decimal("0") <= start < Decimal("86400")):
                out_of_day += 1
                continue
            slot_index = int(start // Decimal("1800"))
            binned[strategy][slot_index] += energy

    if len(unique_action_keys) != len(action_rows):
        raise ValueError("action_timing_audit.csv contains duplicate session-day action keys")
    if window_violations or out_of_day or nonpositive_energy:
        raise ValueError(
            "invalid action rows: "
            f"window={window_violations}, out_of_day={out_of_day}, nonpositive_energy={nonpositive_energy}"
        )

    raw_keys: set[tuple[str, str, str, str]] = set()
    reconciliation_mismatches = 0
    for row in raw_rows:
        key = (row["task_id"], row["instance_id"], row["seed"], row["grid_date"])
        raw_keys.add(key)
        observed = action_by_pair.get(key)
        if observed is None:
            reconciliation_mismatches += 1
            continue
        count_matches = observed[0] == int(row["charging_action_count"])
        energy_matches = abs(observed[1] - Decimal(row["charging_energy_kwh"])) <= Decimal("0.000001")
        if not (count_matches and energy_matches):
            reconciliation_mismatches += 1
    extra_action_keys = set(action_by_pair) - raw_keys
    if reconciliation_mismatches or extra_action_keys or len(raw_keys) != len(raw_rows):
        raise ValueError(
            "action/raw reconciliation failed: "
            f"mismatches={reconciliation_mismatches}, extras={len(extra_action_keys)}, "
            f"raw_unique={len(raw_keys)}, raw_rows={len(raw_rows)}"
        )

    total_energy = decimal_sum(action_rows, "energy_kwh")
    if sum(binned["ASAP"], Decimal("0")) != total_energy:
        raise ValueError("ASAP binned energy does not equal the whole-denominator energy")
    if sum(binned["CARBON"], Decimal("0")) != total_energy:
        raise ValueError("CARBON binned energy does not equal the whole-denominator energy")

    distribution_rows: list[dict[str, object]] = []
    for index in range(48):
        asap_energy = binned["ASAP"][index]
        carbon_energy = binned["CARBON"][index]
        distribution_rows.append(
            {
                "hourly_calendar_row": index + 1,
                "start_hour": fmt_decimal(Decimal(index) / Decimal("2"), 1),
                "asap_energy_kwh": fmt_decimal(asap_energy, 9),
                "carbon_energy_kwh": fmt_decimal(carbon_energy, 9),
                "asap_energy_share_pct": fmt_decimal(asap_energy / total_energy * 100, 9),
                "carbon_energy_share_pct": fmt_decimal(carbon_energy / total_energy * 100, 9),
                "energy_denominator_kwh": fmt_decimal(total_energy, 9),
                "session_days": len(action_rows),
            }
        )

    metric_specs = (
        (
            "charging_emissions_kg",
            "充电排放",
            "kg CO2e",
            "asap_charging_emissions_kg",
            "carbon_charging_emissions_kg",
        ),
        (
            "system_emissions_kg",
            "系统排放",
            "kg CO2e",
            "asap_system_total_emissions_kg",
            "carbon_system_total_emissions_kg",
        ),
        (
            "charging_electricity_cost_cny",
            "充电电费",
            "CNY",
            "asap_charging_electricity_cost_cny",
            "carbon_charging_electricity_cost_cny",
        ),
        (
            "full_model_cost_cny",
            "完整模型成本",
            "CNY",
            "asap_full_model_cost_cny",
            "carbon_full_model_cost_cny",
        ),
    )
    table_rows: list[dict[str, object]] = []
    metric_values: dict[str, dict[str, str]] = {}
    for metric_id, metric_cn, unit, asap_field, carbon_field in metric_specs:
        asap = decimal_sum(raw_rows, asap_field)
        carbon = decimal_sum(raw_rows, carbon_field)
        change = (carbon - asap) / asap * 100
        table_rows.append(
            {
                "metric_id": metric_id,
                "metric_cn": metric_cn,
                "unit": unit,
                "denominator": "11340 paired solution-days (405 solutions x 28 dates)",
                "asap_absolute": fmt_decimal(asap, 12),
                "carbon_absolute": fmt_decimal(carbon, 12),
                "relative_change_pct": fmt_decimal(change, 12),
                "paired_solution_days": len(raw_rows),
                "fixed_solutions": len({(r["task_id"], r["instance_id"], r["seed"]) for r in raw_rows}),
                "calendar_days": len({r["grid_date"] for r in raw_rows}),
            }
        )
        metric_values[metric_id] = {
            "asap": fmt_decimal(asap, 12),
            "carbon": fmt_decimal(carbon, 12),
            "relative_change_pct": fmt_decimal(change, 12),
        }

    checks = {
        "session_days": len(action_rows),
        "paired_solution_days": len(raw_rows),
        "fixed_solutions": len({(r["task_id"], r["instance_id"], r["seed"]) for r in raw_rows}),
        "calendar_days": len({r["grid_date"] for r in raw_rows}),
        "action_pair_keys": len(action_by_pair),
        "unique_action_keys": len(unique_action_keys),
        "reconciliation_mismatches": reconciliation_mismatches,
        "extra_action_pair_keys": len(extra_action_keys),
        "window_violations": window_violations,
        "out_of_day_starts": out_of_day,
        "nonpositive_energy_rows": nonpositive_energy,
        "total_energy_kwh": fmt_decimal(total_energy, 12),
        "asap_binned_energy_kwh": fmt_decimal(sum(binned["ASAP"], Decimal("0")), 12),
        "carbon_binned_energy_kwh": fmt_decimal(sum(binned["CARBON"], Decimal("0")), 12),
        "metric_values": metric_values,
    }
    return distribution_rows, table_rows, checks


def build_carbon_curves(calendar_rows: list[dict[str, str]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    selected: dict[str, list[dict[str, str]]] = {}
    for region, label, city, source in REPRESENTATIVE_GRIDS:
        rows = [
            row
            for row in calendar_rows
            if row["region"] == region and row["city"] == city and row["date"] == TYPICAL_DATE
        ]
        rows.sort(key=lambda row: int(row["hourly_calendar_row"]))
        if len(rows) != 48 or {int(row["hourly_calendar_row"]) for row in rows} != set(range(1, 49)):
            raise ValueError(f"incomplete representative curve for {region}/{city}/{TYPICAL_DATE}")
        if {row["carbon_source_column"] for row in rows} != {source}:
            raise ValueError(f"unexpected carbon source for {region}/{city}/{TYPICAL_DATE}")
        selected[region] = rows

    wide_rows: list[dict[str, object]] = []
    for index in range(48):
        row: dict[str, object] = {
            "hourly_calendar_row": index + 1,
            "start_hour": fmt_decimal(Decimal(index) / Decimal("2"), 1),
        }
        for region, _label, _city, _source in REPRESENTATIVE_GRIDS:
            value = Decimal(selected[region][index]["carbon_factor_kgco2e_per_kwh"])
            row[f"{region}_carbon_kgco2e_per_kwh"] = fmt_decimal(value, 8)
            row[f"{region}_carbon_gco2e_per_kwh"] = fmt_decimal(value * 1000, 4)
        wide_rows.append(row)
    selection = {
        "date": TYPICAL_DATE,
        "rule": TYPICAL_DAY_RULE,
        "representative_grids": [
            {"region": region, "label": label, "city": city, "carbon_source_column": source}
            for region, label, city, source in REPRESENTATIVE_GRIDS
        ],
        "slots_per_curve": 48,
    }
    return wide_rows, selection


def render_figure_tex(
    carbon_rows: list[dict[str, object]],
    distribution_rows: list[dict[str, object]],
) -> str:
    carbon_path = "e4_typical_day_carbon.csv"
    distribution_path = "e4_energy_weighted_start_distribution.csv"
    final_carbon = carbon_rows[-1]
    final_distribution = distribution_rows[-1]
    return rf"""\documentclass[tikz,border=3pt]{{standalone}}
\usepackage{{fontspec}}
\usepackage{{xeCJK}}
\usepackage{{pgfplots}}
\usepgfplotslibrary{{groupplots}}
\pgfplotsset{{compat=1.18}}
\setmainfont[Path=/System/Library/Fonts/Supplemental/,BoldFont={{Arial Bold.ttf}}]{{Arial.ttf}}
\setsansfont[Path=/System/Library/Fonts/Supplemental/,BoldFont={{Arial Bold.ttf}}]{{Arial.ttf}}
\setCJKmainfont[Path=/System/Library/Fonts/,BoldFont={{STHeiti Medium.ttc}}]{{STHeiti Light.ttc}}
\setCJKsansfont[Path=/System/Library/Fonts/,BoldFont={{STHeiti Medium.ttc}}]{{STHeiti Light.ttc}}
\renewcommand{{\familydefault}}{{\sfdefault}}
\definecolor{{EBlue}}{{HTML}}{{1F77B4}}
\definecolor{{ERed}}{{HTML}}{{D62728}}
\definecolor{{EGreen}}{{HTML}}{{2CA02C}}
\definecolor{{EGray}}{{HTML}}{{666666}}
\begin{{document}}
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=1 by 2, vertical sep=1.05cm}},
  width=15.1cm,
  height=6.0cm,
  xmin=0,
  xmax=24,
  xtick={{0,4,8,12,16,20,24}},
  tick align=outside,
  tick style={{black, line width=0.45pt}},
  axis line style={{black, line width=0.55pt}},
  axis x line*=bottom,
  axis y line*=left,
  scaled ticks=false,
  label style={{font=\small}},
  tick label style={{font=\small}},
  legend style={{draw=none, fill=none, font=\small, cells={{anchor=west}}}},
  clip=false,
]
\nextgroupplot[
  ylabel={{碳强度（g CO\textsubscript{{2}}e/kWh）}},
  ymin=0,
  ymax=700,
  ytick={{0,100,200,300,400,500,600,700}},
  xticklabels={{}},
  legend columns=3,
  legend style={{at={{(0.02,0.96)}}, anchor=north west, column sep=6pt}},
]
\addplot+[const plot mark right, no marks, color=EBlue, line width=1.05pt]
  table[x=start_hour,y=jjj_carbon_gco2e_per_kwh,col sep=comma] {{{carbon_path}}};
\addlegendentry{{京津冀（北京）}}
\addplot+[no marks, color=EBlue, line width=1.05pt, forget plot]
  coordinates {{(23.5,{final_carbon['jjj_carbon_gco2e_per_kwh']}) (24,{final_carbon['jjj_carbon_gco2e_per_kwh']})}};
\addplot+[const plot mark right, no marks, color=ERed, densely dashed, line width=1.05pt]
  table[x=start_hour,y=prd_carbon_gco2e_per_kwh,col sep=comma] {{{carbon_path}}};
\addlegendentry{{珠三角（广东）}}
\addplot+[no marks, color=ERed, densely dashed, line width=1.05pt, forget plot]
  coordinates {{(23.5,{final_carbon['prd_carbon_gco2e_per_kwh']}) (24,{final_carbon['prd_carbon_gco2e_per_kwh']})}};
\addplot+[const plot mark right, no marks, color=EGreen, dotted, line width=1.25pt]
  table[x=start_hour,y=cy_carbon_gco2e_per_kwh,col sep=comma] {{{carbon_path}}};
\addlegendentry{{成渝（重庆）}}
\addplot+[no marks, color=EGreen, dotted, line width=1.25pt, forget plot]
  coordinates {{(23.5,{final_carbon['cy_carbon_gco2e_per_kwh']}) (24,{final_carbon['cy_carbon_gco2e_per_kwh']})}};
\node[anchor=south west,font=\small] at (rel axis cs:0,1.015) {{(a)}};
\node[anchor=north east,font=\footnotesize,text=EGray] at (rel axis cs:0.995,0.965) {{{TYPICAL_DATE}}};

\nextgroupplot[
  xlabel={{充电开始时刻（h）}},
  ylabel={{充电电量占比（\%）}},
  ymin=0,
  legend columns=2,
  legend style={{at={{(0.98,0.96)}}, anchor=north east, column sep=8pt}},
]
\addplot+[const plot mark right, no marks, color=EGray, densely dashed, line width=1.05pt]
  table[x=start_hour,y=asap_energy_share_pct,col sep=comma] {{{distribution_path}}};
\addlegendentry{{ASAP}}
\addplot+[no marks, color=EGray, densely dashed, line width=1.05pt, forget plot]
  coordinates {{(23.5,{final_distribution['asap_energy_share_pct']}) (24,{final_distribution['asap_energy_share_pct']})}};
\addplot+[const plot mark right, no marks, color=ERed, line width=1.20pt]
  table[x=start_hour,y=carbon_energy_share_pct,col sep=comma] {{{distribution_path}}};
\addlegendentry{{CARBON}}
\addplot+[no marks, color=ERed, line width=1.20pt, forget plot]
  coordinates {{(23.5,{final_distribution['carbon_energy_share_pct']}) (24,{final_distribution['carbon_energy_share_pct']})}};
\node[anchor=south west,font=\small] at (rel axis cs:0,1.015) {{(b)}};
\node[anchor=north west,font=\footnotesize,text=EGray] at (rel axis cs:0.02,0.965)
  {{44,072 个会话日；1,234,753.936 kWh}};
\end{{groupplot}}
\end{{tikzpicture}}
\end{{document}}
"""


def render_caption_tex() -> str:
    return r"""\caption{E4固定路径、车辆、客户服务关系与充电总量条件下的典型日电网碳强度和全分母能量加权充电开始时刻分布：\textup{(a)} 固定日历位置2025年2月12日的京津冀、珠三角和成渝代表电网48个半小时时段碳强度；\textup{(b)} 44,072个会话日按单次充电电量加权的ASAP与CARBON开始时刻分布；两臂的唯一变动量为充电开始时刻。}
\label{fig:e4-timing-migration}
"""


def render_table_tex(table_rows: list[dict[str, object]]) -> str:
    rendered_rows = []
    for row in table_rows:
        asap = Decimal(str(row["asap_absolute"]))
        carbon = Decimal(str(row["carbon_absolute"]))
        change = Decimal(str(row["relative_change_pct"]))
        sign = "+" if change > 0 else ""
        unit = r"kg CO$_2$e" if row["unit"] == "kg CO2e" else "CNY"
        rendered_rows.append(
            f"{row['metric_cn']} & {unit} & 11\\,340解--日对 & "
            f"{tex_number(asap, 3 if row['unit'] == 'kg CO2e' else 2)} & "
            f"{tex_number(carbon, 3 if row['unit'] == 'kg CO2e' else 2)} & "
            f"{sign}{change:.4f} \\\\"
        )
    body = "\n".join(rendered_rows)
    return rf"""\begin{{table*}}[!htbp]
\centering
\caption{{E4固定路径充电择时的排放与成本汇总}}
\label{{tab:e4-main}}
\small
\begin{{tabular}}{{llcrrr}}
\toprule
指标 & 单位 & 分母 & ASAP & CARBON & 相对变化（\%） \\
\midrule
{body}
\bottomrule
\end{{tabular}}

\vspace{{2pt}}
\begin{{minipage}}{{0.94\textwidth}}
\footnotesize 注：每项为405个固定解与28个日历日形成的11,340个配对解--日总量；相对变化按$(\mathrm{{CARBON}}-\mathrm{{ASAP}})/\mathrm{{ASAP}}\times100\%$计算。路径、车辆、客户服务关系和充电总量在两臂间保持固定。
\end{{minipage}}
\end{{table*}}
"""


def compile_figure(tex_path: Path) -> tuple[Path, Path]:
    xelatex = shutil.which("xelatex")
    pdftocairo = shutil.which("pdftocairo")
    if not xelatex or not pdftocairo:
        raise RuntimeError("xelatex and pdftocairo are required to build the figure")
    command = [
        xelatex,
        "--disable-installer",
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]
    subprocess.run(command, cwd=OUTPUT_DIR, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    pdf_path = tex_path.with_suffix(".pdf")
    if not pdf_path.is_file():
        raise RuntimeError("XeLaTeX did not produce the figure PDF")
    png_prefix = OUTPUT_DIR / tex_path.stem
    subprocess.run(
        [pdftocairo, "-png", "-singlefile", "-r", "300", str(pdf_path), str(png_prefix)],
        cwd=OUTPUT_DIR,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    png_path = tex_path.with_suffix(".png")
    if not png_path.is_file():
        raise RuntimeError("pdftocairo did not produce the 300 dpi PNG")
    for suffix in (".aux", ".log"):
        auxiliary = tex_path.with_suffix(suffix)
        if auxiliary.exists():
            auxiliary.unlink()
    return pdf_path, png_path


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    input_hashes = validate_hashes()
    action_rows, _ = read_csv(ACTION_CSV, ACTION_REQUIRED)
    raw_rows, _ = read_csv(RAW_RUNS_CSV, RAW_REQUIRED)
    calendar_rows, _ = read_csv(CALENDAR_CSV, CALENDAR_REQUIRED)

    distribution_rows, table_rows, checks = build_aggregates(action_rows, raw_rows)
    carbon_rows, selection = build_carbon_curves(calendar_rows)

    write_csv(
        OUTPUT_DIR / "e4_energy_weighted_start_distribution.csv",
        [
            "hourly_calendar_row",
            "start_hour",
            "asap_energy_kwh",
            "carbon_energy_kwh",
            "asap_energy_share_pct",
            "carbon_energy_share_pct",
            "energy_denominator_kwh",
            "session_days",
        ],
        distribution_rows,
    )
    write_csv(
        OUTPUT_DIR / "e4_typical_day_carbon.csv",
        [
            "hourly_calendar_row",
            "start_hour",
            "jjj_carbon_kgco2e_per_kwh",
            "jjj_carbon_gco2e_per_kwh",
            "prd_carbon_kgco2e_per_kwh",
            "prd_carbon_gco2e_per_kwh",
            "cy_carbon_kgco2e_per_kwh",
            "cy_carbon_gco2e_per_kwh",
        ],
        carbon_rows,
    )
    write_csv(
        OUTPUT_DIR / "table_e4_main.csv",
        [
            "metric_id",
            "metric_cn",
            "unit",
            "denominator",
            "asap_absolute",
            "carbon_absolute",
            "relative_change_pct",
            "paired_solution_days",
            "fixed_solutions",
            "calendar_days",
        ],
        table_rows,
    )

    figure_tex = OUTPUT_DIR / "figure_e4_timing_migration.tex"
    figure_tex.write_text(render_figure_tex(carbon_rows, distribution_rows), encoding="utf-8")
    (OUTPUT_DIR / "figure_e4_timing_migration_caption.tex").write_text(
        render_caption_tex(), encoding="utf-8"
    )
    (OUTPUT_DIR / "table_e4_main.tex").write_text(render_table_tex(table_rows), encoding="utf-8")
    pdf_path, png_path = compile_figure(figure_tex)

    validation = {
        "schema": "resetp.e4-figure-table-validation.v1",
        "source_mode": "sealed_data_only",
        "new_experiments_run": 0,
        "sources": {
            "action_timing_audit_csv": str(ACTION_CSV.relative_to(PROJECT_ROOT)),
            "raw_runs_csv": str(RAW_RUNS_CSV.relative_to(PROJECT_ROOT)),
            "calendar_csv": str(CALENDAR_CSV.relative_to(PROJECT_ROOT)),
            "sha256": input_hashes,
        },
        "required_fields_complete": True,
        "checks": checks,
        "typical_day_selection": selection,
        "figure": {
            "pdf": pdf_path.name,
            "png": png_path.name,
            "png_requested_dpi": 300,
            "strategy_styles": {
                "ASAP": {"color": "#666666", "line": "dashed"},
                "CARBON": {"color": "#D62728", "line": "solid"},
            },
        },
    }
    (OUTPUT_DIR / "validation_summary.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "BUILT", "checks": checks, "typical_day": selection}, ensure_ascii=False))


if __name__ == "__main__":
    main()
