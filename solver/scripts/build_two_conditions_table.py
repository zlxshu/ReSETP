#!/usr/bin/env python3
"""生成"两个条件分别与同时成立时本文安排相对即充的变化"表（tab:two-conditions，2026-09-09）。

只读脚本：不跑任何求解，只读 solver/reports/grid2x2_v3_20260906 四格里两臂各 run 的
best_solution.json / metadata.json，写出 docs/paper_v2/generated_tables/two_conditions_table.tex
的 tabular* 片段。

4.4.2 节的结论是"同时降本降碳只可能通过两个条件实现"：谷段与低碳时段重合、车队跨过油电平价点。
本表把两个条件分别施加与同时施加，在同一条件下比较本文安排（cost_plus_carbon，MTC-HGS 臂）
与有可用时段即充电（asap，MT-HGS 臂）——回答 4.4.1 的问题"考虑时变碳强度能否减少总排放"。
每格两臂各 10 次均值；电动车数为 10 次均值（众数只打印到 stderr）；每行两组之间总成本、碳排量较小者加粗。
四格八臂元数据已逐字段核对（同算例、溢价 100 即无补贴、无配额、同停机规则、同首趟窗口、
午谷两格读 china81_cf_calendar_midday_valley_v1_20260904，北京两格读 runtime_parameter_authority_v4），
两臂之间唯一差别是充电时刻打分方式。
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics as st
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GRID_DIR = REPO_ROOT / "solver/reports/grid2x2_v3_20260906"
OUT_TEX = REPO_ROOT / "docs/paper_v2/generated_tables/two_conditions_table.tex"

# (条件标签, 格目录)
ROWS = [
    (r"北京现行时段，碳价0.20（基准）", "beijing/P=0.2"),
    (r"谷段设在午间，碳价0.20", "midday/P=0.2"),
    (r"北京现行时段，碳价1.00", "beijing/P=1.0"),
    (r"谷段设在午间，碳价1.00", "midday/P=1.0"),
]
ARMS = (("MT-HGS", "asap"), ("MTC-HGS", "cost_plus_carbon"))
METRICS = ("total_cost", "E_total", "E_cv_direct", "E_ev_indirect")


def load_arm(cell: Path, arm: str, policy: str) -> list[dict]:
    rows = []
    for run_dir in sorted(p for p in cell.glob(f"{arm}/run_*") if p.is_dir()):
        sol_p = run_dir / "best_solution.json"
        if not sol_p.exists():
            continue
        meta = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        if meta.get("status") != "COMPLETE":
            raise SystemExit(f"{run_dir}: status={meta.get('status')!r}")
        got = (meta.get("mechanism_closure") or {}).get("effective_charge_timing_policy")
        if got != policy:
            raise SystemExit(f"{run_dir}: 实际充电时刻策略 {got!r}，本列要求 {policy!r}")
        if meta.get("effective_ev_daily_premium_cny") != 100.0 or meta.get("effective_carbon_quota_kg") != 0.0:
            raise SystemExit(f"{run_dir}: 溢价/配额与本表口径不符")
        sol = json.loads(sol_p.read_text(encoding="utf-8"))
        if not sol["evaluation"].get("feasible", True):
            raise SystemExit(f"{run_dir}: 解不可行")
        b = sol["evaluation"]["breakdown"]
        row = {k: float(b[k]) for k in METRICS}
        row["fleet"] = f"{int(b['n_veh_cv'])}油{int(b['n_veh_ev'])}电"
        row["n_ev"] = int(b["n_veh_ev"])
        rows.append(row)
    if len(rows) != 10:
        raise SystemExit(f"{cell}/{arm}: 期望 10 次，实得 {len(rows)}")
    return rows


def mode(rows: list[dict]) -> str:
    return collections.Counter(r["fleet"] for r in rows).most_common(1)[0][0]


def delta(x: float) -> str:
    return f"${'+' if x >= 0 else '-'}${abs(x):.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT_TEX)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lines = [
        r"  \begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}ccccccc@{}}",
        r"    \toprule",
        r"    \multirow{2}{*}{条件} & \multicolumn{3}{c}{有可用时段即充电} & \multicolumn{3}{c}{考虑时变碳强度与分时电价}\\",
        r"    \cmidrule(lr){2-4}\cmidrule(lr){5-7}",
        r"     & \makecell{电动车数均值\\（辆）} & \makecell{总成本\\（元）} & \makecell{碳排量\\（kgCO$_2$e）} & "
        r"\makecell{电动车数均值\\（辆）} & \makecell{总成本\\（元）} & \makecell{碳排量\\（kgCO$_2$e）}\\",
        r"    \midrule",
    ]
    for label, rel in ROWS:
        cell = GRID_DIR / rel
        asap = load_arm(cell, *ARMS[0])
        both = load_arm(cell, *ARMS[1])
        ev = [st.mean(r["n_ev"] for r in asap), st.mean(r["n_ev"] for r in both)]
        tc = [st.mean(r["total_cost"] for r in asap), st.mean(r["total_cost"] for r in both)]
        em = [st.mean(r["E_total"] for r in asap), st.mean(r["E_total"] for r in both)]
        tcs = [f"{v:.2f}" for v in tc]; ems = [f"{v:.2f}" for v in em]
        tcs[tc.index(min(tc))] = r"\textbf{" + tcs[tc.index(min(tc))] + "}"
        ems[em.index(min(em))] = r"\textbf{" + ems[em.index(min(em))] + "}"
        lines.append(f"    {label} & {ev[0]:.1f} & {tcs[0]} & {ems[0]} & {ev[1]:.1f} & {tcs[1]} & {ems[1]}\\\\")
        print(f"{label}: 即充 电动车 {ev[0]:.1f} {tc[0]:.2f}/{em[0]:.2f} | 本文 电动车 {ev[1]:.1f} {tc[1]:.2f}/{em[1]:.2f} | 众数 {mode(asap)}→{mode(both)}", file=sys.stderr)
    lines += [r"    \bottomrule", r"  \end{tabular*}"]
    tex = "\n".join(lines) + "\n"
    if args.dry_run:
        print(tex)
    else:
        args.out.write_text(tex, encoding="utf-8")
        print(f"写出 {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
