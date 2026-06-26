#!/usr/bin/env python3
"""09r hard fleet-cap feasibility audit.

Read-only diagnostic. It checks whether E2 generated instances are already
capacity-infeasible once num_cv/num_ev are interpreted as hard route/vehicle
upper bounds under the current Q=1600 kg setting. It does not change promoted
parameters, generated bundles, solver semantics, or paper text.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.construction import build_initial_solution


BENCHMARK_ROOT = Path("models/data_bundle/generated_instances/e2_benchmark")
RAW_ROOT = Path("models/data_bundle/raw_instances/goeke_uk")
PAPER_TEX = Path("docs/paper_submission_final/paper_main.tex")
DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/hard_cap_feasibility_audit_data")
DEFAULT_REPORT = Path("baselines/e2_alns/hard_cap_feasibility_audit.md")
GOEKE_Q_KG = 3650.0
VANILLA_MULTIDEPOT_SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
THREESHIFT_SIZES = (50, 75, 100, 150, 200)
REPLICATES = (1, 2, 3)


@dataclass(frozen=True)
class InstanceRef:
    category: str
    instance: str
    size: int
    replicate: int
    bundle_dir: Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT))
    parser.add_argument("--goeke-q-kg", type=float, default=GOEKE_Q_KG)
    parser.add_argument("--constructor-smoke", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--artifact-commit-hash", default="")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    output_dir = repo_root / args.output_dir
    report_path = repo_root / args.report_path
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    metadata = build_metadata(repo_root, args)
    refs = expected_instances(repo_root)
    source_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    for ref in refs:
        if not ref.bundle_dir.exists():
            missing_rows.append(row_base(ref) | {"status": "MISSING_BUNDLE", "bundle_dir": str(ref.bundle_dir)})
            continue
        try:
            source_row, audit_row = audit_instance(repo_root, ref, float(args.goeke_q_kg))
        except Exception as exc:  # noqa: BLE001 - report, do not hide incomplete audit.
            missing_rows.append(row_base(ref) | {"status": "AUDIT_ERROR", "error": repr(exc)})
            continue
        source_rows.append(source_row)
        audit_rows.append(audit_row)

    summary_rows = summarize_capacity(audit_rows)
    verdict = decide_verdict(audit_rows, source_rows, missing_rows)
    smoke_rows = constructor_smoke(repo_root) if args.constructor_smoke else [
        {
            "category": "",
            "instance": "",
            "status": "SKIPPED",
            "route_count": "",
            "elapsed_seconds": 0.0,
            "error": "constructor smoke disabled by default; capacity lower-bound audit does not need ALNS or warm-start search",
        }
    ]
    metadata["elapsed_seconds"] = round(time.perf_counter() - started, 6)
    metadata["instance_count_expected"] = len(refs)
    metadata["instance_count_audited"] = len(audit_rows)
    metadata["verdict"] = verdict["verdict"]

    write_json(output_dir / "metadata.json", metadata)
    write_csv(output_dir / "capacity_bound_audit.csv", audit_rows)
    write_csv(output_dir / "source_consistency.csv", source_rows)
    write_csv(output_dir / "capacity_summary.csv", summary_rows)
    write_csv(output_dir / "audit_missing_or_error.csv", missing_rows)
    write_csv(output_dir / "constructor_smoke.csv", smoke_rows)
    write_json(output_dir / "conclusion.json", verdict)
    (output_dir / "decision_options.md").write_text(render_decision_options(verdict), encoding="utf-8")
    report_path.write_text(
        render_report(metadata, verdict, audit_rows, source_rows, summary_rows, missing_rows, smoke_rows),
        encoding="utf-8",
    )

    print(json.dumps({"verdict": verdict["verdict"], "audited": len(audit_rows), "expected": len(refs)}, ensure_ascii=False, indent=2))
    return 0 if verdict["verdict"] != "AUDIT_INCOMPLETE" else 2


def build_metadata(repo_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    tex = (repo_root / PAPER_TEX).read_text(encoding="utf-8", errors="ignore")
    return {
        "script": "baselines/e2_alns/hard_cap_feasibility_audit.py",
        "repo_root": str(repo_root),
        "command": " ".join(sys.argv),
        "head": git_output(repo_root, "rev-parse", "HEAD"),
        "artifact_commit_hash": args.artifact_commit_hash or "pending",
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "default_q_capacity": float(DEFAULT_PRICES.Q_capacity),
        "goeke_q_counterfactual": float(args.goeke_q_kg),
        "paper_q_mentions_1600": bool(re.search(r"1\\,600|1600", tex)),
        "paper_fleet_cap_formula_present": "\\label{eq:fleet_size_cap}" in tex,
        "paper_hard_cap_note_present": "不能替代车辆数量硬约束" in tex,
        "frozen_files": [
            "solver/src/setp_solver/prices.py",
            "solver/src/setp_solver/cost.py",
            "solver/src/setp_solver/check.py",
            "solver/src/setp_solver/search/evaluation.py",
            "models/data_bundle/generated_instances/e2_benchmark",
            "docs/paper_submission_final/paper_main.tex",
        ],
        "output_dir": str(DEFAULT_OUTPUT_DIR),
        "report_path": str(DEFAULT_REPORT),
    }


def expected_instances(repo_root: Path) -> list[InstanceRef]:
    refs: list[InstanceRef] = []
    for category, sizes in (
        ("vanilla", VANILLA_MULTIDEPOT_SIZES),
        ("multidepot", VANILLA_MULTIDEPOT_SIZES),
        ("threeshift", THREESHIFT_SIZES),
    ):
        for size in sizes:
            for rep in REPLICATES:
                instance = f"e2-{category}-{size}c-{rep:02d}"
                refs.append(
                    InstanceRef(
                        category=category,
                        instance=instance,
                        size=size,
                        replicate=rep,
                        bundle_dir=repo_root / BENCHMARK_ROOT / category / instance,
                    )
                )
    return refs


def audit_instance(repo_root: Path, ref: InstanceRef, goeke_q: float) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = load_search_bundle(ref.bundle_dir)
    instance_json = read_json(ref.bundle_dir / "instance.json")
    manifest_json = read_json(ref.bundle_dir / "scenario_manifest.json")
    text_counts = read_text_fleet_counts(ref.bundle_dir / "instance_evrptwmf.txt")
    metadata = instance_json.get("metadata", {})
    manifest_metadata = manifest_json.get("metadata", {})
    manifest_config = manifest_json.get("config", {})
    base_path = raw_base_path(repo_root, ref, metadata, manifest_metadata, manifest_config)
    raw_counts = read_text_fleet_counts(base_path) if base_path and base_path.exists() else {"num_cv": None, "num_ev": None}

    customer_nodes = [node for node in bundle.instance.nodes if node.node_type.lower() == "c"]
    depot_count = sum(1 for node in bundle.instance.nodes if node.node_type.lower() == "d")
    station_count = sum(1 for node in bundle.instance.nodes if node.node_type.lower() == "f")
    total_demand = sum(float(node.demand) for node in customer_nodes)
    num_cv = int(bundle.instance.num_cv) if bundle.instance.num_cv is not None else None
    num_ev = int(bundle.instance.num_ev) if bundle.instance.num_ev is not None else None
    total_cap = (num_cv or 0) + (num_ev or 0)
    current_q = float(DEFAULT_PRICES.Q_capacity)

    current_lb = capacity_lower_bound(total_demand, current_q)
    goeke_lb = capacity_lower_bound(total_demand, goeke_q)
    current_surplus = total_cap * current_q - total_demand
    goeke_surplus = total_cap * goeke_q - total_demand
    source_match = (
        eq_opt(num_cv, metadata.get("num_cv"))
        and eq_opt(num_ev, metadata.get("num_ev"))
        and eq_opt(num_cv, manifest_metadata.get("num_cv"))
        and eq_opt(num_ev, manifest_metadata.get("num_ev"))
        and eq_opt(num_cv, manifest_config.get("num_cv"))
        and eq_opt(num_ev, manifest_config.get("num_ev"))
        and eq_opt(num_cv, text_counts.get("num_cv"))
        and eq_opt(num_ev, text_counts.get("num_ev"))
        and (raw_counts.get("num_cv") is None or eq_opt(num_cv, raw_counts.get("num_cv")))
        and (raw_counts.get("num_ev") is None or eq_opt(num_ev, raw_counts.get("num_ev")))
    )

    source_row = row_base(ref) | {
        "bundle_dir": rel(repo_root, ref.bundle_dir),
        "base_instance_path": rel(repo_root, base_path) if base_path else "",
        "bundle_instance_num_cv": num_cv,
        "bundle_instance_num_ev": num_ev,
        "instance_metadata_num_cv": metadata.get("num_cv", ""),
        "instance_metadata_num_ev": metadata.get("num_ev", ""),
        "manifest_metadata_num_cv": manifest_metadata.get("num_cv", ""),
        "manifest_metadata_num_ev": manifest_metadata.get("num_ev", ""),
        "manifest_config_num_cv": manifest_config.get("num_cv", ""),
        "manifest_config_num_ev": manifest_config.get("num_ev", ""),
        "text_num_cv": text_counts.get("num_cv", ""),
        "text_num_ev": text_counts.get("num_ev", ""),
        "raw_num_cv": raw_counts.get("num_cv", ""),
        "raw_num_ev": raw_counts.get("num_ev", ""),
        "source_consistent": source_match,
    }
    audit_row = row_base(ref) | {
        "bundle_dir": rel(repo_root, ref.bundle_dir),
        "customers": len(customer_nodes),
        "depots": depot_count,
        "stations": station_count,
        "num_cv": num_cv,
        "num_ev": num_ev,
        "total_vehicle_cap": total_cap,
        "total_demand_kg": round(total_demand, 6),
        "current_q_kg": current_q,
        "current_capacity_total_kg": round(total_cap * current_q, 6),
        "current_capacity_surplus_kg": round(current_surplus, 6),
        "current_demand_lower_bound_routes": current_lb,
        "current_capacity_bound_feasible": total_cap >= current_lb,
        "goeke_q_kg": goeke_q,
        "goeke_capacity_total_kg": round(total_cap * goeke_q, 6),
        "goeke_capacity_surplus_kg": round(goeke_surplus, 6),
        "goeke_demand_lower_bound_routes": goeke_lb,
        "goeke_capacity_bound_feasible": total_cap >= goeke_lb,
        "route_vehicle_assumption": "one dispatched route consumes one vehicle slot in current checker",
        "source_consistent": source_match,
    }
    return source_row, audit_row


def raw_base_path(repo_root: Path, ref: InstanceRef, *sources: dict[str, Any]) -> Path | None:
    for source in sources:
        value = source.get("base_instance_path")
        if value:
            path = Path(str(value))
            return path if path.is_absolute() else repo_root / path
    candidate = repo_root / RAW_ROOT / f"E-UK{ref.size}_{ref.replicate:02d}.txt"
    return candidate if candidate.exists() else None


def read_text_fleet_counts(path: Path) -> dict[str, int | None]:
    out: dict[str, int | None] = {"num_cv": None, "num_ev": None}
    if not path.exists():
        return out
    text = path.read_text(encoding="utf-8", errors="ignore")
    out["num_cv"] = regex_int(text, r"numPetrolVeh\s*/\s*([0-9]+)\s*/")
    out["num_ev"] = regex_int(text, r"numElectroVeh\s*/\s*([0-9]+)\s*/")
    return out


def constructor_smoke(repo_root: Path) -> list[dict[str, Any]]:
    examples = [
        ("vanilla", "e2-vanilla-10c-01"),
        ("vanilla", "e2-vanilla-100c-01"),
        ("threeshift", "e2-threeshift-200c-02"),
    ]
    rows: list[dict[str, Any]] = []
    for category, instance in examples:
        bundle_dir = repo_root / BENCHMARK_ROOT / category / instance
        started = time.perf_counter()
        try:
            bundle = load_search_bundle(bundle_dir)
            solution = build_initial_solution(bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)
            rows.append(
                {
                    "category": category,
                    "instance": instance,
                    "status": "OK",
                    "route_count": len(solution.routes),
                    "elapsed_seconds": round(time.perf_counter() - started, 6),
                    "error": "",
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "category": category,
                    "instance": instance,
                    "status": "INIT_INFEASIBLE_OR_CONSTRUCTOR_ERROR",
                    "route_count": "",
                    "elapsed_seconds": round(time.perf_counter() - started, 6),
                    "error": str(exc)[:1000],
                }
            )
    return rows


def summarize_capacity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, Any], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(("ALL", "ALL"), []).append(row)
        groups.setdefault((str(row["category"]), "ALL"), []).append(row)
        groups.setdefault((str(row["category"]), int(row["size"])), []).append(row)
    out: list[dict[str, Any]] = []
    for (category, size), items in sorted(groups.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))):
        out.append(
            {
                "category": category,
                "size": size,
                "instance_count": len(items),
                "current_q_infeasible_count": sum(not truthy(row["current_capacity_bound_feasible"]) for row in items),
                "current_q_feasible_count": sum(truthy(row["current_capacity_bound_feasible"]) for row in items),
                "goeke_q_infeasible_count": sum(not truthy(row["goeke_capacity_bound_feasible"]) for row in items),
                "goeke_q_feasible_count": sum(truthy(row["goeke_capacity_bound_feasible"]) for row in items),
                "min_current_capacity_surplus_kg": min(float(row["current_capacity_surplus_kg"]) for row in items),
                "max_current_capacity_surplus_kg": max(float(row["current_capacity_surplus_kg"]) for row in items),
                "min_goeke_capacity_surplus_kg": min(float(row["goeke_capacity_surplus_kg"]) for row in items),
                "max_goeke_capacity_surplus_kg": max(float(row["goeke_capacity_surplus_kg"]) for row in items),
            }
        )
    return out


def decide_verdict(
    audit_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    missing_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if missing_rows or not audit_rows or len(audit_rows) != 69:
        return {
            "verdict": "AUDIT_INCOMPLETE",
            "reason": f"Audited {len(audit_rows)}/69 instances; missing/error rows={len(missing_rows)}.",
        }
    if any(not truthy(row["source_consistent"]) for row in source_rows):
        return {
            "verdict": "METADATA_MISMATCH",
            "reason": "At least one instance has inconsistent num_cv/num_ev across raw, manifest, text, or loaded bundle.",
        }
    current_bad = [row for row in audit_rows if not truthy(row["current_capacity_bound_feasible"])]
    goeke_bad = [row for row in audit_rows if not truthy(row["goeke_capacity_bound_feasible"])]
    if current_bad:
        return {
            "verdict": "HARD_CAP_CAPACITY_INFEASIBLE_CURRENT_Q",
            "reason": (
                f"{len(current_bad)}/69 E2 instances have total_vehicle_cap * 1600kg below total demand. "
                "This is a capacity lower-bound conflict, not an ALNS or warm-start failure."
            ),
            "current_q_infeasible_count": len(current_bad),
            "goeke_q_feasible_count": 69 - len(goeke_bad),
            "goeke_q_infeasible_count": len(goeke_bad),
            "goeke_counterfactual_note": (
                "Goeke Q=3650 is a counterfactual only; it explains part of the conflict but is not promoted by this audit."
            ),
        }
    return {
        "verdict": "CONSTRUCTOR_ONLY_FAILURE",
        "reason": "All instances pass the capacity lower bound under current Q; any warm-start failure should be debugged in construction/search.",
    }


def render_report(
    metadata: dict[str, Any],
    verdict: dict[str, Any],
    audit_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    missing_rows: list[dict[str, Any]],
    smoke_rows: list[dict[str, Any]],
) -> str:
    current_bad = [row for row in audit_rows if not truthy(row["current_capacity_bound_feasible"])]
    goeke_bad = [row for row in audit_rows if not truthy(row["goeke_capacity_bound_feasible"])]
    worst_current = sorted(audit_rows, key=lambda row: float(row["current_capacity_surplus_kg"]))[:8]
    worst_goeke = sorted(audit_rows, key=lambda row: float(row["goeke_capacity_surplus_kg"]))[:8]
    lines = [
        "# 09r 车辆硬上限可行性只读审计",
        "",
        f"Verdict: `{verdict['verdict']}`",
        "",
        "## 一句话结论",
        "",
        (
            "在当前 `Q=1600kg` 且 `num_cv/num_ev` 是硬上限的口径下，E2 69 个正式实例全部从容量下界就不可行。"
            if len(current_bad) == len(audit_rows) and audit_rows
            else f"在当前 `Q=1600kg` 口径下，{len(current_bad)}/{len(audit_rows)} 个实例从容量下界不可行。"
        ),
        "",
        "这不是 warm start 笨，也不是 ALNS 没搜到；只要“一条 route 占用一辆车”成立，`总车辆数 × 1600kg < 总需求` 就已经把可行性否掉了。",
        "",
        "## 当前事实",
        "",
        f"- Repo HEAD: `{metadata['head'][:8]}`",
        f"- Artifact commit hash: `{metadata.get('artifact_commit_hash', 'pending')}`",
        f"- 当前代码/论文容量 `Q`: `{metadata['default_q_capacity']}` kg",
        f"- Goeke 反事实容量: `{metadata['goeke_q_counterfactual']}` kg",
        f"- 论文 hard-cap 公式存在: `{metadata['paper_fleet_cap_formula_present']}`",
        f"- 车辆硬约束说明存在: `{metadata['paper_hard_cap_note_present']}`",
        f"- 审计实例: `{len(audit_rows)}/69`",
        f"- 来源一致性: `{sum(truthy(row['source_consistent']) for row in source_rows)}/{len(source_rows)}`",
        "",
        "## 容量下界结果",
        "",
        "| 口径 | 容量下界不可行 | 容量下界可行 | 解释 |",
        "|---|---:|---:|---|",
        f"| 当前 Q=1600kg | {len(current_bad)} | {len(audit_rows) - len(current_bad)} | 当前正式参数；若车辆数为硬上限，则这些实例不能进入正式 E2/T3。 |",
        f"| Goeke Q=3650kg 反事实 | {len(goeke_bad)} | {len(audit_rows) - len(goeke_bad)} | 只用于说明冲突是否来自容量口径；本报告不自动改参数。 |",
        "",
        "## 最严重的当前 Q 缺口",
        "",
        "| category | instance | cap | demand kg | Q=1600 capacity kg | surplus kg | current lower bound |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in worst_current:
        lines.append(
            f"| {row['category']} | {row['instance']} | {row['total_vehicle_cap']} | {fmt(row['total_demand_kg'])} | "
            f"{fmt(row['current_capacity_total_kg'])} | {fmt(row['current_capacity_surplus_kg'])} | {row['current_demand_lower_bound_routes']} |"
        )
    lines.extend(
        [
            "",
            "## Goeke Q=3650 反事实边界",
            "",
            "| category | instance | cap | demand kg | Q=3650 capacity kg | surplus kg | Goeke lower bound |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in worst_goeke:
        lines.append(
            f"| {row['category']} | {row['instance']} | {row['total_vehicle_cap']} | {fmt(row['total_demand_kg'])} | "
            f"{fmt(row['goeke_capacity_total_kg'])} | {fmt(row['goeke_capacity_surplus_kg'])} | {row['goeke_demand_lower_bound_routes']} |"
        )
    lines.extend(
        [
            "",
            "## 构造器 smoke 只作旁证",
            "",
            "构造器 smoke 是可选旁证，默认不跑，避免让慢构造器拖住容量下界审计。若显式启用，它也不能推翻上面的容量下界结论。",
            "",
            "| category | instance | status | route_count | error |",
            "|---|---|---|---:|---|",
        ]
    )
    for row in smoke_rows:
        lines.append(f"| {row['category']} | {row['instance']} | {row['status']} | {row['route_count']} | {md_escape(str(row['error'])[:180])} |")
    if missing_rows:
        lines.extend(["", "## Missing/Error Rows", "", f"`{len(missing_rows)}` rows prevented a complete audit; see `audit_missing_or_error.csv`.", ""])
    lines.extend(
        [
            "",
            "## 输出文件",
            "",
            "- `baselines/e2_alns/hard_cap_feasibility_audit_data/metadata.json`",
            "- `baselines/e2_alns/hard_cap_feasibility_audit_data/capacity_bound_audit.csv`",
            "- `baselines/e2_alns/hard_cap_feasibility_audit_data/source_consistency.csv`",
            "- `baselines/e2_alns/hard_cap_feasibility_audit_data/capacity_summary.csv`",
            "- `baselines/e2_alns/hard_cap_feasibility_audit_data/constructor_smoke.csv`",
            "- `baselines/e2_alns/hard_cap_feasibility_audit_data/decision_options.md`",
            "- `baselines/e2_alns/hard_cap_feasibility_audit_data/conclusion.json`",
            "",
            "## 决策边界",
            "",
            "本报告不决定改 `Q`、不决定重标车辆数、不决定引入多车次。它只说明：当前 `Q=1600kg + Goeke车辆硬上限 + route=vehicle` 这组三件事不能同时支撑 E2 正式实验。",
            "",
        ]
    )
    return "\n".join(lines)


def render_decision_options(verdict: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# 09r 后续决策表",
            "",
            f"当前审计 verdict: `{verdict['verdict']}`",
            "",
            "## 可以选的三条路",
            "",
            "| 方案 | 做什么 | 优点 | 风险/代价 | 下一步必须验证 |",
            "|---|---|---|---|---|",
            "| A 恢复 Goeke 容量口径 | 将 `Q` 的主场景重新审计为 Goeke 原始 `3650kg` 或同源容量 | 车辆数与原始实例更匹配，来源清楚 | 会影响论文参数表、代码注释、容量/成本/能耗结果，需要重跑正式实验 | 先做 Q=3650 in-memory 可行性和混合比例 gate，不直接落盘 |",
            "| B 保留 Q=1600，重标车辆数 | 继续用当前中型车容量，但按当前容量重新生成/解释 `num_cv/num_ev` | 保住当前车辆容量场景 | 新车辆数不能拍脑袋，必须有文献/行业或生成规则来源 | 先调查同类算例车辆数随容量缩放规则，再生成新实例候选 |",
            "| C 多车次/车辆复用 | 允许一辆车在一个阶段内跑多条 route 或把 route 与 vehicle 解耦 | 理论上可同时保留 Q=1600 和较少车辆 | 这是正式模型变化，涉及时间衔接、固定费、checker、TeX，不是小修 | 先写模型改造计划，不可直接改代码 |",
            "",
            "## 不能做的事",
            "",
            "- 不能继续跑 E2/T3，假装这只是 ALNS 初始化失败。",
            "- 不能只调电池或碳价来绕过容量下界。",
            "- 不能把 Goeke `num_cv/num_ev` 当硬上限，同时又保留当前 `Q=1600kg` 并要求 69 个实例可行。",
            "",
        ]
    )


def row_base(ref: InstanceRef) -> dict[str, Any]:
    return {"category": ref.category, "instance": ref.instance, "size": ref.size, "replicate": ref.replicate}


def capacity_lower_bound(total_demand: float, q: float) -> int:
    if q <= 0:
        return 10**9
    return int(math.ceil((total_demand - 1e-9) / q))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def regex_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def eq_opt(left: Any, right: Any) -> bool:
    if left in {None, ""} and right in {None, ""}:
        return True
    if left in {None, ""} or right in {None, ""}:
        return False
    return int(float(left)) == int(float(right))


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes"}


def rel(repo_root: Path, path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(repo_root))
    except ValueError:
        return str(path)


def fmt(value: Any) -> str:
    return f"{float(value):.1f}"


def md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def git_output(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=repo_root, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return ""


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
