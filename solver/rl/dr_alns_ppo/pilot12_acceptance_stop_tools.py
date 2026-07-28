from __future__ import annotations

import argparse
import csv
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .schemas import BlockDecodedAction
from .worker_client import WorkerClient


EXPECTED_WORKER_PYTHON = r"C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe"
EXPECTED_NUMPY_VERSION = "2.3.5"

THREESHIFT_PROBE_BUNDLES: tuple[dict[str, str], ...] = (
    {
        "bundle_role": "train_probe",
        "bundle_name": "e2-threeshift-50c-01",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-01",
    },
    {
        "bundle_role": "train_probe",
        "bundle_name": "e2-threeshift-50c-02",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-02",
    },
    {
        "bundle_role": "train_probe",
        "bundle_name": "e2-threeshift-50c-03",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-50c-03",
    },
    {
        "bundle_role": "held_probe",
        "bundle_name": "e2-threeshift-75c-01",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-01",
    },
    {
        "bundle_role": "held_probe",
        "bundle_name": "e2-threeshift-75c-02",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-02",
    },
    {
        "bundle_role": "held_probe",
        "bundle_name": "e2-threeshift-75c-03",
        "bundle_path": "models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-75c-03",
    },
)

IMPLEMENTED_POLICIES: dict[str, dict[str, float]] = {
    "best_static_meta": {"q_ratio": 0.40, "threshold_ratio": 0.0025, "exploration_ratio": 0.15},
    "strict_accept": {"q_ratio": 0.40, "threshold_ratio": 0.0, "exploration_ratio": 0.15},
    "loose_accept": {"q_ratio": 0.40, "threshold_ratio": 0.0075, "exploration_ratio": 0.15},
    "very_loose_accept": {"q_ratio": 0.40, "threshold_ratio": 0.02, "exploration_ratio": 0.15},
}

UNIMPLEMENTED_POLICIES: tuple[dict[str, str], ...] = (
    {
        "policy_label": "early_stop",
        "status": "UNIMPLEMENTABLE_STATIC_POLICY",
        "reason": "worker.block_step has no early-stop control point; it runs until budget or block_size.",
    },
    {
        "policy_label": "adaptive_stop",
        "status": "UNIMPLEMENTABLE_STATIC_POLICY",
        "reason": "stagnation is observable in trace, but no static worker action can stop or restart the search.",
    },
    {
        "policy_label": "restart_on_stagnation",
        "status": "UNIMPLEMENTABLE_STATIC_POLICY",
        "reason": "reset/restart would change worker loop semantics and needs a later opt-in interface.",
    },
)

EVIDENCE_ITEMS: list[dict[str, str]] = [
    {
        "source": "HANDOFF.md:131-134",
        "claim": "Pilot08 was WEAK after healthy training; Pilot09 found meta headroom; Pilot10 did not beat best static meta; Pilot11 selected acceptance/stop control.",
        "resetp_implication": "Do not rerun same-shape PPO; test a new control surface before training.",
        "phase": "Phase 0",
    },
    {
        "source": "docs/handoff/dr_alns_project_rhythm_manual.md:70-108",
        "claim": "Current block PPO and block_meta lanes are stopped; acceptance-control pilot is the first candidate path.",
        "resetp_implication": "Pilot12 must be no-training first and compare against best static/tuned meta.",
        "phase": "Phase 0",
    },
    {
        "source": "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot11_interface_audit/pilot11_interface_audit.md:46-52",
        "claim": "acceptance_or_stop_control is missing; first audit step is replaying accepted/rejected candidate traces.",
        "resetp_implication": "The Phase A tool should measure accepted/rejected rates and objective changes without modifying solver semantics.",
        "phase": "Phase A",
    },
    {
        "source": "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/literature_materials/dr_alns_gap_diagnosis_20260626.md:18-20",
        "claim": "Reference DR-ALNS/PPO-ALNS methods include acceptance or stop decisions, while current ReSETP block PPO does not.",
        "resetp_implication": "Acceptance/stop is a literature-backed missing action head.",
        "phase": "Phase A",
    },
    {
        "source": "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/literature_materials/dr_alns_deep_read_master_20260626.md:319-333",
        "claim": "PPO-ALNS exposes destroy, repair, accept, and stop actions with richer observations and acceptance/stop rewards.",
        "resetp_implication": "A ReSETP accept/stop audit should check whether this lever is observable before training.",
        "phase": "Phase A",
    },
    {
        "source": "Reference Algorithm/ALNS-7.0.0@N-Wouda/alns/accept and alns/stop",
        "claim": "Reference ALNS has separate acceptance criteria and stopping criteria modules.",
        "resetp_implication": "Acceptance and stopping are standard search-control interfaces, not ad-hoc neural decorations.",
        "phase": "Phase A",
    },
    {
        "source": "Reference Algorithm/ppo-alns-main/ppo/vrptwenv.py and alns/alns4ppo.py",
        "claim": "The local PPO-ALNS reference implementation exposes accept and stop decisions as policy actions.",
        "resetp_implication": "ReSETP can audit acceptance first, but stop requires a new opt-in worker control point.",
        "phase": "Phase B/C",
    },
]


@dataclass(frozen=True)
class BundleSpec:
    bundle_role: str
    bundle_path: str
    bundle_name: str = ""


def paired_relative_percent(*, policy_cost: float, baseline_cost: float) -> float:
    baseline = float(baseline_cost)
    if baseline == 0.0 or not math.isfinite(baseline):
        raise ValueError(f"baseline_cost must be finite and non-zero: {baseline_cost!r}")
    policy = float(policy_cost)
    if not math.isfinite(policy):
        raise ValueError(f"policy_cost must be finite: {policy_cost!r}")
    return (baseline - policy) / baseline * 100.0


def acceptance_row_gate(row: dict[str, Any]) -> tuple[bool, str]:
    worker = str(row.get("worker_python_executable", ""))
    if worker.lower() != EXPECTED_WORKER_PYTHON.lower():
        return False, f"worker mismatch: {worker}"
    numpy_version = str(row.get("worker_numpy_version", ""))
    if numpy_version != EXPECTED_NUMPY_VERSION:
        return False, f"numpy mismatch: {numpy_version}"
    if int(float(row.get("violation_count", 1))) != 0:
        return False, f"violation_count={row.get('violation_count')}"
    best_obj = float(row.get("best_obj", math.inf))
    if not math.isfinite(best_obj):
        return False, f"non-finite best_obj={row.get('best_obj')}"
    actual_evals = int(float(row.get("actual_evals", -1)))
    eval_budget = int(float(row.get("eval_budget", -2)))
    if actual_evals != eval_budget:
        return False, f"actual_evals {actual_evals} != eval_budget {eval_budget}"
    elapsed = float(row.get("elapsed_seconds", 0.0))
    if not math.isfinite(elapsed) or elapsed <= 0.0:
        return False, f"invalid elapsed_seconds={row.get('elapsed_seconds')}"
    return True, ""


def classify_acceptance_observability(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": "HALT_NO_ACCEPTANCE_SIGNAL", "reason": "no rows"}

    rates = [float(row.get("accepted_rate", 0.0)) for row in rows]
    accepted_rate_spread = max(rates) - min(rates)
    comparison_rows = _held_probe_rows(rows)
    by_policy = _objectives_by_policy(comparison_rows)
    baseline_values = by_policy.get("best_static_meta", [])
    if not baseline_values:
        return {
            "status": "HALT_NO_ACCEPTANCE_SIGNAL",
            "reason": "missing best_static_meta rows",
            "accepted_rate_spread": accepted_rate_spread,
        }

    baseline_mean = mean(baseline_values)
    best_policy, best_relative = _best_relative_policy(by_policy, baseline_mean)
    if accepted_rate_spread < 0.20:
        return {
            "status": "HALT_NO_ACCEPTANCE_SIGNAL",
            "reason": "accepted-rate spread below 0.20",
            "accepted_rate_spread": accepted_rate_spread,
            "best_policy": best_policy,
            "best_relative_percent": best_relative,
        }
    if best_relative < 0.30:
        return {
            "status": "HALT_NO_ACCEPTANCE_SIGNAL",
            "reason": "held-probe objective signal below +0.30%",
            "accepted_rate_spread": accepted_rate_spread,
            "best_policy": best_policy,
            "best_relative_percent": best_relative,
        }
    return {
        "status": "PASS_ACCEPTANCE_OBSERVABLE",
        "accepted_rate_spread": accepted_rate_spread,
        "best_policy": best_policy,
        "best_relative_percent": best_relative,
    }


def classify_static_headroom(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": "HALT_ACCEPT_STOP_NO_HEADROOM", "reason": "no rows"}
    gate_failures = _row_gate_failures(rows)
    if gate_failures:
        return {"status": "HALT_PILOT12_ACCEPTANCE_AUDIT", "row_gate_failures": gate_failures}

    summaries = summarize_policies(rows)
    held = [row for row in summaries if row["bundle_role"] == "held_probe" and row["policy_label"] != "best_static_meta"]
    train = {row["policy_label"]: row for row in summaries if row["bundle_role"] == "train_probe"}
    if not held:
        return {"status": "HALT_ACCEPT_STOP_NO_HEADROOM", "reason": "no held-probe policy rows"}

    best = max(held, key=lambda row: float(row.get("relative_vs_best_static_meta_percent") or -math.inf))
    best_policy = str(best["policy_label"])
    held_rel = float(best.get("relative_vs_best_static_meta_percent") or -math.inf)
    held_wins = float(best.get("wins_vs_best_static_meta_ratio") or 0.0)
    train_rel = float(train.get(best_policy, {}).get("relative_vs_best_static_meta_percent") or -math.inf)
    runtime_ratio = float(best.get("runtime_ratio_vs_best_static_meta") or math.inf)
    if held_rel >= 0.50 and held_wins >= 0.60 and train_rel >= -0.25 and runtime_ratio <= 1.50:
        return {
            "status": "PASS_ACCEPTANCE_HEADROOM",
            "best_policy": best_policy,
            "held_relative_percent": held_rel,
            "held_wins_ratio": held_wins,
            "train_relative_percent": train_rel,
            "runtime_ratio_vs_best_static_meta": runtime_ratio,
        }
    return {
        "status": "HALT_ACCEPT_STOP_NO_HEADROOM",
        "best_policy": best_policy,
        "held_relative_percent": held_rel,
        "held_wins_ratio": held_wins,
        "train_relative_percent": train_rel,
        "runtime_ratio_vs_best_static_meta": runtime_ratio,
    }


def load_top_level_eval_bundles(manifest_path: Path) -> list[dict[str, str]]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    for role in ("train", "held_out"):
        for bundle_path in payload.get(role, []) or []:
            rows.append({"bundle_role": role, "bundle_name": Path(str(bundle_path)).name, "bundle_path": str(bundle_path)})
    return rows


def threeshift_probe_bundles() -> list[dict[str, str]]:
    return [dict(item) for item in THREESHIFT_PROBE_BUNDLES]


def unimplemented_policy_rows() -> list[dict[str, str]]:
    return [dict(item) for item in UNIMPLEMENTED_POLICIES]


def write_evidence_ledger(output_dir: Path, evidence_items: list[dict[str, str]] | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    items = EVIDENCE_ITEMS if evidence_items is None else evidence_items
    path = output_dir / "evidence_ledger.md"
    lines = [
        "# Pilot12 Evidence Ledger",
        "",
        "This ledger anchors Pilot12 to prior x86 DR evidence, local literature archives, and local reference-code material.",
        "",
        "| Source | Claim used | ReSETP implication | Phase |",
        "|---|---|---|---|",
    ]
    for item in items:
        lines.append(
            "| {source} | {claim} | {resetp_implication} | {phase} |".format(
                source=item["source"],
                claim=item["claim"],
                resetp_implication=item["resetp_implication"],
                phase=item["phase"],
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_audit(
    *,
    manifest_path: Path | None,
    output_dir: Path,
    eval_budget: int,
    block_size: int,
    seeds: Iterable[int],
    threeshift_probe: bool = False,
    bundle_names: set[str] | None = None,
    policy_labels: list[str] | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    return _run_policy_probe(
        phase="A",
        command_name="audit",
        manifest_path=manifest_path,
        output_dir=output_dir,
        eval_budget=eval_budget,
        block_size=block_size,
        seeds=seeds,
        threeshift_probe=threeshift_probe,
        bundle_names=bundle_names,
        policy_labels=policy_labels,
        max_rows=max_rows,
        gate_fn=classify_acceptance_observability,
    )


def run_static_probe(
    *,
    manifest_path: Path | None,
    output_dir: Path,
    eval_budget: int,
    block_size: int,
    seeds: Iterable[int],
    threeshift_probe: bool = False,
    bundle_names: set[str] | None = None,
    policy_labels: list[str] | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    return _run_policy_probe(
        phase="B",
        command_name="static_probe",
        manifest_path=manifest_path,
        output_dir=output_dir,
        eval_budget=eval_budget,
        block_size=block_size,
        seeds=seeds,
        threeshift_probe=threeshift_probe,
        bundle_names=bundle_names,
        policy_labels=policy_labels,
        max_rows=max_rows,
        gate_fn=classify_static_headroom,
    )


def _run_policy_probe(
    *,
    phase: str,
    command_name: str,
    manifest_path: Path | None,
    output_dir: Path,
    eval_budget: int,
    block_size: int,
    seeds: Iterable[int],
    threeshift_probe: bool,
    bundle_names: set[str] | None,
    policy_labels: list[str] | None,
    max_rows: int | None,
    gate_fn: Any,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = write_evidence_ledger(output_dir)
    bundle_specs = _bundle_specs(manifest_path=manifest_path, threeshift_probe=threeshift_probe)
    if bundle_names:
        bundle_specs = [bundle for bundle in bundle_specs if bundle.bundle_name in bundle_names]
    selected_policies = policy_labels if policy_labels is not None else list(IMPLEMENTED_POLICIES)
    for policy_label in selected_policies:
        if policy_label not in IMPLEMENTED_POLICIES:
            raise ValueError(f"unknown policy_label: {policy_label}")
    if not bundle_specs:
        raise ValueError("no bundles selected")
    rows: list[dict[str, Any]] = []
    partial_path = output_dir / f"pilot12_{command_name}_rows.partial.csv"
    for bundle in bundle_specs:
        for seed in seeds:
            for policy_label in selected_policies:
                if max_rows is not None and len(rows) >= int(max_rows):
                    break
                rows.append(
                    run_single_policy(
                        bundle=bundle,
                        seed=int(seed),
                        policy_label=policy_label,
                        eval_budget=int(eval_budget),
                        block_size=int(block_size),
                    )
                )
                write_rows_csv(partial_path, rows)
            if max_rows is not None and len(rows) >= int(max_rows):
                break
        if max_rows is not None and len(rows) >= int(max_rows):
            break

    row_gate_failures = _row_gate_failures(rows)
    gate = {"status": "HALT_PILOT12_ACCEPTANCE_AUDIT", "row_gate_failures": row_gate_failures} if row_gate_failures else gate_fn(rows)
    policy_summary = summarize_policies(rows)
    write_rows_csv(output_dir / f"pilot12_{command_name}_rows.csv", rows)
    write_rows_csv(output_dir / "pilot12_unimplemented_policy_rows.csv", unimplemented_policy_rows())
    write_rows_csv(output_dir / f"pilot12_{command_name}_policy_summary.csv", policy_summary)
    summary = {
        "phase": phase,
        "command_name": command_name,
        "manifest_path": "" if manifest_path is None else str(manifest_path),
        "bundle_source": "three_shift_probe" if threeshift_probe else "manifest",
        "selected_bundle_names": sorted(bundle_names) if bundle_names else [],
        "selected_policy_labels": list(selected_policies),
        "max_rows": max_rows,
        "eval_budget": int(eval_budget),
        "block_size": int(block_size),
        "row_count": len(rows),
        "evidence_ledger": str(evidence_path),
        "gate": gate,
        "policy_summary": policy_summary,
        "unimplemented_policies": unimplemented_policy_rows(),
    }
    (output_dir / f"pilot12_{command_name}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / f"pilot12_{command_name}_report.md").write_text(
        render_pilot12_report(
            rows=rows,
            gate=gate,
            evidence_items=EVIDENCE_ITEMS,
            policy_summary=policy_summary,
            unimplemented_policies=unimplemented_policy_rows(),
        ),
        encoding="utf-8",
    )
    return summary


def run_single_policy(
    *,
    bundle: BundleSpec,
    seed: int,
    policy_label: str,
    eval_budget: int,
    block_size: int,
) -> dict[str, Any]:
    if policy_label not in IMPLEMENTED_POLICIES:
        raise ValueError(f"unknown policy_label: {policy_label}")
    start = time.perf_counter()
    client = WorkerClient(bundle.bundle_path, seed=int(seed), max_evals=int(eval_budget))
    total_iterations = 0
    accepted = 0
    rejected = 0
    improved_current = 0
    improved_best = 0
    last: dict[str, Any] | None = None
    try:
        last = client.reset()
        while int(last.get("actual_evals", 0)) < int(eval_budget):
            decoded = _decoded_policy_action(policy_label, block_size=block_size)
            response = client.block_step(decoded)
            last = response
            trace = response.get("trace", {}) or {}
            block_iterations = int(float(trace.get("block_iterations", 0)))
            total_iterations += block_iterations
            accepted += int(float(trace.get("block_accepted_count", 0)))
            rejected += int(float(trace.get("block_rejected_count", 0)))
            improved_current += int(float(trace.get("block_improved_current_count", 0)))
            improved_best += int(float(trace.get("block_improved_best_count", 0)))
    finally:
        client.close()

    if last is None:
        raise RuntimeError("worker produced no response")
    elapsed = time.perf_counter() - start
    trace = last.get("trace", {}) or {}
    iterations = max(1, total_iterations)
    accepted_worse = max(0, accepted - improved_current)
    policy = IMPLEMENTED_POLICIES[policy_label]
    return {
        "bundle_role": bundle.bundle_role,
        "bundle_name": bundle.bundle_name or Path(bundle.bundle_path).name,
        "bundle_path": bundle.bundle_path,
        "seed": int(seed),
        "policy_label": policy_label,
        "eval_budget": int(eval_budget),
        "block_size": int(block_size),
        "q_ratio": float(policy["q_ratio"]),
        "threshold_ratio": float(policy["threshold_ratio"]),
        "exploration_ratio": float(policy["exploration_ratio"]),
        "actual_evals": int(last.get("actual_evals", 0)),
        "elapsed_seconds": float(elapsed),
        "worker_python_executable": str(trace.get("worker_python_executable", "")),
        "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
        "violation_count": int(last.get("violation_count", -1)),
        "best_obj": float(last.get("best_obj", math.inf)),
        "current_obj": float(last.get("current_obj", math.inf)),
        "candidate_scores": int(last.get("candidate_scores", 0)),
        "accepted_count": int(accepted),
        "rejected_count": int(rejected),
        "improved_current_count": int(improved_current),
        "improved_best_count": int(improved_best),
        "accepted_worse_count": int(accepted_worse),
        "accepted_rate": float(accepted / iterations),
        "rejected_rate": float(rejected / iterations),
        "accepted_worse_rate": float(accepted_worse / iterations),
        "improved_current_rate": float(improved_current / iterations),
        "improved_best_rate": float(improved_best / iterations),
        "stagnation_ratio": float(float(trace.get("stagnation_steps", 0.0)) / max(float(eval_budget), 1.0)),
        "stop_reason": "budget",
    }


def summarize_policies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["bundle_role"]), str(row["policy_label"])), []).append(row)
    baseline_by_role = {
        role: values
        for (role, policy), values in grouped.items()
        if policy == "best_static_meta"
    }
    summary: list[dict[str, Any]] = []
    for (role, policy), values in sorted(grouped.items()):
        mean_obj = mean(float(row["best_obj"]) for row in values)
        baseline_values = baseline_by_role.get(role, [])
        baseline_mean = mean(float(row["best_obj"]) for row in baseline_values) if baseline_values else math.nan
        relative = None if not baseline_values else paired_relative_percent(policy_cost=mean_obj, baseline_cost=baseline_mean)
        wins_ratio = None
        runtime_ratio = None
        if baseline_values and policy != "best_static_meta":
            wins_ratio = _wins_ratio(values, baseline_values)
            baseline_runtime = mean(float(row["elapsed_seconds"]) for row in baseline_values)
            runtime_ratio = mean(float(row["elapsed_seconds"]) for row in values) / max(baseline_runtime, 1e-12)
        summary.append(
            {
                "bundle_role": role,
                "policy_label": policy,
                "n": len(values),
                "mean_best_obj": mean_obj,
                "mean_elapsed_seconds": mean(float(row["elapsed_seconds"]) for row in values),
                "mean_accepted_rate": mean(float(row["accepted_rate"]) for row in values),
                "mean_accepted_worse_rate": mean(float(row["accepted_worse_rate"]) for row in values),
                "relative_vs_best_static_meta_percent": relative,
                "wins_vs_best_static_meta_ratio": wins_ratio,
                "runtime_ratio_vs_best_static_meta": runtime_ratio,
            }
        )
    return summary


def render_pilot12_report(
    *,
    rows: list[dict[str, Any]],
    gate: dict[str, Any],
    evidence_items: list[dict[str, str]],
    policy_summary: list[dict[str, Any]] | None = None,
    unimplemented_policies: list[dict[str, str]] | None = None,
) -> str:
    summaries = summarize_policies(rows) if policy_summary is None else policy_summary
    lines = [
        "# Pilot12 Acceptance/Stop Report",
        "",
        f"Gate: `{gate.get('status', 'UNKNOWN')}`",
        "",
        "Scope: Phase 0 plus no-training acceptance-threshold diagnostics. No training, no solver semantic changes, and no x86-vs-M1 absolute-number comparison.",
        "",
        "Instance rule: three-shift 50c/75c probes first; 100c is pressure-only after a pass.",
        "",
        "Baseline rule: future DR must beat best static/tuned meta, not default AlphaUCB.",
        "",
        "Stop-control caveat: early stop/restart is not currently expressible through the worker action API and is reported as unimplemented until an opt-in interface is added.",
        "",
        "## Evidence Used",
        "",
    ]
    for item in evidence_items:
        lines.append(f"- `{item['source']}`: {item['resetp_implication']}")
    if summaries:
        lines.extend(["", "## Policy Summary", ""])
        for item in summaries:
            rel = item["relative_vs_best_static_meta_percent"]
            rel_text = "n/a" if rel is None else f"{float(rel):.4f}%"
            wins = item["wins_vs_best_static_meta_ratio"]
            wins_text = "n/a" if wins is None else f"{float(wins):.3f}"
            lines.append(
                "- {role} / {policy}: mean_obj={obj:.6f}, accepted_rate={acc:.4f}, accepted_worse_rate={worse:.4f}, rel_vs_best_static={rel}, wins={wins}".format(
                    role=item["bundle_role"],
                    policy=item["policy_label"],
                    obj=float(item["mean_best_obj"]),
                    acc=float(item["mean_accepted_rate"]),
                    worse=float(item["mean_accepted_worse_rate"]),
                    rel=rel_text,
                    wins=wins_text,
                )
            )
    if unimplemented_policies:
        lines.extend(["", "## Unimplemented Static Policies", ""])
        for item in unimplemented_policies:
            lines.append(f"- `{item['policy_label']}`: `{item['status']}` - {item['reason']}")
    lines.extend(["", "## Gate Detail", "", "```json", json.dumps(gate, ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines) + "\n"


def write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _bundle_specs(*, manifest_path: Path | None, threeshift_probe: bool) -> list[BundleSpec]:
    if threeshift_probe:
        return [BundleSpec(**row) for row in threeshift_probe_bundles()]
    if manifest_path is None:
        raise ValueError("--manifest is required unless --threeshift-probe is set")
    return [BundleSpec(**row) for row in load_top_level_eval_bundles(manifest_path)]


def _decoded_policy_action(policy_label: str, *, block_size: int) -> BlockDecodedAction:
    policy = IMPLEMENTED_POLICIES[policy_label]
    raw = _raw_for_policy(policy)
    return BlockDecodedAction(
        destroy_id="alpha_ucb",
        repair_id="alpha_ucb",
        q_ratio=float(policy["q_ratio"]),
        threshold_ratio=float(policy["threshold_ratio"]),
        exploration_ratio=float(policy["exploration_ratio"]),
        block_size=int(block_size),
        raw=raw,
        control_mode="block_ppo",
    )


def _raw_for_policy(policy: dict[str, float]) -> tuple[int, int, int, int, int]:
    q_values = [0.10, 0.16, 0.23, 0.30, 0.40]
    t_values = [0.0, 0.0025, 0.0075, 0.02]
    e_values = [0.0, 0.05, 0.15, 0.30]
    return (
        6,
        3,
        _nearest_index(q_values, float(policy["q_ratio"])),
        _nearest_index(t_values, float(policy["threshold_ratio"])),
        _nearest_index(e_values, float(policy["exploration_ratio"])),
    )


def _nearest_index(values: list[float], target: float) -> int:
    return min(range(len(values)), key=lambda idx: abs(float(values[idx]) - target))


def _row_gate_failures(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for idx, row in enumerate(rows):
        ok, reason = acceptance_row_gate(row)
        if not ok:
            failures.append(
                {
                    "row_index": str(idx),
                    "bundle_name": str(row.get("bundle_name", "")),
                    "policy_label": str(row.get("policy_label", "")),
                    "reason": reason,
                }
            )
    return failures


def _held_probe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    held = [row for row in rows if str(row.get("bundle_role", "")) in {"held_probe", "held_out"}]
    return held if held else rows


def _objectives_by_policy(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    by_policy: dict[str, list[float]] = {}
    for row in rows:
        by_policy.setdefault(str(row.get("policy_label", "")), []).append(float(row.get("best_obj", math.inf)))
    return by_policy


def _best_relative_policy(by_policy: dict[str, list[float]], baseline_mean: float) -> tuple[str, float]:
    best_policy = ""
    best_relative = -math.inf
    for policy, values in by_policy.items():
        if policy == "best_static_meta" or not values:
            continue
        rel = paired_relative_percent(policy_cost=mean(values), baseline_cost=baseline_mean)
        if rel > best_relative:
            best_relative = rel
            best_policy = policy
    return best_policy, best_relative


def _wins_ratio(values: list[dict[str, Any]], baseline_values: list[dict[str, Any]]) -> float:
    baseline_by_key = {
        (str(row.get("bundle_name", "")), int(row.get("seed", 0))): float(row["best_obj"])
        for row in baseline_values
    }
    wins = 0
    total = 0
    for row in values:
        key = (str(row.get("bundle_name", "")), int(row.get("seed", 0)))
        if key not in baseline_by_key:
            continue
        total += 1
        if float(row["best_obj"]) < baseline_by_key[key]:
            wins += 1
    return float(wins / total) if total else 0.0


def _parse_seeds(text: str) -> list[int]:
    seeds = [int(part.strip()) for part in str(text).split(",") if part.strip()]
    if not seeds:
        raise ValueError("at least one seed is required")
    return seeds


def _parse_optional_list(text: str) -> list[str] | None:
    values = [part.strip() for part in str(text or "").split(",") if part.strip()]
    return values or None


def _parse_optional_set(text: str) -> set[str] | None:
    values = set(_parse_optional_list(text) or [])
    return values or None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pilot12 acceptance/stop no-training audit tools.")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Run Phase A no-training observability audit.")
    audit.add_argument("--manifest", type=Path)
    audit.add_argument("--threeshift-probe", action="store_true")
    audit.add_argument("--output-dir", type=Path, required=True)
    audit.add_argument("--eval-budget", type=int, default=600)
    audit.add_argument("--block-size", type=int, default=32)
    audit.add_argument("--seeds", type=str, default="1,2,3")
    audit.add_argument("--jobs", type=int, default=1)
    audit.add_argument("--bundle-names", type=str, default="")
    audit.add_argument("--policies", type=str, default="")
    audit.add_argument("--max-rows", type=int)

    static_probe = sub.add_parser("static-probe", help="Run Phase B static acceptance-threshold headroom probe.")
    static_probe.add_argument("--manifest", type=Path)
    static_probe.add_argument("--threeshift-probe", action="store_true")
    static_probe.add_argument("--output-dir", type=Path, required=True)
    static_probe.add_argument("--eval-budget", type=int, default=1500)
    static_probe.add_argument("--block-size", type=int, default=32)
    static_probe.add_argument("--seeds", type=str, default="1,2,3,4,5")
    static_probe.add_argument("--jobs", type=int, default=1)
    static_probe.add_argument("--bundle-names", type=str, default="")
    static_probe.add_argument("--policies", type=str, default="")
    static_probe.add_argument("--max-rows", type=int)

    ledger = sub.add_parser("evidence-ledger", help="Write the Phase 0 evidence ledger only.")
    ledger.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "evidence-ledger":
        write_evidence_ledger(args.output_dir)
        return 0
    if args.command in {"audit", "static-probe"}:
        if int(args.jobs) != 1:
            raise SystemExit("Pilot12 no-training probes only support --jobs 1 to keep worker evidence simple.")
        runner = run_audit if args.command == "audit" else run_static_probe
        summary = runner(
            manifest_path=args.manifest,
            output_dir=args.output_dir,
            eval_budget=int(args.eval_budget),
            block_size=int(args.block_size),
            seeds=_parse_seeds(args.seeds),
            threeshift_probe=bool(args.threeshift_probe),
            bundle_names=_parse_optional_set(args.bundle_names),
            policy_labels=_parse_optional_list(args.policies),
            max_rows=args.max_rows,
        )
        print(json.dumps(summary["gate"], ensure_ascii=False, indent=2))
        return 0
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
