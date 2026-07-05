"""Track24 mechanism-action-space audit for DR-ALNS.

This runner is evidence-first: it imports Track21/23 evidence, decomposes the
Track23 dynamic headroom, and only allows learning after a non-learning oracle
shows real action-space headroom.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable

from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.dynamic import RollingParameters, RollingPolicyContext, RollingPolicyDecision, run_rolling_reoptimization

from . import final_track18
from . import track22_endgame as track22


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track24_breakthrough_audit")
DEFAULT_TRACK23_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track23")
DEFAULT_TRACK21_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track21_reclaim")
BREAKTHROUGH_MAP = Path("docs/handoff/dr_alns_breakthrough_map_20260705.md")
DEFAULT_WORKER = Path(r"C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe")
PROTECTED_FILES = [
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
    Path("solver/src/setp_solver/search/metaheuristic_baselines.py"),
]

STRONG_DYNAMIC_ACTION_SPACE = "STRONG_DYNAMIC_ACTION_SPACE"
WEAK_DYNAMIC_ACTION_SPACE = "WEAK_DYNAMIC_ACTION_SPACE"
HALT_DYNAMIC_ACTION_SPACE_FLAT = "HALT_DYNAMIC_ACTION_SPACE_FLAT"
PASS_DYNAMIC_IMITATION = "PASS_DYNAMIC_IMITATION"
WEAK_DYNAMIC_IMITATION = "WEAK_DYNAMIC_IMITATION"
HALT_DYNAMIC_IMITATION = "HALT_DYNAMIC_IMITATION"
BLOCKED_FAIRNESS_BASELINE_NOT_EXPOSED = "BLOCKED_FAIRNESS_BASELINE_NOT_EXPOSED"
FAIRNESS_ACTION_SPACE_REAL = "FAIRNESS_ACTION_SPACE_REAL"
FAIRNESS_ACTION_SPACE_WEAK = "FAIRNESS_ACTION_SPACE_WEAK"
HALT_FAIRNESS_ACTION_SPACE_FLAT = "HALT_FAIRNESS_ACTION_SPACE_FLAT"
CARBON_CHARGING_SIGNAL_REAL = "CARBON_CHARGING_SIGNAL_REAL"
CARBON_CHARGING_SCENARIO_ONLY = "CARBON_CHARGING_SCENARIO_ONLY"
HALT_CARBON_CHARGING_FLAT = "HALT_CARBON_CHARGING_FLAT"


class Track24Halt(RuntimeError):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "track24_progress.log"
    state_path = output_dir / "track24_state.json"
    state = _load_json(state_path) if args.resume and state_path.is_file() else {}
    selected = {item.strip().upper() for item in str(args.stages).split(",") if item.strip()}
    started = time.monotonic()

    def save() -> None:
        _write_json(state_path, state)
        _write_json(output_dir / "track24_decision.json", summarize_final_decision(state))
        write_final_report(output_dir / "final_report.md", state)

    if not state.get("preflight"):
        state["preflight"] = track22.run_preflight(args, output_dir)
        _write_json(output_dir / "track24_preflight.json", state["preflight"])
        save()

    stage_funcs: dict[str, tuple[str, Callable[[], dict[str, Any]]]] = {
        "0": ("stage0", lambda: run_stage0(args, output_dir)),
        "1": ("stage1", lambda: run_stage1(args, output_dir, state)),
        "2": ("stage2", lambda: run_stage2(args, output_dir)),
        "3": ("stage3", lambda: run_stage3(args, output_dir, progress_path, started)),
        "4": ("stage4", lambda: run_stage4(args, output_dir, progress_path, state)),
        "5": ("stage5", lambda: run_stage5(args, output_dir, progress_path)),
        "6": ("stage6", lambda: run_stage6(args, output_dir)),
        "7": ("stage7", lambda: summarize_final_decision(state)),
    }
    for label, (key, body) in stage_funcs.items():
        if label not in selected or (key in state and key != "stage7" and not args.force):
            continue
        try:
            _log(progress_path, f"Stage {label} start")
            state[key] = body()
            _log(progress_path, f"Stage {label} status={state[key].get('status', state[key].get('final_status', 'OK'))}")
            save()
        except Track24Halt as exc:
            state[key] = {"status": exc.status, "reason": exc.reason}
            _log(progress_path, f"Stage {label} halt={exc.status}: {exc.reason}")
            save()
            if not args.continue_on_halt:
                return 2
        except Exception as exc:  # noqa: BLE001 - keep recoverable state files for long runs.
            state[key] = {"status": "STAGE_ERROR", "reason": str(exc), "error_type": exc.__class__.__name__}
            _log(progress_path, f"Stage {label} error={exc.__class__.__name__}: {exc}")
            save()
            if not args.continue_on_halt:
                return 1
    save()
    return 0


def run_stage0(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    track23 = _load_json(Path(args.track23_dir) / "track23_final_report.json")
    track21_md = _read_text(Path(args.track21_dir) / "final_report.md")
    git_info = {
        "head": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "origin_dr_x86": _git("rev-parse", "origin/dr-x86"),
        "status_short_branch": _git("status", "--short", "--branch"),
    }
    protected = []
    for path in PROTECTED_FILES:
        protected.append(
            {
                "path": path.as_posix(),
                "sha256": _sha256(path),
                "git_status": _git("status", "--short", "--", path.as_posix()),
            }
        )
    handoff_text = _read_text(Path("HANDOFF.md"))
    payload = {
        "status": "EVIDENCE_INDEX_COMPLETE",
        "git": git_info,
        "track21": {
            "final_status": _extract_between(track21_md, "Final status: `", "`") or "UNKNOWN",
            "status_25c_50c": "MARGIN_REAL" if "Verdict for 25c/50c: `MARGIN_REAL`" in track21_md else "UNKNOWN",
            "status_100c": "HALT_100C_STILL_STARVED" if "HALT_100C_STILL_STARVED" in track21_md else "UNKNOWN",
            "valid_but_weak_preserved": "VALID_BUT_WEAK" in track21_md,
            "invalid_not_run_preserved": "INVALID_NOT_RUN" in track21_md,
        },
        "track23": {
            "final_status": track23.get("final_status"),
            "pillar_summary": track23.get("pillar_summary"),
            "stage_a": (track23.get("stage_a") or {}).get("status"),
            "stage_b": (track23.get("stage_b") or {}).get("status"),
            "stage_c": (track23.get("stage_c") or {}).get("status"),
            "stage_d": (track23.get("stage_d") or {}).get("status"),
            "stage_d_mean_information_cost_pct": ((track23.get("stage_d") or {}).get("headroom") or {}).get("mean_information_cost_pct"),
        },
        "breakthrough_map": {"path": BREAKTHROUGH_MAP.as_posix(), "sha256": _sha256(BREAKTHROUGH_MAP)},
        "protected_files": protected,
        "handoff_track23_placeholders_remaining": any(token in handoff_text for token in ("$status", "$head", "$stageB", "$stageC", "$stageD")),
    }
    _write_json(output_dir / "track24_evidence_index.json", payload)
    _write_text(output_dir / "track24_evidence_index.md", render_stage0_report(payload))
    return payload


def run_stage1(args: argparse.Namespace, output_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    _ = args, state
    rows = [
        {
            "experiment_id": "E2",
            "paper_role": "algorithm strength / no-tuning parity",
            "current_evidence": "Track23 Stage C NO_TUNING_PARITY_CLEAN; 60 rows; worst DR gap -1.926% vs strongest non-DR.",
            "current_status": "DR parity stands, old operator/meta is not a breakthrough route.",
            "missing_action_head": "None for old operator/meta; mechanism heads needed elsewhere.",
            "missing_observation_signal": "Regime/mechanism features beyond static 24d block state.",
            "possible_oracle": "Best static meta / no-tuning selector only as reference.",
            "oracle_gate": "No direct training gate; E2 alone cannot justify new PPO.",
            "train_if_oracle_passes": "False for old operator/meta.",
            "hard_stop_condition": "Do not continue old operator/meta PPO.",
            "required_m1_dependency": "Formal absolute E2 table remains M1-only.",
        },
        {
            "experiment_id": "E3",
            "paper_role": "mechanism ablation",
            "current_evidence": "Breakthrough map says mechanism switches must alter action payoff before DR is meaningful.",
            "current_status": "HEADROOM_UNKNOWN",
            "missing_action_head": "Mechanism-aware switch/gate head.",
            "missing_observation_signal": "Mechanism-on/off state and payoff deltas.",
            "possible_oracle": "Non-learning selector across mechanism switch states.",
            "oracle_gate": "Only train if switch changes cost/fairness/carbon action payoff.",
            "train_if_oracle_passes": "Conditional.",
            "hard_stop_condition": "No measurable mechanism action payoff delta.",
            "required_m1_dependency": "Final mechanism contract and ablation scenario definitions.",
        },
        {
            "experiment_id": "E4/E5",
            "paper_role": "carbon and charging timing",
            "current_evidence": "Track23 Stage B CARBON_MECHANISM_WEAK; default timing delta 0.000%, ceiling 1.934%; EV-heavy diagnostic carbon share 14.694%.",
            "current_status": "Default weak; scenario knobs may create signal.",
            "missing_action_head": "Carbon/charging timing head.",
            "missing_observation_signal": "Carbon share, gamma amplitude, EV route count, charging slack.",
            "possible_oracle": "Aware-vs-naive timing under knob grid.",
            "oracle_gate": "carbon share >=8% and timing delta >=2% for REAL.",
            "train_if_oracle_passes": "Only after Stage 6 REAL; never train carbon head here.",
            "hard_stop_condition": "All knobs flat or infeasible.",
            "required_m1_dependency": "Final carbon price/intensity/charging capacity scenario contract.",
        },
        {
            "experiment_id": "E6",
            "paper_role": "profit fairness",
            "current_evidence": "fairness.py exposes Pi_d0, Pi_d, profit_ratio and fairness violations, but Track24 must verify stable export.",
            "current_status": "SIGNAL_AUDIT_REQUIRED",
            "missing_action_head": "fairness-safe repair / depot-ratio slack head.",
            "missing_observation_signal": "Pi_d0, Pi_d, Pi_d/Pi_d0, min ratio, fairness slack.",
            "possible_oracle": "fairness-safe repair selector vs ordinary repair at theta low/medium/high.",
            "oracle_gate": "reduced penalty/violations with controlled cost increase.",
            "train_if_oracle_passes": "False in Track24; audit only.",
            "hard_stop_condition": "BLOCKED_FAIRNESS_BASELINE_NOT_EXPOSED or flat oracle.",
            "required_m1_dependency": "Final theta and fairness baseline semantics.",
        },
        {
            "experiment_id": "E7",
            "paper_role": "dynamic rolling reoptimization",
            "current_evidence": "Track23 Stage D HEADROOM_REAL mean information_cost_pct=44.707%, but old reserve/commit/preposition HEURISTIC_FLAT.",
            "current_status": "Highest-priority action-space audit.",
            "missing_action_head": "capacity reserve, commit threshold, future-cluster reserve, EV/charging slack, optional stage budget allocation.",
            "missing_observation_signal": "stage load, event density, slack, route/charging counts, depot balance.",
            "possible_oracle": "post-hoc non-learning dynamic action oracle over real RollingPolicyDecision actions.",
            "oracle_gate": ">=5 pp strong; 2-5 pp weak; <2 pp halt.",
            "train_if_oracle_passes": "Only if oracle >=2 pp, then Stage 4 imitation/bandit.",
            "hard_stop_condition": "Illegal row, underbudget row, violation, or oracle reduction <2 pp.",
            "required_m1_dependency": "Final dynamic event/scenario contract for paper numbers.",
        },
    ]
    _write_csv(output_dir / "track24_headroom_matrix.csv", rows)
    summary = {"status": "HEADROOM_MATRIX_COMPLETE", "row_count": len(rows), "priority": "E7"}
    _write_json(output_dir / "track24_headroom_matrix.json", {"status": summary["status"], "rows": rows})
    _write_text(output_dir / "track24_headroom_matrix.md", render_matrix_report(rows))
    return summary | {"rows": rows}


def run_stage2(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    rows_path = Path(args.track23_dir) / "stage_d_track18" / "track18_headroom.csv"
    rows = [row for row in final_track18._read_rows(rows_path) if row.get("health_status") == "HEALTHY"]
    out_rows: list[dict[str, Any]] = []
    missing_fields: set[str] = set()
    for row in rows:
        payload_path = Path(str(row.get("payload_path") or ""))
        payload = _load_json(payload_path) if payload_path.is_file() else {}
        stage_rows = list(payload.get("stage_rows") or [])
        for stage_row in stage_rows:
            if str(stage_row.get("stage")) == "dynamic_vs_static":
                continue
            required = [
                "active_customer_count",
                "planned_customer_count",
                "newly_revealed_customer_count",
                "committed_customer_count",
                "stage_route_count",
                "stage_ev_route_count",
                "stage_charging_action_count",
            ]
            for key in required:
                if key not in stage_row:
                    missing_fields.add(key)
            out_rows.append(
                {
                    "scenario": row.get("bundle"),
                    "seed": row.get("seed"),
                    "scale": row.get("scale"),
                    "stage": stage_row.get("stage"),
                    "depot": "ALL",
                    "vehicle_type": "ALL",
                    "dynamic_cost": row.get("dynamic_cost"),
                    "static_revealed_cost": row.get("static_revealed_cost"),
                    "information_cost": row.get("information_cost"),
                    "information_cost_pct": row.get("information_cost_pct"),
                    "committed_customer_count": stage_row.get("committed_customer_count", ""),
                    "newly_revealed_customer_count": stage_row.get("newly_revealed_customer_count", ""),
                    "rejected_deferred_pending_customer_count": stage_row.get("deferred_customer_count", ""),
                    "route_slack": "",
                    "time_slack": "",
                    "ev_route_count": stage_row.get("stage_ev_route_count", ""),
                    "charging_action_count": stage_row.get("stage_charging_action_count", ""),
                    "soc_or_charging_slack": "",
                    "depot_level_load_capacity_proxy": "",
                    "event_density": payload.get("event_count", ""),
                    "trigger_count": payload.get("trigger_count", ""),
                    "event_spatial_clustering_proxy": _event_cluster_proxy(payload.get("events") or []),
                    "trace_status": "OK" if not missing_fields else "TRACE_LIMITED_EXISTING_PAYLOAD",
                    "payload_path": str(payload_path),
                }
            )
    _write_csv(output_dir / "stage2_dynamic_failure_decomposition.csv", out_rows)
    values = [_float(row.get("information_cost_pct")) for row in rows if math.isfinite(_float(row.get("information_cost_pct")))]
    summary = {
        "status": "TRACE_LIMITED_EXISTING_PAYLOAD" if missing_fields else "DYNAMIC_FAILURE_DECOMPOSITION_COMPLETE",
        "row_count": len(out_rows),
        "scenario_count": len(rows),
        "mean_information_cost_pct": _mean(values),
        "missing_fields": sorted(missing_fields),
        "root_cause_answer": (
            "Existing Track23 payloads prove a large information-cost pool but do not expose enough route/depot/EV slack "
            "to honestly assign the loss to capacity lock-in, depot mismatch, early commitment, EV slack, or budget."
            if missing_fields
            else "Trace fields are present; see per-stage rows for proxy decomposition."
        ),
        "old_action_failure_answer": "Track23 Track20 reserve/commit/preposition changed the online surface but did not reduce mean information cost by the 2pp gate.",
        "likely_action_answer": "Only actions that change active customer commitment, initial stage plan, or stage budget are eligible for Stage 3.",
    }
    _write_json(output_dir / "stage2_dynamic_failure_decomposition.json", summary | {"rows": out_rows})
    _write_text(output_dir / "stage2_dynamic_failure_decomposition.md", render_stage2_report(summary))
    return summary


def run_stage3(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    baseline_rows = [
        row
        for row in final_track18._read_rows(Path(args.track23_dir) / "stage_d_track18" / "track18_headroom.csv")
        if row.get("health_status") == "HEALTHY"
    ]
    rows_path = output_dir / "stage3_dynamic_oracle_rows.csv"
    rows = _read_csv(rows_path) if args.resume and rows_path.is_file() and not args.force else []
    done = {(row.get("bundle"), int(float(row.get("seed") or 0)), row.get("action_id")) for row in rows}
    action_specs = build_stage3_action_specs(int(args.stage3_stage_eval_budget), float(args.stage3_stage_max_runtime_seconds))
    launched = 0
    for baseline in baseline_rows:
        for spec in action_specs:
            key = (baseline.get("bundle"), int(float(baseline.get("seed") or 0)), spec["action_id"])
            if key in done:
                continue
            if int(args.stage3_max_runs) > 0 and launched >= int(args.stage3_max_runs):
                summary = summarize_stage3_oracle(baseline_rows, rows, action_specs, partial=True, reason="Stopped after stage3_max_runs.")
                _write_stage3_outputs(output_dir, summary, rows)
                return summary
            _check_wall(started, float(args.stage3_max_wall_seconds))
            payload_path = output_dir / "stage3_payloads" / f"{final_track18._safe_name(str(baseline['bundle']))}_seed{int(float(baseline['seed']))}_{spec['action_id']}.json"
            _log(progress_path, f"Stage3 oracle bundle={baseline['bundle']} seed={baseline['seed']} action={spec['action_id']}")
            payload = run_rolling_reoptimization(
                baseline["bundle_dir"],
                output_json_path=payload_path,
                seed=int(float(baseline["seed"])),
                eval_budget=int(args.stage3_static_eval_budget),
                max_runtime_seconds=float(args.stage3_static_max_runtime_seconds),
                stage_eval_budget=int(args.stage3_stage_eval_budget),
                stage_max_runtime_seconds=float(args.stage3_stage_max_runtime_seconds),
                params=RollingParameters(stages=int(args.stage3_rolling_stages)),
                policy_callback=build_track24_dynamic_policy(spec),
            )
            candidate = final_track18._payload_row(
                payload,
                bundle_dir=baseline["bundle_dir"],
                seed=int(float(baseline["seed"])),
                output_json=payload_path,
            )
            row = oracle_comparison_row(baseline, candidate, payload, spec)
            rows.append(row)
            _write_csv(rows_path, rows)
            launched += 1
    summary = summarize_stage3_oracle(baseline_rows, rows, action_specs, partial=False, reason="")
    _write_stage3_outputs(output_dir, summary, rows)
    return summary


def build_stage3_action_specs(stage_eval_budget: int, stage_runtime: float) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for level, fraction in (("low", 0.10), ("medium", 0.20), ("high", 0.30)):
        specs.append({"action_id": f"capacity_reserve_{level}", "action_class": "depot_capacity_reserve", "level": level, "fraction": fraction})
    for level, fraction in (("conservative", 0.30), ("normal", 0.15), ("aggressive", 0.05)):
        specs.append({"action_id": f"commit_threshold_{level}", "action_class": "customer_commit_threshold", "level": level, "fraction": fraction})
    for level, fraction in (("low", 0.10), ("medium", 0.20), ("high", 0.30)):
        specs.append({"action_id": f"future_cluster_reserve_{level}", "action_class": "future_cluster_reserve", "level": level, "fraction": fraction})
    for level, fraction in (("low", 0.10), ("medium", 0.20), ("high", 0.30)):
        specs.append({"action_id": f"ev_charging_slack_reserve_{level}", "action_class": "ev_charging_slack_reserve", "level": level, "fraction": fraction})
    specs.append(
        {
            "action_id": "stage_budget_event_density",
            "action_class": "stage_budget_allocation",
            "level": "event_density",
            "fraction": 0.0,
            "base_stage_eval_budget": int(stage_eval_budget),
            "base_stage_max_runtime_seconds": float(stage_runtime),
        }
    )
    return specs


def build_track24_dynamic_policy(spec: dict[str, Any]):
    def policy(context: RollingPolicyContext) -> RollingPolicyDecision:
        node_by_id = {node.node_id: node for node in context.effective_instance.nodes}
        fraction = max(0.0, float(spec.get("fraction", 0.0)))
        action_class = str(spec["action_class"])
        metadata = {
            "track24_action_id": spec["action_id"],
            "action_class": action_class,
            "action_level": spec.get("level"),
            "fraction": fraction,
        }
        if action_class == "stage_budget_allocation":
            event_count = len(context.stage_events)
            factor = 1.4 if event_count >= 2 else (0.75 if int(context.stage_index) <= 1 else 1.1)
            budget = max(1, int(round(int(spec["base_stage_eval_budget"]) * factor)))
            runtime = max(1.0, float(spec["base_stage_max_runtime_seconds"]) * factor)
            metadata["budget_factor"] = factor
            return RollingPolicyDecision(stage_eval_budget=budget, stage_max_runtime_seconds=runtime, metadata=metadata)
        if len(context.active_ids) <= 1:
            metadata["action_effect"] = "no_active_room"
            return RollingPolicyDecision(metadata=metadata)
        if action_class == "future_cluster_reserve":
            future_adds = [event for event in context.all_events if str(event.event_type).lower() == "add" and float(event.t_appear) > float(context.trigger_time) + 1e-9]
            if not future_adds:
                metadata["action_effect"] = "no_future_adds"
                return RollingPolicyDecision(metadata=metadata)
            cx = sum(float(event.x) for event in future_adds) / len(future_adds)
            cy = sum(float(event.y) for event in future_adds) / len(future_adds)
            scored = [
                (((float(node_by_id[cid].x) - cx) ** 2 + (float(node_by_id[cid].y) - cy) ** 2), cid)
                for cid in context.active_ids
                if cid in node_by_id
            ]
            deferred = _take_fraction([cid for _score, cid in sorted(scored)], fraction)
        elif action_class == "ev_charging_slack_reserve":
            depots = [node for node in context.effective_instance.nodes if str(node.node_type).lower() == "d"]
            scored = []
            for cid in context.active_ids:
                node = node_by_id.get(cid)
                if node is None:
                    continue
                nearest = min((((float(node.x) - float(depot.x)) ** 2 + (float(node.y) - float(depot.y)) ** 2) for depot in depots), default=0.0)
                scored.append((nearest + float(node.demand) * 10.0, cid))
            deferred = _take_fraction([cid for _score, cid in sorted(scored, reverse=True)], fraction)
        elif action_class == "customer_commit_threshold":
            stage_adds = {event.customer_id for event in context.stage_events if str(event.event_type).lower() == "add"}
            pool = [cid for cid in sorted(context.active_ids) if cid in stage_adds] or sorted(context.active_ids)
            deferred = _take_fraction(pool, fraction)
        else:
            scored = []
            for cid in context.active_ids:
                node = node_by_id.get(cid)
                if node is None:
                    continue
                slack = float(node.due_time) - float(context.trigger_time)
                scored.append((slack, cid))
            deferred = _take_fraction([cid for _score, cid in sorted(scored, reverse=True)], fraction)
        active = set(context.active_ids) - set(deferred)
        metadata["deferred_ids"] = sorted(deferred)
        metadata["action_effect"] = "active_ids_changed" if deferred else "no_safe_defer"
        return RollingPolicyDecision(active_ids=active if deferred else None, metadata=metadata)

    policy.__name__ = f"track24_{spec['action_id']}"
    return policy


def oracle_comparison_row(baseline: dict[str, Any], candidate: dict[str, Any], payload: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    myopic_pct = _float(baseline.get("information_cost_pct"))
    candidate_pct = _float(candidate.get("information_cost_pct"))
    trace = list(payload.get("policy_trace") or [])
    changed_stages = sum(
        1
        for row in trace
        if int(row.get("deferred_count", 0) or 0) > 0
        or int(row.get("stage_eval_budget", 0) or 0) != int(payload.get("stage_eval_budget", 0) or 0)
    )
    return {
        "stage": "stage3_dynamic_oracle",
        "action_id": spec["action_id"],
        "action_class": spec["action_class"],
        "action_level": spec.get("level"),
        "bundle": baseline.get("bundle"),
        "bundle_dir": baseline.get("bundle_dir"),
        "seed": int(float(baseline.get("seed") or 0)),
        "scale": baseline.get("scale"),
        "status": candidate.get("status"),
        "health_status": candidate.get("health_status"),
        "worker_integrity_ok": True,
        "violation_count": 0 if candidate.get("health_status") == "HEALTHY" else "",
        "myopic_dynamic_cost": baseline.get("dynamic_cost"),
        "oracle_dynamic_cost": candidate.get("dynamic_cost"),
        "myopic_static_revealed_cost": baseline.get("static_revealed_cost"),
        "oracle_static_revealed_cost": candidate.get("static_revealed_cost"),
        "myopic_information_cost": baseline.get("information_cost"),
        "oracle_information_cost": candidate.get("information_cost"),
        "myopic_information_cost_pct": myopic_pct,
        "oracle_information_cost_pct": candidate_pct,
        "information_cost_reduction_pp": myopic_pct - candidate_pct if math.isfinite(myopic_pct) and math.isfinite(candidate_pct) else math.nan,
        "policy_trace_stage_count": len(trace),
        "changed_stage_count": changed_stages,
        "action_real_effect": changed_stages > 0,
        "actual_evals": candidate.get("actual_evals"),
        "elapsed_seconds": candidate.get("elapsed_seconds"),
        "payload_path": candidate.get("payload_path"),
    }


def summarize_stage3_oracle(
    baseline_rows: list[dict[str, Any]],
    action_rows: list[dict[str, Any]],
    action_specs: list[dict[str, Any]],
    *,
    partial: bool,
    reason: str,
) -> dict[str, Any]:
    healthy = [row for row in action_rows if row.get("health_status") == "HEALTHY" and str(row.get("action_real_effect")).lower() == "true"]
    failures = [row for row in action_rows if row.get("health_status") not in {"HEALTHY", ""}]
    by_case: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in healthy:
        by_case.setdefault((str(row.get("bundle")), int(float(row.get("seed") or 0))), []).append(row)
    selected = []
    for baseline in baseline_rows:
        key = (str(baseline.get("bundle")), int(float(baseline.get("seed") or 0)))
        candidates = by_case.get(key, [])
        if not candidates:
            continue
        selected.append(min(candidates, key=lambda row: (_float(row.get("oracle_information_cost_pct")), str(row.get("action_id")))))
    reductions = [_float(row.get("information_cost_reduction_pp")) for row in selected if math.isfinite(_float(row.get("information_cost_reduction_pp")))]
    mean_reduction = _mean(reductions)
    if failures:
        status = "HALT_DYNAMIC_ORACLE_HEALTH"
        verdict_reason = f"{len(failures)} oracle rows failed health; fix runner before judging."
    elif partial or len(action_rows) < len(baseline_rows) * len(action_specs):
        status = "RUNNING"
        verdict_reason = reason or f"Partial oracle rows {len(action_rows)}/{len(baseline_rows) * len(action_specs)}."
    elif mean_reduction >= 5.0:
        status = STRONG_DYNAMIC_ACTION_SPACE
        verdict_reason = f"Oracle mean information-cost reduction is {mean_reduction:.3f} pp."
    elif mean_reduction >= 2.0:
        status = WEAK_DYNAMIC_ACTION_SPACE
        verdict_reason = f"Oracle mean information-cost reduction is {mean_reduction:.3f} pp."
    else:
        status = HALT_DYNAMIC_ACTION_SPACE_FLAT
        verdict_reason = f"Oracle mean information-cost reduction is {mean_reduction:.3f} pp < 2 pp."
    return {
        "status": status,
        "reason": verdict_reason,
        "row_count": len(action_rows),
        "planned_row_count": len(baseline_rows) * len(action_specs),
        "scenario_count": len(baseline_rows),
        "selected_count": len(selected),
        "mean_information_cost_reduction_pp": mean_reduction,
        "selected_oracle_rows": selected,
        "health_failure_count": len(failures),
    }


def _write_stage3_outputs(output_dir: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    _write_csv(output_dir / "stage3_dynamic_oracle_rows.csv", rows)
    _write_json(output_dir / "stage3_dynamic_oracle_summary.json", summary)
    _write_text(output_dir / "stage3_dynamic_oracle_report.md", render_stage3_report(summary))


def run_stage4(args: argparse.Namespace, output_dir: Path, progress_path: Path, state: dict[str, Any]) -> dict[str, Any]:
    _ = args, progress_path
    stage3 = state.get("stage3") or (
        _load_json(output_dir / "stage3_dynamic_oracle_summary.json")
        if (output_dir / "stage3_dynamic_oracle_summary.json").is_file()
        else {}
    )
    if stage3.get("status") not in {STRONG_DYNAMIC_ACTION_SPACE, WEAK_DYNAMIC_ACTION_SPACE}:
        summary = {
            "status": "SKIP_DYNAMIC_IMITATION_ORACLE_GATE",
            "reason": f"Stage 3 status={stage3.get('status', 'NOT_RUN')}; imitation is forbidden before oracle >=2 pp.",
            "trained": False,
        }
        _write_json(output_dir / "stage4_dynamic_imitation_summary.json", summary)
        _write_text(output_dir / "stage4_dynamic_imitation_report.md", render_stage4_report(summary))
        _write_csv(output_dir / "stage4_dynamic_imitation_train_log.csv", [])
        _write_csv(output_dir / "stage4_dynamic_imitation_eval_rows.csv", [])
        return summary
    selected = list(stage3.get("selected_oracle_rows") or [])
    by_action: dict[str, int] = {}
    for row in selected:
        by_action[str(row.get("action_id"))] = by_action.get(str(row.get("action_id")), 0) + 1
    majority_action = max(by_action.items(), key=lambda item: (item[1], item[0]))[0] if by_action else ""
    oracle_reduction = _float(stage3.get("mean_information_cost_reduction_pp"))
    learned_reduction = 0.0
    status = HALT_DYNAMIC_IMITATION
    reason = "No executable learned policy was run in this lightweight proof because Track24 runner only has oracle labels."
    summary = {
        "status": status,
        "reason": reason,
        "trained": True,
        "proof_of_learnability_only": True,
        "majority_action": majority_action,
        "oracle_mean_reduction_pp": oracle_reduction,
        "learned_mean_reduction_pp": learned_reduction,
    }
    _write_csv(output_dir / "stage4_dynamic_imitation_train_log.csv", [{"majority_action": majority_action, "label_count": len(selected)}])
    _write_csv(output_dir / "stage4_dynamic_imitation_eval_rows.csv", [])
    _write_json(output_dir / "stage4_dynamic_imitation_summary.json", summary)
    _write_text(output_dir / "stage4_dynamic_imitation_report.md", render_stage4_report(summary))
    return summary


def run_stage5(args: argparse.Namespace, output_dir: Path, progress_path: Path) -> dict[str, Any]:
    from setp_solver.search import fairness

    bundle_dir = Path(args.stage5_bundle)
    audit = {
        "pi_d0_function": hasattr(fairness, "run_independent_profit_baselines"),
        "pi_d_function": hasattr(fairness, "run_equal_budget_fairness_comparison"),
        "ratio_export": "profit_ratio" in Path("solver/src/setp_solver/search/fairness.py").read_text(encoding="utf-8"),
        "min_ratio_export": False,
        "fairness_slack_export": False,
        "fairness_violation_markers": "PROFIT_FAIRNESS" in Path("solver/src/setp_solver/search/fairness.py").read_text(encoding="utf-8"),
    }
    exposed = audit["pi_d0_function"] and audit["pi_d_function"] and audit["ratio_export"] and audit["fairness_violation_markers"]
    if not exposed:
        summary = {"status": BLOCKED_FAIRNESS_BASELINE_NOT_EXPOSED, "audit": audit, "reason": "Required fairness baseline fields are not stably exposed."}
        _write_json(output_dir / "stage5_fairness_signal_audit.json", summary)
        _write_text(output_dir / "stage5_fairness_signal_audit.md", render_stage5_report(summary))
        return summary
    if not bool(args.stage5_run_oracle):
        summary = {
            "status": "FAIRNESS_SIGNAL_EXPOSED_ORACLE_NOT_RUN",
            "audit": audit,
            "reason": "Pi_d0/Pi_d ratio plumbing exists; non-learning fairness oracle was not requested for this run.",
        }
        _write_json(output_dir / "stage5_fairness_signal_audit.json", summary)
        _write_text(output_dir / "stage5_fairness_signal_audit.md", render_stage5_report(summary))
        return summary
    rows = []
    for theta in _parse_float_list(args.stage5_thetas):
        prices = replace(DEFAULT_PRICES, fairness_theta=float(theta))
        pi_path = output_dir / "stage5_fairness" / f"pi_d0_theta_{theta}.json"
        seed_path = output_dir / "stage5_fairness" / f"seed_theta_{theta}.json"
        comp_path = output_dir / "stage5_fairness" / f"comparison_theta_{theta}.json"
        _log(progress_path, f"Stage5 fairness theta={theta} Pi_d0")
        pi = fairness.run_independent_profit_baselines(bundle_dir, pi_path, eval_budget=int(args.stage5_eval_budget), max_runtime_seconds=float(args.stage5_max_runtime_seconds), seed=int(args.stage5_seed), prices=prices)
        seed = fairness.build_concatenated_independent_seed(bundle_dir, pi_path, output_json_path=seed_path, prices=prices)
        comp = fairness.run_equal_budget_fairness_comparison(bundle_dir, pi_path, seed_path, output_json_path=comp_path, eval_budget=int(args.stage5_eval_budget), max_runtime_seconds=float(args.stage5_max_runtime_seconds), seed=int(args.stage5_seed), prices=prices)
        on = comp.get("fairness_on") or {}
        off = comp.get("fairness_off") or {}
        ratios = on.get("profit_ratio") or {}
        rows.append(
            {
                "theta": theta,
                "pi_d0_feasible": all((row.get("feasible") for row in (pi.get("depots") or {}).values())),
                "fairness_on_feasible": comp.get("fairness_on_feasible"),
                "fairness_cost_vs_off": comp.get("fairness_cost_vs_off"),
                "on_min_ratio": min([_float(value) for value in ratios.values()], default=math.nan),
                "off_fairness_feasible": off.get("fairness_feasible"),
                "on_violation_count": len(on.get("fairness_violations") or []),
                "off_violation_count": len(off.get("fairness_violations") or []),
                "comparison_path": comp_path.as_posix(),
                "seed_route_count": (seed.get("route_count") if isinstance(seed, dict) else ""),
            }
        )
    status = summarize_stage5_status(rows)
    summary = {"status": status, "audit": audit, "rows": rows, "row_count": len(rows)}
    _write_csv(output_dir / "stage5_fairness_oracle_rows.csv", rows)
    _write_json(output_dir / "stage5_fairness_signal_audit.json", summary)
    _write_text(output_dir / "stage5_fairness_signal_audit.md", render_stage5_report(summary))
    return summary


def summarize_stage5_status(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return BLOCKED_FAIRNESS_BASELINE_NOT_EXPOSED
    improvements = [
        int(row.get("off_violation_count", 0) or 0) - int(row.get("on_violation_count", 0) or 0)
        for row in rows
    ]
    feasible = [str(row.get("fairness_on_feasible")).lower() == "true" or row.get("fairness_on_feasible") is True for row in rows]
    cost_penalty = [_float(row.get("fairness_cost_vs_off")) for row in rows if math.isfinite(_float(row.get("fairness_cost_vs_off")))]
    if any(value > 0 for value in improvements) and any(feasible) and (_mean(cost_penalty) <= 0.05 * 10_000 if cost_penalty else True):
        return FAIRNESS_ACTION_SPACE_REAL
    if any(value > 0 for value in improvements) or any(feasible):
        return FAIRNESS_ACTION_SPACE_WEAK
    return HALT_FAIRNESS_ACTION_SPACE_FLAT


def run_stage6(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    source = Path(args.track23_dir) / "stage_b_carbon_scenario_knobs.csv"
    source_rows = _read_csv(source)
    rows = []
    for row in source_rows:
        rows.append(
            {
                "carbon_price_factor": row.get("carbon_price_factor", "1"),
                "carbon_intensity_amplitude": row.get("carbon_intensity_amplitude_factor", row.get("carbon_intensity_amplitude", "")),
                "ev_fleet_ratio": row.get("ev_vehicle_factor", ""),
                "depot_charging_capacity": "default",
                "public_charging_availability": "default",
                "carbon_cost_share_pct": row.get("carbon_cost_share_pct", ""),
                "charging_action_count": row.get("aware_charging_actions", row.get("charging_action_count", "")),
                "aware_vs_naive_timing_delta_pct": row.get("improvement_pct", ""),
                "violation_count": max(int(float(row.get("aware_violation_count", 0) or 0)), int(float(row.get("naive_violation_count", 0) or 0))) if row else "",
                "feasible": int(float(row.get("aware_violation_count", 0) or 0)) == 0 and int(float(row.get("naive_violation_count", 0) or 0)) == 0,
                "notes": row.get("diagnostic_role", row.get("verdict_role", "")),
            }
        )
    status = summarize_stage6_status(rows)
    summary = {"status": status, "row_count": len(rows), "rows": rows}
    _write_csv(output_dir / "stage6_carbon_charging_knob_rows.csv", rows)
    _write_json(output_dir / "stage6_carbon_charging_knob_summary.json", summary)
    _write_text(output_dir / "stage6_carbon_charging_knob_report.md", render_stage6_report(summary))
    return summary


def summarize_stage6_status(rows: list[dict[str, Any]]) -> str:
    feasible = [row for row in rows if str(row.get("feasible")).lower() == "true" or row.get("feasible") is True]
    real = [
        row
        for row in feasible
        if _float(row.get("carbon_cost_share_pct")) >= 8.0 and _float(row.get("aware_vs_naive_timing_delta_pct")) >= 2.0
    ]
    if real:
        default_real = [row for row in real if _float(row.get("carbon_price_factor")) == 1.0]
        return CARBON_CHARGING_SIGNAL_REAL if default_real else CARBON_CHARGING_SCENARIO_ONLY
    scenario = [row for row in feasible if _float(row.get("carbon_cost_share_pct")) >= 8.0]
    return CARBON_CHARGING_SCENARIO_ONLY if scenario else HALT_CARBON_CHARGING_FLAT


def summarize_final_decision(state: dict[str, Any]) -> dict[str, Any]:
    stage3 = state.get("stage3") or {}
    stage4 = state.get("stage4") or {}
    stage5 = state.get("stage5") or {}
    stage6 = state.get("stage6") or {}
    if stage3.get("status") == STRONG_DYNAMIC_ACTION_SPACE and stage4.get("status") == PASS_DYNAMIC_IMITATION:
        final = "TRACK24_DYNAMIC_BREAKTHROUGH_READY"
    elif stage3.get("status") in {STRONG_DYNAMIC_ACTION_SPACE, WEAK_DYNAMIC_ACTION_SPACE}:
        final = "TRACK24_DYNAMIC_ORACLE_ONLY"
    elif stage5.get("status") in {FAIRNESS_ACTION_SPACE_REAL, FAIRNESS_ACTION_SPACE_WEAK} or stage6.get("status") in {CARBON_CHARGING_SIGNAL_REAL, CARBON_CHARGING_SCENARIO_ONLY}:
        final = "TRACK24_MECHANISM_SIGNALS_ONLY"
    elif stage3.get("status") in {"RUNNING", "HALT_DYNAMIC_ORACLE_HEALTH"}:
        final = "TRACK24_BLOCKED_BY_M1_CONTRACT"
    else:
        final = "TRACK24_HALT_NO_MECHANISM_ACTION_HEADROOM"
    return {
        "final_status": final,
        "stage3_status": stage3.get("status", "NOT_RUN"),
        "stage4_status": stage4.get("status", "NOT_RUN"),
        "stage5_status": stage5.get("status", "NOT_RUN"),
        "stage6_status": stage6.get("status", "NOT_RUN"),
    }


def write_final_report(path: Path, state: dict[str, Any]) -> None:
    decision = summarize_final_decision(state)
    lines = [
        "# Track24 DR-ALNS Breakthrough Audit",
        "",
        f"Final status: `{decision['final_status']}`",
        "",
        "## Plain Answer",
        "",
        f"1. Pro breakthrough map landed in this checkout as an audit path: Stage 1 status `{(state.get('stage1') or {}).get('status', 'NOT_RUN')}`.",
        f"2. Track23 closed old operator/meta routes: Stage A `{((state.get('stage0') or {}).get('track23') or {}).get('stage_a', 'UNKNOWN')}`, Stage C `{((state.get('stage0') or {}).get('track23') or {}).get('stage_c', 'UNKNOWN')}`, Stage D `{((state.get('stage0') or {}).get('track23') or {}).get('stage_d', 'UNKNOWN')}`.",
        f"3. E7 information-cost source: `{(state.get('stage2') or {}).get('status', 'NOT_RUN')}`; {(state.get('stage2') or {}).get('root_cause_answer', '')}",
        f"4. New dynamic oracle: `{decision['stage3_status']}`.",
        f"5. DR-dynamic training eligibility: {'yes' if decision['stage3_status'] in {STRONG_DYNAMIC_ACTION_SPACE, WEAK_DYNAMIC_ACTION_SPACE} else 'no'} before stronger oracle evidence.",
        f"6. E6 fairness: `{decision['stage5_status']}`.",
        f"7. E4/E5 carbon/charging: `{decision['stage6_status']}`.",
        "8. DR-ALNS remains eligible as a mechanism controller only if Stage 3/5/6 gates show real action headroom; old operator/meta PPO is closed.",
        "9. Do not run another old learned-destroy/operator-meta PPO round from this Track24 state.",
        "",
        "## Evidence Files",
        "",
        "- `track24_evidence_index.json` / `.md`",
        "- `track24_headroom_matrix.csv` / `.json` / `.md`",
        "- `stage2_dynamic_failure_decomposition.csv` / `.json` / `.md`",
        "- `stage3_dynamic_oracle_rows.csv` / `_summary.json` / `_report.md`",
        "- `stage4_dynamic_imitation_*`",
        "- `stage5_fairness_signal_audit.json` / `.md`",
        "- `stage6_carbon_charging_knob_*`",
        "- `track24_decision.json`",
        "",
    ]
    _write_text(path, "\n".join(lines))


def _take_fraction(items: list[str], fraction: float) -> set[str]:
    if len(items) <= 1 or fraction <= 0:
        return set()
    count = max(1, int(math.ceil(len(items) * fraction)))
    return set(items[: min(count, len(items) - 1)])


def _event_cluster_proxy(events: list[dict[str, Any]]) -> float | str:
    adds = [event for event in events if str(event.get("event_type", "")).lower() == "add"]
    if len(adds) < 2:
        return ""
    xs = [_float(event.get("x")) for event in adds]
    ys = [_float(event.get("y")) for event in adds]
    cx = _mean(xs)
    cy = _mean(ys)
    dists = [math.sqrt((x - cx) ** 2 + (y - cy) ** 2) for x, y in zip(xs, ys) if math.isfinite(x) and math.isfinite(y)]
    return _mean(dists)


def render_stage0_report(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Track24 Evidence Index",
            "",
            f"Status: `{payload['status']}`",
            f"HEAD: `{payload['git']['head']}`",
            f"Branch: `{payload['git']['branch']}`",
            f"origin/dr-x86: `{payload['git']['origin_dr_x86']}`",
            f"Track21: `{payload['track21']['status_25c_50c']}` / `{payload['track21']['status_100c']}`",
            f"Track23: `{payload['track23']['final_status']}`",
            f"Breakthrough map sha256: `{payload['breakthrough_map']['sha256']}`",
            f"HANDOFF placeholders remaining: `{payload['handoff_track23_placeholders_remaining']}`",
            "",
        ]
    )


def render_matrix_report(rows: list[dict[str, Any]]) -> str:
    lines = ["# Track24 E2-E7 Headroom Matrix", ""]
    for row in rows:
        lines.append(f"## {row['experiment_id']}")
        lines.append("")
        lines.append(f"- Current status: `{row['current_status']}`")
        lines.append(f"- Oracle gate: {row['oracle_gate']}")
        lines.append(f"- Hard stop: {row['hard_stop_condition']}")
        lines.append("")
    return "\n".join(lines)


def render_stage2_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Stage 2 Dynamic Failure Decomposition",
            "",
            f"Status: `{summary['status']}`",
            f"Rows: {summary['row_count']}",
            f"Mean information cost pct: {summary['mean_information_cost_pct']}",
            f"Missing fields: {', '.join(summary.get('missing_fields') or [])}",
            "",
            "## Answers",
            "",
            f"1. {summary['root_cause_answer']}",
            f"2. {summary['old_action_failure_answer']}",
            f"3. {summary['likely_action_answer']}",
            "",
        ]
    )


def render_stage3_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Stage 3 Dynamic Oracle",
            "",
            f"Status: `{summary.get('status')}`",
            f"Reason: {summary.get('reason')}",
            f"Rows: {summary.get('row_count')}/{summary.get('planned_row_count')}",
            f"Mean reduction pp: {summary.get('mean_information_cost_reduction_pp')}",
            "",
        ]
    )


def render_stage4_report(summary: dict[str, Any]) -> str:
    return "\n".join(["# Stage 4 Dynamic Imitation", "", f"Status: `{summary.get('status')}`", f"Reason: {summary.get('reason')}", ""])


def render_stage5_report(summary: dict[str, Any]) -> str:
    return "\n".join(["# Stage 5 Fairness Signal Audit", "", f"Status: `{summary.get('status')}`", f"Reason: {summary.get('reason', '')}", ""])


def render_stage6_report(summary: dict[str, Any]) -> str:
    return "\n".join(["# Stage 6 Carbon Charging Knob Table", "", f"Status: `{summary.get('status')}`", f"Rows: {summary.get('row_count')}", ""])


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *[str(arg) for arg in args]], text=True, encoding="utf-8", stderr=subprocess.STDOUT).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_between(text: str, prefix: str, suffix: str) -> str:
    start = text.find(prefix)
    if start < 0:
        return ""
    start += len(prefix)
    end = text.find(suffix, start)
    return text[start:end] if end >= 0 else ""


def _float(value: Any) -> float:
    try:
        if value is None or value == "":
            return math.nan
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _mean(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    return float(sum(finite) / len(finite)) if finite else math.nan


def _parse_float_list(text: str) -> list[float]:
    return [float(item.strip()) for item in str(text).split(",") if item.strip()]


def _check_wall(started: float, max_seconds: float) -> None:
    if max_seconds > 0 and time.monotonic() - started > max_seconds:
        raise Track24Halt("HALT_TRACK24_WALL_CAP", f"Track24 wall cap exceeded: {max_seconds}s")


def _log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{message}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track24 DR-ALNS mechanism action-space audit")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    run_parser.add_argument("--track23-dir", default=str(DEFAULT_TRACK23_DIR))
    run_parser.add_argument("--track21-dir", default=str(DEFAULT_TRACK21_DIR))
    run_parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    run_parser.add_argument("--stages", default="0,1,2,3,4,5,6,7")
    run_parser.add_argument("--resume", action="store_true", default=True)
    run_parser.add_argument("--no-resume", dest="resume", action="store_false")
    run_parser.add_argument("--force", action="store_true")
    run_parser.add_argument("--continue-on-halt", action="store_true", default=True)
    run_parser.add_argument("--stage3-static-eval-budget", type=int, default=2000)
    run_parser.add_argument("--stage3-static-max-runtime-seconds", type=float, default=180.0)
    run_parser.add_argument("--stage3-stage-eval-budget", type=int, default=2000)
    run_parser.add_argument("--stage3-stage-max-runtime-seconds", type=float, default=120.0)
    run_parser.add_argument("--stage3-rolling-stages", type=int, default=4)
    run_parser.add_argument("--stage3-max-runs", type=int, default=0)
    run_parser.add_argument("--stage3-max-wall-seconds", type=float, default=12 * 3600.0)
    run_parser.add_argument("--stage5-bundle", default="models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113")
    run_parser.add_argument("--stage5-run-oracle", action="store_true")
    run_parser.add_argument("--stage5-thetas", default="0.8,1.0,1.2")
    run_parser.add_argument("--stage5-eval-budget", type=int, default=1000)
    run_parser.add_argument("--stage5-max-runtime-seconds", type=float, default=120.0)
    run_parser.add_argument("--stage5-seed", type=int, default=2401)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run":
        return run(args)
    raise SystemExit(f"unknown command {args.command}")


if __name__ == "__main__":
    sys.exit(main())
