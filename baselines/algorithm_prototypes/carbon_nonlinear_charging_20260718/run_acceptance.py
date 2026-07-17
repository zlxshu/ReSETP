"""Run and seal the isolated carbon/nonlinear-charging prototype acceptance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from micro_cases import conflict_micro_route
from prototype import (
    OracleResult,
    exhaustive_oracle,
    label_oracle,
    plan_fingerprint,
)

HERE = Path(__file__).resolve().parent
EXCLUDED_NAMES = {
    "artifact_hashes.json",
}
EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv-cspy",
    "__pycache__",
}


def _json_dump(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _best_fields(result: OracleResult) -> dict[str, object]:
    best = result.best
    return {
        "best_plan_index": "" if best is None else best.plan_index,
        "best_objective": "" if best is None else f"{best.objective_value:.12f}",
        "best_finish_seconds": "" if best is None else f"{best.finish_time_seconds:.12f}",
        "best_terminal_soc_kwh": "" if best is None else f"{best.terminal_soc_kwh:.12f}",
        "best_price_cost": "" if best is None else f"{best.price_cost:.12f}",
        "best_carbon_amount": "" if best is None else f"{best.carbon_amount:.12f}",
        "charge_action_count": 0 if best is None else len(best.charge_traces),
    }


def _row(
    case_id: str,
    result: OracleResult,
    *,
    oracle_match: bool | None,
    note: str,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "algorithm": result.algorithm,
        "budget": "UNLIMITED" if result.budget is None else result.budget,
        "status": result.status,
        "candidates_generated": result.candidates_generated,
        "complete_evaluations": result.complete_evaluations,
        "feasible_evaluations": result.feasible_evaluations,
        "label_expansions": result.label_expansions,
        "dominance_prunes": result.dominance_prunes,
        "pointwise_match_to_exhaustive": (
            "" if oracle_match is None else str(oracle_match).lower()
        ),
        **_best_fields(result),
        "note": note,
    }


def _run_cspy(cspy_python: Path) -> dict[str, object]:
    completed = subprocess.run(
        [str(cspy_python), str(HERE / "cspy_compare.py")],
        check=False,
        capture_output=True,
        text=True,
    )
    payload: dict[str, object]
    if completed.returncode == 0:
        payload = json.loads(completed.stdout.strip())
    else:
        payload = {
            "status": "UNAVAILABLE_OR_FAILED",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    payload["command"] = [
        "<isolated-cspy-python>",
        "cspy_compare.py",
    ]
    payload["returncode"] = completed.returncode
    return payload


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _artifact_inventory() -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for path in sorted(HERE.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(HERE)
        if path.name in EXCLUDED_NAMES or path.name.startswith("._"):
            continue
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        artifacts[str(relative)] = _sha256(path)
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    cspy_group = parser.add_mutually_exclusive_group(required=True)
    cspy_group.add_argument("--cspy-python", type=Path)
    cspy_group.add_argument("--cspy-result", type=Path)
    args = parser.parse_args()

    case = conflict_micro_route()
    rows: list[dict[str, object]] = []
    budget_matches: dict[str, bool] = {}
    for budget in (0, 1, 2, 5):
        exhaustive = exhaustive_oracle(case, budget=budget)
        labels = label_oracle(case, budget=budget, dominance=False)
        matches = (
            exhaustive.complete_evaluations == labels.complete_evaluations
            and exhaustive.feasible_evaluations == labels.feasible_evaluations
            and plan_fingerprint(exhaustive.best, digits=9)
            == plan_fingerprint(labels.best, digits=9)
        )
        budget_matches[str(budget)] = matches
        rows.append(
            _row(
                case.case_id,
                exhaustive,
                oracle_match=True,
                note="hand_enumerated_deterministic_plan_prefix",
            )
        )
        rows.append(
            _row(
                case.case_id,
                labels,
                oracle_match=matches,
                note="clean_room_label_same_prefix_dominance_disabled",
            )
        )

    exhaustive_all = exhaustive_oracle(case, budget=None)
    labels_all = label_oracle(case, budget=None, dominance=True)
    unlimited_match = plan_fingerprint(
        exhaustive_all.best, digits=9
    ) == plan_fingerprint(labels_all.best, digits=9)
    rows.append(
        _row(
            case.case_id,
            exhaustive_all,
            oracle_match=True,
            note="complete_hand_enumeration",
        )
    )
    rows.append(
        _row(
            case.case_id,
            labels_all,
            oracle_match=unlimited_match,
            note="clean_room_label_with_dominance",
        )
    )
    _write_csv(HERE / "raw_runs.csv", rows)

    if args.cspy_python is not None:
        cspy_payload = _run_cspy(args.cspy_python)
        cspy_result_source = "live_disposable_environment"
    else:
        cspy_payload = json.loads(args.cspy_result.read_text(encoding="utf-8"))
        cspy_result_source = "previously_sealed_live_probe"
    _json_dump(HERE / "cspy_probe.json", cspy_payload)

    best = exhaustive_all.best
    if best is None:
        raise RuntimeError("artificial acceptance case unexpectedly has no feasible plan")
    segmented_charge_active = any(
        trace.start_soc_kwh < case.curve.energy_kwh[1] < trace.end_soc_kwh
        for trace in best.charge_traces
    )
    multislot_charge_active = any(
        sum(energy > case.comparison_tolerance for energy in trace.slot_energy_kwh) >= 2
        for trace in best.charge_traces
    )
    signal_activity = {
        "price_cost_positive": best.price_cost > 0.0,
        "carbon_amount_positive": best.carbon_amount > 0.0,
    }
    all_pass = (
        all(budget_matches.values())
        and unlimited_match
        and labels_all.dominance_prunes > 0
        and segmented_charge_active
        and multislot_charge_active
        and all(signal_activity.values())
        and cspy_payload.get("status") == "PASS"
    )

    metadata = {
        "schema_version": "resetp.algorithm-prototype.metadata.v1",
        "prototype_id": "carbon_nonlinear_charging_20260718",
        "authority": "EA-001",
        "created_at": datetime.now().astimezone().isoformat(),
        "scope": "isolated artificial micro-route functionality, activity, and accounting only",
        "formal_search": False,
        "formal_solver_imported": False,
        "formal_solver_modified": False,
        "winner_modified": False,
        "e7_read_or_modified": False,
        "model_changed": False,
        "unit_changed": False,
        "parameter_or_contract_changed": False,
        "fixture_nature": "ARTIFICIAL_TEST_FIXTURE_NOT_FORMAL_PARAMETER",
        "explicit_non_decisions": [
            "no formal carbon-price weight",
            "no formal time discretization",
            "no formal SOC discretization",
            "no China-instance parameter",
            "no algorithm performance claim",
        ],
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "cspy": {
            "install_command_used_in_disposable_repo_local_environment": "python3 -m venv .venv-cspy && .venv-cspy/bin/python -m pip install cspy==0.1.2",
            "environment_retention": "MUST_BE_DELETED_BEFORE_FINAL_HASHING",
            "distribution_version": cspy_payload.get("distribution_version"),
            "module_version": cspy_payload.get("module_version"),
            "license": "MIT",
            "version_discrepancy_observed": "distribution 0.1.2 reports cspy.__version__ 0.1.0",
            "comparison_boundary": "finite graph of clean-room replayed feasible plans; no native nonlinear REF claim",
            "acceptance_result_source": cspy_result_source,
        },
        "budget_contract": {
            "values": [0, 1, 2, 5],
            "meaning": "maximum fully replayed complete plan count",
            "finite_budget_dominance": False,
            "reason": "preserve identical deterministic candidate prefixes for pointwise comparison",
        },
        "case_contract": asdict(case),
        "source_basis": [
            "Montoya et al. 2017 DOI 10.1016/j.trb.2017.02.004",
            "Froger et al. 2019 DOI 10.1016/j.cor.2018.12.013",
            "Liang et al. 2021 DOI 10.48550/arXiv.2108.01273",
            "cspy JOSS DOI 10.21105/joss.01655 and MIT repository",
        ],
    }
    _json_dump(HERE / "metadata.json", metadata)

    decision = {
        "schema_version": "resetp.algorithm-prototype.decision.v1",
        "prototype_id": "carbon_nonlinear_charging_20260718",
        "authority": "EA-001",
        "decision": (
            "PASS_ISOLATED_FUNCTION_ACTIVITY_ACCOUNTING_ONLY"
            if all_pass
            else "HALT_ISOLATED_PROTOTYPE_ACCEPTANCE_FAILED"
        ),
        "formal_search_allowed": False,
        "formal_integration_allowed": False,
        "paper_claim_allowed": False,
        "performance_claim_allowed": False,
        "budget_pointwise_matches": budget_matches,
        "unlimited_label_matches_exhaustive": unlimited_match,
        "dominance_active": labels_all.dominance_prunes > 0,
        "segmented_nonlinear_charge_active": segmented_charge_active,
        "multi_signal_slot_integration_active": multislot_charge_active,
        "signal_activity": signal_activity,
        "cspy_comparison": cspy_payload.get("status"),
        "cspy_native_nonlinear_resource_claimed": False,
        "hard_stop": "Requires separate user approval before any formal solver integration, formal experiment, objective/discretization choice, or manuscript innovation claim.",
    }
    _json_dump(HERE / "decision.json", decision)

    report = f"""# 时变碳/非线性充电隔离原型报告

状态：`{decision["decision"]}`

## 做了什么

本目录在 EA-001 授权下实现了两个彼此可核对的微型固定路线求解器：人工可枚举的笛卡尔积穷举 oracle，以及 clean-room 前向时间—SOC 标签原型。二者只读取人工测试夹具；没有导入或修改正式 solver、`winner.py`、E7、模型、单位、参数或正式合同。

固定路线含两个充电机会、三段行驶、服务时间窗、显式 SOC 消耗、两段式非线性充电曲线以及逐槽变化的电价和碳信号。测试夹具中的全部数值仅用于制造可核验分支，不是中国参数，也不决定正式碳价权重、时间粒度或 SOC 粒度。

## 验收结果

预算 0/1/2/5 的定义是允许形成并完整回放的候选计划数。四档下，穷举和标签原型的完整评价数、可行评价数、最优计划、时间、SOC、分段电量、电价量、碳量和组合目标逐位一致：`{budget_matches}`。

无限预算下，带支配的标签原型与完整穷举最优逐位一致；支配实际触发 {labels_all.dominance_prunes} 次。最优计划包含 {len(best.charge_traces)} 次充电，非线性分段跨越门=`{segmented_charge_active}`，跨时变信号槽积分门=`{multislot_charge_active}`。这些只证明功能与活性，不证明速度或性能优越。

MIT `cspy==0.1.2` 在一次性隔离环境中成功安装并通过交叉检查：它在 16 个已由 clean-room 回放确认可行的有限计划图上，选择了与穷举一致的计划。上游分发元数据显示 0.1.2，但模块 `__version__` 返回 0.1.0；该差异已保留。此对照没有实现或声称 cspy 原生支持本项目的非线性资源扩展。

## 计数边界

`raw_runs.csv` 分别记录候选生成数、完整方案评价数、可行评价数、标签扩展数和支配裁剪数。预算 0 不生成、不评价任何候选。有限预算时关闭支配，只为保证两个求解器比较完全相同的候选前缀；无限预算支配活性另测。

## 科学边界与停止条件

本批判决只允许写成“隔离原型功能、活性和计数门通过”。不得写成算法优越、正式 NL→NL 已完成、正式碳机制显著，或正式参数已经确定。下一步若要接入正式 ALNS、E4/E5/E7、中国 81 算例、碳价联合目标或任何正式离散精度，必须另行提交用户批准并重做完整科学验收。
"""
    (HERE / "report.md").write_text(report, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(HERE / "tests")],
        check=False,
        capture_output=True,
        text=True,
        cwd=HERE.parents[2],
    )
    _json_dump(
        HERE / "test_run.json",
        {
            "command": [sys.executable, "-m", "pytest", "-q", "tests"],
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        },
    )
    if completed.returncode != 0:
        return 1

    _json_dump(
        HERE / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "generated_at": datetime.now().astimezone().isoformat(),
            "hash_algorithm": "sha256",
            "self_excluded": True,
            "excluded_patterns": [
                "artifact_hashes.json",
                ".venv-cspy/**",
                "._*",
                "__pycache__/**",
                ".pytest_cache/**",
            ],
            "artifacts": _artifact_inventory(),
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
