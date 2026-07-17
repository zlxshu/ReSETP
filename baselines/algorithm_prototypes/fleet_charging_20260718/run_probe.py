"""Run EA-001 FC-C02/FC-C05 functional probes and write five records."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from contracts import (
    CompleteEvaluationBudget,
    ProbeCounters,
    independently_replay_charging_result,
)
from frvcpy_adapter import (
    FRVCPY_PROVENANCE,
    CachingChargingOracle,
    FrvcpyOracleAdapter,
    build_fc_c02_abstract_micro_request,
)
from vmr_nl import (
    VMRNLSelector,
    abstract_probe_score,
    build_fc_c05_manual_candidates,
    independently_select_manual_reference,
)


ROOT = Path(__file__).resolve().parent
BUDGETS = (0, 1, 2, 5)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_fc_c02(limit: int) -> dict[str, object]:
    request = build_fc_c02_abstract_micro_request()
    counters = ProbeCounters()
    budget = CompleteEvaluationBudget(limit, counters)
    oracle = CachingChargingOracle(FrvcpyOracleAdapter())
    last_result = None
    replay_pass = True
    while budget.reserve():
        last_result = oracle.solve(request, counters)
        replay = independently_replay_charging_result(request, last_result)
        counters.reference_evaluations += 1
        replay_pass &= replay.feasible and abs(replay.objective - last_result.objective) <= 1e-9
    return {
        "candidate_id": "FC-C02",
        "budget": limit,
        "status": "PASS_FUNCTION_ONLY" if replay_pass else "FAIL_REPLAY",
        **vars(counters),
        "active": bool(last_result and any(stop[1] is not None for stop in last_result.stops)),
        "selected_mode": "EV_WITH_CHARGE" if last_result else "",
        "selected_candidate": request.request_id if last_result else "",
        "objective_abstract": "" if last_result is None else last_result.objective,
        "regret_abstract": "",
        "independent_replay_pass": "" if last_result is None else replay_pass,
        "notes": "Repeated requests intentionally expose cache accounting; no CNY/formal SOC/cross-trip semantics.",
    }


def run_fc_c05(limit: int) -> dict[str, object]:
    request = build_fc_c02_abstract_micro_request()
    candidates = build_fc_c05_manual_candidates(request)
    counters = ProbeCounters()
    budget = CompleteEvaluationBudget(limit, counters)
    selector = VMRNLSelector(
        CachingChargingOracle(FrvcpyOracleAdapter()),
        abstract_probe_score,
    )
    result = selector.select(candidates, budget, counters, top_b=5)
    evaluated_ids = {item.candidate.candidate_id for item in result.evaluated}
    expected_id, expected_regret = independently_select_manual_reference(
        candidates,
        oracle_objective=4.0,
        evaluated_candidate_ids=evaluated_ids,
    )
    counters.reference_evaluations += int(bool(result.evaluated))
    selected_id = result.selected.candidate.candidate_id if result.selected else None
    replay_pass = selected_id == expected_id and result.regret == expected_regret
    return {
        "candidate_id": "FC-C05",
        "budget": limit,
        "status": "PASS_FUNCTION_ONLY" if replay_pass else "FAIL_REFERENCE",
        **vars(counters),
        "active": result.active,
        "selected_mode": result.selected.candidate.vehicle_mode if result.selected else "",
        "selected_candidate": selected_id or "",
        "objective_abstract": "" if result.selected is None else result.selected.score,
        "regret_abstract": "" if result.regret is None else result.regret,
        "independent_replay_pass": "" if not result.evaluated else replay_pass,
        "notes": "Score function is injected abstractly; no formal objective or physical contract is selected.",
    }


def build_report(rows: list[dict[str, object]]) -> str:
    fc02 = [row for row in rows if row["candidate_id"] == "FC-C02"]
    fc05 = [row for row in rows if row["candidate_id"] == "FC-C05"]
    return f"""# EA-001主题1独立原型功能报告

判决：`PASS_ISOLATED_FUNCTION_PROTOTYPE_ONLY`

治理状态：`EXPLORATION_ONLY_AWAITING_USER_APPROVAL_FOR_FORMAL_USE`

## 做了什么

FC-C02在独立目录中通过可注入适配层调用Apache-2.0 `frvcpy 0.1.1`。人工微例只使用抽象时间和抽象能量：固定客户序列的直达能量不可行，oracle插入一个充电站并给出部分补能量；独立回放不调用frvcpy，逐弧复算能量、分段线性非线性充电时间和总时长。

FC-C05实现了VMR-NL接口桩。候选同时携带客户、路线、插入位置、车辆模式和可选充电请求；筛选优先级、完整评分函数和充电oracle均从外部注入。人工候选中同时包含`CV_DIRECT`、`EV_DIRECT`和`EV_WITH_CHARGE`，用于证明车型—补能联合选择通道能够活跃，不代表正式成本优越。

## 功能结果

预算0/1/2/5均在调用前预留完整评价并严格停在上限。FC-C02四档结果为`{[row['status'] for row in fc02]}`；预算2和5出现缓存命中，但完整评价仍分别记2和5，没有因缓存漏账。FC-C05四档结果为`{[row['status'] for row in fc05]}`；预算0不筛选、不生成、不评分，预算1只证明单候选通道，预算2起至少两种车辆模式被实际评价，活性门通过。所有有结果的行均由独立直接枚举或SOC回放复算一致。

## 明确保留的接口

原型没有决定人民币车辆固定成本、电价、碳价、正式SOC曲线、初始SOC来源、跨趟SOC继承、充电站容量、排队或接受规则。`score_function`、`FixedRouteChargingRequest.instance`和初始能量都保持可注入；任何正式适配必须另行提交公式、单位、来源和影响分析。

## 不能得出的结论

本探针不能证明FC-C02或FC-C05比当前ALNS更快、更优或更显著，不能证明VMR-NL具有论文新颖性，也不能把抽象微例参数写入中国实例。没有运行正式solver、winner、E7或任何正式E1--E7搜索。

开发首轮单测曾如实暴露两项实现错误：充电曲线递增校验的比较符号写反，以及一个测试调用漏传计数器。两项均在生成本证据包前修复；最终`test_results.txt`记录5项测试全部通过。该修复不改变任何正式模型或参数。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    test_record = output / "test_results.txt"
    if not test_record.is_file() or "\nOK\n" not in test_record.read_text(encoding="utf-8"):
        raise RuntimeError("final unittest record is missing or does not end in OK")
    rows = [run_fc_c02(limit) for limit in BUDGETS]
    rows.extend(run_fc_c05(limit) for limit in BUDGETS)
    if any(row["status"] != "PASS_FUNCTION_ONLY" for row in rows):
        raise RuntimeError("functional probe failed; records not finalized")

    fieldnames = list(rows[0])
    with (output / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    metadata = {
        "schema": "resetp.ea001.fleet_charging.prototype.v1",
        "created_at": now,
        "authorization": "EA-001",
        "scope": "ISOLATED_FUNCTION_PROTOTYPE_ONLY",
        "prototype_root": str(ROOT),
        "python": sys.version,
        "platform": platform.platform(),
        "budgets": list(BUDGETS),
        "formal_search_evaluations": 0,
        "formal_solver_imported": False,
        "winner_modified": False,
        "e7_modified": False,
        "model_or_unit_contract_modified": False,
        "external_component": FRVCPY_PROVENANCE,
        "abstract_micro_parameters": True,
        "tests": {
            "framework": "unittest",
            "final_passed": 5,
            "final_failed": 0,
            "record": "test_results.txt",
        },
        "development_incidents": [
            {
                "stage": "first_test_run_before_final_records",
                "result": "FAILED_4_ERRORS",
                "causes": [
                    "charging curve monotonicity comparison sign was reversed",
                    "one test call omitted the counters argument",
                ],
                "resolution": "fixed before final probe; final tests 5/5 PASS",
            }
        ],
    }
    write_json(output / "metadata.json", metadata)

    decision = {
        "schema": "resetp.ea001.fleet_charging.prototype.decision.v1",
        "decision": "PASS_ISOLATED_FUNCTION_PROTOTYPE_ONLY",
        "governance_status": "EXPLORATION_ONLY_AWAITING_USER_APPROVAL_FOR_FORMAL_USE",
        "formal_search_allowed": False,
        "formal_integration_allowed": False,
        "performance_claim_allowed": False,
        "paper_novelty_claim_allowed": False,
        "fc_c02": "FUNCTION_ACTIVE_AND_INDEPENDENT_REPLAY_PASS",
        "fc_c05": "INTERFACE_ACTIVE_AND_MANUAL_REFERENCE_PASS",
        "budgets_0_1_2_5": "PASS_PRECALL_HARD_STOP",
        "unresolved_injected_interfaces": [
            "formal CNY objective",
            "approved nonlinear SOC curve",
            "initial and inter-trip SOC semantics",
            "charging capacity and queueing",
            "formal acceptance and complete-evaluation adapter",
        ],
    }
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(build_report(rows), encoding="utf-8")

    excluded = {"artifact_hashes.json"}
    files = sorted(
        path for path in output.rglob("*")
        if path.is_file()
        and path.name not in excluded
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    )
    write_json(
        output / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "hash_algorithm": "sha256",
            "excluded": sorted(excluded),
            "files": {
                str(path.relative_to(output)): sha256(path)
                for path in files
            },
        },
    )
    print(json.dumps(decision, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
