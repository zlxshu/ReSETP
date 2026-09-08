#!/usr/bin/env python3
"""汇总"不同充电安排下的配送方案对比"表（tab:carbon-charging，四列版，2026-09-06）。

只读脚本：不跑任何求解，只读四个臂目录下各 run 的 best_solution.json / metadata.json，
生成 docs/paper_v2/generated_tables/carbon_charging_table.tex 里的
\\begin{tabular*}...\\end{tabular*} 片段。

四列（用户 2026-09-06 定，路线在四列里都是决策变量，只差安排充电时刻时看什么信号）：
  列1 有可用时段即充电            = asap            （不看电价、不看碳强度；机制关闭即强制 asap）
  列2 考虑分时电价                = cost_min        （只按电价）
  列3 考虑时变碳强度              = carbon_min      （只按碳强度）
  列4 考虑时变碳强度与分时电价    = cost_plus_carbon（电价＋碳价×碳强度）
每列＝该臂全部 run 的算术均值；燃油/电动列＝该臂 10 次里出现最多的车队构型（只打印到 stderr，
不写进表）。所有 run 必须同一算例、同一碳价、同一首趟补电窗口口径、状态 COMPLETE，
且 metadata 里记录的实际充电时刻策略与该列的定义一致，否则直接退出。

取代 2026-09-06 上午的 build_carbon_charging_table.py（三列版，读 comparison/summary.json）。
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics as st
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# (输出键, breakdown 键, 缩放) —— 与 build_charge_timing_comparison.METRICS 同一口径
ROWS = [
    ("总成本（元）", "total_cost", 1.0),
    ("启动成本（元）", "cost_fix", 1.0),
    ("行驶成本（元）", "cost_km", 1.0),
    ("充电成本（元）", "cost_elec", 1.0),
    ("油耗成本（元）", "cost_fuel", 1.0),
    ("碳成本（元）", "cost_carbon", 1.0),
    ("总距离（km）", "distance_total", 1e-3),
    ("充电电量（kWh）", "electricity_kwh", 1.0),
    ("燃油车直接排放（kgCO$_2$e）", "E_cv_direct", 1.0),
    ("电动车充电排放（kgCO$_2$e）", "E_ev_indirect", 1.0),
    ("总排放（kgCO$_2$e）", "E_total", 1.0),
]

# 每行取最小值加粗的行（用户 08-12 通用规矩；是否保留待用户看四列版后定）
BOLD_KEYS = {"total_cost", "E_total"}

COLUMNS = (
    # (列头 tex, 期望的实际充电时刻策略, 参数名)
    # 2026-09-10 用户令：安排名改用文献用语（无序充电 / 有序充电，Li 2024；Woody 2021 回场即充为基准）
    ("无序充电", "asap", "asap_dir"),
    ("电价引导有序充电", "cost_min", "price_dir"),
    ("碳强度引导有序充电", "carbon_min", "carbon_dir"),
    (r"\makecell{考虑时变碳强度\\与分时电价}", "cost_plus_carbon", "both_dir"),
)


def load_arm(arm_dir: Path, expected_policy: str, skip_policy_check: bool) -> tuple[list[dict], dict]:
    runs = []
    shared: dict = {}
    run_dirs = sorted(p for p in arm_dir.glob("run_*") if (p / "best_solution.json").exists())
    if not run_dirs:
        raise SystemExit(f"{arm_dir}: 没有任何带 best_solution.json 的 run 目录")
    for run_dir in run_dirs:
        sol = json.loads((run_dir / "best_solution.json").read_text(encoding="utf-8"))
        meta = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        status = meta.get("status")
        if status not in (None, "COMPLETE", "RUN_COMPLETE"):
            raise SystemExit(f"{run_dir}: status={status!r}")
        policy = (meta.get("mechanism_closure") or {}).get("effective_charge_timing_policy")
        if not skip_policy_check and policy != expected_policy:
            raise SystemExit(f"{run_dir}: 实际充电时刻策略 {policy!r}，本列要求 {expected_policy!r}")
        window = (meta.get("route_engine_wiring") or {}).get("first_trip_window") or "same_day"
        keys = {
            "instance_id": meta.get("instance_id"),
            "carbon_price_cny_per_kg": meta.get("carbon_price_cny_per_kg"),
            "first_trip_window": window,
            "fleet_parameter_class": meta.get("fleet_parameter_class"),
        }
        for k, v in keys.items():
            if k in shared and shared[k] != v:
                raise SystemExit(f"{run_dir}: {k}={v!r} 与同批其他 run 的 {shared[k]!r} 不一致")
            shared[k] = v
        b = sol["evaluation"]["breakdown"]
        if not sol["evaluation"].get("feasible", True):
            raise SystemExit(f"{run_dir}: 解不可行")
        row = {key: float(b[key]) * scale for _, key, scale in ROWS}
        row["fleet"] = (int(b["n_veh_cv"]), int(b["n_veh_ev"]))
        row["run"] = run_dir.name
        runs.append(row)
    return runs, shared


def fmt(x: float) -> str:
    return f"{x:.2f}"


def build_tex(means: list[dict], bold: bool, relative_rows: bool = False, columns=COLUMNS) -> str:
    lines = [r"  \begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}l" + "c" * len(columns) + r"@{}}", r"    \toprule"]
    lines.append("    指标 & " + " & ".join(h for h, _, _ in columns) + r"\\")
    lines.append(r"    \midrule")
    for label, key, _ in ROWS:
        vals = [m[key] for m in means]
        cells = [fmt(v) for v in vals]
        if bold and key in BOLD_KEYS:
            i = vals.index(min(vals))
            cells[i] = r"\textbf{" + cells[i] + "}"
        lines.append(f"    {label} & " + " & ".join(cells) + r"\\")
    if relative_rows:
        # 2026-09-10 用户"美化表格"：追加相对本文安排（末列）的变化率，让"多花多少钱换多少减排"在表内可见
        lines.append(r"    \midrule")
        for label, key in (("总成本较本文安排变化（\%）", "total_cost"), ("总排放较本文安排变化（\%）", "E_total")):
            base = means[-1][key]
            cells = [f"${'+' if m[key] >= base else '-'}${abs(m[key] - base) / base * 100:.2f}" for m in means[:-1]] + ["---"]
            lines.append(f"    {label} & " + " & ".join(cells) + r"\\")
    lines += [r"    \bottomrule", r"  \end{tabular*}"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grid = REPO_ROOT / "solver/reports/grid2x2_v3_20260906/beijing/P=0.2"
    new = REPO_ROOT / "solver/reports/charging_arrangements_20260906"
    ap.add_argument("--asap-dir", type=Path, default=grid / "MT-HGS")
    ap.add_argument("--price-dir", type=Path, default=new / "cost_min")
    ap.add_argument("--carbon-dir", type=Path, default=new / "carbon_min")
    ap.add_argument("--both-dir", type=Path, default=grid / "MTC-HGS")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "docs/paper_v2/generated_tables/carbon_charging_table.tex")
    ap.add_argument("--no-bold", action="store_true", help="总成本/总排放行不加粗")
    ap.add_argument("--no-both", action="store_true", help="2026-09-10 用户令：删去第四列（考虑时变碳强度与分时电价），三列版")
    ap.add_argument("--skip-policy-check", action="store_true", help="只用于脚本自测，正式出表不得使用")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    ap.add_argument("--relative-rows", action="store_true", help="末尾追加两行：总成本/总排放较末列（本文安排）的变化率（%%）")
    ap.add_argument(
        "--statistic",
        choices=("mean", "best"),
        default="mean",
        help="每臂取值口径：mean=该臂全部 run 的算术均值（默认，行为不变）；"
        "best=该臂 run_* 中 total_cost 最小的那一次的各项指标",
    )
    args = ap.parse_args()

    means, shared_all = [], None
    columns = COLUMNS[:3] if args.no_both else COLUMNS
    for header, policy, attr in columns:
        arm_dir = getattr(args, attr).resolve()
        runs, shared = load_arm(arm_dir, policy, args.skip_policy_check)
        if shared_all is None:
            shared_all = shared
        elif shared != shared_all:
            raise SystemExit(f"{arm_dir}: 批次口径 {shared} 与首列 {shared_all} 不一致")
        fleets = collections.Counter(r["fleet"] for r in runs)
        tc = [r["total_cost"] for r in runs]
        em = [r["E_total"] for r in runs]
        print(
            f"[{policy:16s}] {arm_dir.relative_to(REPO_ROOT)}  n={len(runs)}  "
            f"总成本 均值 {st.mean(tc):.2f} sd {st.pstdev(tc):.2f} 极差 {max(tc)-min(tc):.2f}  "
            f"总排放 均值 {st.mean(em):.2f} sd {st.pstdev(em):.2f}  "
            f"车队构型计数 {dict(fleets)}（众数 {fleets.most_common(1)[0][0]}）",
            file=sys.stderr,
        )
        if args.statistic == "best":
            best_run = min(runs, key=lambda r: r["total_cost"])
            m = {key: best_run[key] for _, key, _ in ROWS}
            print(
                f"  → best（total_cost 最小）：{best_run['run']}  "
                f"车队构型(cv,ev)={best_run['fleet']}  total_cost={best_run['total_cost']:.2f}",
                file=sys.stderr,
            )
        else:
            m = {key: st.mean(r[key] for r in runs) for _, key, _ in ROWS}
        means.append(m)
    print(f"批次口径：{shared_all}", file=sys.stderr)
    tex = build_tex(means, bold=not args.no_bold, relative_rows=args.relative_rows, columns=columns)
    if not args.dry_run:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(tex, encoding="utf-8")
        print(f"已写出: {args.out}", file=sys.stderr)
    print(tex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
