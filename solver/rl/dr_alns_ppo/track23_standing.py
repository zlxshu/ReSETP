from __future__ import annotations

import argparse
import math
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from setp_solver.prices import DEFAULT_PRICES

from . import final_track18, final_track20, track22_endgame as track22
from .pilot20_learned_destroy_phaseA import DEFAULT_WORKER, _parse_int_list


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track23")
DEFAULT_TRACK22R_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track22r")
PILOT08_BLOCK_SIZE = 32
PILOT08_UPDATE_0240 = Path(
    "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot08/train_final/checkpoints/async_block_ppo_update_0240.pt"
)
EUK100_01 = "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113"
EUK100_02 = "models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113"
EUK100_03 = "models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113"

DESTROY_LEVERAGE_AT_BUDGET = "DESTROY_LEVERAGE_AT_BUDGET"
LEVERAGE_MARGINAL = "LEVERAGE_MARGINAL"
NO_DESTROY_LEVERAGE_ANY_BUDGET = "NO_DESTROY_LEVERAGE_ANY_BUDGET"
SKIP_A2_NO_LEVERAGE = "SKIP_A2_NO_LEVERAGE"
PASS_LEARNED_DESTROY_CLEAN = "PASS_LEARNED_DESTROY_CLEAN"
WEAK = "WEAK"
HALT_NO_GAIN_CLEAN = "HALT_NO_GAIN_CLEAN"
NO_TUNING_PARITY_CLEAN = "NO_TUNING_PARITY_CLEAN"
PARITY_LOST_CLEAN = "PARITY_LOST_CLEAN"
NO_ANTICIPATION_HEADROOM_CLEAN = "NO_ANTICIPATION_HEADROOM_CLEAN"
HEURISTIC_MOVES_HEADROOM = "HEURISTIC_MOVES_HEADROOM"
HEURISTIC_FLAT = "HEURISTIC_FLAT"
DYNAMIC_INTERFACE_PARTIAL = "DYNAMIC_INTERFACE_PARTIAL"


class Track23Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = str(status)
        self.message = str(message)


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "track23_progress.log"
    state_path = output_dir / "track23_state.json"
    state = track22._load_json(state_path) if args.resume and state_path.exists() else {}
    selected = {item.strip().upper() for item in str(args.stages).split(",") if item.strip()}
    if not selected:
        selected = {"A", "A2", "B", "C", "D", "E"}
    try:
        _log(progress_path, "Track23 run start")
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = track22.run_preflight(args, output_dir)
        track22._write_json(output_dir / "track23_preflight.json", state["preflight"])
        _save_state(state_path, state)

        if "A" in selected and not state.get("stage_a"):
            manifest = track22.ensure_track22_bundles(args, output_dir)
            state["bundle_manifest"] = manifest
            track22._write_json(output_dir / "track23_bundle_manifest.json", manifest)
            rows = run_stage_a_destroy_ladder(args, output_dir, progress_path, manifest)
            state["stage_a"] = summarize_stage_a_destroy(rows)
            track22._write_json(output_dir / "stage_a_destroy_ladder_summary.json", state["stage_a"])
            write_stage_a_report(output_dir / "stage_a_destroy_ladder_report.md", state["stage_a"])
            _save_state(state_path, state)
            _log(progress_path, f"Stage A status={state['stage_a']['status']}")

        if "A2" in selected and not state.get("stage_a2"):
            stage_a = state.get("stage_a") or {}
            if not should_run_stage_a2(stage_a):
                state["stage_a2"] = {
                    "status": SKIP_A2_NO_LEVERAGE,
                    "trained": False,
                    "reason": f"Stage A status={stage_a.get('status', 'NOT_RUN')}; learned-destroy training skipped.",
                }
            else:
                state["stage_a2"] = run_stage_a2_learned_destroy(args, output_dir, progress_path, state)
            track22._write_json(output_dir / "stage_a2_learned_destroy_summary.json", state["stage_a2"])
            _save_state(state_path, state)
            _log(progress_path, f"Stage A2 status={state['stage_a2']['status']}")

        if "B" in selected and not state.get("stage_b"):
            manifest = state.get("bundle_manifest") or track22.ensure_track22_bundles(args, output_dir)
            state["bundle_manifest"] = manifest
            state["stage_b"] = run_stage_b_carbon(args, output_dir, progress_path, state)
            track22._write_json(output_dir / "stage_b_carbon_summary.json", state["stage_b"])
            _save_state(state_path, state)
            _log(progress_path, f"Stage B status={state['stage_b']['status']}")

        if "C" in selected and not state.get("stage_c"):
            rows = run_stage_c_parity(args, output_dir, progress_path)
            state["stage_c"] = summarize_stage_c_parity(rows)
            track22._write_json(output_dir / "stage_c_no_tuning_parity_summary.json", state["stage_c"])
            write_stage_c_report(output_dir / "stage_c_no_tuning_parity_report.md", state["stage_c"])
            _save_state(state_path, state)
            _log(progress_path, f"Stage C status={state['stage_c']['status']}")

        if "D" in selected and not state.get("stage_d"):
            state["stage_d"] = run_stage_d_dynamic(args, output_dir, progress_path, started)
            track22._write_json(output_dir / "stage_d_dynamic_summary.json", state["stage_d"])
            _save_state(state_path, state)
            _log(progress_path, f"Stage D status={state['stage_d']['status']}")

        state["pillar_summary"] = summarize_pillars(state)
        state["final_status"] = "TRACK23_COMPLETE"
        state["final_reason"] = _pillar_sentence(state["pillar_summary"])
        state["wall_time_seconds"] = float(time.monotonic() - started)
        track22._write_json(output_dir / "track23_final_report.json", state)
        write_final_report(output_dir / "final_report.md", state)
        _save_state(state_path, state)
        return 0
    except (track22.Track22Halt, Track23Halt) as exc:
        status = getattr(exc, "status", "HALT_TRACK23")
        message = getattr(exc, "message", str(exc))
        state["final_status"] = status
        state["final_reason"] = message
        state["wall_time_seconds"] = float(time.monotonic() - started)
        track22._write_json(output_dir / "track23_final_report.json", state)
        write_final_report(output_dir / "final_report.md", state)
        _save_state(state_path, state)
        _log(progress_path, f"HALT {status}: {message}")
        return 2


def run_stage_a_destroy_ladder(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    rows_path = output_dir / "stage_a_destroy_ladder_rows.csv"
    rows = track22._read_csv(rows_path) if args.resume else []
    if not rows:
        rows = import_track22r_stage_a_rows(Path(args.track22r_dir))
        if rows:
            track22._write_csv(rows_path, rows)
    completed = {
        (row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0), int(float(row.get("budget_steps") or 0)))
        for row in rows
    }
    for item in stage_a_work_items(args, manifest):
        key = (item["algorithm"], item["bundle"], int(item["seed"]), int(item["budget_steps"]))
        if key in completed:
            continue
        _log(
            progress_path,
            f"Stage A {item['algorithm']} bundle={item['bundle']} seed={item['seed']} steps={item['budget_steps']}",
        )
        if item["algorithm"] == "operator_select":
            row = track22.run_operator_select_steps(item["bundle"], seed=int(item["seed"]), step_count=int(item["budget_steps"]))
        elif item["algorithm"] == "worst_removal_fixed":
            row = track22.run_worst_removal_steps(item["bundle"], seed=int(item["seed"]), step_count=int(item["budget_steps"]))
        else:
            row = track22.run_best_of_k_steps(
                item["bundle"],
                seed=int(item["seed"]),
                step_count=int(item["budget_steps"]),
                candidate_k=int(args.stage_a_best_of_k),
            )
        row.update({k: v for k, v in item.items() if k not in row})
        row["track"] = "track23"
        row["stage"] = "A"
        row["probe_mode"] = track22.EQUAL_STEPS_ORACLE
        row["evidence_role"] = "DESTROY_LEVERAGE_GATE"
        rows.append(annotate_stage_a_budget(row))
        track22._write_csv(rows_path, rows)
    return rows


def import_track22r_stage_a_rows(track22r_dir: Path) -> list[dict[str, Any]]:
    source = track22r_dir / "track22r_destroy_leverage_equal_steps_rows.csv"
    imported: list[dict[str, Any]] = []
    for row in track22._read_csv(source):
        if str(row.get("scale")) != "25c":
            continue
        budget_steps = int(float(row.get("target_steps") or row.get("budget_steps") or 0))
        if budget_steps != 4000:
            continue
        out = dict(row)
        out.update(
            {
                "track": "track23",
                "stage": "A",
                "evidence_role": "DESTROY_LEVERAGE_GATE",
                "budget_steps": budget_steps,
                "budget_label": "25c_4000",
                "probe_mode": track22.EQUAL_STEPS_ORACLE,
                "source_track": "track22r_reannotated",
            }
        )
        imported.append(annotate_stage_a_budget(out))
    return imported


def stage_a_work_items(args: argparse.Namespace, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    bundle_rows = list((manifest.get("roles") or {}).get("stage2_probe") or [])
    bundles = [str(row["path"]) for row in bundle_rows]
    if Path(EUK100_03).exists():
        bundles.append(EUK100_03)
    out: list[dict[str, Any]] = []
    for bundle in bundles:
        scale = track22._scale_label(bundle)
        for budget_steps in stage_a_budget_steps_for_scale(scale):
            seeds = _parse_int_list(args.stage_a_100c_seeds if scale == "100c" else args.stage_a_seeds)
            for seed in seeds:
                for algorithm in ("operator_select", "worst_removal_fixed", "best_of_k_destroy"):
                    out.append(
                        {
                            "algorithm": algorithm,
                            "bundle": bundle,
                            "scale": scale,
                            "seed": int(seed),
                            "budget_steps": int(budget_steps),
                            "budget_label": f"{scale}_{budget_steps}",
                        }
                    )
    return out


def stage_a_budget_steps_for_scale(scale: str) -> tuple[int, ...]:
    if str(scale) == "25c":
        return (250, 1000, 4000)
    if str(scale) == "50c":
        return (750, 3000)
    if str(scale) == "100c":
        return (1000,)
    return (1000,)


def annotate_stage_a_budget(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    budget_steps = int(float(out.get("budget_steps") or out.get("target_steps") or 0))
    actual = _int(out.get("actual_evals"))
    wall = _float(out.get("wall_time_seconds"))
    wall_floor = float(track22.STAGE2_WALL_FLOOR_SECONDS)
    eval_ratio = float(actual) / max(float(budget_steps), 1.0)
    wall_ratio = float(wall) / wall_floor if math.isfinite(wall) else 0.0
    out.update(
        {
            "budget_steps": int(budget_steps),
            "target_steps": int(out.get("target_steps") or budget_steps),
            "eval_floor": int(budget_steps),
            "eval_floor_ratio": float(eval_ratio),
            "wall_floor_seconds": float(wall_floor),
            "wall_floor_ratio": float(wall_ratio),
            "budget_status": track22.OK_BUDGET if actual >= budget_steps or wall_ratio >= 1.0 else track22.UNDERPOWERED,
        }
    )
    return out


def summarize_stage_a_destroy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gate_rows = [row for row in rows if row.get("evidence_role") == "DESTROY_LEVERAGE_GATE"]
    if not gate_rows:
        raise Track23Halt("HALT_STAGE_A_NO_ROWS", "Stage A has no destroy-leverage rows.")
    track22.assert_no_underpowered_for_verdict(gate_rows, stage="Track23 Stage A")
    track22.assert_consistent_nominal_budget(
        gate_rows,
        stage="Track23 Stage A",
        group_fields=("scale", "budget_steps"),
        budget_fields=("budget_steps", "eval_floor", "wall_floor_seconds"),
    )
    budget_rows = [_stage_a_budget_row(label, values) for label, values in sorted(_group_stage_a(gate_rows).items())]
    max_row = max(budget_rows, key=lambda row: _finite_or(row["best_of_k_headroom_pct"], -math.inf))
    max_headroom = _float(max_row.get("best_of_k_headroom_pct"))
    worker_ok = all(track22._truthy(row.get("worker_integrity_ok")) for row in gate_rows)
    zero_violations = track22._all_zero(gate_rows, "violation_count")
    if not worker_ok:
        status = track22.HALT_WORKER_INTEGRITY
        reason = "At least one Stage A row did not use the py313/NumPy2.3.5 worker."
    elif not zero_violations:
        status = "HALT_STAGE_A_VIOLATION"
        reason = "At least one Stage A row has nonzero violation_count."
    elif max_headroom >= 3.0:
        status = DESTROY_LEVERAGE_AT_BUDGET
        reason = f"Budget ladder found best-of-k destroy leverage >=3%; max={max_headroom:.3f}% at {max_row['label']}."
    elif max_headroom >= 1.0:
        status = LEVERAGE_MARGINAL
        reason = f"Budget ladder found marginal leverage 1-3%; max={max_headroom:.3f}% at {max_row['label']}."
    else:
        status = NO_DESTROY_LEVERAGE_ANY_BUDGET
        reason = f"All budget ladder rows are <1%; max={max_headroom:.3f}% at {max_row['label']}."
    return {
        "status": status,
        "reason": reason,
        "row_count": len(gate_rows),
        "worker_integrity_ok": worker_ok,
        "zero_violations": zero_violations,
        "budget_rows": budget_rows,
        "max_budget_row": max_row,
        "max_headroom_pct": max_headroom,
        "budget_summary": track22.budget_summary(gate_rows),
        "gate_rule": "Max paired best_of_k vs operator_select over all scale-budget cells: >=3 pass, 1-3 marginal, <1 clean negative.",
    }


def _group_stage_a(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get("budget_label") or f"{row.get('scale')}_{row.get('budget_steps')}")
        grouped.setdefault(label, []).append(row)
    return grouped


def _stage_a_budget_row(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)): row for row in rows}
    best_gains: list[float] = []
    worst_gains: list[float] = []
    for row in rows:
        if row.get("algorithm") != "operator_select":
            continue
        key = (row.get("bundle"), int(row.get("seed") or 0))
        op = _float(row.get("best_obj"))
        best = by_key.get(("best_of_k_destroy", *key))
        worst = by_key.get(("worst_removal_fixed", *key))
        if best:
            best_gains.append(_improvement_pct(op, _float(best.get("best_obj"))))
        if worst:
            worst_gains.append(_improvement_pct(op, _float(worst.get("best_obj"))))
    scale = str(rows[0].get("scale", "")) if rows else ""
    budget_steps = int(float(rows[0].get("budget_steps") or 0)) if rows else 0
    return {
        "label": label,
        "scale": scale,
        "budget_steps": budget_steps,
        "row_count": len(rows),
        "paired_count": len(best_gains),
        "best_of_k_headroom_pct": _mean(best_gains),
        "worst_removal_headroom_pct": _mean(worst_gains),
    }


def should_run_stage_a2(stage_a_summary: dict[str, Any]) -> bool:
    return str(stage_a_summary.get("status")) in {DESTROY_LEVERAGE_AT_BUDGET, LEVERAGE_MARGINAL}


def run_stage_a2_learned_destroy(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    stage_a = state.get("stage_a") or {}
    max_row = stage_a.get("max_budget_row") or {}
    budget = int(float(max_row.get("budget_steps") or args.stage3_test_eval_budget))
    a2_args = argparse.Namespace(**vars(args))
    a2_args.stage3_train_eval_budget = budget
    a2_args.stage3_validation_eval_budget = budget
    a2_args.stage3_test_eval_budget = budget
    _log(progress_path, f"Stage A2 using learned-destroy eval budget={budget} from Stage A max row")
    a2_manifest = ensure_stage_a2_bundle_manifest(args, output_dir, max_row)
    a2_state = dict(state)
    a2_state["bundle_manifest"] = a2_manifest
    track22._write_json(output_dir / "stage_a2_bundle_manifest.json", a2_manifest)
    _log(progress_path, f"Stage A2 using fresh same-scale manifest scale={max_row.get('scale')}")
    summary = track22.run_stage3_learned_destroy(a2_args, output_dir, progress_path, a2_state)
    status = str(summary.get("status"))
    if status == track22.WEAK_LEARNED_DESTROY_CLEAN:
        summary["status"] = WEAK
    elif status == track22.HALT_LEARNED_DESTROY_CLEAN:
        summary["status"] = HALT_NO_GAIN_CLEAN
    elif status == track22.PASS_LEARNED_DESTROY_CLEAN:
        summary["status"] = PASS_LEARNED_DESTROY_CLEAN
    summary["track23_eval_budget_from_stage_a"] = budget
    summary["track23_train_scale_from_stage_a"] = str(max_row.get("scale", ""))
    summary["track23_stage_a2_manifest"] = "stage_a2_bundle_manifest.json"
    return summary


def ensure_stage_a2_bundle_manifest(args: argparse.Namespace, output_dir: Path, max_row: dict[str, Any]) -> dict[str, Any]:
    scale = str(max_row.get("scale") or "25c")
    try:
        n_customers = int(scale.rstrip("c"))
    except ValueError:
        n_customers = 25
    root = Path(".").resolve()
    template = track22._load_template_config((root / track22.DEFAULT_TEMPLATE_MANIFEST).resolve())
    specs_by_role = {
        "stage3_train": (
            track22.CurriculumSpec(f"E-UK{n_customers}_T23_A2_TR01", n_customers, 33001 + n_customers),
            track22.CurriculumSpec(f"E-UK{n_customers}_T23_A2_TR02", n_customers, 33002 + n_customers),
            track22.CurriculumSpec(f"E-UK{n_customers}_T23_A2_TR03", n_customers, 33003 + n_customers),
        ),
        "stage3_val": (
            track22.CurriculumSpec(f"E-UK{n_customers}_T23_A2_VA01", n_customers, 33101 + n_customers),
        ),
        "stage3_test": (
            track22.CurriculumSpec(f"E-UK{n_customers}_T23_A2_TE01", n_customers, 33201 + n_customers),
            track22.CurriculumSpec(f"E-UK{n_customers}_T23_A2_TE02", n_customers, 33202 + n_customers),
        ),
    }
    rows_by_role: dict[str, list[dict[str, Any]]] = {}
    for role, specs in specs_by_role.items():
        rows: list[dict[str, Any]] = []
        for spec in specs:
            output = root / track22.DEFAULT_GENERATED_ROOT / spec.scenario_id
            if output.exists() and not bool(args.regenerate_bundles):
                manifest = track22.validate_generated_bundle(output, expected_n=spec.n_customers)
            else:
                if output.exists():
                    track22._remove_existing_output(output, (root / track22.DEFAULT_GENERATED_ROOT).resolve())
                scenario_config, manifest_config = track22.build_config_for_spec(root, template, spec)
                scenario = track22.generate_scenario(scenario_config)
                track22.write_scenario_bundle(scenario, output, config=manifest_config)
                manifest = track22.validate_generated_bundle(output, expected_n=spec.n_customers)
            rows.append(
                {
                    "role": role,
                    "name": spec.scenario_id,
                    "path": track22._manifest_bundle_path(root, output),
                    "n_customers": int(manifest["validation"]["customer_count"]),
                    "validation_passed": bool(manifest["validation"]["passed"]),
                    "has_carbon_profile": bool((output / "carbon_profile.csv").is_file()),
                    "seed": int(spec.seed),
                    "base_id": spec.base_id,
                    "scale": f"{n_customers}c",
                }
            )
        track22._write_json(output_dir / f"stage_a2_bundle_manifest_{role}.json", track22.build_curriculum_manifest(rows))
        rows_by_role[role] = rows
    flat = [row for role_rows in rows_by_role.values() for row in role_rows]
    return {
        "schema_version": "track23-stage-a2-bundle-manifest.v1",
        "roles": rows_by_role,
        "all": flat,
        "scale": f"{n_customers}c",
        "non_overlap_ok": len({row["path"] for row in flat}) == len(flat),
    }


def run_stage_b_carbon(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    summary = track22.run_stage4_carbon_timing(args, output_dir, progress_path, state)
    if summary.get("status") == track22.CARBON_CEILING_TOO_SMALL_DEFAULT:
        knob_rows = build_carbon_knob_table(args, output_dir, progress_path, state)
        track22._write_csv(output_dir / "stage_b_carbon_scenario_knobs.csv", knob_rows)
        summary["scenario_knob_rows"] = len(knob_rows)
        summary["scenario_knob_table"] = "stage_b_carbon_scenario_knobs.csv"
    return summary


def build_carbon_knob_table(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    manifest = state.get("bundle_manifest") or track22.ensure_track22_bundles(args, output_dir)
    bundles = [str(row["path"]) for row in manifest["roles"]["stage2_probe"][:2]]
    rows: list[dict[str, Any]] = []
    for bundle in bundles:
        for seed in _parse_int_list(args.stage4_seeds)[:1]:
            _log(progress_path, f"Stage B carbon knob seed solution bundle={bundle} seed={seed}")
            loaded = track22.load_search_bundle(bundle)
            customer_count = len([node for node in loaded.instance.nodes if str(node.node_type).lower() == "c"])
            base_cv = int(loaded.instance.num_cv or 1)
            base_ev = int(loaded.instance.num_ev or 1)
            for ev_factor in (1.0, 1.5, 2.0):
                for price_factor in (1.0, 5.0, 10.0):
                    for amplitude_factor in (0.5, 1.0, 2.0):
                        profile = amplify_carbon_profile(loaded.carbon_profile, amplitude_factor=amplitude_factor)
                        prices = replace(DEFAULT_PRICES, carbon_price=float(DEFAULT_PRICES.carbon_price) * float(price_factor))
                        ev_cap = max(base_ev, int(math.ceil(base_ev * float(ev_factor))))
                        limits = track22.FleetLimits(cv=max(1, base_cv), ev=ev_cap, source="track23_scenario_knob_ev_factor")
                        synthetic_instance = replace(loaded.instance, num_cv=int(limits.cv), num_ev=int(limits.ev))
                        synthetic = replace(loaded, instance=synthetic_instance, carbon_profile=profile)
                        solution = track22.build_initial_solution(
                            synthetic_instance,
                            profile,
                            prices,
                            fleet_limits=limits,
                            introduce_ev=True,
                            require_charging_signal=False,
                        )
                        row = track22.carbon_compare_solution(
                            bundle,
                            synthetic,
                            solution,
                            seed=int(seed),
                            diagnostic_role="scenario_knob_carbon_share_only",
                            source="winner_kernel_fixed_route_knob_table",
                            candidate_evals=int(args.stage4_candidate_evals),
                            prices=prices,
                        )
                        row.update(
                            {
                                "ev_vehicle_factor": float(ev_factor),
                                "ev_vehicle_cap": int(ev_cap),
                                "cv_vehicle_cap": int(limits.cv),
                                "customer_count": int(customer_count),
                                "carbon_price_factor": float(price_factor),
                                "carbon_intensity_amplitude_factor": float(amplitude_factor),
                                "verdict_role": "scenario_design_material_only",
                            }
                        )
                        rows.append(row)
    return rows


def amplify_carbon_profile(profile: list[dict[str, Any]], *, amplitude_factor: float) -> list[dict[str, Any]]:
    values = [_float(row.get("actual_gco2_per_kwh")) for row in profile if math.isfinite(_float(row.get("actual_gco2_per_kwh")))]
    mean = _mean(values)
    out: list[dict[str, Any]] = []
    for row in profile:
        new_row = dict(row)
        for key in ("actual_gco2_per_kwh", "forecast_gco2_per_kwh"):
            value = _float(row.get(key))
            if math.isfinite(value) and math.isfinite(mean):
                new_row[key] = max(0.0, mean + (value - mean) * float(amplitude_factor))
        out.append(new_row)
    return out


def run_stage_c_parity(args: argparse.Namespace, output_dir: Path, progress_path: Path) -> list[dict[str, Any]]:
    from .pilot08_eval_tools import run_policy_row
    from .pilot09_rescue_tools import run_alpha_ucb_meta_row

    if not PILOT08_UPDATE_0240.is_file():
        raise Track23Halt("HALT_STAGE_C_MISSING_PILOT08_CKPT", f"Missing checkpoint: {PILOT08_UPDATE_0240}")
    rows_path = output_dir / "stage_c_no_tuning_parity_rows.csv"
    rows = track22._read_csv(rows_path) if args.resume else []
    completed = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)) for row in rows}
    bundles = [EUK100_01, EUK100_02, EUK100_03]
    for bundle in bundles:
        role = Path(bundle).name.split("__", 1)[0]
        for seed in _parse_int_list(args.stage_c_seeds):
            tasks = (
                ("ppo_block_best", "ppo_block"),
                ("alpha_ucb_block", "alpha_ucb_block"),
                ("best_static_meta", "best_static_meta"),
                ("official_winner_kernel", "official_winner_kernel"),
            )
            for label, algorithm in tasks:
                key = (label, bundle, int(seed))
                if key in completed:
                    continue
                _log(progress_path, f"Stage C {label} bundle={bundle} seed={seed}")
                if algorithm == "best_static_meta":
                    row = run_alpha_ucb_meta_row(
                        bundle=bundle,
                        seed=int(seed),
                        eval_budget=int(args.stage_c_eval_budget),
                        block_size=int(args.stage_c_block_size),
                        q_ratio=0.40,
                        threshold_ratio=0.0025,
                        exploration_ratio=0.15,
                        bundle_role=role,
                        model_label="best_static_meta",
                    )
                    row["algorithm"] = label
                else:
                    row = run_policy_row(
                        algorithm=algorithm,
                        bundle=bundle,
                        seed=int(seed),
                        eval_budget=int(args.stage_c_eval_budget),
                        model_path=PILOT08_UPDATE_0240 if algorithm == "ppo_block" else None,
                        model_label="best" if algorithm == "ppo_block" else "",
                        checkpoint_update_value=240 if algorithm == "ppo_block" else "",
                        bundle_role=role,
                        eval_mode="budget",
                        runtime_target_seconds=0.0,
                        block_size=int(args.stage_c_block_size),
                        official_max_runtime_seconds=float(args.stage_c_official_max_runtime_seconds),
                    )
                    if algorithm == "ppo_block":
                        row["algorithm"] = label
                row["stage"] = "C"
                row["track"] = "track23"
                rows.append(row)
                track22._write_csv(rows_path, rows)
    return rows


def summarize_stage_c_parity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise Track23Halt("HALT_STAGE_C_NO_ROWS", "Stage C has no parity rows.")
    health = [
        row
        for row in rows
        if int(float(row.get("violation_count") or 0)) == 0 and int(float(row.get("actual_evals") or 0)) >= int(float(row.get("eval_budget") or 0))
    ]
    health_ok = len(health) == len(rows)
    by_bundle: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        by_bundle.setdefault(str(row.get("bundle")), {}).setdefault(str(row.get("algorithm")), []).append(_float(row.get("best_obj")))
    bundle_rows = []
    for bundle, algos in sorted(by_bundle.items()):
        dr_mean = _mean(algos.get("ppo_block_best", []))
        non_dr = {
            algo: _mean(values)
            for algo, values in algos.items()
            if algo != "ppo_block_best" and values
        }
        strongest_algo, strongest_mean = min(non_dr.items(), key=lambda item: item[1]) if non_dr else ("", math.nan)
        gap = _improvement_pct(strongest_mean, dr_mean) if math.isfinite(strongest_mean) and math.isfinite(dr_mean) else math.nan
        bundle_rows.append(
            {
                "bundle": bundle,
                "dr_mean_obj": dr_mean,
                "strongest_non_dr_algorithm": strongest_algo,
                "strongest_non_dr_mean_obj": strongest_mean,
                "dr_gap_pct_vs_strongest_non_dr": gap,
            }
        )
    min_gap = min((_finite_or(row["dr_gap_pct_vs_strongest_non_dr"], math.inf) for row in bundle_rows), default=math.nan)
    if not health_ok:
        status = "HALT_STAGE_C_HEALTH"
        reason = "At least one Stage C row violated constraints or did not use the requested eval budget."
    elif min_gap >= -2.0:
        status = NO_TUNING_PARITY_CLEAN
        reason = f"DR stayed within -2% of the strongest non-DR opponent on every bundle; min_gap={min_gap:.3f}%."
    else:
        status = PARITY_LOST_CLEAN
        reason = f"DR fell below the -2% parity floor on at least one bundle; min_gap={min_gap:.3f}%."
    return {
        "status": status,
        "reason": reason,
        "row_count": len(rows),
        "health_ok": health_ok,
        "bundle_rows": bundle_rows,
        "min_gap_pct_vs_strongest_non_dr": min_gap,
    }


def run_stage_d_dynamic(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    started: float,
) -> dict[str, Any]:
    headroom_args = argparse.Namespace(
        output_dir=str(output_dir / "stage_d_track18"),
        worker_python=args.worker_python,
        bundles=args.stage_d_bundles,
        seeds=args.stage_d_seeds,
        eval_budget=args.stage_d_eval_budget,
        max_runtime_seconds=args.stage_d_max_runtime_seconds,
        stage_eval_budget=args.stage_d_stage_eval_budget,
        stage_max_runtime_seconds=args.stage_d_stage_max_runtime_seconds,
        stages=args.stage_d_rolling_stages,
        max_wall_seconds=args.stage_d_max_wall_seconds,
        max_runs=args.stage_d_max_runs,
        resume=args.resume,
        force=False,
    )
    headroom_output = Path(headroom_args.output_dir)
    headroom_output.mkdir(parents=True, exist_ok=True)
    headroom = final_track18.run_headroom(headroom_args, headroom_output, progress_path, started)
    track22._write_json(output_dir / "stage_d_track18_headroom_summary.json", headroom)
    track18_rows = headroom_output / "track18_headroom.csv"
    mean_pct = _float(headroom.get("mean_information_cost_pct"))
    if mean_pct < 5.0:
        return {
            "status": NO_ANTICIPATION_HEADROOM_CLEAN,
            "reason": f"Fixed-worker information_cost mean is <5%; mean={mean_pct:.3f}%.",
            "headroom": headroom,
            "heuristics": [],
        }
    heuristic_summaries = []
    for mode in ("reserve_capacity", "commit_defer", "preposition"):
        h_args = argparse.Namespace(
            output_dir=str(output_dir / f"stage_d_track20_{mode}"),
            worker_python=args.worker_python,
            track18_rows=str(track18_rows),
            eval_budget=args.stage_d_eval_budget,
            max_runtime_seconds=args.stage_d_max_runtime_seconds,
            stage_eval_budget=args.stage_d_stage_eval_budget,
            stage_max_runtime_seconds=args.stage_d_stage_max_runtime_seconds,
            stages=args.stage_d_rolling_stages,
            reserve_fraction=args.stage_d_reserve_fraction,
            policy_mode=mode,
            defer_min_slack_seconds=args.stage_d_defer_min_slack_seconds,
            max_wall_seconds=args.stage_d_max_wall_seconds,
            max_runs=args.stage_d_max_runs,
            resume=args.resume,
            force=False,
        )
        h_output = Path(h_args.output_dir)
        h_output.mkdir(parents=True, exist_ok=True)
        regression = final_track20.run_myopic_callback_regression(h_args, h_output, progress_path, started)
        if regression["verdict"] == "HALT_MYOPIC_CALLBACK_REGRESSION":
            heuristic_summaries.append({"mode": mode, "verdict": regression["verdict"], "reason": regression["reason"]})
            continue
        sanity = final_track20.run_action_sanity(h_args, h_output, progress_path, started)
        sanity["mode"] = mode
        heuristic_summaries.append(sanity)
    return summarize_stage_d_dynamic(headroom, heuristic_summaries)


def summarize_stage_d_dynamic(headroom: dict[str, Any], heuristics: list[dict[str, Any]]) -> dict[str, Any]:
    mean_pct = _float(headroom.get("mean_information_cost_pct"))
    if mean_pct < 5.0:
        return {
            "status": NO_ANTICIPATION_HEADROOM_CLEAN,
            "reason": f"information_cost mean {mean_pct:.3f}% <5%; dynamic pillar stops before heuristics.",
            "headroom": headroom,
            "heuristics": heuristics,
        }
    best_pp = max((_heuristic_pct_point_reduction(summary) for summary in heuristics), default=math.nan)
    partial = any(str(summary.get("verdict", "")).startswith("HALT") for summary in heuristics)
    if math.isfinite(best_pp) and best_pp >= 2.0:
        status = HEURISTIC_MOVES_HEADROOM
        reason = f"At least one heuristic reduced information_cost_pct by >=2 percentage points; best={best_pp:.3f} pp."
    elif partial:
        status = DYNAMIC_INTERFACE_PARTIAL
        reason = "At least one dynamic heuristic/interface check halted; do not claim the dynamic pillar."
    else:
        status = HEURISTIC_FLAT
        reason = f"No heuristic reduced information_cost_pct by >=2 percentage points; best={best_pp:.3f} pp."
    return {"status": status, "reason": reason, "headroom": headroom, "heuristics": heuristics, "best_reduction_pp": best_pp}


def _heuristic_pct_point_reduction(summary: dict[str, Any]) -> float:
    rows = list(summary.get("rows") or [])
    values = [
        _float(row.get("myopic_information_cost_pct")) - _float(row.get("heuristic_information_cost_pct"))
        for row in rows
        if math.isfinite(_float(row.get("myopic_information_cost_pct"))) and math.isfinite(_float(row.get("heuristic_information_cost_pct")))
    ]
    return _mean(values)


def summarize_pillars(state: dict[str, Any]) -> dict[str, str]:
    stage_a = state.get("stage_a") or {}
    stage_a2 = state.get("stage_a2") or {}
    stage_c = state.get("stage_c") or {}
    stage_d = state.get("stage_d") or {}
    quality = "站住" if stage_c.get("status") == NO_TUNING_PARITY_CLEAN else ("没站住" if stage_c else "未判")
    efficiency = "站住" if stage_a2.get("status") == PASS_LEARNED_DESTROY_CLEAN else (
        "没站住" if stage_a.get("status") == NO_DESTROY_LEVERAGE_ANY_BUDGET or stage_a2.get("status") in {HALT_NO_GAIN_CLEAN, WEAK} else "未判"
    )
    dynamic = "站住" if stage_d.get("status") == HEURISTIC_MOVES_HEADROOM else (
        "没站住" if stage_d.get("status") in {NO_ANTICIPATION_HEADROOM_CLEAN, HEURISTIC_FLAT, DYNAMIC_INTERFACE_PARTIAL} else "未判"
    )
    return {"DR_PILLAR_QUALITY": quality, "DR_PILLAR_EFFICIENCY": efficiency, "DR_PILLAR_DYNAMIC": dynamic}


def _pillar_sentence(pillars: dict[str, str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in pillars.items())


def write_stage_a_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Track23 Stage A Destroy Leverage Budget Ladder",
        "",
        f"Verdict: `{summary.get('status')}`",
        f"Reason: {summary.get('reason')}",
        "",
        "## Budget Cells",
        "",
    ]
    for row in summary.get("budget_rows", []):
        lines.append(
            f"- {row['label']}: pairs={row['paired_count']}, best_of_k_vs_operator={_float(row['best_of_k_headroom_pct']):.3f}%, worst_vs_operator={_float(row['worst_removal_headroom_pct']):.3f}%"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_stage_c_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Track23 Stage C No-Tuning Parity",
        "",
        f"Verdict: `{summary.get('status')}`",
        f"Reason: {summary.get('reason')}",
        "",
        "## Bundles",
        "",
    ]
    for row in summary.get("bundle_rows", []):
        lines.append(
            f"- {Path(str(row['bundle'])).name}: DR mean={_float(row['dr_mean_obj']):.6f}, strongest={row['strongest_non_dr_algorithm']} mean={_float(row['strongest_non_dr_mean_obj']):.6f}, gap={_float(row['dr_gap_pct_vs_strongest_non_dr']):.3f}%"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_final_report(path: Path, state: dict[str, Any]) -> None:
    pillars = state.get("pillar_summary") or summarize_pillars(state)
    stage_a = state.get("stage_a") or {}
    stage_a2 = state.get("stage_a2") or {}
    stage_b = state.get("stage_b") or {}
    stage_c = state.get("stage_c") or {}
    stage_d = state.get("stage_d") or {}
    lines = [
        "# Track23 DR-ALNS Standing Report",
        "",
        f"Final status: `{state.get('final_status', 'UNKNOWN')}`",
        f"Final reason: {state.get('final_reason', '')}",
        "",
        "## Pillars",
        "",
        f"- DR_PILLAR_QUALITY: `{pillars.get('DR_PILLAR_QUALITY', '未判')}`",
        f"- DR_PILLAR_EFFICIENCY: `{pillars.get('DR_PILLAR_EFFICIENCY', '未判')}`",
        f"- DR_PILLAR_DYNAMIC: `{pillars.get('DR_PILLAR_DYNAMIC', '未判')}`",
        "",
        "## Stage Status",
        "",
        f"- Stage A: `{stage_a.get('status', 'NOT_RUN')}` - {stage_a.get('reason', '')}",
        f"- Stage A2: `{stage_a2.get('status', 'NOT_RUN')}` - {stage_a2.get('reason', '')}",
        f"- Stage B: `{stage_b.get('status', 'NOT_RUN')}` - {stage_b.get('reason', '')}",
        f"- Stage C: `{stage_c.get('status', 'NOT_RUN')}` - {stage_c.get('reason', '')}",
        f"- Stage D: `{stage_d.get('status', 'NOT_RUN')}` - {stage_d.get('reason', '')}",
        "",
        "## Claim List",
        "",
        *_claim_lines(state),
        "",
        "## Evidence Files",
        "",
        "- `stage_a_destroy_ladder_rows.csv`",
        "- `stage_a_destroy_ladder_summary.json`",
        "- `track22_carbon_timing_rows.csv`",
        "- `stage_c_no_tuning_parity_rows.csv`",
        "- `stage_d_track18/track18_headroom.csv`",
        "- `track23_final_report.json`",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _claim_lines(state: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    stage_c = state.get("stage_c") or {}
    if stage_c.get("status") == NO_TUNING_PARITY_CLEAN:
        lines.append("- Now writable: DR no-tuning parity held against the strongest non-DR opponent in Stage C; evidence `stage_c_no_tuning_parity_rows.csv`.")
    else:
        lines.append("- Not yet writable: no-tuning parity still needs a clean Stage C pass.")
    stage_a2 = state.get("stage_a2") or {}
    if stage_a2.get("status") == PASS_LEARNED_DESTROY_CLEAN:
        lines.append("- Now writable: learned-destroy improved over operator-select at the leveraged budget; evidence `stage_a2_learned_destroy_summary.json`.")
    else:
        lines.append("- Not yet writable: learned-destroy efficiency needs Stage A leverage plus a clean Stage A2 pass.")
    stage_d = state.get("stage_d") or {}
    if stage_d.get("status") == HEURISTIC_MOVES_HEADROOM:
        lines.append("- Now writable: dynamic anticipatory actions reduce information cost; evidence `stage_d_dynamic_summary.json`.")
    else:
        lines.append("- Not yet writable: dynamic pillar needs fixed-worker headroom plus a heuristic action that eats it.")
    return lines


def _save_state(path: Path, state: dict[str, Any]) -> None:
    track22._write_json(path, state)


def _log(path: Path, message: str) -> None:
    track22._log(path, message)


def _float(value: Any) -> float:
    return track22._float(value)


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _finite_or(value: Any, fallback: float) -> float:
    number = _float(value)
    return number if math.isfinite(number) else fallback


def _mean(values: list[float]) -> float:
    clean = [value for value in values if math.isfinite(value)]
    return sum(clean) / len(clean) if clean else math.nan


def _improvement_pct(base: float, candidate: float) -> float:
    return track22._improvement_pct(base, candidate)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track23 DR-ALNS standing runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    run_parser.add_argument("--track22r-dir", default=str(DEFAULT_TRACK22R_DIR))
    run_parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    run_parser.add_argument("--resume", action="store_true", default=True)
    run_parser.add_argument("--no-resume", dest="resume", action="store_false")
    run_parser.add_argument("--stages", default="A,A2,B,C,D,E")
    run_parser.add_argument("--regenerate-bundles", action="store_true")
    run_parser.add_argument("--min-free-disk-gb", type=float, default=5.0)
    run_parser.add_argument("--require-self-py313", action="store_true")

    run_parser.add_argument("--stage-a-seeds", default="1201,1202,1203")
    run_parser.add_argument("--stage-a-100c-seeds", default="1201,1202")
    run_parser.add_argument("--stage-a-best-of-k", type=int, default=4)

    run_parser.add_argument("--stage3-seed", type=int, default=2601)
    run_parser.add_argument("--stage3-train-episodes", type=int, default=1000)
    run_parser.add_argument("--stage3-train-eval-budget", type=int, default=120)
    run_parser.add_argument("--stage3-validation-eval-budget", type=int, default=120)
    run_parser.add_argument("--stage3-test-eval-budget", type=int, default=180)
    run_parser.add_argument("--stage3-validation-seeds", default="2701")
    run_parser.add_argument("--stage3-test-seeds", default="2801,2802,2803,2804,2805")
    run_parser.add_argument("--stage3-pomo-rollouts", type=int, default=4)
    run_parser.add_argument("--stage3-rollout-min-groups", type=int, default=1)
    run_parser.add_argument("--stage3-validation-every-updates", type=int, default=10)
    run_parser.add_argument("--stage3-max-train-seconds", type=float, default=28800.0)
    run_parser.add_argument("--stage3-max-customers", type=int, default=128)
    run_parser.add_argument("--stage3-hidden-size", type=int, default=128)
    run_parser.add_argument("--stage3-learning-rate", type=float, default=1e-4)
    run_parser.add_argument("--stage3-final-learning-rate", type=float, default=1e-5)
    run_parser.add_argument("--stage3-ppo-epochs", type=int, default=1)
    run_parser.add_argument("--stage3-minibatch-size", type=int, default=64)
    run_parser.add_argument("--stage3-clip-range", type=float, default=0.1)
    run_parser.add_argument("--stage3-target-kl", type=float, default=0.08)
    run_parser.add_argument("--stage3-value-coef", type=float, default=0.5)
    run_parser.add_argument("--stage3-entropy-coef", type=float, default=0.01)
    run_parser.add_argument("--stage3-max-grad-norm", type=float, default=0.5)

    run_parser.add_argument("--stage4-bundle-count", type=int, default=5)
    run_parser.add_argument("--stage4-seeds", default="2901,2902,2903")
    run_parser.add_argument("--stage4-eval-budget", type=int, default=300)
    run_parser.add_argument("--stage4-candidate-evals", type=int, default=200)
    run_parser.add_argument("--stage4-max-runtime-seconds", type=float, default=120.0)
    run_parser.add_argument("--stage4-ev-heavy-seed", type=int, default=2999)
    run_parser.add_argument("--stage4-ev-heavy-carbon-price-factor", type=float, default=10.0)

    run_parser.add_argument("--stage-c-seeds", default="1,2,3,4,5")
    run_parser.add_argument("--stage-c-eval-budget", type=int, default=3000)
    run_parser.add_argument("--stage-c-block-size", type=int, default=PILOT08_BLOCK_SIZE)
    run_parser.add_argument("--stage-c-official-max-runtime-seconds", type=float, default=900.0)

    run_parser.add_argument("--stage-d-bundles", default=",".join(final_track18.DEFAULT_BUNDLES))
    run_parser.add_argument("--stage-d-seeds", default="901,902,903,904,905,906,907,908,909,910")
    run_parser.add_argument("--stage-d-eval-budget", type=int, default=2000)
    run_parser.add_argument("--stage-d-max-runtime-seconds", type=float, default=180.0)
    run_parser.add_argument("--stage-d-stage-eval-budget", type=int, default=2000)
    run_parser.add_argument("--stage-d-stage-max-runtime-seconds", type=float, default=120.0)
    run_parser.add_argument("--stage-d-rolling-stages", type=int, default=4)
    run_parser.add_argument("--stage-d-max-wall-seconds", type=float, default=6 * 3600.0)
    run_parser.add_argument("--stage-d-max-runs", type=int, default=0)
    run_parser.add_argument("--stage-d-reserve-fraction", type=float, default=0.20)
    run_parser.add_argument("--stage-d-defer-min-slack-seconds", type=float, default=7200.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run":
        return run(args)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
