#!/usr/bin/env python3
"""生成"不同电价时段方案与单位碳价下两种充电安排的对比"表（tab:grid2x2）。

只读脚本：不跑任何求解，只读四格批次里两臂各 run 的 best_solution.json，
写出 docs/paper_v2/generated_tables/grid2x2_table.tex 的 tabular* 片段。

2026-09-06 用户令："路线不变方案"不论代码还是正文一律不得存在（路线是决策变量）。
本表由此从三组列改为两组：
  有可用时段即充电              = 该格 MT-HGS 臂（充电时刻机制关闭＝一可用就充）10 次均值
  考虑时变碳强度与分时电价      = 该格 MTC-HGS 臂（电价＋碳价择时）10 次均值
不再读任何 comparison/summary.json（那是固定路线重排的产物，已删）。
每行两组各取总成本、碳排量；同一行两组之间较小者加粗。
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
OUT_TEX = REPO_ROOT / "docs/paper_v2/generated_tables/grid2x2_table.tex"

# (电价时段方案标签, 单位碳价标签, 格目录)
ROWS = [
    ("北京现行时段", "0.20", "beijing/P=0.2"),
    ("北京现行时段", "1.00", "beijing/P=1.0"),
    ("午间谷段", "0.20", "midday/P=0.2"),
    ("午间谷段", "1.00", "midday/P=1.0"),
]
ARMS = (("有可用时段即充电", "MT-HGS", "asap"), ("考虑时变碳强度与分时电价", "MTC-HGS", "cost_plus_carbon"))


def load_arm(cell: Path, arm: str, policy: str) -> list[dict]:
    rows = []
    for run_dir in sorted(cell.glob(f"{arm}/run_*")):
        sol_p = run_dir / "best_solution.json"
        if not sol_p.exists():
            continue
        meta = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        if meta.get("status") != "COMPLETE":
            raise SystemExit(f"{run_dir}: status={meta.get('status')!r}")
        got = (meta.get("mechanism_closure") or {}).get("effective_charge_timing_policy")
        if got != policy:
            raise SystemExit(f"{run_dir}: 实际充电时刻策略 {got!r}，本列要求 {policy!r}")
        b = json.loads(sol_p.read_text(encoding="utf-8"))["evaluation"]["breakdown"]
        rows.append({"total_cost": float(b["total_cost"]), "E_total": float(b["E_total"]),
                     "fleet": (int(b["n_veh_cv"]), int(b["n_veh_ev"]))})
    if not rows:
        raise SystemExit(f"{cell}/{arm}: 没有任何完成的 run")
    return rows


def fmt(x: float) -> str:
    return f"{x:.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid-dir", type=Path, default=GRID_DIR)
    ap.add_argument("--out", type=Path, default=OUT_TEX)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lines = [
        r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}llcccc@{}}",
        r"\toprule",
        r"\multirow{2}{*}{\makecell{电价\\时段方案}} & \multirow{2}{*}{\makecell{单位碳价\\（元/kgCO$_2$）}} & "
        + " & ".join(r"\multicolumn{2}{c}{" + h + "}" for h, _, _ in ARMS) + r"\\",
        r"\cmidrule(lr){3-4}\cmidrule(lr){5-6}",
        r" & & " + " & ".join([r"\makecell{总成本\\（元）} & \makecell{碳排量\\（kgCO$_2$）}"] * len(ARMS)) + r"\\",
        r"\midrule",
    ]
    prev_label = None
    for label, price, cell_rel in ROWS:
        cell = args.grid_dir / cell_rel
        stats = []
        for _, arm, policy in ARMS:
            rows = load_arm(cell, arm, policy)
            tc = [r["total_cost"] for r in rows]
            em = [r["E_total"] for r in rows]
            fleets = collections.Counter(r["fleet"] for r in rows)
            stats.append((st.mean(tc), st.mean(em)))
            print(f"{label} × {price} {arm}: n={len(rows)} 总成本 {st.mean(tc):.2f}（sd {st.pstdev(tc):.2f}） "
                  f"碳排量 {st.mean(em):.2f}（sd {st.pstdev(em):.2f}） 车队 {dict(fleets)}", file=sys.stderr)
        cells = []
        for (c, e) in stats:
            cc = fmt(c)
            ee = fmt(e)
            cells += [cc, ee]
        if label != prev_label:
            if prev_label is not None:
                lines.append(r"\midrule")
            first = r"\multirow{2}{*}{" + label + "}"
        else:
            first = ""
        lines.append(f"{first} & {price} & " + " & ".join(cells) + r"\\")
        prev_label = label
    lines += [r"\bottomrule", r"\end{tabular*}"]
    tex = "\n".join(lines) + "\n"
    if not args.dry_run:
        args.out.write_text(tex, encoding="utf-8")
        print(f"已写出: {args.out}", file=sys.stderr)
    print(tex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
