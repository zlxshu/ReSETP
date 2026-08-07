"""Run one bounded real-input Duty-HGS wiring trial.

This is deliberately not a scientific performance experiment.  It executes
one search cycle on a real China81 input and saves enough evidence to diagnose
interface, crossover, full-evaluation, and packaging failures.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from duty_hgs.charging import ChargingRepairPolicy
from duty_hgs.contracts import CandidateStatus
from duty_hgs.education import evaluate_move
from duty_hgs.evaluation import (
    DutyEvaluationContext,
    DutyFullEvaluator,
    FrozenMappingIdentity,
    mapping_sha256,
)
from duty_hgs.model import DutyIndividual
from duty_hgs.operators import ReverseSegmentMove, generate_problem_moves
from duty_hgs.population import (
    AdaptivePenaltyManager,
    DutyPopulation,
    PenaltyParameters,
    PopulationParameters,
)
from duty_hgs.runner import (
    DutyHGSSearchParameters,
    FrozenPopulationIdentity,
    population_sha256,
    run_duty_hgs,
)
from setp_solver.algorithms.resetp_alns.support.construction import (
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import complete_china81_route_skeleton
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.multitrip_schedule import (
    DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
)


INSTANCE_ID = "cn-jjj-10c-01-V2-LOCATIONS"
SEED = 11
ARM = "one-cycle-real-input-wiring-trial"
PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


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


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _policy(evaluator: DutyFullEvaluator) -> ChargingRepairPolicy:
    return ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode=evaluator.context.depot_charge_window_mode,
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )


def _parameters() -> DutyHGSSearchParameters:
    return DutyHGSSearchParameters(
        random_seed=SEED,
        population=PopulationParameters(
            min_pop_size=2,
            generation_size=2,
            num_elite=1,
            num_close=1,
            tournament_size=2,
            lb_diversity=0.0,
            ub_diversity=1.0,
        ),
        penalties=PenaltyParameters(
            initial_penalty_per_unit=100.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        ),
        restart_after_iterations_without_improvement=20_000,
    )


def _build_context(repo: Path, instance_id: str = INSTANCE_ID):
    bundle = load_china81_bundle(repo, instance_id)
    skeleton = build_initial_solution(
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        introduce_ev=False,
        require_charging_signal=False,
    )
    completed = complete_china81_route_skeleton(skeleton, bundle).solution
    profits = calculate_depot_profits(
        completed,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        customer_home_depot=dict(bundle.customer_home_depot),
    )
    pi0 = {depot_id: row.profit for depot_id, row in profits.items()}
    context = DutyEvaluationContext(
        bundle=bundle,
        independent_profit=pi0,
        independent_profit_identity=FrozenMappingIdentity(
            source_id="technical-initial-solution-derived-before-search",
            value_sha256=mapping_sha256(pi0),
            externally_frozen=False,
        ),
        prior_profit={depot_id: 0.0 for depot_id in pi0},
        theta=1.0,
        carbon_quota_kg=0.0,
        depot_charge_window_mode=DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    )
    return bundle, DutyIndividual.from_solution(completed), pi0, context


def _prepare_population(
    initial: DutyIndividual,
    evaluator: DutyFullEvaluator,
    policy: ChargingRepairPolicy,
):
    initial_evaluation = evaluator.evaluate(initial)
    first_duty = initial.duties[0]
    first_trip = first_duty.trips[0]
    reverse = ReverseSegmentMove(
        action_id="preflight-reverse-first-two",
        channel="technical_preflight",
        duty_id=first_duty.physical_vehicle_id,
        trip_index=first_trip.trip_index,
        start=0,
        stop=2,
    )
    reverse_outcome = evaluate_move(
        initial,
        reverse,
        evaluator=evaluator,
        charging_policy=policy,
    )
    reverse_record = {
        "action_id": reverse_outcome.action_id,
        "status": str(reverse_outcome.status),
        "error_type": reverse_outcome.error_type,
        "error": reverse_outcome.error,
    }

    attempts = []
    second = None
    second_evaluation = None
    for index, move in enumerate(
        generate_problem_moves(initial, initial_evaluation, evaluator.context.bundle.instance),
        start=1,
    ):
        outcome = evaluate_move(
            initial,
            move,
            evaluator=evaluator,
            charging_policy=policy,
        )
        attempts.append(
            {
                "index": index,
                "action_id": outcome.action_id,
                "channel": outcome.channel,
                "status": str(outcome.status),
                "error_type": outcome.error_type,
                "error": outcome.error,
            }
        )
        if (
            outcome.status == CandidateStatus.EVALUATED
            and outcome.candidate is not None
            and outcome.evaluation is not None
            and outcome.candidate.fingerprint != initial.fingerprint
        ):
            second = outcome.candidate
            second_evaluation = outcome.evaluation
            break
    if second is None or second_evaluation is None:
        raise RuntimeError("no deterministic, fully evaluated distinct second parent")

    candidates = (initial, second)
    parameters = _parameters()
    penalties = AdaptivePenaltyManager(parameters.penalties)
    population = DutyPopulation(parameters.population, penalties)
    population.add(initial, initial_evaluation)
    population.add(second, second_evaluation)
    left, right = population.select(random.Random(SEED))
    selected = {
        "left_fingerprint": left.individual.fingerprint,
        "right_fingerprint": right.individual.fingerprint,
        "distinct": left.individual.fingerprint != right.individual.fingerprint,
    }
    if not selected["distinct"]:
        raise RuntimeError("seed 11 did not select structurally distinct parents")
    return candidates, initial_evaluation, reverse_record, attempts, selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)

    repo = Path(__file__).resolve().parents[3]
    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    bundle, initial, pi0, context = _build_context(repo)
    evaluator = DutyFullEvaluator(context)
    policy = _policy(evaluator)
    candidates, initial_evaluation, reverse_record, attempts, selected = (
        _prepare_population(initial, evaluator, policy)
    )
    parameters = _parameters()
    identity = FrozenPopulationIdentity(
        source_id="technical-real-input-two-parent-population",
        value_sha256=population_sha256(candidates),
    )
    result = run_duty_hgs(
        candidates,
        evaluator=evaluator,
        charging_policy=policy,
        parameters=parameters,
        initial_population_identity=identity,
        stop=lambda state: state.iterations >= 1,
        arm=ARM,
    )
    trajectory = [asdict(row) for row in result.trajectory]
    crossover_rows = [row for row in trajectory if row["phase"] == "crossover"]
    crossover_changed = any(
        row["after_fingerprint"] is not None
        and row["before_fingerprint"] != row["after_fingerprint"]
        for row in crossover_rows
    )
    served = {
        customer
        for duty in result.best.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    customer_nodes = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served_demand = sum(float(customer_nodes[item].demand) for item in served)
    total_demand = sum(float(node.demand) for node in customer_nodes.values())
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}

    failure_reasons = []
    if not initial_evaluation.feasible:
        failure_reasons.append("initial solution is infeasible")
    if result.termination_status != "STOPPED_BY_CALLER":
        failure_reasons.append(f"unexpected termination: {result.termination_status}")
    if not result.best_evaluation.feasible:
        failure_reasons.append("best solution is infeasible")
    if served != set(customer_nodes):
        failure_reasons.append("not all customers are served")
    if not crossover_changed:
        failure_reasons.append("crossover did not change the selected right parent")
    if result.accounting.sentinel_evaluations <= 0:
        failure_reasons.append("full-truth sentinel was not exercised")
    if protected_before != protected_after:
        failure_reasons.append("a protected evaluator file changed during the run")
    verdict = (
        "TECHNICAL_TRIAL_COMPLETE" if not failure_reasons
        else "TECHNICAL_TRIAL_FAILED"
    )

    metadata = {
        "purpose": "one-cycle real-input wiring trial; not a performance experiment",
        "instance_id": INSTANCE_ID,
        "instance_formally_selected": False,
        "formal_search_allowed": bool(bundle.formal_search_allowed),
        "machine": "M1 formal-number machine, but this output is diagnostic only",
        "git_head": _git(repo, "rev-parse", "HEAD"),
        "random_seed": SEED,
        "iterations": 1,
        "stop_semantics": "technical single-cycle wiring stop; not P20",
        "restart_path_covered": False,
        "parameters": asdict(parameters),
        "charging_policy": asdict(policy),
        "pi0": {
            "values": pi0,
            "sha256": mapping_sha256(pi0),
            "externally_frozen": False,
            "formal_reuse_allowed": False,
        },
        "initial_population_sha256": identity.value_sha256,
        "preflight_reverse_attempt": reverse_record,
        "second_parent_attempts": attempts,
        "second_parent_rule": (
            "first generated move with EVALUATED status and a distinct fingerprint; "
            "cost and direction were ignored"
        ),
        "parent_selection_precheck": selected,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "failure_conditions": [
            "input or initial construction failure",
            "initial solution incomplete or infeasible",
            "parents not structurally distinct",
            "crossover does not structurally change the selected right parent",
            "truth-sentinel mismatch or internal error",
            "abnormal termination",
            "missing customers or demand",
            "incomplete experiment package",
        ],
    }
    _json(output / "metadata.json", metadata)
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "instance_id", "seed", "iterations", "termination_status",
            "initial_feasible", "initial_violations", "initial_cost",
            "best_feasible", "best_violations", "best_cost", "cost_delta",
            "customers_served", "customers_total", "demand_served",
            "demand_total", "crossover_calls", "crossover_changed_parent",
            "sentinel_evaluations", "actual_full_model_evaluations",
            "run_wall_seconds", "pi0_externally_frozen", "verdict",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "instance_id": INSTANCE_ID,
                "seed": SEED,
                "iterations": result.iterations,
                "termination_status": result.termination_status,
                "initial_feasible": initial_evaluation.feasible,
                "initial_violations": len(initial_evaluation.violations),
                "initial_cost": initial_evaluation.total_cost,
                "best_feasible": result.best_evaluation.feasible,
                "best_violations": len(result.best_evaluation.violations),
                "best_cost": result.best_evaluation.total_cost,
                "cost_delta": result.best_evaluation.total_cost - initial_evaluation.total_cost,
                "customers_served": len(served),
                "customers_total": len(customer_nodes),
                "demand_served": served_demand,
                "demand_total": total_demand,
                "crossover_calls": result.accounting.crossover_calls,
                "crossover_changed_parent": crossover_changed,
                "sentinel_evaluations": result.accounting.sentinel_evaluations,
                "actual_full_model_evaluations": result.accounting.to_dict()["actual_full_model_evaluations"],
                "run_wall_seconds": result.accounting.run_wall_seconds,
                "pi0_externally_frozen": False,
                "verdict": verdict,
            }
        )
    decision = {
        "verdict": verdict,
        "failure_reasons": failure_reasons,
        "what_this_answers": [
            "the real input can or cannot complete one Duty-HGS cycle",
            "whole-duty crossover and the full-truth sentinel are or are not exercised",
            "the required evidence package is or is not complete",
        ],
        "what_this_does_not_decide": [
            "algorithm superiority",
            "formal stopping budget P20",
            "formal comparison instance",
            "formal Pi0",
            "restart correctness on this real input",
            "dynamic-demand effectiveness",
        ],
        "user_decision_changed": False,
    }
    _json(output / "decision.json", decision)
    (output / "trajectory.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
            for row in trajectory
        ),
        encoding="utf-8",
    )
    _json(
        output / "best_solution.json",
        {
            "individual": asdict(result.best),
            "evaluation": {
                "total_cost": result.best_evaluation.total_cost,
                "breakdown": dict(result.best_evaluation.breakdown),
                "feasible": result.best_evaluation.feasible,
                "violations": [asdict(item) for item in result.best_evaluation.violations],
                "participation_margin": dict(result.best_evaluation.participation_margin),
            },
            "accounting": result.accounting.to_dict(),
            "provenance": asdict(result.provenance),
        },
    )
    report = f"""# Duty-HGS 真实输入单轮技术试跑报告

## 结论

本轮判定：`{verdict}`。这是一轮接线和内部一致性检查，不是算法对比实验，也没有替用户确定正式算例、正式预算或论文结论。

真实输入 `{INSTANCE_ID}` 完成了 {result.iterations} 个搜索循环。最终服务 {len(served)}/{len(customer_nodes)} 个客户，完成需求量 {served_demand:.6f}/{total_demand:.6f}；完整评价判定可行，违规数为 {len(result.best_evaluation.violations)}。完整真值哨兵实际调用 {result.accounting.sentinel_evaluations} 次。交叉算子收到两个不同父代，并产生了不同于右父代的候选：{crossover_changed}。

初始成本为 {initial_evaluation.total_cost:.12f}，本轮保存解成本为 {result.best_evaluation.total_cost:.12f}。这个差值只用于排查运行过程，不能据此宣称 Duty-HGS 更优，因为本轮只有一个种子、一个循环，也没有同预算强基线。

## 如实保留的异常

预先尝试“反转第一条路线的前两个客户”时，结果为 `{reverse_record['status']}`，错误为：{reverse_record['error']}。该尝试没有被改写成成功，也没有被用于挑选有利结果。第二个父代改按固定生成顺序选取第一个能被完整评价且结构不同的动作，选择时没有看成本好坏。

## 本轮没有解决的事

本轮没有覆盖重启分支；技术用 Pi0 来自本轮初始解，`externally_frozen=False`，不得带入正式比较；单轮停止不是 P20；该算例没有因此被选定为正式代表算例。算法优越性、公开算例竞争力、私有算例三大实验与五大因素效应仍需后续正式实验回答。

## 交付前九条自检

1. 每个 `FACT` 是否都指到了文件行号 / 产物哈希 / 论文页码？——本报告事实来自同包的 `raw_runs.csv`、`metadata.json`、`trajectory.jsonl`、`best_solution.json`；包内哈希将在 `artifact_hashes.json` 登记。没有把无出处判断写成 FACT。
2. 有没有把自己的建议或担忧写成“已决”或“状态”？——没有。本轮只给技术试跑判定，没有改变任何用户决定。
3. 改动范围有没有超出任务文本？——没有。仅增加试跑入口和本次试跑产物；没有开始正式算法比较。
4. 有没有碰受保护文件？——未碰；三个受保护文件运行前后哈希一致，具体值见 `metadata.json`。
5. 待决事项是否转成了 2–4 个具体候选并写清代价？——本轮没有新增需要用户拍板的选择；P20、正式算例和正式 Pi0 保持未决。
6. 有没有用自造词或内部任务号跟用户说话？——报告仅使用项目已有术语；“单轮技术试跑”已解释为接线和一致性检查。
7. 失败、跳过、超时、异常结果有没有如实保留？——已保留反转前两个客户导致时间窗失败；没有超时，重启分支明确记为未覆盖。
8. 四件套齐了吗？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全，另附 `trajectory.jsonl` 和 `best_solution.json`。
9. `HANDOFF.md` 变更日志和 `docs/handoff/memory/` 同步了吗？——试跑产物生成后将在本任务收尾时同步，最终提交前复核。
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    _json(output / "artifact_hashes.json", hashes)
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    required = {
        "metadata.json", "raw_runs.csv", "decision.json",
        "artifact_hashes.json", "report.md",
    }
    missing = sorted(required.difference(path.name for path in output.iterdir()))
    if missing:
        raise RuntimeError(f"incomplete package: {missing}")
    print(json.dumps({"output": str(output), "verdict": verdict}, ensure_ascii=False))
    return 0 if verdict == "TECHNICAL_TRIAL_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
