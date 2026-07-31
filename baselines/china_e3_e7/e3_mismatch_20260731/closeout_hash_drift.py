#!/usr/bin/env python3
"""Seal the zero-search E3 mismatch halt caused by source-contract drift."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EXPECTED_CONTRACT_SHA256 = (
    "075f0093e90bb583b6c9f0431eeaf186cf30ff109dc164923ca914257f503b5e"
)
CURRENT_CONTRACT_SHA256 = (
    "0e10e8ea20917eb140a945909539cc3ee1e649774758252c0477741d4e742c35"
)
INSTANCES = (
    "cn-prd-150c-01-V2-LOCATIONS",
    "cn-prd-150c-02-V2-LOCATIONS",
    "cn-prd-150c-03-V2-LOCATIONS",
    "cn-prd-200c-01-V2-LOCATIONS",
    "cn-prd-200c-02-V2-LOCATIONS",
    "cn-prd-200c-03-V2-LOCATIONS",
)
PROTECTED = {
    "solver/src/setp_solver/cost.py":
        "2717b4b4de39bb4c2a9a1bda602f4420cb3e3b1e87faa83678dfa64f88fc80be",
    "solver/src/setp_solver/check.py":
        "9c81e254e05591667c8225965bb9d0ba4e8bbfc53eb0f8c61ffdb4325a1403a8",
    "solver/src/setp_solver/search/evaluation.py":
        "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
    "solver/src/setp_solver/profit.py":
        "216c4f16f2e26f1c2840fa272adbf1e3ccb056c3de9403dd15b71fa5edfef1dc",
    (
        "baselines/algorithm_prototypes/"
        "china81_mechanism_hybrid_20260720/route_pool_sp.py"
    ):
        "976ef21d4952b3c488300de9a8d3e351411305d26f1e2601ca17c15185d462c1",
    (
        "baselines/algorithm_prototypes/"
        "china81_mechanism_hybrid_20260720/epochal_hgs.py"
    ):
        "655fa347b52a3e8ac20c5da6213c84b09ac90f96c1513ca95554753aad3f8a91",
}
RAW_FIELDS = (
    "instance_id",
    "sample_role",
    "seed",
    "arm",
    "hard_home_depot_lock",
    "total_cost_cny",
    "vehicle_count",
    "route_count",
    "cross_site_service_count",
    "distance_total_m",
    "carbon_emissions_kg",
    "time_window_satisfied_customer_count",
    "wallclock_seconds",
    "complete_candidate_budget_cap",
    "complete_candidate_evaluations_consumed",
    "termination_reason",
    "feasible_candidates",
    "infeasible_candidates",
    "constraint_filtered_candidates",
    "error_candidates",
    "violation_count",
    "solution_sha256",
    "status",
)
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", "monitor_runtime"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def payload_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def remove_appledouble() -> int:
    removed = 0
    for path in sorted(HERE.rglob("._*")):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def main() -> int:
    if (HERE / "done.json").exists():
        raise RuntimeError("done.json already exists")
    if (HERE / "budget_lock.json").exists():
        raise RuntimeError("unexpected budget lock after zero-search halt")
    probe_statuses = [
        path
        for path in (HERE / "probe/task_status").glob("*.json")
        if not path.name.startswith("._")
    ]
    formal_statuses = [
        path
        for path in (HERE / "formal/task_status").glob("*.json")
        if not path.name.startswith("._")
    ]
    if probe_statuses or formal_statuses:
        raise RuntimeError("search artifacts exist; zero-search closeout refused")

    contract = (
        REPO
        / "docs/handoff/"
        "experiment_contract_v2_journal_aligned_20260730.md"
    )
    if sha256(contract) != CURRENT_CONTRACT_SHA256:
        raise RuntimeError("source contract changed again during closeout")
    protected_now = {
        relative: sha256(REPO / relative)
        for relative in PROTECTED
    }
    if protected_now != PROTECTED:
        raise RuntimeError("protected solver or search hash drift")

    audit = json.loads(
        (HERE / "input_audit/summary.json").read_text(encoding="utf-8")
    )
    nonzero = {
        row["instance_id"]: {
            "customer_count": int(row["customer_count"]),
            "mismatch_customer_count": int(
                row["mismatch_customer_count"]
            ),
            "mismatch_rate_pct": float(row["mismatch_rate_pct"]),
        }
        for row in audit["nonzero_instances"]
    }
    mismatch_rates = {
        instance: nonzero[instance]["mismatch_rate_pct"]
        for instance in INSTANCES
    }

    halt_evidence = {
        "schema": "resetp.e3-mismatch-restart.halt-evidence.v1",
        "status": "HALT_SOURCE_CONTRACT_HASH_DRIFT_BEFORE_SEARCH",
        "created_at_utc": now_iso(),
        "search_evaluations_observed": 0,
        "probe_units_started": 0,
        "formal_units_started": 0,
        "expected_source_contract_sha256":
            EXPECTED_CONTRACT_SHA256,
        "observed_source_contract_sha256":
            CURRENT_CONTRACT_SHA256,
        "source_contract_path":
            "docs/handoff/"
            "experiment_contract_v2_journal_aligned_20260730.md",
        "source_contract_mtime_local":
            "2026-07-30T15:13:17+0800",
        "monitor_detection_at_utc":
            "2026-07-30T07:13:23+00:00",
        "monitor_action": "SIGSTOP",
        "monitor_scene":
            "monitor_runtime/campaign/scenes/"
            "20260730-151323-anomaly",
        "protected_solver_and_search_hashes": protected_now,
        "pre_registration_sha256": sha256(
            HERE / "pre_registration.json"
        ),
        "input_audit_sha256": sha256(
            HERE / "input_audit/summary.json"
        ),
    }
    halt_evidence["halt_evidence_id"] = payload_sha256(
        halt_evidence
    )
    atomic_json(HERE / "halt_evidence.json", halt_evidence)

    with (HERE / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        writer.writeheader()
        handle.flush()
        os.fsync(handle.fileno())

    decision = {
        "schema": "resetp.e3-mismatch-restart.decision.v1",
        "task_id": "E3-MISMATCH-RESTART-20260731",
        "verdict":
            "HALT_SOURCE_CONTRACT_HASH_DRIFT_BEFORE_SEARCH",
        "created_at_utc": now_iso(),
        "formal_units_expected": 180,
        "formal_units_run": 0,
        "instances_preregistered": list(INSTANCES),
        "instances_run": [],
        "arms": ["IND", "ZONE", "JOINT"],
        "seeds": list(range(1, 11)),
        "budget_cap": None,
        "effect_ind_to_zone_pct": None,
        "effect_zone_to_joint_pct": None,
        "effect_ind_to_joint_pct": None,
        "halt_evidence_id":
            halt_evidence["halt_evidence_id"],
        "no_result_filtering": True,
        "historical_l_main_numbers_used_as_evidence": False,
    }
    decision["decision_id"] = payload_sha256(decision)
    atomic_json(HERE / "decision.json", decision)

    metadata = {
        "schema": "resetp.e3-mismatch-restart.metadata.v1",
        "task_id": "E3-MISMATCH-RESTART-20260731",
        "status":
            "HALT_SOURCE_CONTRACT_HASH_DRIFT_BEFORE_SEARCH",
        "created_at_utc": now_iso(),
        "instances_preregistered": list(INSTANCES),
        "instances_run": [],
        "arms": ["IND", "ZONE", "JOINT"],
        "seeds": list(range(1, 11)),
        "formal_units_expected": 180,
        "formal_units_run": 0,
        "probe_units_run": 0,
        "search_evaluations_observed": 0,
        "budget_cap": None,
        "input_audit_status": audit["status"],
        "nonzero_mismatch_instances_found":
            audit["nonzero_mismatch_instances_found"],
        "mismatched_customers_total":
            audit["mismatched_customers_total"],
        "mismatch_rates": mismatch_rates,
        "protected_solver_and_search_hashes": protected_now,
        "expected_source_contract_sha256":
            EXPECTED_CONTRACT_SHA256,
        "observed_source_contract_sha256":
            CURRENT_CONTRACT_SHA256,
        "file_enumeration_exclusions": [
            "._*",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
        ],
    }
    atomic_json(HERE / "metadata.json", metadata)

    report = """# E3 行政—道路责任错配三臂结构对照

状态：`HALT_SOURCE_CONTRACT_HASH_DRIFT_BEFORE_SEARCH`。81 个 China81 实例的输入复核和三臂预注册已经完成；正式搜索在源合同漂移门触发前尚未启动，探针与正式评价数均为 0。

## 错配复核

全量复核覆盖 81 个实例、5805 个客户，其中 45 个多车场实例、36 个单车场实例。复核确认 6 个非零错配实例，与对抗性审查报告完全一致；最近车场距离并列数为 0。

| 算例 | 错配客户 | 错配率 |
|---|---:|---:|
| cn-prd-150c-01-V2-LOCATIONS | 3/150 | 2.000% |
| cn-prd-150c-02-V2-LOCATIONS | 2/150 | 1.333% |
| cn-prd-150c-03-V2-LOCATIONS | 4/150 | 2.667% |
| cn-prd-200c-01-V2-LOCATIONS | 7/200 | 3.500% |
| cn-prd-200c-02-V2-LOCATIONS | 6/200 | 3.000% |
| cn-prd-200c-03-V2-LOCATIONS | 2/200 | 1.000% |

六个实例合计错配 24 个客户，占 China81 全部客户的 0.413437%。loader 的 `customer_home_depot` 由客户城市映射到同城唯一车场；有向道路距离复核发现，11 个东莞客户距离广州车场更近，13 个广州客户距离佛山车场更近。相对同城行政车场，道路距离缩短 920.837--6044.788 m，为行政距离的 2.996%--16.513%。

六个实例由三个 150c 和三个 200c 复本组成。预注册按输入错配率选 `cn-prd-200c-01` 为主展示，其余五个形成同规模复本和跨规模稳健性面板；所有六个自然非零错配实例均入选，实例选择不依赖搜索结果。

## 三臂预注册

IND 将每个客户硬锁给 `customer_home_depot`；ZONE 将客户改配到有向道路距离最近车场并保持硬锁；JOINT 复用 ZONE 责任图与初解骨架，解除责任锁。IND→ZONE 定义为空间组织价值，ZONE→JOINT 定义为剩余协同价值，IND→JOINT 定义为总价值。正值表示后一臂成本下降，负值和零值原样保留。

正式矩阵锁定六个实例、三臂、种子 1--10，共 180 个单元；执行顺序按输入错配率递减，每个实例 30 个单元完整落盘后再进入下一个。长探针预定为 `cn-prd-200c-01`、JOINT、seed 1、cap 1500，正式共同 cap 由预注册平台期规则产生，最低 400、最高 1500。由于探针未启动，本轮 `budget_cap=null`。

## 停止事件

预注册锁定的源合同 `docs/handoff/experiment_contract_v2_journal_aligned_20260730.md` 在等待 worker 期间发生外部写入：SHA-256 从 `075f0093...f503b5e` 变为 `0e10e8ea...742c35`，文件时间为 2026-07-30 15:13:17 +08:00。监控器于 15:13:23 +08:00 检出 `PROTECTED_FILE_DRIFT` 并暂停 E3 进程组。暂停时 `budget_lock.json` 不存在，probe/formal task status 均为 0，搜索评价数为 0。

`cost.py`、`check.py`、`search/evaluation.py`、`profit.py`、`route_pool_sp.py` 和 `epochal_hgs.py` 的关闭哈希均与任务锁定值一致。原合同字节没有被覆盖恢复，也没有用漂移后的哈希重签预注册。

## 结果面

本轮正式行数为 0/180，IND→ZONE、ZONE→JOINT、IND→JOINT 三项成本效应均为 `null`。零错配封存对照仍保留原值：`cn-prd-50c-01` 和 `cn-prd-100c-02` 的错配率均为 0，JOINT 相对 ZONE 分别节省 2.272759% 和 0.693115%。陈雨蝶（2025）表 9 报告联合相对分区总成本 −3.44%、碳排放 +2.86%、车辆 8→7；陈雨蝶（2023）表 5 报告总成本 −6.09%、距离 −6.34%、时间 −5.07%、碳排 −4.79%。

正文保留本报告的错配复核表与预注册定义。`input_audit/all_instances.csv`、`input_audit/all_customers.csv`、`input_audit/mismatched_customers.csv`、18 份输入证书、监控异常现场和源锁仅存档。没有正式结果图，也不设附录。
"""
    (HERE / "report.md").write_text(report, encoding="utf-8")

    removed_sidecars = remove_appledouble()
    metadata["appledouble_sidecars_removed_before_manifest"] = (
        removed_sidecars
    )
    atomic_json(HERE / "metadata.json", metadata)

    def real_artifact(path: Path) -> bool:
        return (
            path.is_file()
            and not path.name.startswith("._")
            and not any(part in EXCLUDED_DIRS for part in path.parts)
            and not path.name.endswith(".tmp")
            and path.name not in {
                "artifact_hashes.json",
                "done.json",
            }
        )

    files = {
        str(path.relative_to(HERE)): sha256(path)
        for path in sorted(HERE.rglob("*"))
        if real_artifact(path)
    }
    artifact_hashes = {
        "schema":
            "resetp.e3-mismatch-restart.artifact-hashes.v1",
        "created_at_utc": now_iso(),
        "status":
            "HALT_SOURCE_CONTRACT_HASH_DRIFT_BEFORE_SEARCH",
        "exclusions": [
            "artifact_hashes.json",
            "done.json",
            "._*",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
            "*.tmp",
        ],
        "files": files,
    }
    artifact_hashes["manifest_id"] = payload_sha256(
        artifact_hashes
    )
    atomic_json(HERE / "artifact_hashes.json", artifact_hashes)

    done = {
        "status":
            "HALT_SOURCE_CONTRACT_HASH_DRIFT_BEFORE_SEARCH",
        "nonzero_mismatch_instances_found": 6,
        "instances_used": [],
        "instances_preregistered": list(INSTANCES),
        "mismatch_rates": mismatch_rates,
        "arms": ["IND", "ZONE", "JOINT"],
        "seeds": 10,
        "budget_cap": None,
        "effect_ind_to_zone_pct": None,
        "effect_zone_to_joint_pct": None,
        "effect_ind_to_joint_pct": None,
        "probe_units_run": 0,
        "formal_units_run": 0,
        "search_evaluations_observed": 0,
        "halt_evidence_id":
            halt_evidence["halt_evidence_id"],
        "decision_id": decision["decision_id"],
        "manifest_id": artifact_hashes["manifest_id"],
        "done_written_last": True,
        "created_at_utc": now_iso(),
    }
    done["done_id"] = payload_sha256(done)
    atomic_json(HERE / "done.json", done)
    print(
        "HALT_SOURCE_CONTRACT_HASH_DRIFT_BEFORE_SEARCH "
        "done.json written last",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
