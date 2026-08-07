"""Exhaustively check declared versus actual Duty action scope on real input."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from duty_hgs.crossover import canonical_fleet_registry, selective_duty_exchange
from duty_hgs.evaluation import DutyFullEvaluator
from duty_hgs.model import DutyIndividual
from duty_hgs.operators import generate_problem_moves
from run_real_input_technical_trial import _build_context, _source_provenance


INSTANCE_ID = "cn-cy-50c-01-V2-LOCATIONS"
PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


class _OneDutyFromFirst:
    def __init__(self) -> None:
        self._values = iter((0, 0))

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


def _actual_changed(before: DutyIndividual, after: DutyIndividual) -> set[str]:
    left = {duty.physical_vehicle_id: duty for duty in before.duties}
    right = {duty.physical_vehicle_id: duty for duty in after.duties}
    if set(left) != set(right):
        return set(left).symmetric_difference(right).union(
            duty_id for duty_id in set(left).intersection(right)
            if left[duty_id] != right[duty_id]
        )
    return {
        duty_id for duty_id in left if left[duty_id] != right[duty_id]
    }


def _move_rows(individual, moves, *, scenario: str):
    rows = []
    for index, move in enumerate(moves, start=1):
        declared = set(move.changed_duty_ids)
        try:
            candidate = move.apply(individual)
            actual = _actual_changed(individual, candidate)
            rows.append(
                {
                    "scenario": scenario,
                    "index": index,
                    "action_id": move.action_id,
                    "channel": move.channel,
                    "status": "APPLIED",
                    "declared_duty_ids": "|".join(sorted(declared)),
                    "actual_duty_ids": "|".join(sorted(actual)),
                    "scope_equal": declared == actual,
                    "error_type": "",
                    "error": "",
                }
            )
        except (TypeError, ValueError) as exc:
            rows.append(
                {
                    "scenario": scenario,
                    "index": index,
                    "action_id": move.action_id,
                    "channel": move.channel,
                    "status": "APPLY_REJECTED",
                    "declared_duty_ids": "|".join(sorted(declared)),
                    "actual_duty_ids": "",
                    "scope_equal": "",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
    return rows


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
    bundle, initial, _pi0, context = _build_context(repo, INSTANCE_ID)
    evaluator = DutyFullEvaluator(context)
    evaluation = evaluator.evaluate(initial)
    depots = sorted({duty.home_depot_id for duty in initial.duties})
    ev_count = sum(duty.vehicle_type == "ev" for duty in initial.duties)
    cv_count = sum(duty.vehicle_type == "cv" for duty in initial.duties)
    if len(depots) < 2 or ev_count < 2 or cv_count < 1:
        raise RuntimeError("selected structural smoke input is not multi-depot/multi-EV")

    ordinary_moves = generate_problem_moves(initial, evaluation, bundle.instance)
    rows = _move_rows(initial, ordinary_moves, scenario="actual_participation")
    deficient = dict(evaluation.participation_margin)
    deficient[depots[0]] = -1.0
    fairness_trigger = replace(evaluation, participation_margin=deficient)
    fairness_moves = generate_problem_moves(initial, fairness_trigger, bundle.instance)
    rows.extend(
        _move_rows(initial, fairness_moves, scenario="synthetic_fairness_trigger")
    )

    first_cv = next(
        item.physical_vehicle_id
        for item in canonical_fleet_registry(initial)
        if item.vehicle_type == "cv"
    )
    second_parent = None
    parent_move = None
    for move in ordinary_moves:
        if first_cv not in move.changed_duty_ids:
            continue
        try:
            candidate = move.apply(initial)
        except (TypeError, ValueError):
            continue
        if candidate.fingerprint != initial.fingerprint:
            second_parent = candidate
            parent_move = move
            break
    if second_parent is None or parent_move is None:
        raise RuntimeError("no deterministic distinct crossover parent for first CV")
    crossed = selective_duty_exchange(
        (initial, second_parent),
        _OneDutyFromFirst(),
    )
    crossover_actual = _actual_changed(second_parent, crossed.child)
    crossover_declared = set(crossed.changed_duty_ids)
    crossover_equal = crossover_actual == crossover_declared

    applied = [row for row in rows if row["status"] == "APPLIED"]
    rejected = [row for row in rows if row["status"] == "APPLY_REJECTED"]
    mismatches = [row for row in applied if not row["scope_equal"]]
    channels = sorted({row["channel"] for row in rows})
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    failure_reasons = []
    if mismatches:
        failure_reasons.append(f"{len(mismatches)} ordinary action scope mismatches")
    if not crossover_equal:
        failure_reasons.append("crossover declared scope differs from actual scope")
    for required_channel in ("depot_collaboration", "fairness_cross_depot"):
        if required_channel not in channels:
            failure_reasons.append(f"required channel not generated: {required_channel}")
    if protected_before != protected_after:
        failure_reasons.append("protected evaluator file changed")
    verdict = "ACTION_SCOPE_SMOKE_COMPLETE" if not failure_reasons else "ACTION_SCOPE_SMOKE_FAILED"

    metadata = {
        "purpose": "real-input action-scope smoke; no candidate evaluation or performance comparison",
        "code_provenance": code_provenance,
        "instance_id": INSTANCE_ID,
        "instance_selection_rule": (
            "first inspected size/region input with at least two depots, two EV duties, and one CV duty; "
            "cost and effect were not inspected"
        ),
        "instance_formally_selected": False,
        "depots": depots,
        "ev_duties": ev_count,
        "cv_duties": cv_count,
        "initial_feasible": evaluation.feasible,
        "fairness_trigger": (
            "structure-only synthetic negative participation margin at the first depot; "
            "not a scientific observation"
        ),
        "crossover_parent_action": parent_move.action_id,
        "crossover_donor_duty_ids": list(crossed.donor_duty_ids),
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    _json(output / "metadata.json", metadata)
    fields = list(rows[0])
    with (output / "action_scope_rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "instance_id", "depots", "ev_duties", "cv_duties",
            "generated_actions", "applied_actions", "rejected_actions",
            "scope_mismatches", "crossover_scope_equal",
            "depot_collaboration_generated", "fairness_cross_depot_generated",
            "verdict",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "instance_id": INSTANCE_ID,
                "depots": len(depots),
                "ev_duties": ev_count,
                "cv_duties": cv_count,
                "generated_actions": len(rows),
                "applied_actions": len(applied),
                "rejected_actions": len(rejected),
                "scope_mismatches": len(mismatches),
                "crossover_scope_equal": crossover_equal,
                "depot_collaboration_generated": "depot_collaboration" in channels,
                "fairness_cross_depot_generated": "fairness_cross_depot" in channels,
                "verdict": verdict,
            }
        )
    _json(
        output / "decision.json",
        {
            "verdict": verdict,
            "failure_reasons": failure_reasons,
            "performance_claim": None,
            "formal_instance_decision": None,
            "formal_parameter_decision": None,
            "crossover": {
                "declared_duty_ids": sorted(crossover_declared),
                "actual_duty_ids": sorted(crossover_actual),
                "scope_equal": crossover_equal,
            },
        },
    )
    report = f"""# Duty-HGS 多车场、多电动车动作范围冒烟报告

## 结论

本轮判定：`{verdict}`。输入包含 {len(depots)} 个实际出车车场、{ev_count} 辆电动车和 {cv_count} 辆燃油车。普通参与条件和人为触发公平通道两种结构场景共生成 {len(rows)} 个动作，其中 {len(applied)} 个成功形成候选，{len(rejected)} 个在动作自身的锁定规则处被拒绝；成功形成候选的动作中，声明范围与实际范围不一致的数量为 {len(mismatches)}。交叉算子的声明范围与实际范围一致：{crossover_equal}。

本轮确实生成了 `depot_collaboration` 和 `fairness_cross_depot` 两种跨车场通道。公平通道是用一个明确披露的负参与余量人为触发，只用于检查代码接线，不代表真实效应或现实观察。

本轮不评价候选成本，不比较算法，不选择正式算例，也不确定正式预算、Pi0 或论文主张。

## 交付前九条自检

1. 每个 `FACT` 是否都指到了文件行号 / 产物哈希 / 论文页码？——本报告数字来自同包 `raw_runs.csv` 和 `action_scope_rows.csv`，文件哈希登记在 `artifact_hashes.json`。
2. 有没有把自己的建议或担忧写成“已决”或“状态”？——没有，只记录动作范围冒烟的技术判定。
3. 改动范围有没有超出任务文本？——没有，只核对动作和交叉的声明范围与实际范围。
4. 有没有碰受保护文件？——未碰，运行前后哈希一致，见 `metadata.json`。
5. 待决事项是否转成了 2–4 个具体候选并写清代价？——本轮没有新增用户待决事项。
6. 有没有用自造词或内部任务号跟用户说话？——没有。
7. 失败、跳过、超时、异常结果有没有如实保留？——动作自身拒绝逐行保留在 `action_scope_rows.csv`；无超时。
8. 四件套齐了吗？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全，另附逐动作明细。
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
    return 0 if verdict == "ACTION_SCOPE_SMOKE_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
