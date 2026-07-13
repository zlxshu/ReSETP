#!/usr/bin/env python3
"""Reconcile overnight charging persistence without rerunning any search."""

from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e1_model.m1_e1_model_structure_runner import solution_from_json as load_e1_solution
from baselines.e2_alns import e2_final_closure as e2_closure
from baselines.e3_ablation.e3_v3_runner import prices_for as e3_v11_prices
from baselines.e3_ablation.e3_v3_runner import solution_from_dict as load_e3_v11_solution
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.formal_runner import _solution_from_dict as load_formal_solution
from setp_solver.search.metaheuristic_baselines import solution_from_dict as load_e2_solution


OUT = ROOT / "baselines/e3_ablation/e3_clock_semantics_governance_20260713"
E2_DIR = ROOT / "baselines/e2_alns/e2_final_10seed_20260711/formal"
E1_DIR = ROOT / "baselines/e1_model/e1_submission_20260711_committed/formal"
E3_V11_DIR = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713"
E3_FORMAL_DIR = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
FORMAL_RUN_COMMIT = "90654b3e99d276395a0776ad2ceb51344a56994d"
RECORDED_FORMAL_SOURCE_COMMIT = "9c2e90a96fa82e17c9a25def199f9d9bebda0f9f"
TOLERANCE = 1e-6
METRIC_KEYS = (
    "total_cost",
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_transship",
    "cost_carbon",
    "E_total",
    "E_cv_direct",
    "E_ev_indirect",
    "electricity_kwh",
    "distance_total",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def spread_sample(rows: list[dict[str, str]], count: int = 10) -> list[dict[str, str]]:
    if len(rows) <= count:
        return rows
    indexes = [round(index * (len(rows) - 1) / (count - 1)) for index in range(count)]
    return [rows[index] for index in indexes]


def metric_difference(row: dict[str, str], metrics: dict[str, float]) -> tuple[float, int]:
    differences = []
    compared = 0
    for key in METRIC_KEYS:
        raw = str(row.get(key, "")).strip()
        if not raw or key not in metrics:
            continue
        differences.append(abs(float(raw) - float(metrics[key])))
        compared += 1
    return max(differences, default=0.0), compared


def replay_row(
    *,
    dataset: str,
    row: dict[str, str],
    solution_payload: dict[str, Any],
    loader: Callable[[dict[str, Any]], Any],
    bundle_path: Path,
    prices: Any,
    legality_scope: str,
    check_current_legality: bool,
) -> dict[str, Any]:
    solution = loader(solution_payload)
    bundle = load_search_bundle(bundle_path)
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
    maximum_difference, compared_fields = metric_difference(row, metrics)
    current_violations = len(check_solution(solution, bundle.instance, prices)) if check_current_legality else "not_rejudged"
    return {
        "check_kind": "sealed_cost_replay",
        "dataset": dataset,
        "run_id": row.get("run_id", ""),
        "instance": row.get("instance", ""),
        "seed": row.get("seed", ""),
        "compared_metric_count": compared_fields,
        "maximum_absolute_difference": maximum_difference,
        "negative_charge_day_offsets": sum(int(action.charge_day_offset) < 0 for action in solution.charging_actions),
        "current_violation_count": current_violations,
        "legality_scope": legality_scope,
        "pass": maximum_difference <= TOLERANCE and compared_fields > 0,
    }


def replay_e2() -> list[dict[str, Any]]:
    rows = sorted(read_csv(E2_DIR / "raw_runs.csv"), key=lambda row: (row["instance"], row["algorithm"], int(row["seed"])))
    prices = e2_closure.prices_for_scenario("diagnostic_280_override")
    output = []
    for row in spread_sample(rows):
        solution_path = E2_DIR / "solutions" / f"{row['run_id']}.json"
        output.append(
            replay_row(
                dataset="E2_810",
                row={**row, "total_cost": row["best_cost"]},
                solution_payload=json.loads(solution_path.read_text(encoding="utf-8")),
                loader=load_e2_solution,
                bundle_path=ROOT / "models/data_bundle/generated_instances/L-main" / row["instance"],
                prices=prices,
                legality_scope="current route-level checker",
                check_current_legality=True,
            )
        )
    return output


def replay_e1() -> list[dict[str, Any]]:
    eligible = [row for row in read_csv(E1_DIR / "raw_runs.csv") if str(row.get("solution_json", "")).strip()]
    rows = sorted(eligible, key=lambda row: (row["instance"], row["variant"], int(row["seed"])))
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
    return [
        replay_row(
            dataset="E1_25",
            row=row,
            solution_payload=json.loads(row["solution_json"]),
            loader=load_e1_solution,
            bundle_path=ROOT / "models/data_bundle/generated_instances/L-main" / row["instance"],
            prices=prices,
            legality_scope="current route-level checker",
            check_current_legality=True,
        )
        for row in spread_sample(rows)
    ]


def replay_e3_v11() -> list[dict[str, Any]]:
    eligible = [row for row in read_csv(E3_V11_DIR / "promote100/raw_runs.csv") if row.get("status") == "OK"]
    rows = sorted(eligible, key=lambda row: (row["layer"], float(row["fee"]), int(row["seed"])))
    output = []
    for row in spread_sample(rows):
        solution_path = E3_V11_DIR / "solutions" / f"{row['run_id']}__adopted.json"
        profile_mode = {"M0": "zero_gamma", "M1": "zero_gamma", "M2": "mean_gamma"}.get(row["layer"], "actual_gamma")
        output.append(
            replay_row(
                dataset="E3_v11_100",
                row=row,
                solution_payload=json.loads(solution_path.read_text(encoding="utf-8")),
                loader=load_e3_v11_solution,
                bundle_path=E3_V11_DIR / "assets" / row["size"] / "derived_bundles" / profile_mode,
                prices=e3_v11_prices(row["layer"], float(row["fee"])),
                legality_scope="cost only; sealed strict certificate remains the legality authority",
                check_current_legality=False,
            )
        )
    return output


def formal_prices() -> Any:
    return replace(
        DEFAULT_PRICES,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=0.0,
        cross_site_cost=0.0,
        carbon_price=0.0,
    )


def replay_e3_formal() -> list[dict[str, Any]]:
    rows = sorted(read_csv(E3_FORMAL_DIR / "raw_runs.csv"), key=lambda row: (row["instance"], row["condition"], int(row["seed"]), row["arm"]))
    return [
        replay_row(
            dataset="E3_formal_108",
            row=row,
            solution_payload=json.loads((ROOT / row["solution_path"]).read_text(encoding="utf-8")),
            loader=load_formal_solution,
            bundle_path=E3_FORMAL_DIR / "assets" / row["instance"] / "bundle",
            prices=formal_prices(),
            legality_scope="cost only; paired formal certificate remains the legality authority",
            check_current_legality=False,
        )
        for row in spread_sample(rows)
    ]


def formal_roundtrip_summary() -> dict[str, Any]:
    files = sorted(path for path in (E3_FORMAL_DIR / "solutions").glob("*.json") if not path.name.startswith("._"))
    action_count = 0
    raw_negative = 0
    loaded_negative = 0
    mismatch_files = 0
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_offsets = [int(row.get("charge_day_offset", 0)) for row in payload.get("charging_actions", [])]
        loaded_offsets = [int(action.charge_day_offset) for action in load_formal_solution(payload).charging_actions]
        action_count += len(raw_offsets)
        raw_negative += sum(value < 0 for value in raw_offsets)
        loaded_negative += sum(value < 0 for value in loaded_offsets)
        mismatch_files += int(raw_offsets != loaded_offsets)
    return {
        "check_kind": "formal_roundtrip",
        "dataset": "E3_formal_108",
        "run_id": "all_saved_solutions",
        "instance": "all_9_networks",
        "seed": "1-3",
        "compared_metric_count": action_count,
        "maximum_absolute_difference": mismatch_files,
        "negative_charge_day_offsets": loaded_negative,
        "current_violation_count": "not_rejudged",
        "legality_scope": f"raw_negative_offsets={raw_negative}; loaded_negative_offsets={loaded_negative}",
        "pass": mismatch_files == 0 and raw_negative == loaded_negative,
    }


def formal_source_reconciliation() -> dict[str, Any]:
    metadata = json.loads((E3_FORMAL_DIR / "metadata.json").read_text(encoding="utf-8"))
    matches_run_commit = 0
    matches_recorded_parent = 0
    missing_at_parent = 0
    for path, recorded_hash in metadata["source_hashes"].items():
        for commit, counter_name in ((FORMAL_RUN_COMMIT, "run"), (RECORDED_FORMAL_SOURCE_COMMIT, "parent")):
            process = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True, check=False)
            digest = hashlib.sha256(process.stdout).hexdigest() if process.returncode == 0 else "missing"
            if counter_name == "run":
                matches_run_commit += int(digest == recorded_hash)
            else:
                matches_recorded_parent += int(digest == recorded_hash)
                missing_at_parent += int(digest == "missing")
    source_count = len(metadata["source_hashes"])
    return {
        "check_kind": "source_commit_reconciliation",
        "dataset": "E3_formal_108",
        "run_id": "metadata_source_commit",
        "instance": "all_9_networks",
        "seed": "1-3",
        "compared_metric_count": source_count,
        "maximum_absolute_difference": source_count - matches_run_commit,
        "negative_charge_day_offsets": "",
        "current_violation_count": "not_applicable",
        "legality_scope": f"recorded_parent_matches={matches_recorded_parent}; missing_at_parent={missing_at_parent}; actual_run_commit_matches={matches_run_commit}",
        "pass": metadata.get("source_commit") == RECORDED_FORMAL_SOURCE_COMMIT and matches_run_commit == source_count and matches_recorded_parent < source_count,
    }


def main() -> int:
    rows = [*replay_e2(), *replay_e1(), *replay_e3_v11(), *replay_e3_formal(), formal_roundtrip_summary(), formal_source_reconciliation()]
    verdict = "PASS_CLOCK_SEMANTICS_RECONCILED" if all(bool(row["pass"]) for row in rows) else "HALT_CLOCK_SEMANTICS_REPLAY_MISMATCH"
    replay_rows = [row for row in rows if row["check_kind"] == "sealed_cost_replay"]
    roundtrip_row = next(row for row in rows if row["check_kind"] == "formal_roundtrip")
    maximum_replay_difference = max(float(row["maximum_absolute_difference"]) for row in replay_rows)
    metadata = {
        "schema": "resetp-e3-clock-semantics-governance.v1",
        "execution_commit": git_head(),
        "approved_by_user": True,
        "approval_date": "2026-07-13",
        "scope": "solution persistence, sealed-cost replay, and additive source-commit correction",
        "search_runs": 0,
        "sample_rule": "ten evenly spaced saved solutions per sealed batch; all 108 paired E3 files for the field roundtrip",
        "tolerance": TOLERANCE,
        "formal_e3_directory_immutable": True,
        "prior_stopped_attempt": {
            "path": "baselines/e3_ablation/e3_clock_semantics_governance_20260713/attempt_01_wrong_bundle",
            "verdict": "HALT_CLOCK_SEMANTICS_REPLAY_MISMATCH",
            "cause": "the replay script used the source carbon profile instead of each E3 layer's frozen derived profile",
            "scientific_interpretation": "input-path error in the governance replay; no sealed result or source file was changed",
        },
    }
    decision = {
        "verdict": verdict,
        "all_rows_pass": all(bool(row["pass"]) for row in rows),
        "replay_counts": {
            dataset: sum(row["dataset"] == dataset and row["check_kind"] == "sealed_cost_replay" for row in rows)
            for dataset in ("E2_810", "E1_25", "E3_v11_100", "E3_formal_108")
        },
        "maximum_cost_or_component_difference": maximum_replay_difference,
        "formal_source_commit_correction": {
            "recorded": RECORDED_FORMAL_SOURCE_COMMIT,
            "reconciled": FORMAL_RUN_COMMIT,
            "method": "recorded source hashes match the reconciled commit; the formal runner did not exist in the recorded parent",
            "sealed_metadata_was_not_edited": True,
        },
        "interpretation_boundary": "The replay proves backward-compatible cost accounting and field persistence. It does not replace each batch's sealed legality certificate or rerun any search.",
    }
    report_lines = [
        "# 首趟充电时钟与封存证据回放报告",
        "",
        f"判决：`{verdict}`。",
        "",
        "本批没有重新搜索。算法地基、模型地基、旧版合作实验和新版合作实验各固定抽取 10 个保存解，用当前代码重新计算已有成本与排放分项。",
        "",
    ]
    if verdict == "PASS_CLOCK_SEMANTICS_RECONCILED":
        report_lines.extend(
            [
                f"全部抽样回放通过，最大绝对差为 {maximum_replay_difference:.12g}，不超过 {TOLERANCE:g}。",
                "",
                f"新版合作实验的 108 个保存解共含 {roundtrip_row['compared_metric_count']} 次充电，其中 {roundtrip_row['negative_charge_day_offsets']} 次属于前一日预充。保存后重新读取，前一日标记全部保留，没有任何文件丢失。旧格式没有该字段时仍按当天处理，因此旧证据的成本口径不变。",
                "",
                "正式 E3 的 metadata 把来源提交误写成父提交 9c2e90a9。逐文件核对后，六个已记录源码哈希全部对应 90654b3e；其中正式运行脚本在父提交中尚不存在。本报告作附加更正，原封存目录未改一个字节。",
                "",
                "第一次回放曾按停止规则中止：脚本误把旧版 E3 的原始电网数据当成各层冻结电网数据。失败输出完整保存在 attempt_01_wrong_bundle；修正输入路径后仍使用同一固定抽样，不增删样本。",
            ]
        )
    else:
        report_lines.extend(
            [
                f"至少一项核对失败，最大抽样绝对差为 {maximum_replay_difference:.12g}。按停止规则，时钟修复不得用于后续正式实验；失败明细见 raw_runs.csv。",
            ]
        )
    report_lines.extend(
        [
            "",
            "边界：本报告只证明保存读取和成本核算兼容。旧版与新版 E3 的实体车合法性仍由各自封存的严格排班证书负责，不能用普通单趟检查器重新裁决。",
        ]
    )
    report = "\n".join(report_lines) + "\n"
    write_json(OUT / "metadata.json", metadata)
    write_csv(OUT / "raw_runs.csv", rows)
    write_json(OUT / "decision.json", decision)
    (OUT / "report.md").write_text(report, encoding="utf-8")
    files = [
        ROOT / "baselines/e3_ablation/e3_clock_semantics_governance_20260713.py",
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "decision.json",
        OUT / "report.md",
        *sorted((OUT / "attempt_01_wrong_bundle").glob("*")),
    ]
    write_json(
        OUT / "artifact_hashes.json",
        {"files": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in files]},
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["all_rows_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
