from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

from setp_solver.search.dynamic import RollingParameters, RollingPolicyContext, RollingPolicyDecision, myopic_rolling_policy, run_rolling_reoptimization
from setp_solver.solution import Route, Solution

from .final_track16 import Track16Halt, _check_wall, _wilcoxon_pvalue, _write_text, run_preflight
from .final_track18 import DEFAULT_BUNDLES, _payload_row, _read_rows, _safe_name, _to_float, _write_rows
from .pilot20_learned_destroy_phaseA import DEFAULT_WORKER
from .pilot22_grounded_fixes import _load_state, _log, _save_state, _write_json


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track20")
DEFAULT_TRACK18_ROWS = Path("solver/reports/dr_alns_ppo_v3/final_track18/track18_headroom.csv")
TERMINAL_STATUSES = {
    "HEURISTIC_MOVES_HEADROOM",
    "HEURISTIC_FLAT",
    "HALT_MYOPIC_CALLBACK_REGRESSION",
    "HALT_HEURISTIC_HEALTH",
    "HALT_PREFLIGHT",
    "HALT_PROTECTED_DIRTY",
}


class Track20Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def run(args: argparse.Namespace) -> int:
    _normalize_preflight_args(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "track20_progress.log"
    state_path = output_dir / "track20_state.json"
    state = _load_state(state_path) if args.resume else {}
    started = time.monotonic()
    final_status = str(state.get("final_status") or "RUNNING")
    final_reason = str(state.get("final_reason") or "")
    try:
        _enforce_resume_guard(state, resume=bool(args.resume), force=bool(args.force))
        if args.force:
            state = {"final_status": "RUNNING", "final_reason": "Force rerun requested."}
        _log(progress_path, "Track20 start")
        preflight = run_preflight(args, output_dir)
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = preflight
        _save_state(state_path, state)

        if not state.get("regression_done"):
            regression = run_myopic_callback_regression(args, output_dir, progress_path, started)
            state["regression"] = regression
            state["regression_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "track20_myopic_callback_regression.json", regression)
            _write_text(output_dir / "track20_myopic_callback_regression.md", _regression_report(regression))
            if regression["verdict"] == "HALT_MYOPIC_CALLBACK_REGRESSION":
                raise Track20Halt(regression["verdict"], regression["reason"])

        if not state.get("action_sanity_done"):
            sanity = run_action_sanity(args, output_dir, progress_path, started)
            state["action_sanity"] = sanity
            state["action_sanity_done"] = sanity["verdict"] in TERMINAL_STATUSES
            _save_state(state_path, state)
            _write_json(output_dir / "track20_action_sanity_report.json", sanity)
            _write_text(output_dir / "track20_action_sanity_report.md", _action_sanity_report(sanity))
            if sanity["verdict"] == "HALT_HEURISTIC_HEALTH":
                raise Track20Halt(sanity["verdict"], sanity["reason"])

        final_status, final_reason = _summarize_final(state)
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        return 0 if final_status in {"HEURISTIC_MOVES_HEADROOM", "HEURISTIC_FLAT"} else 2
    except Track16Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 2
    except Track20Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 2
    finally:
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _write_json(state_path, state)
        _write_json(output_dir / "final_report.json", state)
        _write_text(output_dir / "final_report.md", _final_report(state))


def run_myopic_callback_regression(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    baseline_rows = [row for row in _read_rows(Path(args.track18_rows)) if row.get("health_status") == "HEALTHY"]
    if not baseline_rows:
        return {"verdict": "HALT_MYOPIC_CALLBACK_REGRESSION", "reason": "No healthy Track18 rows found for callback regression.", "rows": []}
    baseline = baseline_rows[0]
    bundle_dir = str(baseline["bundle_dir"])
    seed = int(baseline["seed"])
    _check_wall(started, float(args.max_wall_seconds))
    output_json = output_dir / "track20_payloads" / f"{_safe_name(str(baseline['bundle']))}_seed{seed}_myopic_callback.json"
    _log(progress_path, f"Track20 myopic callback regression bundle={baseline['bundle']} seed={seed}")
    payload = run_rolling_reoptimization(
        bundle_dir,
        output_json_path=output_json,
        seed=seed,
        eval_budget=int(args.eval_budget),
        max_runtime_seconds=float(args.max_runtime_seconds),
        stage_eval_budget=int(args.stage_eval_budget),
        stage_max_runtime_seconds=float(args.stage_max_runtime_seconds),
        params=RollingParameters(stages=int(args.stages)),
        policy_callback=myopic_rolling_policy,
    )
    candidate = _payload_row(payload, bundle_dir=bundle_dir, seed=seed, output_json=output_json)
    row = _regression_row(baseline, candidate)
    _write_rows(output_dir / "track20_myopic_callback_regression.csv", [row])
    ok = row["regression_status"] == "PASS"
    return {
        "verdict": "MYOPIC_CALLBACK_REGRESSION_PASS" if ok else "HALT_MYOPIC_CALLBACK_REGRESSION",
        "reason": "Myopic callback reproduced the Track18 baseline row." if ok else "Myopic callback changed Track18 baseline metrics.",
        "rows": [row],
    }


def run_action_sanity(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    rows_path = output_dir / "track20_rows.csv"
    rows = [] if args.force else (_read_rows(rows_path) if args.resume and rows_path.exists() else [])
    baseline_rows = [row for row in _read_rows(Path(args.track18_rows)) if row.get("health_status") == "HEALTHY"]
    baseline_by_key = {(str(row["bundle"]), int(row["seed"])): row for row in baseline_rows}
    done = {(row["bundle"], int(row["seed"])) for row in rows if row.get("status") != "RUNNING"}
    launched = 0
    policy = build_reserve_defer_policy(
        mode=str(args.policy_mode),
        reserve_fraction=float(args.reserve_fraction),
        min_slack_seconds=float(args.defer_min_slack_seconds),
    )
    for baseline in baseline_rows:
        bundle_name = str(baseline["bundle"])
        seed = int(baseline["seed"])
        if (bundle_name, seed) in done:
            continue
        if int(args.max_runs) > 0 and launched >= int(args.max_runs):
            return _summarize_action_sanity(rows, planned_count=len(baseline_rows), partial=True, reason="Stopped after max_runs.")
        _check_wall(started, float(args.max_wall_seconds))
        output_json = output_dir / "track20_payloads" / f"{_safe_name(bundle_name)}_seed{seed}_heuristic.json"
        _log(progress_path, f"Track20 heuristic bundle={bundle_name} seed={seed}")
        payload = run_rolling_reoptimization(
            baseline["bundle_dir"],
            output_json_path=output_json,
            seed=seed,
            eval_budget=int(args.eval_budget),
            max_runtime_seconds=float(args.max_runtime_seconds),
            stage_eval_budget=int(args.stage_eval_budget),
            stage_max_runtime_seconds=float(args.stage_max_runtime_seconds),
            params=RollingParameters(stages=int(args.stages)),
            policy_callback=policy,
        )
        heuristic = _payload_row(payload, bundle_dir=baseline["bundle_dir"], seed=seed, output_json=output_json)
        row = _comparison_row(baseline_by_key[(bundle_name, seed)], heuristic, payload)
        rows.append(row)
        _write_rows(rows_path, rows)
        launched += 1
        if row.get("health_status") != "HEALTHY":
            return _summarize_action_sanity(rows, planned_count=len(baseline_rows), partial=True, reason=f"{bundle_name}/seed{seed} failed heuristic health: {row.get('health_status')}")
    return _summarize_action_sanity(rows, planned_count=len(baseline_rows), partial=False, reason="")


def build_reserve_defer_policy(*, mode: str = "defer_adds", reserve_fraction: float, min_slack_seconds: float):
    def reserve_defer_policy(context: RollingPolicyContext) -> RollingPolicyDecision:
        if mode == "preposition":
            return _preposition_decision(context)
        defer_mode = {"reserve_capacity": "reserve_defer", "commit_defer": "defer_adds"}.get(mode, mode)
        future_events = [event for event in context.all_events if float(event.t_appear) > float(context.trigger_time) + 1e-9]
        if not future_events or len(context.active_ids) <= 1:
            return RollingPolicyDecision(metadata={"action": "myopic_no_future"})
        node_by_id = {node.node_id: node for node in context.effective_instance.nodes}
        max_defer = min(len(context.active_ids) - 1, max(1, int(math.ceil(len(context.active_ids) * max(0.0, reserve_fraction)))))
        add_ids = {event.customer_id for event in context.stage_events if str(event.event_type).lower() == "add"}
        candidates: list[tuple[float, str]] = []
        for customer_id in sorted(context.active_ids):
            if defer_mode == "defer_adds" and customer_id not in add_ids:
                continue
            node = node_by_id.get(customer_id)
            if node is None:
                continue
            slack = float(node.due_time) - float(context.trigger_time)
            if slack >= float(min_slack_seconds):
                candidates.append((slack, customer_id))
        deferred = {customer_id for _slack, customer_id in sorted(candidates, reverse=True)[:max_defer]}
        if not deferred:
            return RollingPolicyDecision(metadata={"action": "myopic_no_safe_defer"})
        active = set(context.active_ids) - deferred
        return RollingPolicyDecision(
            active_ids=active,
            metadata={
                "action": f"{defer_mode}_reserve_capacity_defer",
                "policy_mode": mode,
                "reserve_capacity_fraction": float(reserve_fraction),
                "deferred_ids": sorted(deferred),
                "future_event_count": len(future_events),
            },
        )

    reserve_defer_policy.__name__ = f"track20_{mode}_policy"
    return reserve_defer_policy


def _preposition_decision(context: RollingPolicyContext) -> RollingPolicyDecision:
    future_adds = [
        event
        for event in context.all_events
        if str(event.event_type).lower() == "add" and float(event.t_appear) > float(context.trigger_time) + 1e-9
    ]
    if not future_adds or not context.active_ids:
        return RollingPolicyDecision(metadata={"action": "preposition_no_future_adds", "policy_mode": "preposition"})
    depots = sorted(
        [node for node in context.effective_instance.nodes if str(node.node_type).lower() == "d"],
        key=lambda node: str(node.node_id),
    )
    if not depots:
        return RollingPolicyDecision(metadata={"action": "preposition_no_depots", "policy_mode": "preposition"})
    cx = sum(float(event.x) for event in future_adds) / len(future_adds)
    cy = sum(float(event.y) for event in future_adds) / len(future_adds)
    depot = min(depots, key=lambda node: ((float(node.x) - cx) ** 2 + (float(node.y) - cy) ** 2, str(node.node_id)))
    node_by_id = {str(node.node_id): node for node in context.effective_instance.nodes}
    active = [customer_id for customer_id in sorted(context.active_ids) if customer_id in node_by_id]
    if not active:
        return RollingPolicyDecision(metadata={"action": "preposition_no_active_customers", "policy_mode": "preposition"})
    vehicle_count = max(1, min(int(context.effective_instance.num_cv or 1), len(active)))
    chunk_size = max(1, int(math.ceil(len(active) / vehicle_count)))
    routes = []
    for idx in range(0, len(active), chunk_size):
        customers = active[idx : idx + chunk_size]
        routes.append(Route(f"CV_PREPOSITION_{len(routes) + 1}", "cv", str(depot.node_id), [str(depot.node_id), *customers, str(depot.node_id)]))
    return RollingPolicyDecision(
        initial_plan=Solution(routes=routes),
        metadata={
            "action": "preposition_initial_plan",
            "policy_mode": "preposition",
            "preposition_depot_id": str(depot.node_id),
            "preposition_route_count": len(routes),
            "future_add_count": len(future_adds),
        },
    )


def _regression_row(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    fields = ("dynamic_cost", "static_revealed_cost", "information_cost", "information_cost_pct")
    deltas = {f"{field}_delta": _to_float(candidate.get(field)) - _to_float(baseline.get(field)) for field in fields}
    passed = all(math.isfinite(value) and abs(value) <= 1e-6 for value in deltas.values())
    return {
        "bundle": baseline.get("bundle"),
        "seed": int(baseline.get("seed", 0) or 0),
        "regression_status": "PASS" if passed else "FAIL",
        "baseline_payload_path": baseline.get("payload_path", ""),
        "callback_payload_path": candidate.get("payload_path", ""),
        **{f"baseline_{field}": baseline.get(field) for field in fields},
        **{f"callback_{field}": candidate.get(field) for field in fields},
        **deltas,
    }


def _comparison_row(baseline: dict[str, Any], heuristic: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    myopic_info = _to_float(baseline.get("information_cost"))
    heuristic_info = _to_float(heuristic.get("information_cost"))
    reduction = myopic_info - heuristic_info
    reduction_pct = (reduction / myopic_info * 100.0) if myopic_info > 0 and math.isfinite(reduction) else math.nan
    policy_trace = list(payload.get("policy_trace") or [])
    defer_total = sum(int(row.get("deferred_count", 0) or 0) for row in policy_trace)
    defer_stages = sum(1 for row in policy_trace if int(row.get("deferred_count", 0) or 0) > 0)
    policy_modes = sorted(
        {
            str((row.get("metadata") or {}).get("policy_mode"))
            for row in policy_trace
            if isinstance(row.get("metadata"), dict) and (row.get("metadata") or {}).get("policy_mode")
        }
    )
    return {
        "stage": "action_sanity",
        "algorithm": "track20_reserve_defer_heuristic",
        "policy_mode": ",".join(policy_modes) if policy_modes else "myopic_or_no_defer",
        "bundle": baseline.get("bundle"),
        "bundle_dir": baseline.get("bundle_dir"),
        "seed": int(baseline.get("seed", 0) or 0),
        "scale": baseline.get("scale"),
        "status": heuristic.get("status"),
        "health_status": heuristic.get("health_status"),
        "myopic_dynamic_cost": _to_float(baseline.get("dynamic_cost")),
        "heuristic_dynamic_cost": _to_float(heuristic.get("dynamic_cost")),
        "myopic_static_revealed_cost": _to_float(baseline.get("static_revealed_cost")),
        "heuristic_static_revealed_cost": _to_float(heuristic.get("static_revealed_cost")),
        "myopic_information_cost": myopic_info,
        "heuristic_information_cost": heuristic_info,
        "myopic_information_cost_pct": _to_float(baseline.get("information_cost_pct")),
        "heuristic_information_cost_pct": _to_float(heuristic.get("information_cost_pct")),
        "information_cost_reduction": reduction,
        "information_cost_reduction_pct_of_myopic": reduction_pct,
        "dynamic_cost_delta": _to_float(heuristic.get("dynamic_cost")) - _to_float(baseline.get("dynamic_cost")),
        "static_cost_delta": _to_float(heuristic.get("static_revealed_cost")) - _to_float(baseline.get("static_revealed_cost")),
        "policy_deferred_total": defer_total,
        "policy_defer_stage_count": defer_stages,
        "policy_trace_stage_count": len(policy_trace),
        "trigger_count": heuristic.get("trigger_count"),
        "event_count": heuristic.get("event_count"),
        "actual_evals": heuristic.get("actual_evals"),
        "elapsed_seconds": heuristic.get("elapsed_seconds"),
        "payload_path": heuristic.get("payload_path"),
    }


def _summarize_action_sanity(rows: list[dict[str, Any]], *, planned_count: int, partial: bool, reason: str) -> dict[str, Any]:
    health_failures = [row for row in rows if row.get("health_status") != "HEALTHY"]
    healthy = [row for row in rows if row.get("health_status") == "HEALTHY"]
    myopic_infos = [_to_float(row.get("myopic_information_cost")) for row in healthy]
    heuristic_infos = [_to_float(row.get("heuristic_information_cost")) for row in healthy]
    pairs = [(m, h) for m, h in zip(myopic_infos, heuristic_infos) if math.isfinite(m) and math.isfinite(h)]
    reductions = [m - h for m, h in pairs]
    reduction_pcts = [(m - h) / m * 100.0 for m, h in pairs if m > 0]
    mean_myopic = _mean([m for m, _h in pairs])
    mean_heuristic = _mean([h for _m, h in pairs])
    mean_reduction = _mean(reductions)
    mean_reduction_pct = _mean(reduction_pcts)
    wins = sum(1 for value in reductions if value > 1e-6)
    losses = sum(1 for value in reductions if value < -1e-6)
    p_value = _wilcoxon_pvalue([h for _m, h in pairs], [m for m, _h in pairs])
    reducible = max(0.0, mean_reduction) if math.isfinite(mean_reduction) else math.nan
    remaining = mean_heuristic if math.isfinite(mean_heuristic) else math.nan
    reducible_share = (reducible / mean_myopic * 100.0) if math.isfinite(reducible) and mean_myopic > 0 else math.nan
    if health_failures:
        verdict = "HALT_HEURISTIC_HEALTH"
        verdict_reason = reason or f"{len(health_failures)} heuristic rows failed dynamic health."
    elif partial or len(rows) < planned_count:
        verdict = "RUNNING"
        verdict_reason = reason or f"Partial Track20 rows: {len(rows)}/{planned_count}."
    elif mean_reduction_pct >= 3.0 and wins >= math.ceil(0.6 * len(pairs)) and math.isfinite(p_value) and p_value <= 0.05:
        verdict = "HEURISTIC_MOVES_HEADROOM"
        verdict_reason = f"Heuristic reduced mean information_cost by {mean_reduction_pct:.3f}% with wins={wins}/{len(pairs)} and Wilcoxon p={p_value:.6g}."
    else:
        verdict = "HEURISTIC_FLAT"
        verdict_reason = f"Heuristic did not pass the action-headroom gate: mean_reduction_pct={mean_reduction_pct}, wins={wins}/{len(pairs)}, p={p_value}."
    return {
        "verdict": verdict,
        "reason": verdict_reason,
        "rows": rows,
        "row_count": len(rows),
        "planned_count": planned_count,
        "healthy_count": len(healthy),
        "health_failure_count": len(health_failures),
        "health_failures": health_failures,
        "mean_myopic_information_cost": mean_myopic,
        "mean_heuristic_information_cost": mean_heuristic,
        "mean_information_cost_reduction": mean_reduction,
        "mean_information_cost_reduction_pct_of_myopic": mean_reduction_pct,
        "wins": wins,
        "losses": losses,
        "wilcoxon_p_value": p_value,
        "reducible_information_cost": reducible,
        "remaining_information_cost": remaining,
        "reducible_share_pct": reducible_share,
        "remaining_share_pct": 100.0 - reducible_share if math.isfinite(reducible_share) else math.nan,
    }


def _mean(values: list[float]) -> float:
    values = [value for value in values if math.isfinite(value)]
    return sum(values) / len(values) if values else math.nan


def _summarize_final(state: dict[str, Any]) -> tuple[str, str]:
    sanity = state.get("action_sanity") or {}
    if sanity.get("verdict"):
        return str(sanity["verdict"]), str(sanity.get("reason", ""))
    regression = state.get("regression") or {}
    if regression.get("verdict") == "HALT_MYOPIC_CALLBACK_REGRESSION":
        return str(regression["verdict"]), str(regression.get("reason", ""))
    return "RUNNING", "Track20 is not complete."


def _regression_report(regression: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Track20 Myopic Callback Regression",
            "",
            f"Verdict: {regression.get('verdict')}",
            f"Reason: {regression.get('reason')}",
            "Rows are also written to `track20_myopic_callback_regression.csv`.",
        ]
    ) + "\n"


def _action_sanity_report(sanity: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Track20 Action Sanity Report",
            "",
            f"Verdict: {sanity.get('verdict')}",
            f"Reason: {sanity.get('reason')}",
            f"Rows: {sanity.get('row_count')}/{sanity.get('planned_count')}",
            f"Healthy rows: {sanity.get('healthy_count')}",
            f"Mean myopic information_cost: {sanity.get('mean_myopic_information_cost')}",
            f"Mean heuristic information_cost: {sanity.get('mean_heuristic_information_cost')}",
            f"Mean information_cost reduction: {sanity.get('mean_information_cost_reduction')}",
            f"Mean reduction pct of myopic: {sanity.get('mean_information_cost_reduction_pct_of_myopic')}",
            f"Wins/losses: {sanity.get('wins')}/{sanity.get('losses')}",
            f"Wilcoxon p-value: {sanity.get('wilcoxon_p_value')}",
            f"Reducible share pct: {sanity.get('reducible_share_pct')}",
            f"Remaining share pct: {sanity.get('remaining_share_pct')}",
            "",
            "No DR policy was trained. This report only tests whether a hand-coded online action can reduce the Track18 information-cost gap.",
        ]
    ) + "\n"


def _final_report(state: dict[str, Any]) -> str:
    regression = state.get("regression") or {}
    sanity = state.get("action_sanity") or {}
    return (
        "# Final Track20 Report\n\n"
        f"Final status: {state.get('final_status', 'RUNNING')}\n"
        f"Final reason: {state.get('final_reason', '')}\n\n"
        "## Regression\n"
        f"Verdict: {regression.get('verdict', 'NOT_RUN')}\n"
        f"Reason: {regression.get('reason', '')}\n\n"
        "## Action Sanity\n"
        f"Verdict: {sanity.get('verdict', 'NOT_RUN')}\n"
        f"Mean myopic information_cost: {sanity.get('mean_myopic_information_cost', math.nan)}\n"
        f"Mean heuristic information_cost: {sanity.get('mean_heuristic_information_cost', math.nan)}\n"
        f"Mean reduction pct of myopic: {sanity.get('mean_information_cost_reduction_pct_of_myopic', math.nan)}\n"
        f"Reducible share pct: {sanity.get('reducible_share_pct', math.nan)}\n"
        f"Remaining share pct: {sanity.get('remaining_share_pct', math.nan)}\n\n"
        "## Decision\n"
        "Track20 tests the dynamic action surface only. A positive result means DR has a credible next interface; a flat result means the current reserve/defer action does not eat the Track18 headroom.\n"
    )


def _enforce_resume_guard(state: dict[str, Any], *, resume: bool, force: bool) -> None:
    status = str(state.get("final_status") or "")
    if resume or force or not status or status in {"RUNNING", "HALT_WALL_CLOCK"}:
        return
    if status in TERMINAL_STATUSES:
        raise Track20Halt(status, f"Existing terminal Track20 state found ({status}); pass --force to rerun.")


def _normalize_preflight_args(args: argparse.Namespace) -> None:
    args.health_bundles = getattr(args, "health_bundles", "") or ""
    args.ablation_bundles = getattr(args, "ablation_bundles", "") or ""
    args.formal_bundles = getattr(args, "formal_bundles", "") or str(args.bundles)
    args.min_free_disk_gb = getattr(args, "min_free_disk_gb", 5.0)
    args.require_self_py313 = getattr(args, "require_self_py313", False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track20 dynamic action sanity runner.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    parser.add_argument("--track18-rows", default=str(DEFAULT_TRACK18_ROWS))
    parser.add_argument("--bundles", default=",".join(DEFAULT_BUNDLES))
    parser.add_argument("--health-bundles", default="")
    parser.add_argument("--ablation-bundles", default="")
    parser.add_argument("--formal-bundles", default="")
    parser.add_argument("--seeds", default="901,902,903,904,905,906,907,908,909,910")
    parser.add_argument("--eval-budget", type=int, default=2000)
    parser.add_argument("--max-runtime-seconds", type=float, default=180.0)
    parser.add_argument("--stage-eval-budget", type=int, default=2000)
    parser.add_argument("--stage-max-runtime-seconds", type=float, default=120.0)
    parser.add_argument("--stages", type=int, default=4)
    parser.add_argument("--reserve-fraction", type=float, default=0.20)
    parser.add_argument(
        "--policy-mode",
        choices=("defer_adds", "reserve_defer", "reserve_capacity", "commit_defer", "preposition"),
        default="defer_adds",
    )
    parser.add_argument("--defer-min-slack-seconds", type=float, default=7200.0)
    parser.add_argument("--max-wall-seconds", type=float, default=6 * 3600.0)
    parser.add_argument("--min-free-disk-gb", type=float, default=5.0)
    parser.add_argument("--require-self-py313", action="store_true")
    parser.add_argument("--max-runs", type=int, default=0, help="Optional smoke cap; 0 means all planned rows.")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
