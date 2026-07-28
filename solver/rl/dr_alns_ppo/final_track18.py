from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

from setp_solver.search.dynamic import RollingParameters, run_rolling_reoptimization

from .final_track16 import Track16Halt, _check_wall, _parse_csv, _write_text, run_preflight
from .pilot20_learned_destroy_phaseA import DEFAULT_WORKER, _parse_int_list
from .pilot22_grounded_fixes import _load_state, _log, _save_state, _write_json


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track18")
DEFAULT_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK25_02__curric_d2_s3_seed2_24h",
    "models/data_bundle/generated_instances/E-UK50_01__curric_d2_s3_seed1_24h",
)
TERMINAL_STATUSES = {
    "HEADROOM_REAL",
    "THIN_HEADROOM",
    "HALT_NO_ANTICIPATION_HEADROOM",
    "HALT_DYNAMIC_POLICY_ENTRYPOINT",
    "HALT_DYNAMIC_HEALTH",
    "HALT_PREFLIGHT",
    "HALT_PROTECTED_DIRTY",
}


class Track18Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def run(args: argparse.Namespace) -> int:
    _normalize_preflight_args(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "track18_progress.log"
    state_path = output_dir / "track18_state.json"
    state = _load_state(state_path) if args.resume else {}
    started = time.monotonic()
    final_status = str(state.get("final_status") or "RUNNING")
    final_reason = str(state.get("final_reason") or "")
    try:
        _enforce_resume_guard(state, resume=bool(args.resume), force=bool(args.force))
        _log(progress_path, "Track18 start")
        preflight = run_preflight(args, output_dir)
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = preflight
        _save_state(state_path, state)

        if not state.get("headroom_done"):
            headroom = run_headroom(args, output_dir, progress_path, started)
            state["headroom"] = headroom
            state["headroom_done"] = headroom["verdict"] in TERMINAL_STATUSES
            _save_state(state_path, state)
            _write_json(output_dir / "track18_dynamic_dr_report.json", headroom)
            _write_text(output_dir / "track18_dynamic_dr_report.md", _headroom_report(headroom))
            if headroom["verdict"] == "HALT_DYNAMIC_HEALTH":
                raise Track18Halt(headroom["verdict"], headroom["reason"])

        headroom = state.get("headroom") or {}
        if headroom.get("verdict") == "HEADROOM_REAL" and not state.get("policy_audit_done"):
            policy_audit = run_policy_audit()
            state["policy_audit"] = policy_audit
            state["policy_audit_done"] = True
            _save_state(state_path, state)
            _write_json(output_dir / "track18_policy_audit.json", policy_audit)
            _write_text(output_dir / "track18_policy_audit.md", _policy_audit_report(policy_audit))
            if policy_audit["verdict"] == "HALT_DYNAMIC_POLICY_ENTRYPOINT":
                raise Track18Halt(policy_audit["verdict"], policy_audit["reason"])

        final_status, final_reason = _summarize_final(state)
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        return 0 if final_status in {"HEADROOM_REAL", "THIN_HEADROOM", "HALT_NO_ANTICIPATION_HEADROOM"} else 2
    except Track16Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 2
    except Track18Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 2
    finally:
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _write_json(state_path, state)
        _write_json(output_dir / "final_report.json", state)
        _write_text(output_dir / "track18_dynamic_dr_report.md", _headroom_report(state.get("headroom") or {}))
        _write_text(output_dir / "final_report.md", _final_report(state))


def run_headroom(args: argparse.Namespace, output_dir: Path, progress_path: Path, started: float) -> dict[str, Any]:
    rows_path = output_dir / "track18_headroom.csv"
    all_rows_path = output_dir / "track18_rows.csv"
    payload_dir = output_dir / "track18_payloads"
    rows = _read_rows(rows_path)
    done = {(row["bundle"], int(row["seed"])) for row in rows if row.get("status") != "RUNNING"}
    bundles = _parse_csv(args.bundles)
    seeds = _parse_int_list(args.seeds)
    planned = [(bundle, seed) for bundle in bundles for seed in seeds]
    max_runs = int(args.max_runs)
    launched = 0
    for bundle_dir in bundles:
        bundle_name = Path(bundle_dir).name
        for seed in seeds:
            if (bundle_name, int(seed)) in done:
                continue
            if max_runs > 0 and launched >= max_runs:
                return _summarize_headroom(rows, planned=planned, partial=True, reason="Stopped after max_runs.")
            _check_wall(started, float(args.max_wall_seconds))
            output_json = payload_dir / f"{_safe_name(bundle_name)}_seed{seed}.json"
            _log(progress_path, f"Track18 headroom bundle={bundle_name} seed={seed}")
            payload = run_rolling_reoptimization(
                bundle_dir,
                output_json_path=output_json,
                seed=int(seed),
                eval_budget=int(args.eval_budget),
                max_runtime_seconds=float(args.max_runtime_seconds),
                stage_eval_budget=int(args.stage_eval_budget),
                stage_max_runtime_seconds=float(args.stage_max_runtime_seconds),
                params=RollingParameters(stages=int(args.stages)),
            )
            row = _payload_row(payload, bundle_dir=bundle_dir, seed=int(seed), output_json=output_json)
            rows.append(row)
            _write_rows(rows_path, rows)
            _write_rows(all_rows_path, rows)
            launched += 1
            if row["health_status"] != "HEALTHY":
                return _summarize_headroom(rows, planned=planned, partial=True, reason=f"{bundle_name}/seed{seed} failed dynamic health: {row['health_status']}")
    return _summarize_headroom(rows, planned=planned, partial=False, reason="")


def _payload_row(payload: dict[str, Any], *, bundle_dir: str | Path, seed: int, output_json: Path) -> dict[str, Any]:
    dynamic = payload.get("dynamic_final_control") or {}
    static = payload.get("static_revealed_control") or {}
    dynamic_cost = _to_float(dynamic.get("total_cost"))
    static_cost = _to_float(static.get("total_cost"))
    information_cost = _to_float(payload.get("information_cost"))
    if math.isnan(information_cost) and not math.isnan(dynamic_cost) and not math.isnan(static_cost):
        information_cost = dynamic_cost - static_cost
    information_cost_pct = (information_cost / static_cost * 100.0) if static_cost and not math.isnan(static_cost) else math.nan
    stage_rows = list(payload.get("stage_rows") or [])
    stage_all_feasible = all(bool(row.get("feasible")) for row in stage_rows)
    dynamic_feasible = bool(dynamic.get("feasible", False))
    static_feasible = bool(static.get("feasible", False))
    all_assertions_pass = bool(payload.get("all_assertions_pass", False))
    gate = str(payload.get("gate") or payload.get("status") or "")
    health_status = _dynamic_health_status(
        gate=gate,
        dynamic_feasible=dynamic_feasible,
        static_feasible=static_feasible,
        stage_all_feasible=stage_all_feasible,
        all_assertions_pass=all_assertions_pass,
        information_cost=information_cost,
        actual_evals=int(payload.get("actual_evals", payload.get("evaluations", 0)) or 0),
    )
    return {
        "stage": "headroom",
        "algorithm": "rolling_alns_reoptimization_vs_full_information_static",
        "bundle": Path(bundle_dir).name,
        "bundle_dir": str(bundle_dir),
        "seed": int(seed),
        "scale": _scale_from_bundle(Path(bundle_dir).name),
        "status": "OK" if not gate else gate,
        "health_status": health_status,
        "dynamic_cost": dynamic_cost,
        "static_revealed_cost": static_cost,
        "information_cost": information_cost,
        "information_cost_pct": information_cost_pct,
        "dynamic_feasible": dynamic_feasible,
        "static_feasible": static_feasible,
        "stage_all_feasible": stage_all_feasible,
        "all_assertions_pass": all_assertions_pass,
        "trigger_count": int(payload.get("trigger_count", 0) or 0),
        "event_count": int(payload.get("event_count", 0) or 0),
        "stage_row_count": len(stage_rows),
        "actual_evals": int(payload.get("actual_evals", payload.get("evaluations", 0)) or 0),
        "eval_budget": int(payload.get("eval_budget", 0) or 0),
        "stage_eval_budget": int(payload.get("stage_eval_budget", 0) or 0),
        "elapsed_seconds": _to_float(payload.get("elapsed_seconds")),
        "payload_path": str(output_json),
        "failure_reason": str(payload.get("failure_reason") or ""),
    }


def _dynamic_health_status(
    *,
    gate: str,
    dynamic_feasible: bool,
    static_feasible: bool,
    stage_all_feasible: bool,
    all_assertions_pass: bool,
    information_cost: float,
    actual_evals: int,
) -> str:
    if gate.startswith("HALT"):
        return gate
    if actual_evals <= 0:
        return "UNHEALTHY_NO_EVALUATIONS"
    if not dynamic_feasible:
        return "UNHEALTHY_DYNAMIC_FINAL"
    if not static_feasible:
        return "UNHEALTHY_STATIC_FINAL"
    if not stage_all_feasible:
        return "UNHEALTHY_STAGE_FEASIBILITY"
    if not all_assertions_pass:
        return "UNHEALTHY_ROLLING_ASSERTIONS"
    if math.isnan(information_cost):
        return "UNHEALTHY_NO_INFORMATION_COST"
    if information_cost < -1e-6:
        return "UNHEALTHY_NEGATIVE_INFORMATION_COST"
    return "HEALTHY"


def _summarize_headroom(rows: list[dict[str, Any]], *, planned: list[tuple[str, int]], partial: bool, reason: str) -> dict[str, Any]:
    row_count = len(rows)
    planned_count = len(planned)
    health_failures = [row for row in rows if row.get("health_status") != "HEALTHY"]
    values = [_to_float(row.get("information_cost_pct")) for row in rows if row.get("health_status") == "HEALTHY"]
    values = [value for value in values if not math.isnan(value)]
    mean_pct = sum(values) / len(values) if values else math.nan
    median_pct = _median(values)
    by_scale: dict[str, dict[str, Any]] = {}
    for scale in sorted({str(row.get("scale", "")) for row in rows}):
        scale_values = [
            _to_float(row.get("information_cost_pct"))
            for row in rows
            if str(row.get("scale", "")) == scale and row.get("health_status") == "HEALTHY"
        ]
        scale_values = [value for value in scale_values if not math.isnan(value)]
        by_scale[scale] = {
            "row_count": len(scale_values),
            "mean_information_cost_pct": sum(scale_values) / len(scale_values) if scale_values else math.nan,
            "median_information_cost_pct": _median(scale_values),
        }
    if health_failures:
        verdict = "HALT_DYNAMIC_HEALTH"
        verdict_reason = reason or f"{len(health_failures)} dynamic headroom rows failed health."
    elif partial or row_count < planned_count:
        verdict = "RUNNING"
        verdict_reason = reason or f"Partial headroom rows: {row_count}/{planned_count}."
    elif mean_pct >= 5.0:
        verdict = "HEADROOM_REAL"
        verdict_reason = f"Mean information_cost_pct={mean_pct:.3f}% >= 5%; anticipation has measurable headroom."
    elif mean_pct < 2.0:
        verdict = "HALT_NO_ANTICIPATION_HEADROOM"
        verdict_reason = f"Mean information_cost_pct={mean_pct:.3f}% < 2%; dynamic DR has little theoretical room."
    else:
        verdict = "THIN_HEADROOM"
        verdict_reason = f"Mean information_cost_pct={mean_pct:.3f}% is between 2% and 5%; headroom is thin."
    return {
        "verdict": verdict,
        "reason": verdict_reason,
        "rows": rows,
        "row_count": row_count,
        "planned_count": planned_count,
        "mean_information_cost_pct": mean_pct,
        "median_information_cost_pct": median_pct,
        "scale_summary": by_scale,
        "health_failure_count": len(health_failures),
        "health_failures": health_failures,
        "note": "Stage0 measures the myopic rolling ALNS gap to full-information static control only; no DR policy is trained or credited here.",
    }


def _summarize_final(state: dict[str, Any]) -> tuple[str, str]:
    policy_audit = state.get("policy_audit") or {}
    if policy_audit.get("verdict") == "HALT_DYNAMIC_POLICY_ENTRYPOINT":
        return str(policy_audit["verdict"]), str(policy_audit.get("reason", ""))
    headroom = state.get("headroom") or {}
    verdict = str(headroom.get("verdict") or "RUNNING")
    reason = str(headroom.get("reason") or "Track18 is not complete.")
    return verdict, reason


def run_policy_audit() -> dict[str, Any]:
    dynamic_py = Path("solver/src/setp_solver/search/dynamic.py").read_text(encoding="utf-8")
    block_env_py = Path("solver/rl/dr_alns_ppo/block_env.py").read_text(encoding="utf-8")
    track15_py = Path("solver/rl/dr_alns_ppo/final_track15.py").read_text(encoding="utf-8")
    train_py = Path("solver/rl/dr_alns_ppo/train_async_block_ppo.py").read_text(encoding="utf-8")
    evidence = [
        {
            "check": "run_rolling_reoptimization_policy_callback",
            "status": "missing",
            "evidence": "run_rolling_reoptimization calls _run_stage_plan directly and exposes no dynamic policy callback.",
            "source": "solver/src/setp_solver/search/dynamic.py",
            "matched": "_run_stage_plan(" in dynamic_py and "policy_callback" not in dynamic_py,
        },
        {
            "check": "stage_plan_control_surface",
            "status": "myopic_alns_only",
            "evidence": "_run_stage_plan signature accepts initial_plan but no reserve/commit/preposition action; it calls run_alns_wouda.",
            "source": "solver/src/setp_solver/search/dynamic.py",
            "matched": "initial_plan: Solution | None" in dynamic_py and "run_alns_wouda(" in dynamic_py,
        },
        {
            "check": "dynamic_reward_signal",
            "status": "not_a_real_signal",
            "evidence": "block_env dynamic phase returns 0.0 when dynamic/rolling keys exist and otherwise falls back to static best_gain.",
            "source": "solver/rl/dr_alns_ppo/block_env.py",
            "matched": "return 0.0" in block_env_py and "no_dynamic_signal" in block_env_py,
        },
        {
            "check": "prior_no_policy_statement",
            "status": "confirmed",
            "evidence": "Track15 explicitly refused to label rolling ALNS control as DR because no trained dynamic DR-online policy entrypoint exists.",
            "source": "solver/rl/dr_alns_ppo/final_track15.py",
            "matched": "No trained dynamic DR-online policy entrypoint exists" in track15_py,
        },
        {
            "check": "trainer_scope",
            "status": "static_block_trainer",
            "evidence": "train_async_block_ppo supports a dynamic curriculum label, but the environment signal is still the static block response.",
            "source": "solver/rl/dr_alns_ppo/train_async_block_ppo.py",
            "matched": "--curriculum-schedule" in train_py and "route,energy,carbon,dynamic" in train_py,
        },
    ]
    all_matched = all(bool(row["matched"]) for row in evidence)
    verdict = "HALT_DYNAMIC_POLICY_ENTRYPOINT"
    reason = (
        "Stage0 found real anticipation headroom, but this checkout has no callable, non-cheating dynamic DR-online policy "
        "entrypoint to train and compare against myopic rolling ALNS."
    )
    return {
        "verdict": verdict,
        "reason": reason,
        "all_evidence_matched": all_matched,
        "evidence": evidence,
        "allowed_next_step": "Add a real dynamic policy control surface before training: reserve capacity/time slack, commit-vs-defer, or vehicle preposition actions injected into stage planning without changing evaluate/check semantics.",
    }


def _headroom_report(headroom: dict[str, Any]) -> str:
    if not headroom:
        return "# Track18 Dynamic DR Report\n\nVerdict: NOT_RUN\n"
    lines = [
        "# Track18 Dynamic DR Report",
        "",
        f"Verdict: {headroom.get('verdict')}",
        f"Reason: {headroom.get('reason')}",
        "",
        "## Headroom",
        "",
        f"Rows: {headroom.get('row_count')}/{headroom.get('planned_count')}",
        f"Mean information_cost_pct: {headroom.get('mean_information_cost_pct')}",
        f"Median information_cost_pct: {headroom.get('median_information_cost_pct')}",
        f"Scale summary: {json.dumps(headroom.get('scale_summary', {}), sort_keys=True)}",
        f"Health failure count: {headroom.get('health_failure_count')}",
        "",
        "## Decision",
        "",
        str(headroom.get("note", "")),
    ]
    return "\n".join(lines) + "\n"


def _policy_audit_report(policy_audit: dict[str, Any]) -> str:
    if not policy_audit:
        return "# Track18 Policy Audit\n\nVerdict: NOT_RUN\n"
    lines = [
        "# Track18 Policy Audit",
        "",
        f"Verdict: {policy_audit.get('verdict')}",
        f"Reason: {policy_audit.get('reason')}",
        f"All evidence matched: {policy_audit.get('all_evidence_matched')}",
        "",
        "## Evidence",
        "",
    ]
    for row in policy_audit.get("evidence", []):
        lines.append(
            f"- {row.get('check')}: {row.get('status')} ({row.get('source')}); matched={row.get('matched')}. {row.get('evidence')}"
        )
    lines.extend(["", "## Next Step", "", str(policy_audit.get("allowed_next_step", ""))])
    return "\n".join(lines) + "\n"


def _final_report(state: dict[str, Any]) -> str:
    headroom = state.get("headroom") or {}
    policy_audit = state.get("policy_audit") or {}
    return (
        "# Final Track18 Report\n\n"
        f"Final status: {state.get('final_status', 'RUNNING')}\n"
        f"Final reason: {state.get('final_reason', '')}\n\n"
        "## Human Decision\n\n"
        f"Information headroom verdict: {headroom.get('verdict', 'NOT_RUN')}.\n\n"
        f"Mean information_cost_pct: {headroom.get('mean_information_cost_pct', math.nan)}.\n\n"
        f"Median information_cost_pct: {headroom.get('median_information_cost_pct', math.nan)}.\n\n"
        f"Policy audit verdict: {policy_audit.get('verdict', 'NOT_RUN')}.\n\n"
        "No dynamic DR policy was trained or evaluated. Stage0 shows anticipation has room, but Stage1 must first add a real online policy control surface; the current static block PPO interface is not sufficient evidence.\n"
    )


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
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


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return math.nan
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _median(values: list[float]) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def _safe_name(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)


def _scale_from_bundle(name: str) -> str:
    if "E-UK25" in name:
        return "25"
    if "E-UK50" in name:
        return "50"
    if "E-UK100" in name:
        return "100"
    return "unknown"


def _enforce_resume_guard(state: dict[str, Any], *, resume: bool, force: bool) -> None:
    final_status = str(state.get("final_status") or "")
    if resume or force or not final_status or final_status in {"RUNNING", "HALT_WALL_CLOCK"}:
        return
    if final_status in TERMINAL_STATUSES:
        raise Track18Halt(final_status, f"Existing terminal Track18 state found ({final_status}); pass --force to rerun.")


def _normalize_preflight_args(args: argparse.Namespace) -> None:
    args.health_bundles = getattr(args, "health_bundles", "") or ""
    args.ablation_bundles = getattr(args, "ablation_bundles", "") or ""
    args.formal_bundles = getattr(args, "formal_bundles", "") or str(args.bundles)
    args.min_free_disk_gb = getattr(args, "min_free_disk_gb", 5.0)
    args.require_self_py313 = getattr(args, "require_self_py313", False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track18 dynamic headroom runner.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
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
    parser.add_argument("--max-wall-seconds", type=float, default=8 * 3600.0)
    parser.add_argument("--min-free-disk-gb", type=float, default=5.0)
    parser.add_argument("--require-self-py313", action="store_true")
    parser.add_argument("--max-runs", type=int, default=0, help="Optional smoke cap; 0 means all planned rows.")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
