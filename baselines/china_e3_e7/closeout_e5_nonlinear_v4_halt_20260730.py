#!/usr/bin/env python3
"""Evidence-only HALT closeout for the E5 v4 AppleDouble crash.

This script does not resume aggregation or compute scientific endpoints.  It
only records already-emitted search and checker evidence, creates the required
HALT artifacts, hashes them, and writes done.json last.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "baselines/china_e3_e7/e5_nonlinear_v4_20260730"
TASK_ID = "E5-NONLINEAR-CHARGING-V4-20260730"
HALT = "HALT_APPLEDOUBLE_CERTIFICATE_DENOMINATOR"


def canonical(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical(payload))
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError("HALT_CLOSEOUT_EMPTY_RAW_RUNS")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def main() -> int:
    if (OUT / "done.json").exists():
        raise RuntimeError("done.json already exists")
    statuses = []
    for path in sorted((OUT / "formal/task_status").glob("*.json")):
        if path.name.startswith("._"):
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("status") != "PASS":
            raise RuntimeError(f"non-PASS formal status: {path}")
        statuses.append(row)
    if len(statuses) != 40:
        raise RuntimeError(f"formal status denominator {len(statuses)}")

    certificate_rows: dict[tuple[str, int, str], dict[str, str]] = {}
    with (OUT / "independent_certificates.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        for row in csv.DictReader(handle):
            key = (row["instance_id"], int(row["seed"]), row["arm"])
            certificate_rows[key] = row
    if len(certificate_rows) != 40:
        raise RuntimeError(
            f"certificate summary denominator {len(certificate_rows)}"
        )
    real_certificates = sorted(
        path
        for path in (OUT / "certificates").glob("*.json")
        if not path.name.startswith("._")
    )
    appledouble_certificates = sorted(
        (OUT / "certificates").glob("._*.json")
    )
    if len(real_certificates) != 40 or len(appledouble_certificates) != 40:
        raise RuntimeError(
            "crash evidence changed: "
            f"real={len(real_certificates)} "
            f"appledouble={len(appledouble_certificates)}"
        )

    raw_rows = []
    for status in sorted(
        statuses,
        key=lambda row: (
            row["instance_id"],
            int(row["seed"]),
            row["arm"],
        ),
    ):
        key = (
            status["instance_id"],
            int(status["seed"]),
            status["arm"],
        )
        certificate = certificate_rows[key]
        raw_rows.append(
            {
                "task_id": TASK_ID,
                "instance_id": status["instance_id"],
                "sample_role": status["sample_role"],
                "seed": status["seed"],
                "arm": status["arm"],
                "complete_candidate_budget_cap": status[
                    "complete_candidate_budget_cap"
                ],
                "complete_candidate_evaluations_consumed": status[
                    "complete_candidate_evaluations_consumed"
                ],
                "termination_reason": status["termination_reason"],
                "feasible_candidates": status["feasible_candidates"],
                "infeasible_candidates": status[
                    "infeasible_candidates"
                ],
                "error_candidates": status["error_candidates"],
                "elapsed_wall_seconds": status["elapsed_wall_seconds"],
                "search_total_cost_cny": status[
                    "search_total_cost_cny"
                ],
                "common_initial_solution_sha256": status[
                    "common_initial_solution_sha256"
                ],
                "search_status": status["status"],
                "independent_certificate_status": certificate[
                    "certificate_status"
                ],
                "planning_physics_feasible": certificate[
                    "planning_physics_feasible"
                ],
                "common_NL90_feasible": certificate[
                    "nonlinear_feasible"
                ],
                "linear_plan_false_feasible": certificate[
                    "linear_plan_false_feasible"
                ],
                "certificate_id": certificate["certificate_id"],
                "scientific_endpoint_inclusion": (
                    "NOT_AGGREGATED_DUE_TO_TERMINAL_CRASH"
                ),
            }
        )
    atomic_csv(OUT / "raw_runs.csv", raw_rows)

    now = datetime.now(UTC).isoformat()
    diagnosis = json.loads(
        (OUT / "probe/null_objective_diagnosis.json").read_text(
            encoding="utf-8"
        )
    )
    proof = json.loads(
        (
            OUT
            / "diagnostics/search_semantics_unchanged_proof.json"
        ).read_text(encoding="utf-8")
    )
    metadata = {
        "schema_version": "E5-METADATA-v4-HALT",
        "task_id": TASK_ID,
        "status": HALT,
        "closed_at_utc": now,
        "budget_cap": 400,
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "instances": [
            "cn-prd-50c-01-V2-LOCATIONS",
            "cn-prd-100c-02-V2-LOCATIONS",
        ],
        "seeds": 10,
        "arms": ["L100_control", "NL90_mild"],
        "formal_search_units_completed": 40,
        "formal_search_units_passed": 40,
        "technical_error_candidates": 0,
        "independent_checker_status": "PASS_40_OF_40",
        "independent_verification_path": (
            "independent_verification.json"
        ),
        "terminal_aggregation_status": "CRASHED_BEFORE_ENDPOINTS",
        "crash": {
            "exception": (
                "RuntimeError: "
                "HALT_E5_V2_CERTIFICATE_DENOMINATOR:80!=40"
            ),
            "real_certificate_json_files": 40,
            "appledouble_certificate_json_files": 40,
            "glob_count_seen_by_loader": 80,
            "log": "finalize.log",
        },
        "search_semantics_unchanged_proof": bool(
            proof["search_semantics_unchanged"]
        ),
    }
    atomic_json(OUT / "metadata.json", metadata)

    decision = {
        "schema_version": "E5-DECISION-v4-HALT",
        "task_id": TASK_ID,
        "status": HALT,
        "scientific_decision": "NOT_ISSUED",
        "endpoints_answered": 0,
        "reason": (
            "Terminal aggregation crashed after independent verification; "
            "the user-mandated crash rule forbids repairing and continuing."
        ),
        "null_objective_diagnosis": {
            "legitimate_infeasible": int(
                diagnosis["totals"]["legitimate_infeasible"]
            ),
            "technical_error": int(
                diagnosis["totals"]["technical_error"]
            ),
        },
        "formal_search_evidence_available": True,
        "independent_certificate_evidence_available": True,
        "endpoint_1_NL90_complete_feasibility": "NOT_AGGREGATED",
        "endpoint_2_linear_false_feasibility": "NOT_AGGREGATED",
        "endpoint_3_common_feasible_cost_effect": "NOT_AGGREGATED",
        "endpoint_4_sessions": "NOT_AGGREGATED",
        "result_filtering_used": False,
        "budget_changed_after_results": False,
    }
    decision["decision_id"] = payload_hash(decision)
    atomic_json(OUT / "decision.json", decision)

    by_instance: dict[str, list[dict[str, Any]]] = {}
    for row in raw_rows:
        by_instance.setdefault(row["instance_id"], []).append(row)
    instance_lines = []
    for instance_id, rows in sorted(by_instance.items()):
        consumed = [
            int(row["complete_candidate_evaluations_consumed"])
            for row in rows
        ]
        instance_lines.append(
            f"| {instance_id} | {len(rows)}/20 | "
            f"{min(consumed)}–{max(consumed)} | "
            f"{sum(int(row['error_candidates']) for row in rows)} | "
            "40/40 checker batch total across both instances |"
        )
    report = f"""# E5 非线性充电实验 v4：HALT 封口

## 结论

本轮不能签发四个科学端点，终态为 `{HALT}`。正式搜索 40/40 单元均完成，技术错误候选为 0，独立 checker 也明确输出 `PASS certificates=40/40`；但独立证书写盘后，外置盘为 40 个真实 JSON 同步生成 40 个 AppleDouble `._*.json`。旧聚合器使用未排除旁文件的 `glob("*.json")`，把证书数读成 80，并以 `HALT_E5_V2_CERTIFICATE_DENOMINATOR:80!=40` 崩溃。按本轮硬规则“崩溃即真故障，不自行修复后继续”，这里停止，不修改过滤器、不删除证书旁文件后重跑聚合、不从现有证书补算端点。

## 二义性诊断

同 seed、同 cap 的搜索语义指纹在增加纯诊断字段前后逐位一致：最终方案哈希、完整目标、331 行评价轨迹投影均相同。双臂探针共 662 次完整评价，368 行目标为空；368/368 均为完整模型明确报告容量或时间窗违约的 `ValueError`，技术错误 0。L100 与 NL90 各为 147 个可行候选、184 个合法不可行候选、0 个技术错误。因此 v3 的“任一空目标即 HALT”确属判据过严；v4 已把合法不可行保留为实际消费数据，并仅在 `error_candidates>0` 时停。

候选级原因允许重叠：每臂 184 个空目标中，112 行含容量违约，178 行含时间窗违约，106 行同时含两类；具体异常类型、完整消息和实例见 `probe/null_objective_diagnosis.json`、`probe/null_objective_root_cause_summary.json` 和两份完整 search trace。

## 正式搜索与独立复算状态

共同正式预算锁为 400 次上限，来自两臂探针在 331 次候选耗尽后向上取整留余量。50c 完成后才启动 100c；全程 1 worker。

| Instance | Search units | Actual evaluations | Error candidates | Independent check |
|---|---:|---:|---:|---|
{chr(10).join(instance_lines)}

40 个真实 plan、40 个真实 certificate 和 `independent_verification.json` 均保留。`raw_runs.csv` 记录所有正式单元的 feasible/infeasible/error 构成和 checker 摘要，但 `scientific_endpoint_inclusion` 明确标为未聚合，不能把这些行冒充已签发端点。

## 未回答的科学端点

端点 1 至 4 均标记为 `NOT_AGGREGATED`：没有签发 NL90 完整可行率、L100 假可行数量/成因、共同可行成本变化或逐会话 SOC/时长汇总。这里的“未回答”来自终端聚合崩溃和明确停机规则，不代表效应为零，也不代表已有独立证书无效。

## 冻结边界

`cost.py`、`check.py`、`search/evaluation.py` 和 `route_pool_sp.py` 哈希未漂移。`epochal_hgs.py` 只增加异常类名/消息诊断字段，逐位语义证明为 PASS。旧 v1/v2/v3 目录未覆盖或删除。`artifact_hashes.json` 排除 AppleDouble、缓存、监控运行态及 `done.json`；`done.json` 作为本次 HALT 完成信号最后写入。
"""
    atomic_text(OUT / "report.md", report)

    excluded = {"artifact_hashes.json", "done.json"}
    artifact_rows = []
    for path in sorted(item for item in OUT.rglob("*") if item.is_file()):
        relative = path.relative_to(OUT)
        parts = set(relative.parts)
        rel = str(relative)
        if (
            rel in excluded
            or rel.startswith("monitor_runtime/")
            or path.name.startswith("._")
            or "__pycache__" in parts
            or ".pytest_cache" in parts
        ):
            continue
        artifact_rows.append(
            {
                "path": rel,
                "sha256": file_hash(path),
                "bytes": path.stat().st_size,
            }
        )
    protected = {
        "solver/src/setp_solver/cost.py": (
            "2717b4b4de39bb4c2a9a1bda602f4420cb3e3b1e87faa83678dfa64f88fc80be"
        ),
        "solver/src/setp_solver/check.py": (
            "9c81e254e05591667c8225965bb9d0ba4e8bbfc53eb0f8c61ffdb4325a1403a8"
        ),
        "solver/src/setp_solver/search/evaluation.py": (
            "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3"
        ),
        (
            "baselines/algorithm_prototypes/"
            "china81_mechanism_hybrid_20260720/route_pool_sp.py"
        ): (
            "976ef21d4952b3c488300de9a8d3e351411305d26f1e2601ca17c15185d462c1"
        ),
        (
            "baselines/algorithm_prototypes/"
            "china81_mechanism_hybrid_20260720/epochal_hgs.py"
        ): (
            "fc4f4fa63e69a413aac9a36ca8e3d10fb359d4365c4365b83e474d1db3fc8808"
        ),
    }
    for relative, expected in protected.items():
        actual = file_hash(REPO / relative)
        if actual != expected:
            raise RuntimeError(
                f"protected hash drift before HALT closeout: {relative}"
            )
    manifest = {
        "schema_version": "E5-ARTIFACT-HASHES-v4-HALT",
        "task_id": TASK_ID,
        "status": HALT,
        "hash_algorithm": "sha256",
        "excluded": [
            "artifact_hashes.json",
            "done.json",
            "monitor_runtime/**",
            "._*",
            "__pycache__/**",
            ".pytest_cache/**",
        ],
        "artifacts": artifact_rows,
        "protected_source_sha256_at_closeout": protected,
    }
    manifest["manifest_id"] = payload_hash(manifest)
    atomic_json(OUT / "artifact_hashes.json", manifest)

    required = (
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    )
    if any(not (OUT / name).is_file() for name in required):
        raise RuntimeError("HALT closeout artifact missing")
    done = {
        "schema_version": "E5-DONE-v4-HALT",
        "task_id": TASK_ID,
        "status": HALT,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "null_objective_diagnosis": {
            "legitimate_infeasible": int(
                diagnosis["totals"]["legitimate_infeasible"]
            ),
            "technical_error": int(
                diagnosis["totals"]["technical_error"]
            ),
        },
        "search_semantics_unchanged_proof": True,
        "budget_cap": 400,
        "instances_completed": [
            "cn-prd-50c-01-V2-LOCATIONS",
            "cn-prd-100c-02-V2-LOCATIONS",
        ],
        "seeds": 10,
        "endpoints_answered": 0,
        "formal_search_units_completed": 40,
        "formal_search_units_passed": 40,
        "independent_certificates_passed": 40,
        "crash_evidence": {
            "exception": (
                "HALT_E5_V2_CERTIFICATE_DENOMINATOR:80!=40"
            ),
            "real_certificates": 40,
            "appledouble_sidecars": 40,
        },
        "required_artifacts": list(required),
        "required_artifact_sha256": {
            name: file_hash(OUT / name) for name in required
        },
        "manifest_id": manifest["manifest_id"],
        "decision_id": decision["decision_id"],
    }
    done["done_id"] = payload_hash(done)
    atomic_json(OUT / "done.json", done)
    print(
        f"DONE path={OUT / 'done.json'} status={HALT}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
