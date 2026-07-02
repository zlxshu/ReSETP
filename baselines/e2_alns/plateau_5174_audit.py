#!/usr/bin/env python3
"""Audit the E2 5174.345 baseline plateau without mutating source artifacts."""

from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = REPO_ROOT / "baselines/e2_alns/ev_heavy_findability_gate_long_same_instance_v2_data"
OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/e2_g0_same_value_platform_audit_data"
BASELINE_ALGORITHMS = {"GA", "LNS", "PSO", "VNS"}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_rows = read_csv(INPUT_DIR / "raw_runs.csv")
    task_rows = read_task_rows(INPUT_DIR / ".tasks")
    metadata = read_json(INPUT_DIR / "metadata.json")
    decision = read_json(INPUT_DIR / "findability_decision.json")
    apple_double = sorted(path for path in INPUT_DIR.rglob("._*") if path.is_file())

    replay_rows, signature_payload = replay_checkpoints(raw_rows, task_rows, metadata)
    history_rows, history_summary_rows = history_tables(raw_rows)
    seed_rows = seed_invariance(raw_rows)
    platform_rows = platform_table(raw_rows, replay_rows)

    write_csv(OUTPUT_DIR / "platform_rows.csv", platform_rows)
    write_csv(OUTPUT_DIR / "baseline_history.csv", history_rows)
    write_csv(OUTPUT_DIR / "baseline_history_summary.csv", history_summary_rows)
    write_csv(OUTPUT_DIR / "checkpoint_replay.csv", replay_rows)
    write_csv(OUTPUT_DIR / "seed_invariance.csv", seed_rows)
    write_json(OUTPUT_DIR / "baseline_plateau_signature.json", signature_payload)

    hash_hygiene = {
        "input_dir": rel(INPUT_DIR),
        "appledouble_count": len(apple_double),
        "appledouble_files": [rel(path) for path in apple_double],
        "artifact_hashes_contains_appledouble": artifact_hashes_contains_appledouble(INPUT_DIR / "artifact_hashes.json"),
    }
    write_json(OUTPUT_DIR / "hash_hygiene.json", hash_hygiene)

    summary = build_summary(
        raw_rows=raw_rows,
        replay_rows=replay_rows,
        history_summary_rows=history_summary_rows,
        metadata=metadata,
        decision=decision,
        hash_hygiene=hash_hygiene,
    )
    write_json(OUTPUT_DIR / "summary.json", summary)
    write_artifact_hashes(OUTPUT_DIR / "artifact_hashes.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_task_rows(task_dir: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    tasks: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in sorted(task_dir.glob("*.json")):
        if path.name.startswith("._") or path.name.endswith("_row.json"):
            continue
        payload = read_json(path)
        key = (str(payload.get("algorithm")), str(payload.get("seed")), str(payload.get("instance")))
        tasks[key] = payload
    return tasks


def replay_checkpoints(
    raw_rows: list[dict[str, str]],
    task_rows: dict[tuple[str, str, str], dict[str, Any]],
    metadata: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import sys

    sys.path.insert(0, str(REPO_ROOT / "solver/src"))
    sys.path.insert(0, str(REPO_ROOT / "models/src"))

    from setp_solver.check import check_solution
    from setp_solver.cost import evaluate
    from setp_solver.prices import DEFAULT_PRICES
    from setp_solver.search.bundle import load_search_bundle
    from setp_solver.search.candidates import solution_signature, solution_signature_hash
    from setp_solver.search.metaheuristic_baselines import solution_from_dict

    first_task = next(iter(task_rows.values()))
    bundle_dir = REPO_ROOT / str(first_task["bundle_dir"])
    battery_kwh = float(metadata.get("battery_kwh", first_task.get("battery_kwh", 280.0)))
    prices = replace(DEFAULT_PRICES, B_battery_kwh=battery_kwh, carbon_price=float(metadata.get("carbon_price", DEFAULT_PRICES.carbon_price)))
    bundle = load_search_bundle(bundle_dir)

    rows: list[dict[str, Any]] = []
    signature_payload: dict[str, Any] = {}
    raw_lookup = {(row["algorithm"], row["seed"], row["instance"]): row for row in raw_rows}
    checkpoint_dir = INPUT_DIR / "checkpoints/neutral"
    for path in sorted(checkpoint_dir.glob("*.json")):
        if path.name.startswith("._"):
            continue
        payload = read_json(path)
        stem = path.stem
        instance, algorithm, seed_text = stem.split("__")
        seed = seed_text.replace("seed", "")
        solution = solution_from_dict(payload["solution"])
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        violations = check_solution(solution, bundle.instance, prices)
        signature = solution_signature(solution)
        signature_hash = solution_signature_hash(solution)
        raw = raw_lookup.get((algorithm, seed, instance), {})
        json_hash = hashlib.sha256(
            json.dumps(payload["solution"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        routes = payload["solution"].get("routes", [])
        charging_actions = payload["solution"].get("charging_actions", [])
        row = {
            "instance": instance,
            "algorithm": algorithm,
            "seed": int(seed),
            "checkpoint": rel(path),
            "checkpoint_eval": int(payload.get("eval", -1)),
            "checkpoint_operator": str(payload.get("operator", "")),
            "checkpoint_best_cost": float(payload.get("best_cost", "nan")),
            "replay_total_cost": float(metrics["total_cost"]),
            "replay_violation_count": len(violations),
            "signature_hash": signature_hash,
            "raw_best_signature": raw.get("best_signature", ""),
            "signature_matches_raw": signature_hash == raw.get("best_signature", ""),
            "solution_json_sha256": json_hash,
            "route_count": len(routes),
            "cv_route_count": sum(1 for route in routes if str(route.get("vehicle_type", "")).lower() == "cv"),
            "ev_route_count": sum(1 for route in routes if str(route.get("vehicle_type", "")).lower() == "ev"),
            "charging_action_count": len(charging_actions),
            "E_total": float(metrics.get("E_total", 0.0)),
            "cost_carbon": float(metrics.get("cost_carbon", 0.0)),
        }
        rows.append(row)
        if algorithm in BASELINE_ALGORITHMS:
            signature_payload.setdefault("baseline_signatures", {})[f"{algorithm}-seed{seed}"] = signature
    signature_payload["input_dir"] = rel(INPUT_DIR)
    signature_payload["note"] = "Generated by plateau_5174_audit.py; route signatures use project solution_signature()."
    return rows, signature_payload


def history_tables(raw_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    history_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if row["algorithm"] not in BASELINE_ALGORITHMS:
            continue
        history = json.loads(row.get("history_json") or "[]")
        improvement_ops = [str(item.get("operator", "")) for item in history[1:]]
        improvement_channels = [str(item.get("channel", "")) for item in history[1:]]
        improvement_evals = [int(item.get("eval", -1)) for item in history[1:]]
        direct_vehicle_channel_ops = [op for op in improvement_ops if "vehicle_type" in op]
        native_channel_ops = [
            op
            for op, channel in zip(improvement_ops, improvement_channels)
            if channel.startswith("native_")
        ]
        flip_channel_ops = [
            op
            for op, channel in zip(improvement_ops, improvement_channels)
            if channel == "flip_operator"
        ]
        common_channel_ops = [
            op
            for op, channel in zip(improvement_ops, improvement_channels)
            if channel == "common_flip_preprocess"
        ]
        pso_initial_vehicle_schedule = (
            row["algorithm"] == "PSO"
            and bool(improvement_ops)
            and set(improvement_ops) == {"pso_initial_particle"}
            and all((eval_count - 2) % 3 == 0 for eval_count in improvement_evals)
        )
        if any(improvement_channels):
            shared_vehicle_channel = len(improvement_ops) > 0 and not native_channel_ops
            channel_basis = "explicit_history_channel"
        else:
            shared_vehicle_channel = (
                len(improvement_ops) > 0
                and (len(direct_vehicle_channel_ops) == len(improvement_ops) or pso_initial_vehicle_schedule)
            )
            channel_basis = (
                "direct_vehicle_type_operator"
                if len(direct_vehicle_channel_ops) == len(improvement_ops)
                else "pso_initial_particle_eval_mod3_vehicle_type_branch"
                if pso_initial_vehicle_schedule
                else "mixed_or_non_vehicle_channel"
            )
        for idx, item in enumerate(history):
            history_rows.append(
                {
                    "algorithm": row["algorithm"],
                    "seed": int(row["seed"]),
                    "step": idx,
                    "eval": int(item.get("eval", -1)),
                    "best_cost": float(item.get("best_cost", "nan")),
                    "current_cost": float(item.get("current_cost", "nan")),
                    "operator": str(item.get("operator", "")),
                    "channel": str(item.get("channel", "")),
                    "route_count": item.get("route_count", ""),
                    "time_seconds": float(item.get("time_seconds", 0.0)),
                }
            )
        summary_rows.append(
            {
                "algorithm": row["algorithm"],
                "seed": int(row["seed"]),
                "history_len": len(history),
                "best_improvement_count": int(row["best_improvement_count"]),
                "first_improvement_eval": int(row["first_improvement_eval"]),
                "final_improvement_eval": int(history[-1].get("eval", -1)) if history else -1,
                "first_improvement_operator": improvement_ops[0] if improvement_ops else "",
                "final_improvement_operator": improvement_ops[-1] if improvement_ops else "",
                "unique_improvement_operators": "|".join(sorted(set(improvement_ops))),
                "all_improvements_vehicle_type_channel": shared_vehicle_channel,
                "vehicle_type_channel_basis": channel_basis,
                "native_best_updates": len(native_channel_ops),
                "flip_best_updates": len(flip_channel_ops),
                "common_best_updates": len(common_channel_ops),
                "actual_evals": int(row["actual_evals"]),
                "post_final_improvement_evals": int(row["actual_evals"]) - (int(history[-1].get("eval", 0)) if history else 0),
            }
        )
    return history_rows, summary_rows


def seed_invariance(raw_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for algorithm in sorted(BASELINE_ALGORITHMS):
        group = [row for row in raw_rows if row["algorithm"] == algorithm]
        if not group:
            continue
        costs = {row["best_cost"] for row in group}
        signatures = {row["best_signature"] for row in group}
        ev_shares = {row["best_ev_share"] for row in group}
        statuses = {row["status"] for row in group}
        rows.append(
            {
                "algorithm": algorithm,
                "seeds": "|".join(row["seed"] for row in sorted(group, key=lambda item: int(item["seed"]))),
                "unique_best_costs": len(costs),
                "best_cost_values": "|".join(sorted(costs)),
                "unique_best_signatures": len(signatures),
                "best_signature_values": "|".join(sorted(signatures)),
                "unique_best_ev_shares": len(ev_shares),
                "best_ev_share_values": "|".join(sorted(ev_shares)),
                "all_status_ok": statuses == {"OK"},
                "all_eval_budget_full": all(int(row["actual_evals"]) == int(row["eval_budget"]) for row in group),
            }
        )
    rows.append(
        {
            "algorithm": "ALL_BASELINES",
            "seeds": "|".join(sorted({row["seed"] for row in raw_rows if row["algorithm"] in BASELINE_ALGORITHMS})),
            "unique_best_costs": len({row["best_cost"] for row in raw_rows if row["algorithm"] in BASELINE_ALGORITHMS}),
            "best_cost_values": "|".join(sorted({row["best_cost"] for row in raw_rows if row["algorithm"] in BASELINE_ALGORITHMS})),
            "unique_best_signatures": len({row["best_signature"] for row in raw_rows if row["algorithm"] in BASELINE_ALGORITHMS}),
            "best_signature_values": "|".join(sorted({row["best_signature"] for row in raw_rows if row["algorithm"] in BASELINE_ALGORITHMS})),
            "unique_best_ev_shares": len({row["best_ev_share"] for row in raw_rows if row["algorithm"] in BASELINE_ALGORITHMS}),
            "best_ev_share_values": "|".join(sorted({row["best_ev_share"] for row in raw_rows if row["algorithm"] in BASELINE_ALGORITHMS})),
            "all_status_ok": all(row["status"] == "OK" for row in raw_rows if row["algorithm"] in BASELINE_ALGORITHMS),
            "all_eval_budget_full": all(int(row["actual_evals"]) == int(row["eval_budget"]) for row in raw_rows if row["algorithm"] in BASELINE_ALGORITHMS),
        }
    )
    return rows


def platform_table(raw_rows: list[dict[str, str]], replay_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replay_lookup = {(row["algorithm"], str(row["seed"]), row["instance"]): row for row in replay_rows}
    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if row["algorithm"] not in BASELINE_ALGORITHMS:
            continue
        replay = replay_lookup[(row["algorithm"], row["seed"], row["instance"])]
        rows.append(
            {
                "instance": row["instance"],
                "algorithm": row["algorithm"],
                "seed": int(row["seed"]),
                "status": row["status"],
                "gate_status": row["gate_status"],
                "initial_cost": float(row["initial_cost"]),
                "best_cost": float(row["best_cost"]),
                "best_ev_share": float(row["best_ev_share"]),
                "actual_evals": int(row["actual_evals"]),
                "eval_budget": int(row["eval_budget"]),
                "best_signature": row["best_signature"],
                "replay_total_cost": replay["replay_total_cost"],
                "replay_violation_count": replay["replay_violation_count"],
                "checkpoint_eval": replay["checkpoint_eval"],
                "checkpoint_operator": replay["checkpoint_operator"],
                "route_count": replay["route_count"],
                "cv_route_count": replay["cv_route_count"],
                "ev_route_count": replay["ev_route_count"],
                "charging_action_count": replay["charging_action_count"],
                "solution_json_sha256": replay["solution_json_sha256"],
            }
        )
    return rows


def artifact_hashes_contains_appledouble(path: Path) -> bool:
    if not path.exists():
        return False
    payload = read_json(path)
    files = payload.get("files", [])
    if isinstance(files, dict):
        paths = [str(key) for key in files]
    else:
        paths = [str(item.get("path", "")) for item in files if isinstance(item, dict)]
    return any("/._" in path_text or path_text.split("/")[-1].startswith("._") for path_text in paths)


def write_artifact_hashes(path: Path) -> None:
    files: list[dict[str, str]] = []
    for item in sorted(OUTPUT_DIR.glob("*")):
        if not item.is_file() or item.name.startswith("._") or item.name == path.name:
            continue
        files.append({"path": rel(item), "sha256": hashlib.sha256(item.read_bytes()).hexdigest()})
    write_json(path, {"schema": "setp-e2-g0-audit-artifact-hashes.v1", "files": files})


def build_summary(
    *,
    raw_rows: list[dict[str, str]],
    replay_rows: list[dict[str, Any]],
    history_summary_rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    decision: dict[str, Any],
    hash_hygiene: dict[str, Any],
) -> dict[str, Any]:
    baseline_rows = [row for row in raw_rows if row["algorithm"] in BASELINE_ALGORITHMS]
    baseline_replays = [row for row in replay_rows if row["algorithm"] in BASELINE_ALGORITHMS]
    all_full_ok = all(row["status"] == "OK" and int(row["actual_evals"]) == int(row["eval_budget"]) for row in baseline_rows)
    one_signature = len({row["best_signature"] for row in baseline_rows}) == 1
    one_cost = len({row["best_cost"] for row in baseline_rows}) == 1
    replay_clean = all(int(row["replay_violation_count"]) == 0 and row["signature_matches_raw"] for row in baseline_replays)
    common_vehicle_channel = all(row["all_improvements_vehicle_type_channel"] for row in history_summary_rows)
    early_final = max(row["final_improvement_eval"] for row in history_summary_rows) <= 42
    min_tail = min(row["post_final_improvement_evals"] for row in history_summary_rows)

    if not (all_full_ok and replay_clean):
        verdict = "BASELINE_HEALTH_UNRESOLVED"
        reason = "Baseline rows did not all replay cleanly or did not all finish full budget."
    elif one_signature and one_cost and common_vehicle_channel and early_final:
        verdict = "ARTIFICIAL_HOMOGENIZATION"
        reason = (
            "All four baselines across two seeds reached the same signature/cost through the shared vehicle-type "
            "mutation channel within <=42 evals, then spent the remaining budget without distinct best updates."
        )
    elif one_signature and one_cost:
        verdict = "HEALTHY_SHARED_LOCAL_OPTIMUM"
        reason = "Same signature/cost reproduced, but the best-update traces are not dominated by one shared channel."
    else:
        verdict = "BASELINE_HEALTH_UNRESOLVED"
        reason = "Baselines did not form a single clean plateau, so the C1 question remains unresolved."

    labels = []
    if hash_hygiene["appledouble_count"] or hash_hygiene["artifact_hashes_contains_appledouble"]:
        labels.append("HASH_CONTAMINATED_APPLEDOUBLE")
    init = float(baseline_rows[0]["initial_cost"]) if baseline_rows else float("nan")
    ev_ref = float(baseline_rows[0]["ev_maximal_reference_cost"]) if baseline_rows else float("nan")
    best_min = min(float(row["best_cost"]) for row in raw_rows)
    if best_min < ev_ref:
        labels.append("EV_MAXIMAL_REFERENCE_NOT_BOUND")

    return {
        "schema": "setp-e2-g0-plateau-5174-audit.v1",
        "input_dir": rel(INPUT_DIR),
        "output_dir": rel(OUTPUT_DIR),
        "metadata_head": metadata.get("head", ""),
        "battery_kwh": float(metadata.get("battery_kwh", "nan")),
        "rows_total": len(raw_rows),
        "baseline_rows": len(baseline_rows),
        "baseline_algorithms": sorted(BASELINE_ALGORITHMS),
        "all_baseline_status_ok_and_full_eval": all_full_ok,
        "single_baseline_best_cost": one_cost,
        "single_baseline_best_signature": one_signature,
        "baseline_best_cost": sorted({row["best_cost"] for row in baseline_rows}),
        "baseline_best_signature": sorted({row["best_signature"] for row in baseline_rows}),
        "replay_clean": replay_clean,
        "all_baseline_improvements_vehicle_type_channel": common_vehicle_channel,
        "max_final_improvement_eval": max(row["final_improvement_eval"] for row in history_summary_rows),
        "min_post_final_improvement_evals": min_tail,
        "findability_decision_verdict": decision.get("verdict", ""),
        "findability_max_closed_gap_fraction": decision.get("max_closed_gap_fraction", None),
        "verdict": verdict,
        "labels": labels,
        "reason": reason,
    }


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


if __name__ == "__main__":
    main()
