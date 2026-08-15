#!/usr/bin/env python3
"""Build and audit the China-only E3--E7 experiment foundation.

The ``foundation`` and ``plan`` commands are read-only with respect to the
solver: they inspect frozen inputs and write planning/evidence artifacts.  The
``run`` command is fail-closed until a later, explicit formal-search release.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1]
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))
if str(ROOT / "solver/src") not in sys.path:
    sys.path.insert(0, str(ROOT / "solver/src"))

try:  # support both ``python adapter.py`` and package imports in tests
    from .charts import figure_specs, generate_figures
    from .contract import (
        CONTRACT_PATH,
        all_source_paths,
        family_by_id,
        file_sha256,
        instance_rows,
        load_contract,
        map_index,
        pair_id,
        primary_cell_id,
        source_hashes,
        task_id,
    )
    from .statistics import RAW_FIELDS, aggregate_raw, write_csv, write_json
except ImportError:  # pragma: no cover - direct script path
    from charts import figure_specs, generate_figures  # noqa: E402
    from contract import (  # noqa: E402
        CONTRACT_PATH,
        all_source_paths,
        family_by_id,
        file_sha256,
        instance_rows,
        load_contract,
        map_index,
        pair_id,
        primary_cell_id,
        source_hashes,
        task_id,
    )
    from statistics import RAW_FIELDS, aggregate_raw, write_csv, write_json  # noqa: E402

try:
    from .tables import render_tables
except ImportError:  # pragma: no cover - direct script path
    from tables import render_tables


DEFAULT_OUT = PACKAGE / "foundation_20260723"
E2_CLOSEOUT = ROOT / "baselines/e2_final_campaign_20260720/ALGORITHM_EXPERIMENTS_CLOSED_20260720.md"


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"
    return result.stdout.strip()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _hash_output_files(out_dir: Path) -> dict[str, str]:
    excluded = re.compile(r"(^|/)(\._|__pycache__|\.pytest_cache)|\.pyc$|\.tmp$")
    hashes: dict[str, str] = {}
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file() or path.name == "artifact_hashes.json":
            continue
        relative = str(path.relative_to(ROOT))
        if excluded.search(relative):
            continue
        hashes[relative] = file_sha256(path)
    return hashes


def _decision_value(path: Path, key: str) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(key)
    except (json.JSONDecodeError, OSError):
        return None


def _instance_audit(contract: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    expected_regions = set(contract["data"]["regions"])
    expected_sizes = set(contract["data"]["customer_sizes"])
    errors: list[str] = []
    counts_by_region: dict[str, int] = {}
    counts_by_size: dict[str, int] = {}
    maps_by_cell: dict[str, list[int]] = {}
    for row in rows:
        instance_id = row.get("instance_id", "")
        region = row.get("region", "").strip().lower()
        size = int(row["customer_count"])
        if region not in expected_regions:
            errors.append(f"unsupported_region:{instance_id}:{region}")
        if size not in expected_sizes:
            errors.append(f"unsupported_size:{instance_id}:{size}")
        counts_by_region[region] = counts_by_region.get(region, 0) + 1
        counts_by_size[str(size)] = counts_by_size.get(str(size), 0) + 1
        cell = primary_cell_id(row)
        maps_by_cell.setdefault(cell, []).append(map_index(row))
    for cell, maps in maps_by_cell.items():
        if sorted(maps) != [1, 2, 3]:
            errors.append(f"map_replicates:{cell}:{sorted(maps)}")
    if len(rows) != contract["data"]["instance_count"]:
        errors.append(f"instance_count:{len(rows)}")
    if any(count != 27 for count in counts_by_region.values()):
        errors.append(f"region_counts:{counts_by_region}")
    if any(count != 9 for count in counts_by_size.values()):
        errors.append(f"size_counts:{counts_by_size}")
    return {
        "status": "PASS" if not errors else "HALT_INSTANCE_CATALOG",
        "instance_count": len(rows),
        "primary_cell_count": len(maps_by_cell),
        "region_counts": counts_by_region,
        "size_counts": counts_by_size,
        "errors": errors,
    }


def _order_audit(contract: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    order_path = ROOT / contract["data"]["orders"]
    if not order_path.is_file():
        return {"status": "HALT_MISSING_ORDER_FILE", "order_count": 0}
    with order_path.open(newline="", encoding="utf-8-sig") as handle:
        order_rows = list(csv.DictReader(handle))
    expected = {row["instance_id"]: int(row["customer_count"]) for row in rows}
    counts: dict[str, int] = {}
    for row in order_rows:
        counts[row["instance_id"]] = counts.get(row["instance_id"], 0) + 1
    errors = [
        f"{instance_id}:expected={customer_count}:observed={counts.get(instance_id, 0)}"
        for instance_id, customer_count in sorted(expected.items())
        if counts.get(instance_id, 0) != customer_count
    ]
    return {
        "status": "PASS" if not errors else "HALT_ORDER_CATALOG",
        "order_count": len(order_rows),
        "expected_order_count": sum(expected.values()),
        "errors": errors,
    }


def _release_gate_audit(contract: dict[str, Any]) -> dict[str, Any]:
    g1 = ROOT / "data/ChinaInstances/china81_g1_independent_frozen_v2_20260718/decision.json"
    nl3b = ROOT / "baselines/model_verification/china81_vehicle_road_profiles_nl3b_20260720/decision.json"
    legacy_lock = ROOT / "data/ChinaInstances/china_parameter_lock_v2_20260718.json"
    calendar_decision = ROOT / contract["source_contracts"]["calendar_machine_decision"]
    runtime = ROOT / contract["source_contracts"]["runtime_parameters"]
    fleet = ROOT / contract["source_contracts"]["finite_fleet"]
    settlement = ROOT / contract["source_contracts"][
        "spatiotemporal_settlement"
    ]
    approval = ROOT / contract["source_contracts"][
        "algorithm_repair_approval"
    ]
    approval_text = (
        approval.read_text(encoding="utf-8")
        if approval.is_file()
        else ""
    )
    checks = {
        "v6_contract_selected": contract.get("schema", "").endswith(
            "formal-release-contract.v6"
        ),
        "contract_formal_search_allowed_false": contract["formal_search_allowed"] is False,
        "contract_search_evaluations_zero": contract.get(
            "search_evaluations"
        )
        == 0,
        "g1_data_freeze_pass": str(_decision_value(g1, "verdict")).startswith(
            "PASS_CHINA81_G1_INDEPENDENT_DATA_FROZEN"
        ),
        "g1_formal_search_allowed_false": _decision_value(g1, "formal_search_allowed") is False,
        "g1_search_evaluations_zero": _decision_value(g1, "search_evaluations") == 0,
        "nl3b_runtime_join_pass": _decision_value(nl3b, "verdict")
        == "PASS_NL3B_CHINA81_81_OF_81_RUNTIME_JOIN",
        "nl3b_formal_search_allowed_false": _decision_value(nl3b, "formal_search_allowed") is False,
        "nl3b_search_evaluations_zero": _decision_value(nl3b, "search_evaluations") == 0,
        "e2_algorithm_closeout_present": E2_CLOSEOUT.is_file(),
        "legacy_parameter_lock_retained_as_historical": (
            legacy_lock.is_file()
            and _decision_value(legacy_lock, "status") == "NOT_FORMAL"
        ),
        "runtime_authority_pass": _decision_value(runtime, "verdict")
        == "PASS_CITY_DATE_SLOT_PARAMETER_AUTHORITY",
        "finite_fleet_authority_pass": _decision_value(fleet, "verdict")
        == "PASS_FINITE_FLEET_ZERO_SEARCH_WITNESSES",
        "settlement_authority_pass": _decision_value(
            settlement,
            "verdict",
        )
        == "PASS_FAIL_CLOSED_SPATIOTEMPORAL_SETTLEMENT_AUTHORITY",
        "d1_d6_release_approval_present": (
            "CHINA-E3-FORMAL-RELEASE-001" in approval_text
        ),
        "calendar_machine_decision_present": calendar_decision.is_file(),
        "calendar_month_and_date_registered": (
            contract["data"]["calendar"]["formal_status"]
            == "PASS_COMMON_MONTH_AND_EXHIBIT_DATE_REGISTERED"
            and contract["data"]["calendar"][
                "common_default_exhibit_day"
            ]
            == "2025-02-12"
        ),
    }
    return {
        "status": "FOUNDATION_PASS_FORMAL_RELEASE_HELD" if all(checks.values()) else "HALT_RELEASE_AUDIT",
        "checks": checks,
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "release_blockers": [
            "本基础检查不直接放行搜索；只有版本一致的 E2、独立复算、"
            "双臂检查、小规模预算试跑、回归检查和最终 GO 包全部通过后"
            "才能启动 E3。",
            "旧参数锁的 NOT_FORMAL 状态保留为历史记录；当前正式依据是"
            "用户批准的 D1--D6 登记及其城市—日期—半小时、有限车队和"
            "结算三份新版机器检查。",
        ],
    }


def _runtime_bundle_audit(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Load all 81 bundles without invoking a search or evaluating a solution."""

    try:
        from setp_solver.china81 import load_china81_bundle
    except Exception as exc:  # pragma: no cover - environment-specific import
        return {"status": "HALT_RUNTIME_IMPORT", "loaded": 0, "errors": [str(exc)]}
    loaded = 0
    errors: list[str] = []
    for row in rows:
        instance_id = row["instance_id"]
        try:
            bundle = load_china81_bundle(ROOT, instance_id)
            if bundle.formal_search_allowed is not False:
                errors.append(f"{instance_id}:bundle_formal_search_allowed_not_false")
            if bundle.region != row["region"].strip().lower():
                errors.append(f"{instance_id}:region_mismatch")
            loaded += 1
        except Exception as exc:  # keep all failures visible
            errors.append(f"{instance_id}:{type(exc).__name__}:{exc}")
    return {
        "status": "PASS" if not errors else "HALT_RUNTIME_BUNDLE_JOIN",
        "loaded": loaded,
        "expected": len(rows),
        "errors": errors,
        "search_evaluations": 0,
        "formal_search_allowed": False,
    }


def preflight(repo_root: Path = ROOT) -> dict[str, Any]:
    contract = load_contract(repo_root)
    rows = instance_rows(repo_root)
    catalog = _instance_audit(contract, rows)
    orders = _order_audit(contract, rows)
    release = _release_gate_audit(contract)
    runtime = _runtime_bundle_audit(rows)
    source_missing = [
        relative
        for relative in all_source_paths(contract)
        if not (repo_root / relative).is_file()
    ]
    paper = repo_root / "docs/paper_v2/RETIRED_paper_main.tex"
    paper_text = paper.read_text(encoding="utf-8") if paper.is_file() else ""
    paper_hooks = {
        "paper_present": paper.is_file(),
        "e3_e7_placeholder_present": "DATA_PLACEHOLDER" in paper_text,
        "china81_label_present": "China81" in paper_text,
    }
    status = "PASS_FOUNDATION_PREFLIGHT_FORMAL_HELD"
    if any(
        item.get("status", "").startswith("HALT")
        for item in (catalog, orders, release, runtime)
    ) or source_missing:
        status = "HALT_FOUNDATION_PREFLIGHT"
    return {
        "schema": "resetp.china.e3-e7-foundation-preflight.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "contract_path": str(CONTRACT_PATH.relative_to(repo_root)),
        "contract_sha256": file_sha256(repo_root / CONTRACT_PATH.relative_to(repo_root)),
        "git_head": _git_head(),
        "catalog": catalog,
        "orders": orders,
        "runtime_bundle_join": runtime,
        "release_gate": release,
        "source_missing": source_missing,
        "paper_hooks": paper_hooks,
        "source_hashes": source_hashes(contract, repo_root),
        "formal_runs_started": False,
        "note": "本预检只读取冻结输入并加载 runtime bundle；没有调用搜索、评价器或正式实验 runner。",
    }


def build_task_manifest(contract: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    seeds = contract["paired_sampling"]["initial_common_seeds"]
    for family in contract["families"]:
        if family["id"] == "E7":
            continue
        for row in rows:
            for seed in seeds:
                for arm in family["arms"]:
                    tasks.append(
                        {
                            "task_id": task_id(family["id"], row["instance_id"], seed, arm["id"]),
                            "pair_id": pair_id(family["id"], row["instance_id"], seed),
                            "status": "PLANNED_NO_RUN",
                            "formal_search_allowed": False,
                            "search_evaluations": 0,
                            "experiment_id": contract["contract_id"],
                            "family": family["id"],
                            "family_title_zh": family["title_zh"],
                            "instance_id": row["instance_id"],
                            "region": row["region"],
                            "customer_size": int(row["customer_count"]),
                            "map_index": map_index(row),
                            "primary_cell": primary_cell_id(row),
                            "seed": seed,
                            "arm": arm["id"],
                            "arm_label_zh": arm["label_zh"],
                            "paired_fields": contract["paired_sampling"]["paired_fields"],
                            "runtime_date": contract["data"]["runtime_date"],
                            "calendar_panel_days": contract["data"]["calendar"]["panel_days"],
                            "calendar_default_exhibit_day": contract["data"]["calendar"]["common_default_exhibit_day"],
                            "algorithm_id": contract["algorithm"]["frozen_id"],
                            "evaluation_budget": "PENDING_FORMAL_RELEASE",
                            "input_status": "FROZEN_INPUT_REFERENCE_ONLY",
                        }
                    )
    e7 = family_by_id(contract, "E7")
    return {
        "schema": "resetp.china.e3-e7-task-manifest.v1",
        "contract_id": contract["contract_id"],
        "status": "PLANNING_ONLY_FORMAL_SEARCH_HELD",
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "task_count_materialized": len(tasks),
        "task_count_e3_to_e6": len(tasks),
        "seed_expansion_projection": {
            "e3_to_e6_task_count_at_blind_cap": 4 * 81 * 7 * 2,
            "e7_task_count_at_blind_cap": 81 * 7 * 5,
            "status": "NOT_MATERIALIZED_RESULT_BLIND_RULE_ONLY",
        },
        "e7_full_matrix_projection": {
            "dimensions": "81 instances x 5 seeds x 5 arms",
            "task_count": 81 * 5 * 5,
            "calendar_panel_days": contract["data"]["calendar"]["panel_days"],
            "calendar_default_exhibit_day": contract["data"]["calendar"]["common_default_exhibit_day"],
            "stage_diagnostic_record_type": "stage_diagnostic",
            "status": "NOT_MATERIALIZED_FORMAL_SEARCH_HELD",
        },
        "e7_result_blind_gate_projection": {
            **e7["approved_result_blind_gate"],
            "calendar_panel_days": contract["data"]["calendar"]["panel_days"],
        },
        "tasks": tasks,
        "no_formal_runner_invoked": True,
    }


def paper_mapping(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "resetp.china.e3-e7-paper-mapping.v1",
        "paper_tex": contract["paper_mapping"]["paper_tex"],
        "status": "PLACEHOLDER_ONLY_UNTIL_SEALED_RESULTS",
        "source_policy": contract["paper_mapping"],
        "families": {
            family["id"]: {
                "title_zh": family["title_zh"],
                "table_key": f"{family['id'].lower()}_summary_table",
                "figure_keys": family["paper_exhibits"],
                "primary_metric": family["primary_metric"],
                "primary_contrast": family.get("primary_contrast"),
                "secondary_contrasts": family.get("secondary_contrasts", []),
                "arms": [arm["id"] for arm in family["arms"]],
                "result_sentence": "DATA_PLACEHOLDER",
            }
            for family in contract["families"]
        },
        "generation_rule": "只有 formal raw_runs + independent recalc certificate + aggregate decision 可用时才替换 DATA_PLACEHOLDER。",
    }


def _write_foundation(out_dir: Path, preflight_result: dict[str, Any]) -> dict[str, Any]:
    contract = load_contract(ROOT)
    rows = instance_rows(ROOT)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "preflight.json", preflight_result)
    write_json(out_dir / "task_manifest.json", build_task_manifest(contract, rows))
    write_json(out_dir / "figure_specs.json", figure_specs(contract))
    write_json(out_dir / "paper_mapping.json", paper_mapping(contract))
    write_csv(out_dir / "raw_runs.csv", [], list(RAW_FIELDS))
    _write_text(
        out_dir / "paper_tables/README.md",
        "# E3–E7 论文表格接线\n\n当前无正式结果，不能生成数据表。后续由统计器从封存 `raw_runs.csv` 生成 TeX 表，不手填数字。\n",
    )
    metadata = {
        "schema": "resetp.china.e3-e7-foundation-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_id": contract["contract_id"],
        "contract_sha256": file_sha256(CONTRACT_PATH),
        "git_head": _git_head(),
        "algorithm_id": contract["algorithm"]["frozen_id"],
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "formal_runs_started": False,
        "uk_series": "ARCHIVE_ONLY_EXCLUDED",
        "materialized_task_count": 4 * 81 * 5 * 2,
        "blind_cap_e3_to_e6_task_count": 4 * 81 * 7 * 2,
        "e7_full_projection_task_count": 81 * 5 * 5,
        "e7_blind_cap_projection_task_count": 81 * 7 * 5,
        "e7_approved_gate_task_count": 75,
        "formal_calendar": contract["data"]["calendar"],
        "source_hashes": preflight_result.get("source_hashes", {}),
    }
    write_json(out_dir / "metadata.json", metadata)
    decision = {
        "schema": "resetp.china.e3-e7-foundation-decision.v1",
        "decision": "PASS_FOUNDATION_ADAPTER_FORMAL_SEARCH_HELD" if preflight_result["status"].startswith("PASS") else "HALT_FOUNDATION_PREFLIGHT",
        "adapter_preflight": preflight_result["status"],
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "formal_runs_started": False,
        "scientific_result_claim_allowed": False,
        "e2_mutated": False,
        "uk_series_in_mainline": False,
        "unresolved_release_blockers": preflight_result["release_gate"]["release_blockers"],
        "note": "这是适配底座的通过/停止判定，不是 E3-E7 科学结果判定。",
    }
    write_json(out_dir / "decision.json", decision)
    _write_text(
        out_dir / "report.md",
        "\n".join(
            [
                "# 中国 E3–E7 全实验适配底座",
                "",
                f"底座判定：`{decision['decision']}`。",
                "",
                "本次只完成中国数据入口、实验任务、统计、图表和论文接线；没有启动正式搜索，也没有新增任何 E3–E7 结果。",
                "",
                "已固定：81 个中国实例、27 个地区—规模统计 cell、每 cell 三张地图、初始五个共同种子、Holm 五族控制、MV-HGS-SP 只读引用，以及 E7 的协同—公平—时变碳交互指标。",
                "",
                "正式中国日历固定登记为 2025 年 2 月完整 28 日；2025-02-12 只是共同解释日，不替代完整面板。E4/E7 的日级或阶段级诊断分别写入 daily_replay/stage_diagnostic 记录。",
                "",
                "E3–E6 任务是 planning-only；E7 全量 2025 任务只做数量投影，75-task 结果盲接线门也未运行。当前 formal_search_allowed=false 继续生效。",
                "",
                "E2 封存结果未改；UK 系列未删除，但没有进入中国主线 manifest、统计、表和图。",
            ]
        )
        + "\n",
    )
    write_json(
        out_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": _hash_output_files(out_dir),
        },
    )
    return decision


def foundation(out_dir: Path = DEFAULT_OUT) -> dict[str, Any]:
    result = preflight(ROOT)
    decision = _write_foundation(out_dir, result)
    aggregate_raw(out_dir / "raw_runs.csv", out_dir / "aggregates", repo_root=ROOT)
    render_tables(out_dir / "aggregates", out_dir / "paper_tables", repo_root=ROOT)
    generate_figures(out_dir / "raw_runs.csv", out_dir / "figures", repo_root=ROOT)
    write_json(
        out_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": _hash_output_files(out_dir),
        },
    )
    return decision


def _fail_formal_run() -> int:
    raise SystemExit(
        "FORMAL_SEARCH_HELD: 当前中国合同 formal_search_allowed=false；本适配器只生成计划、预检、统计和图表接线，不启动正式搜索。"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("foundation", "preflight", "plan"):
        command = sub.add_parser(name)
        command.add_argument("--out", type=Path, default=DEFAULT_OUT)
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--raw", type=Path, default=DEFAULT_OUT / "raw_runs.csv")
    aggregate.add_argument("--out", type=Path, default=DEFAULT_OUT / "aggregates")
    plot = sub.add_parser("plot")
    plot.add_argument("--raw", type=Path, default=DEFAULT_OUT / "raw_runs.csv")
    plot.add_argument("--out", type=Path, default=DEFAULT_OUT / "figures")
    plot.add_argument(
        "--aggregate",
        type=Path,
        default=None,
        help=(
            "independent-recalc aggregate directory; required before "
            "formal-result figures can be released"
        ),
    )
    tables = sub.add_parser("tables")
    tables.add_argument("--aggregate", type=Path, default=DEFAULT_OUT / "aggregates")
    tables.add_argument("--out", type=Path, default=DEFAULT_OUT / "paper_tables")
    sub.add_parser("run")
    args = parser.parse_args(argv)
    if args.command == "foundation":
        decision = foundation(args.out)
        print(json.dumps(decision, ensure_ascii=False, indent=2))
        return 0 if decision["decision"].startswith("PASS") else 2
    if args.command == "preflight":
        print(json.dumps(preflight(ROOT), ensure_ascii=False, indent=2))
        return 0
    if args.command == "plan":
        contract = load_contract(ROOT)
        manifest = build_task_manifest(contract, instance_rows(ROOT))
        args.out.mkdir(parents=True, exist_ok=True)
        write_json(args.out / "task_manifest.json", manifest)
        print(json.dumps({"status": manifest["status"], "task_count": manifest["task_count_materialized"]}, ensure_ascii=False))
        return 0
    if args.command == "aggregate":
        print(json.dumps(aggregate_raw(args.raw, args.out, repo_root=ROOT), ensure_ascii=False, indent=2))
        return 0
    if args.command == "plot":
        print(
            json.dumps(
                generate_figures(
                    args.raw,
                    args.out,
                    repo_root=ROOT,
                    aggregate_dir=args.aggregate,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "tables":
        print(json.dumps(render_tables(args.aggregate, args.out, repo_root=ROOT), ensure_ascii=False, indent=2))
        return 0
    return _fail_formal_run()


if __name__ == "__main__":
    raise SystemExit(main())
