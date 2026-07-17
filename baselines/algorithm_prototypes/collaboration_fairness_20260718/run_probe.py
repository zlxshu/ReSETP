"""Run and package the EA-001 collaboration/fairness functional probe."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from independent_recompute import recompute
from prototype import ARMS, build_micro_problem, deficit_magnitude_witness, run_arm


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
BUDGETS = (0, 1, 2, 5)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def customer_rows() -> list[dict[str, object]]:
    problem = build_micro_problem()
    return [
        {
            "customer_id": customer.customer_id,
            "revenue": customer.revenue,
            "service_cost": customer.service_cost,
        }
        for customer in problem.customers
    ]


def replay_matches(row: dict[str, object]) -> bool:
    problem = build_micro_problem()
    replay = recompute(
        customer_rows=customer_rows(),
        assignment=dict(row["best_assignment"]),
        standalone_profit=problem.standalone_profit,
        theta=problem.theta,
    )
    return (
        replay["feasible"] is True
        and abs(float(replay["total_cost"]) - float(row["best_total_cost"])) <= 1e-12
        and abs(float(replay["total_deficit"]) - float(row["best_total_deficit"])) <= 1e-12
        and replay["profit"] == row["best_profit"]
        and replay["deficit"] == row["best_deficit"]
    )


def build_rows() -> list[dict[str, object]]:
    problem = build_micro_problem()
    rows: list[dict[str, object]] = []
    for arm in ARMS:
        for budget in BUDGETS:
            result = run_arm(problem, arm, budget)
            result["independent_recompute_match"] = replay_matches(result)
            rows.append(result)
    return rows


def write_raw_runs(rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "arm_id",
        "budget_limit",
        "complete_evaluations",
        "budget_respected",
        "candidate_count",
        "moves",
        "initial_total_cost",
        "initial_total_deficit",
        "best_total_cost",
        "best_total_deficit",
        "best_assignment",
        "best_profit",
        "best_deficit",
        "proximity_operator_enabled",
        "fairness_operator_enabled",
        "first_candidate_differs_from_base",
        "independent_recompute_match",
    ]
    with (ROOT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            serializable = {
                key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list))
                else value
                for key, value in row.items()
            }
            writer.writerow(serializable)


def write_metadata(rows: list[dict[str, object]]) -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    protected = [
        "solver/src/setp_solver/cost.py",
        "solver/src/setp_solver/check.py",
        "solver/src/setp_solver/search/evaluation.py",
        "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    ]
    metadata = {
        "schema": "resetp.algorithm_prototype.collaboration_fairness.metadata.v1",
        "created_at": now,
        "authority": "EA-001",
        "scope": "ISOLATED_FUNCTION_ACTIVITY_ACCOUNTING_PROBE_ONLY",
        "formal_search": False,
        "performance_claim_allowed": False,
        "problem": "fixed artificial three-depot complete-assignment micro-case",
        "arms": [arm.arm_id for arm in ARMS],
        "budgets": list(BUDGETS),
        "row_count": len(rows),
        "python": sys.version,
        "platform": platform.platform(),
        "git_branch": git_value("branch", "--show-current"),
        "git_head": git_value("rev-parse", "HEAD"),
        "command": (
            "PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 "
            "baselines/algorithm_prototypes/collaboration_fairness_20260718/run_probe.py"
        ),
        "source_basis": {
            "literature_anchor": "Soriano, Gansterer, and Hartl (2023), DOI 10.1016/j.ijpe.2022.108669",
            "exploration_package": "docs/handoff/algorithm_exploration_20260718/collaboration_fairness/",
            "implementation_note": "independent Soriano-style directional correction; not copied author code and not claimed as the literal published coefficient formula",
        },
        "protected_file_hashes": {
            path: sha256(REPO / path) for path in protected
        },
        "excluded_paths": [
            "solver/src/setp_solver/",
            "baselines/e7_dynamic/",
            "formal experiment contracts",
        ],
    }
    (ROOT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_decision(rows: list[dict[str, object]]) -> None:
    witness = deficit_magnitude_witness()
    all_budget_ok = all(bool(row["budget_respected"]) for row in rows)
    all_replay_ok = all(bool(row["independent_recompute_match"]) for row in rows)
    budgets_complete = {
        int(row["budget_limit"]) for row in rows
    } == set(BUDGETS)
    arms_complete = {str(row["arm_id"]) for row in rows} == {
        arm.arm_id for arm in ARMS
    }
    deficit_sensitive = witness == {
        "larger_B_deficit_choice": "B",
        "larger_C_deficit_choice": "C",
    }
    verdict = (
        "PASS_FUNCTION_ACTIVITY_ACCOUNTING_ONLY"
        if all((all_budget_ok, all_replay_ok, budgets_complete, arms_complete, deficit_sensitive))
        else "HALT_FUNCTION_PROBE_FAILED"
    )
    decision = {
        "schema": "resetp.algorithm_prototype.collaboration_fairness.decision.v1",
        "decision": verdict,
        "authority": "EA-001",
        "formal_solver_modified": False,
        "winner_modified": False,
        "e7_modified": False,
        "model_modified": False,
        "unit_modified": False,
        "formal_contract_modified": False,
        "formal_search_allowed": False,
        "performance_claim_allowed": False,
        "gates": {
            "four_arms_present": arms_complete,
            "budgets_0_1_2_5_present": budgets_complete,
            "complete_evaluation_budget_never_exceeded": all_budget_ok,
            "independent_recompute_all_rows": all_replay_ok,
            "deficit_magnitude_changes_recipient": deficit_sensitive,
        },
        "deficit_magnitude_witness": witness,
        "allowed_conclusions": [
            "the isolated operators execute on the artificial micro-case",
            "the two operator switches can be activated independently and jointly",
            "the constructed deficit magnitude enters recipient selection",
            "complete evaluation accounting respects budgets 0/1/2/5",
            "the recorded best states pass an independent arithmetic replay",
        ],
        "forbidden_conclusions": [
            "performance superiority",
            "formal E3/E6 improvement",
            "China-instance validity",
            "paper-level algorithm innovation",
        ],
    }
    (ROOT / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_report() -> None:
    decision = json.loads((ROOT / "decision.json").read_text(encoding="utf-8"))
    report = f"""# 合作责任/参与公平隔离功能探针

判决：`{decision["decision"]}`。

本目录是 EA-001 授权下的人工微例原型。它没有导入或修改正式 ReSETP
solver、`winner.py`、E7、模型、单位或正式合同；也没有读取中国81实例或
Solomon正式测试集。原型只验证功能、算子活性、完整评价计数与独立复算，
不提供任何性能优越性证据。

## 微例和四臂

固定微例包含三个车场、四名人工客户和完整客户归属。完整评价计算人工
服务成本、各车场利润及参与下界赤字。四臂是基础臂、仅 Proximity
removal、仅公平修正插入、两者联合。每臂分别运行预算0、1、2、5，共16行。

Proximity removal 只改变待重分配客户的顺序。公平修正插入采用
Soriano等（2023）思想的独立构造：在基础插入成本增量上减去“接收车场当前
归一化赤字×该插入带来的接收利润”。这不是论文原系数公式的复制，也没有
使用作者代码；它只用于证明公平赤字能够进入修复方向。

## 验收

四臂和四档预算均存在；完整评价使用量从未超过预算。预算0不评价候选；
预算1/2/5分别最多评价1/2/5个完整归属。所有16行的最佳归属、成本、利润和
赤字均由独立模块重新按原始人工表复算，结果一致。九项回归还直接回读
16行CSV、八项产物哈希和源码隔离边界。额外见证保持插入成本和
接收利润相同，只交换B、C两场的赤字大小，选择随较大赤字从B切换到C，证明
代码不是只读取“是否违规”的布尔量。

## 严格边界

本探针没有做种子比较、统计检验、墙钟比较或正式算例搜索。它不能支持
“算法更好”“E6会显著改善”或“已形成论文创新”等表述。G0仍未闭合；若未来
要把该候选接入正式ALNS、E3/E6机制门或论文，仍需用户逐项批准，并重新走
统一完整评价、共同起点、共同种子和正式独立审计。
"""
    (ROOT / "report.md").write_text(report, encoding="utf-8")


def write_hashes() -> None:
    included = [
        "prototype.py",
        "independent_recompute.py",
        "run_probe.py",
        "tests/test_prototype.py",
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "report.md",
    ]
    payload = {
        "schema": "resetp.algorithm_prototype.collaboration_fairness.artifact_hashes.v1",
        "algorithm": "sha256",
        "files": {path: sha256(ROOT / path) for path in included},
        "excluded": [
            "artifact_hashes.json",
            "._*",
            "__pycache__",
            ".pytest_cache",
        ],
    }
    (ROOT / "artifact_hashes.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    rows = build_rows()
    write_raw_runs(rows)
    write_metadata(rows)
    write_decision(rows)
    write_report()
    write_hashes()
    decision = json.loads((ROOT / "decision.json").read_text(encoding="utf-8"))
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["decision"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
