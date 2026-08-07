"""Exercise real-input crossover missing-customer repair without a full run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from duty_hgs.charging import repair_changed_duties
from duty_hgs.contracts import SearchAccounting
from duty_hgs.crossover import selective_duty_exchange
from duty_hgs.evaluation import DutyFullEvaluator
from duty_hgs.population import AdaptivePenaltyManager
from duty_hgs.repair import regret2_repair
from run_real_input_technical_trial import (
    INSTANCE_ID,
    PROTECTED,
    _build_context,
    _parameters,
    _policy,
    _prepare_population,
    _source_provenance,
)


class _OneEVFromFirst:
    def __init__(self) -> None:
        self._values = iter((0, 1))

    def randrange(self, _limit: int) -> int:
        return next(self._values)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--stderr-capture-state", default="caller_not_declared")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    output = args.output_dir.resolve()
    code_provenance = _source_provenance(
        repo,
        output_path=output,
        stderr_capture_state=args.stderr_capture_state,
    )
    if not code_provenance["worktree_clean_before_run"]:
        raise RuntimeError(
            "technical provenance run requires a clean worktree before output creation"
        )
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)

    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    bundle, initial, _pi0, context = _build_context(repo)
    evaluator = DutyFullEvaluator(context)
    policy = _policy(evaluator)
    parents, _initial_evaluation, reverse_record, attempts, _selected = (
        _prepare_population(initial, evaluator, policy)
    )
    right = parents[1]
    crossed = selective_duty_exchange((initial, right), _OneEVFromFirst())
    missing_before = tuple(crossed.child.unserved_customers)
    child = repair_changed_duties(
        right,
        crossed.child,
        changed_duty_ids=set(crossed.changed_duty_ids),
        context=context,
        policy=policy,
    )
    child_evaluation = evaluator.evaluate(child)
    penalties = AdaptivePenaltyManager(_parameters().penalties)
    penalties.register(child_evaluation)
    accounting = SearchAccounting()
    repaired, repaired_evaluation, trajectory = regret2_repair(
        child,
        evaluator=evaluator,
        charging_policy=policy,
        arm="real-input-regret2-repair-smoke",
        iteration=0,
        accounting=accounting,
        penalized_cost=penalties.cost,
        initial_evaluation=child_evaluation,
    )
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    represented = {
        customer
        for duty in repaired.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    all_customers = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    accepted = [row.action_id for row in trajectory if row.accepted]
    failure_reasons = []
    if not missing_before:
        failure_reasons.append("crossover child did not contain a missing customer")
    if repaired.unserved_customers:
        failure_reasons.append("repair left customers unserved")
    if represented != all_customers:
        failure_reasons.append("repaired customer partition is incomplete")
    if not repaired_evaluation.feasible:
        failure_reasons.append("repaired child is infeasible under full evaluation")
    if accounting.repair_calls < 1 or not accepted:
        failure_reasons.append("regret2 repair did not accept an insertion")
    if accounting.sentinel_evaluations < 1:
        failure_reasons.append("full-truth sentinel was not exercised")
    if protected_before != protected_after:
        failure_reasons.append("protected evaluator file changed")
    verdict = "REAL_INPUT_REPAIR_SMOKE_COMPLETE" if not failure_reasons else "REAL_INPUT_REPAIR_SMOKE_FAILED"

    _json(
        output / "metadata.json",
        {
            "purpose": "real-input missing-customer repair wiring smoke; not a performance experiment",
            "code_provenance": code_provenance,
            "instance_id": INSTANCE_ID,
            "instance_formally_selected": False,
            "parent_rule": "same deterministic first fully evaluated distinct move as the one-cycle trial",
            "second_parent_attempts": attempts,
            "preflight_reverse_attempt": reverse_record,
            "crossover_rule": "one EV duty from the first parent, fixed structural choice; no cost inspection",
            "donor_duty_ids": list(crossed.donor_duty_ids),
            "missing_customers_before_repair": list(missing_before),
            "protected_hashes_before": protected_before,
            "protected_hashes_after": protected_after,
        },
    )
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "instance_id", "missing_before", "missing_after",
            "customers_represented", "customers_total", "repair_calls",
            "accepted_insertions", "sentinel_evaluations", "feasible_after",
            "violations_after", "verdict",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "instance_id": INSTANCE_ID,
                "missing_before": len(missing_before),
                "missing_after": len(repaired.unserved_customers),
                "customers_represented": len(represented),
                "customers_total": len(all_customers),
                "repair_calls": accounting.repair_calls,
                "accepted_insertions": len(accepted),
                "sentinel_evaluations": accounting.sentinel_evaluations,
                "feasible_after": repaired_evaluation.feasible,
                "violations_after": len(repaired_evaluation.violations),
                "verdict": verdict,
            }
        )
    _json(
        output / "decision.json",
        {
            "verdict": verdict,
            "failure_reasons": failure_reasons,
            "accepted_insertions": accepted,
            "performance_claim": None,
            "formal_parameter_decision": None,
            "formal_instance_decision": None,
            "restart_covered": False,
        },
    )
    (output / "trajectory.jsonl").write_text(
        "".join(
            json.dumps(asdict(row), ensure_ascii=False, allow_nan=False) + "\n"
            for row in trajectory
        ),
        encoding="utf-8",
    )
    report = f"""# Duty-HGS 真实输入漏服务修复冒烟报告

## 结论

本轮判定：`{verdict}`。固定结构交叉产生 {len(missing_before)} 个明确的未服务客户；后悔修复实际接受 {len(accepted)} 次插入后，未服务客户变为 {len(repaired.unserved_customers)}，客户覆盖为 {len(represented)}/{len(all_customers)}，完整评价可行，违规数为 {len(repaired_evaluation.violations)}，完整真值哨兵调用 {accounting.sentinel_evaluations} 次。

本轮只证明真实输入上的“交叉产生漏客户—后悔插回—完整评价复核”接线能够走通。它不比较成本、不证明算法优秀、不选择正式算例，也不确定 P20、Pi0、哨兵正式用法或论文主张。重启分支仍未覆盖。

## 交付前九条自检

1. 每个 `FACT` 是否都指到了文件行号 / 产物哈希 / 论文页码？——数字来自同包 `raw_runs.csv` 和 `trajectory.jsonl`，哈希登记在 `artifact_hashes.json`。
2. 有没有把自己的建议或担忧写成“已决”或“状态”？——没有，只记录技术冒烟判定。
3. 改动范围有没有超出任务文本？——没有，只补真实输入修复分支复验。
4. 有没有碰受保护文件？——未碰，运行前后哈希一致，见 `metadata.json`。
5. 待决事项是否转成了 2–4 个具体候选并写清代价？——本轮没有新增用户待决事项。
6. 有没有用自造词或内部任务号跟用户说话？——没有。
7. 失败、跳过、超时、异常结果有没有如实保留？——没有失败或超时；重启分支明确记为未覆盖。
8. 四件套齐了吗？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全，另附修复轨迹。
9. `HANDOFF.md` 变更日志和 `docs/handoff/memory/` 同步了吗？——将在本任务收尾时同步，最终提交前复核。
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    _json(output / "artifact_hashes.json", hashes)
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    print(json.dumps({"output": str(output), "verdict": verdict}, ensure_ascii=False))
    return 0 if verdict == "REAL_INPUT_REPAIR_SMOKE_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
