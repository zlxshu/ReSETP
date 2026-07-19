"""Resumable formal experiment runner for E0-E7.

v2026-06-12: Z2-Z4 implementation scaffold. Each run is addressed by
``{experiment, instance, algorithm, seed, variant}``, completed runs are
recorded in a manifest, and all algorithm scores go through the shared
``evaluate/check/repair`` stack.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from dataclasses import replace as dataclass_replace
import hashlib
import json
import math
from pathlib import Path
import shutil
from statistics import mean
import time
from typing import Any, Callable

from ..check import check_solution
from ..cost import evaluate
from ..prices import DEFAULT_PRICES, PriceParameters
from ..profit import calculate_depot_profits
from ..solution import (
    CrossSiteService,
    Route,
    Solution,
    charging_action_from_dict,
)
from .alns_wouda import SearchPolicy, run_alns_wouda
from .alns_crush import ALNS_DEFAULT_INSTANCE_ORDER, INSTANCE_DIRS
from .bundle import load_search_bundle
from .candidates import PRIMARY_ALGORITHM, Z1_CANDIDATES, run_candidate
from .candidates import make_shared_initial_solution
from .dynamic import (
    DynamicEvent,
    RollingParameters,
    _active_customer_ids_after_events,
    _build_trigger_batches,
    _read_dynamic_events,
    run_rolling_reoptimization,
    write_t9_dynamic_csv,
)
from .e5_ablation import run_e5_charging_ablation
from .evaluation import EvaluationContext, fairness_context_for_solution
from .fairness import build_concatenated_independent_seed, infer_customer_home_depots, run_equal_budget_fairness_comparison, run_independent_profit_baselines
from .gates import b2_feasible_domain_gate
from .instance_registry import assert_formal_benchmark_ready
from .root_cause import WANG_ROOT_CAUSE_ALGORITHMS, run_alns_root_cause_diagnostics


RunCallable = Callable[[], dict[str, Any]]
FORMAL_MAIN_INSTANCE = ALNS_DEFAULT_INSTANCE_ORDER[-1]


def _main_bundle_dir(repo_root: str | Path, instance_name: str = FORMAL_MAIN_INSTANCE) -> Path:
    assert_formal_benchmark_ready(repo_root)
    return Path(repo_root) / INSTANCE_DIRS[instance_name]


@dataclass(frozen=True)
class RunKey:
    experiment: str
    instance: str
    algorithm: str
    seed: int
    variant: str

    def as_id(self) -> str:
        return "|".join([self.experiment, self.instance, self.algorithm, str(self.seed), self.variant])


class ResumeLedger:
    """JSON manifest for completed/failed formal runs."""

    def __init__(self, manifest_path: str | Path):
        self.path = Path(manifest_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records = self._load()

    def completed(self, key: RunKey) -> bool:
        row = self._records.get(key.as_id())
        return bool(row and row.get("status") == "completed")

    def run(self, key: RunKey, func: RunCallable, *, retry: int = 1) -> dict[str, Any]:
        if self.completed(key):
            row = dict(self._records[key.as_id()])
            row["skipped"] = True
            return row
        attempts = 0
        last_error = ""
        while attempts <= retry:
            attempts += 1
            started = time.perf_counter()
            try:
                result = func()
                row = {
                    "key": asdict(key),
                    "key_id": key.as_id(),
                    "status": "completed",
                    "attempts": attempts,
                    "elapsed_seconds": time.perf_counter() - started,
                    "result": result,
                    "skipped": False,
                }
                self._records[key.as_id()] = row
                self._save()
                return row
            except Exception as exc:  # pragma: no cover - failures are persisted for long batch diagnosis.
                last_error = f"{type(exc).__name__}: {exc}"
        row = {
            "key": asdict(key),
            "key_id": key.as_id(),
            "status": "failed",
            "attempts": attempts,
            "failure_reason": last_error,
            "skipped": False,
        }
        self._records[key.as_id()] = row
        self._save()
        return row

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return {row["key_id"]: row for row in payload.get("runs", [])}

    def _save(self) -> None:
        payload = {
            "schema_version": "setp-formal-runner-ledger.v1",
            "build_note": "v2026-06-12: Z2-Z4 resumable runner manifest.",
            "runs": list(self._records.values()),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def run_e0_gate(repo_root: str | Path, output_csv_path: str | Path) -> dict[str, Any]:
    """Write T1 instance-gate rows for the active formal L-main set."""

    root = Path(repo_root)
    assert_formal_benchmark_ready(repo_root)
    instances = [(name, root / INSTANCE_DIRS[name]) for name in ALNS_DEFAULT_INSTANCE_ORDER]
    rows = []
    for instance_name, bundle_dir in instances:
        bundle = load_search_bundle(bundle_dir)
        gate = b2_feasible_domain_gate(bundle_dir)
        manifest = _load_optional_json(bundle_dir / "scenario_manifest.json")
        rows.append(
            {
                "instance": instance_name,
                "customers": _node_count(bundle.instance, "c"),
                "depots": _node_count(bundle.instance, "d"),
                "stations": _node_count(bundle.instance, "f"),
                "total_demand_kg": round(sum(float(node.demand) for node in bundle.instance.nodes if node.node_type.lower() == "c"), 3),
                "window_width_h": _window_width_summary(bundle.instance),
                "deleted_customers": manifest.get("deleted_customers", manifest.get("deleted_customer_count", 0)),
                "isolated": manifest.get("isolated_customer_share", manifest.get("validation", {}).get("isolated_customer_share", "")),
                "gamma_slots": len(bundle.carbon_profile),
                "anchor_day": "2025-11-13",
                "bundle_hash": _bundle_hash(bundle_dir),
                "b2_safe": gate.safe,
            }
        )
    _write_csv(output_csv_path, rows)
    expected_rows = len(ALNS_DEFAULT_INSTANCE_ORDER)
    return {"gate": "PASS" if len(rows) == expected_rows and all(row["gamma_slots"] == 48 and row["b2_safe"] for row in rows) else "HALT_E0", "rows": rows}


def compute_default_carbon_quota(
    bundle_dir: str | Path,
    output_json_path: str | Path,
    *,
    seed: int = 1,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
    force: bool = False,
) -> dict[str, Any]:
    """Run/cache the no-quota baseline and return CE=0.8*E_total."""

    output = Path(output_json_path)
    if output.exists() and not force:
        cached = json.loads(output.read_text(encoding="utf-8"))
        cached["cache_hit"] = True
        return cached
    bundle = load_search_bundle(bundle_dir)
    started = time.perf_counter()
    result = run_alns_wouda(
        bundle.bundle_dir,
        iterations=None,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        policy=SearchPolicy(require_charging_signal=False),
        carbon_quota_kg=math.inf,
    )
    elapsed_seconds = time.perf_counter() - started
    metrics = evaluate(result.best_solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES, carbon_quota_kg=math.inf)
    payload = {
        "schema_version": "setp-carbon-quota-baseline.v1",
        "build_note": "v2026-06-12: Z0a no-quota CE baseline; default CE is 80 percent of E_total.",
        "bundle_dir": str(Path(bundle_dir)),
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "evaluations": int(result.evaluations),
        "actual_evals": int(result.evaluations),
        "elapsed_seconds": elapsed_seconds,
        "feasible": bool(result.feasible and not check_solution(result.best_solution, bundle.instance, DEFAULT_PRICES)),
        "baseline_emissions_kg": float(metrics["E_total"]),
        "default_ce_kg": float(metrics["E_total"]) * 0.8,
        "metrics": metrics,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def run_e2_algorithm_comparison(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int] | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
    algorithms: list[str] | None = None,
    exclude_algorithms: list[str] | None = None,
) -> dict[str, Any]:
    """Run E2 for all Z1-available algorithms and write T3/F2 sources."""

    root = Path(repo_root)
    assert_formal_benchmark_ready(repo_root)
    out = Path(output_dir)
    ledger = ResumeLedger(out / "formal_runner_manifest.json")
    seeds = seeds or list(range(1, 11))
    instances = {name: root / INSTANCE_DIRS[name] for name in ALNS_DEFAULT_INSTANCE_ORDER}
    algorithms = _resolve_e2_algorithms(algorithms, exclude_algorithms)
    initial_solutions = {
        instance_name: make_shared_initial_solution(load_search_bundle(bundle_dir))
        for instance_name, bundle_dir in instances.items()
    }
    run_rows: list[dict[str, Any]] = []
    for instance_name, bundle_dir in instances.items():
        for algorithm in algorithms:
            for seed in seeds:
                key = RunKey("E2", instance_name, algorithm, seed, "formal")
                row = ledger.run(
                    key,
                    lambda algorithm=algorithm, bundle_dir=bundle_dir, seed=seed: _run_algorithm_once(
                        algorithm,
                        bundle_dir,
                        seed=seed,
                        eval_budget=eval_budget,
                        max_runtime_seconds=max_runtime_seconds,
                        initial_solution=initial_solutions[instance_name],
                    ),
                )
                run_rows.append(_flatten_run_row(key, row))
    finals = _e2_final_rows(run_rows)
    _write_csv(out / "tables" / "t3_algorithm_comparison.csv", finals)
    _write_csv(out / "figures" / "f2_algorithm_finals.csv", _f2_final_rows(run_rows))
    _write_csv(out / "figures" / "f2_algorithm_curves.csv", _f2_curve_rows(run_rows))
    _write_e2_solution_outputs(root, out, run_rows)
    return {"run_count": len(run_rows), "finals": finals, "manifest": str(ledger.path)}


def _resolve_e2_algorithms(algorithms: list[str] | None, exclude_algorithms: list[str] | None = None) -> list[str]:
    selected = [item.strip() for item in (algorithms or [PRIMARY_ALGORITHM, *Z1_CANDIDATES]) if item.strip()]
    excluded = {item.strip() for item in (exclude_algorithms or []) if item.strip()}
    resolved = [algorithm for algorithm in selected if algorithm not in excluded]
    if not resolved:
        raise ValueError("E2 algorithm selection is empty")
    return resolved


def run_alns_fix_validation(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int] | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
) -> dict[str, Any]:
    """Run a fair-budget E2 validation into an isolated output directory."""

    root = Path(repo_root)
    out = Path(output_dir)
    result = run_e2_algorithm_comparison(root, out, seeds=seeds, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds)
    run_rows = _load_run_rows_from_manifest(out / "formal_runner_manifest.json")
    before_rows = _load_prior_alns_wouda_rows(root)
    before_after = _alns_wouda_before_after_rows(run_rows, before_rows)
    _write_csv(out / "tables" / "alns_wouda_before_after.csv", before_after)
    _write_csv(out / "tables" / "t3_fair_budget_algorithm_comparison.csv", result["finals"])
    shutil.copyfile(out / "figures" / "f2_algorithm_finals.csv", out / "figures" / "f2_fair_budget_finals.csv")
    shutil.copyfile(out / "figures" / "f2_algorithm_curves.csv", out / "figures" / "f2_fair_budget_curves.csv")
    gate = _alns_fix_validation_gate(result["finals"])
    (out / "README.md").write_text(_alns_fix_validation_readme(eval_budget, max_runtime_seconds, gate, result), encoding="utf-8")
    return {
        **result,
        "gate": gate,
        "before_after": str(out / "tables" / "alns_wouda_before_after.csv"),
        "fair_t3": str(out / "tables" / "t3_fair_budget_algorithm_comparison.csv"),
    }


def run_alns_strong_validation(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    target_algorithm: str,
    seeds: list[int] | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
) -> dict[str, Any]:
    out = Path(output_dir)
    algorithms = [target_algorithm, "DR-ALNS", "scikit-opt-SA"]
    result = run_alns_root_cause_diagnostics(
        repo_root,
        out,
        seeds=seeds or [1, 2, 3],
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        algorithms=algorithms,
    )
    gate = _alns_strong_gate(out, target_algorithm)
    manifest_path = out / "strong_validation_manifest.json"
    manifest = {
        "schema_version": "setp-alns-strong-validation.v1",
        "target_algorithm": target_algorithm,
        "gate": gate,
        "root_cause_manifest": result.get("manifest"),
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "README.md").write_text(_alns_strong_readme(target_algorithm, eval_budget, max_runtime_seconds, gate), encoding="utf-8")
    return {**result, "gate": gate, "strong_manifest": str(manifest_path)}


def run_alns_wang_root_cause(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int] | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
) -> dict[str, Any]:
    result = run_alns_root_cause_diagnostics(
        repo_root,
        output_dir,
        seeds=seeds or [1],
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        algorithms=WANG_ROOT_CAUSE_ALGORITHMS,
    )
    gate = _wang_root_cause_gate(Path(output_dir))
    manifest_path = Path(output_dir) / "wang_root_cause_manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": "setp-wang-root-cause.v1", "gate": gate, "root_cause_manifest": result.get("manifest")}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {**result, "gate": gate, "wang_manifest": str(manifest_path)}


def run_alns_wang_strong_validation(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    root_cause_dir: str | Path | None = None,
    seeds: list[int] | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
) -> dict[str, Any]:
    source = Path(root_cause_dir) if root_cause_dir else Path(repo_root) / "solver" / "reports" / "alns_wang_root_cause"
    root_gate = _wang_root_cause_gate(source) if source.exists() else "HALT_WANG_ROOT_CAUSE_MISSING"
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if root_gate != "PASS_WANG_SAME_ROOT_CAUSE":
        manifest_path = out / "strong_validation_manifest.json"
        manifest_path.write_text(
            json.dumps({"schema_version": "setp-wang-strong-validation.v1", "gate": "HALT_WANG_DIFFERENT_ROOT_CAUSE_NEEDS_PLAN", "root_cause_gate": root_gate}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"gate": "HALT_WANG_DIFFERENT_ROOT_CAUSE_NEEDS_PLAN", "strong_manifest": str(manifest_path)}
    return run_alns_strong_validation(
        repo_root,
        out,
        target_algorithm="ALNS@wangqianlongucas-strong",
        seeds=seeds or [1, 2, 3],
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
    )


def run_e1_main_and_counterfactuals(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seed: int = 1,
    seeds: list[int] | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
) -> dict[str, Any]:
    """Run E1 full model plus CV/EV/mixed fleet counterfactuals."""

    root = Path(repo_root)
    out = Path(output_dir)
    run_seeds = seeds or [seed]
    bundle_dir = _main_bundle_dir(root)
    quota = compute_default_carbon_quota(
        bundle_dir,
        out / "carbon_quota_L-main.json",
        seed=run_seeds[0],
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
    )["default_ce_kg"]
    ledger = ResumeLedger(out / "formal_runner_manifest.json")
    variants = {
        "mixed": SearchPolicy(require_charging_signal=False),
        "cv_only": SearchPolicy(require_charging_signal=False, max_ev=0),
        "ev_only": SearchPolicy(require_charging_signal=False, max_cv=0),
    }
    rows = []
    for variant, policy in variants.items():
        for run_seed in run_seeds:
            key = RunKey("E1", FORMAL_MAIN_INSTANCE, PRIMARY_ALGORITHM, run_seed, variant)
            row = ledger.run(
                key,
                lambda policy=policy, run_seed=run_seed: _run_alns_metrics(
                    bundle_dir,
                    seed=run_seed,
                    eval_budget=eval_budget,
                    max_runtime_seconds=max_runtime_seconds,
                    policy=policy,
                    carbon_quota_kg=float(quota),
                ),
            )
            rows.append(_flatten_run_row(key, row))
    table_rows = _e1_table_rows(rows)
    _write_csv(out / "tables" / "t4_solution_decomposition.csv", table_rows)
    _write_csv(out / "tables" / "t4_solution_decomposition_seed_detail.csv", _e1_seed_detail_rows(rows))
    return {"run_count": len(rows), "rows": table_rows, "manifest": str(ledger.path)}


def run_e3_ablation(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int] | None = None,
    variants_filter: list[str] | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
) -> dict[str, Any]:
    """Run E3 M0-M5 cumulative ablations."""

    root = Path(repo_root)
    out = Path(output_dir)
    bundle_dir = _main_bundle_dir(root)
    quota = compute_default_carbon_quota(
        bundle_dir,
        out / "carbon_quota_L-main.json",
        seed=1,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
    )["default_ce_kg"]
    seeds = seeds or list(range(1, 11))
    variants = _e3_variant_specs(float(quota))
    requested = {item.upper() for item in variants_filter or []}
    if requested:
        variants = [spec for spec in variants if str(spec["code"]).upper() in requested]
    derived_root = out / "e3_derived_bundles"
    derived_bundles = {
        mode: _write_e3_derived_bundle(bundle_dir, derived_root / mode, mode)
        for mode in sorted({str(spec["carbon_profile_mode"]) for spec in variants})
    }
    ledger = ResumeLedger(out / "formal_runner_manifest.json")
    run_rows = []
    for spec in variants:
        for seed in seeds:
            code = str(spec["code"])
            key = RunKey("E3", FORMAL_MAIN_INSTANCE, PRIMARY_ALGORITHM, seed, code)
            row = ledger.run(
                key,
                lambda spec=spec, seed=seed: _run_e3_variant(
                    derived_bundles[str(spec["carbon_profile_mode"])],
                    out,
                    spec,
                    seed=seed,
                    eval_budget=eval_budget,
                    max_runtime_seconds=max_runtime_seconds,
                ),
            )
            flat = _flatten_run_row(key, row)
            flat["label"] = spec["label"]
            run_rows.append(flat)
    if requested and "M0" not in requested:
        run_rows.extend(_retained_e3_m0_rows(root))
    table_rows = _e3_table_rows(run_rows)
    _write_csv(out / "tables" / "t5_ablation.csv", table_rows)
    _write_csv(out / "tables" / "t5_ablation_notes.csv", _e3_note_rows(variants))
    return {"run_count": len(run_rows), "rows": table_rows, "manifest": str(ledger.path)}


def run_e4_carbon_sensitivity(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seed: int = 1,
    seeds: list[int] | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
    carbon_price_factors: list[float] | None = None,
    quota_factors: list[float] | None = None,
) -> dict[str, Any]:
    """Run E4 carbon-price by quota grid with fairness off."""

    root = Path(repo_root)
    out = Path(output_dir)
    bundle_dir = _main_bundle_dir(root)
    baseline = compute_default_carbon_quota(
        bundle_dir,
        out / "carbon_quota_L-main.json",
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
    )
    base_emissions = float(baseline["baseline_emissions_kg"])
    carbon_prices = carbon_price_factors if carbon_price_factors else [0.5, 1.0, 2.0, 4.0]
    quotas = quota_factors if quota_factors else [0.5, 0.8, 1.0, 1.2]
    run_seeds = seeds or list(range(1, 6))
    ledger = ResumeLedger(out / "formal_runner_manifest.json")
    rows = []
    for price_factor in carbon_prices:
        for quota_factor in quotas:
            variant = f"p={price_factor:g};ce={quota_factor:g}"
            for run_seed in run_seeds:
                key = RunKey("E4", FORMAL_MAIN_INSTANCE, PRIMARY_ALGORITHM, run_seed, variant)
                row = ledger.run(
                    key,
                    lambda price_factor=price_factor, quota_factor=quota_factor, run_seed=run_seed: _run_e4_once(
                        bundle_dir,
                        seed=run_seed,
                        eval_budget=eval_budget,
                        max_runtime_seconds=max_runtime_seconds,
                        base_emissions=base_emissions,
                        price_factor=price_factor,
                        quota_factor=quota_factor,
                    ),
                )
                rows.append(_flatten_run_row(key, row))
    table_rows = _e4_table_rows(rows)
    _write_csv(out / "tables" / "t7_carbon_sensitivity.csv", table_rows)
    _write_csv(out / "tables" / "t7_carbon_sensitivity_seed_detail.csv", _e4_seed_detail_rows(rows))
    _write_csv(out / "tables" / "e4_carbon_price_diagnostics.csv", _e4_diagnostic_rows(rows))
    _write_csv(out / "figures" / "f5_carbon_heatmap.csv", table_rows)
    return {"run_count": len(rows), "rows": table_rows, "diagnostics": _e4_diagnostic_rows(rows), "manifest": str(ledger.path)}


def run_e6_fairness_scan(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int] | None = None,
    thetas: list[float] | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
) -> dict[str, Any]:
    """Run Z2/E6 theta scan with concatenated seed and equal budget."""

    root = Path(repo_root)
    out = Path(output_dir)
    bundle_dir = _main_bundle_dir(root)
    pi_path = root / "solver" / "reports" / "pi_d0_L-main.json"
    seed_path = out / "x0_L-main_independent_concat_seed_formal.json"
    if not seed_path.exists():
        build_concatenated_independent_seed(bundle_dir, pi_path, output_json_path=seed_path)
    ledger = ResumeLedger(out / "formal_runner_manifest.json")
    seeds = seeds or list(range(1, 11))
    thetas = thetas or [0.90, 0.95, 1.00, 1.05, 1.10]
    run_rows = []
    for theta in thetas:
        for seed in seeds:
            key = RunKey("E6", FORMAL_MAIN_INSTANCE, PRIMARY_ALGORITHM, seed, f"theta={theta:.2f}")
            row = ledger.run(
                key,
                lambda theta=theta, seed=seed: run_equal_budget_fairness_comparison(
                    bundle_dir,
                    pi_path,
                    seed_path,
                    eval_budget=eval_budget,
                    max_runtime_seconds=max_runtime_seconds,
                    seed=seed,
                    prices=_prices_with_theta(theta),
                ),
            )
            run_rows.append(_flatten_run_row(key, row))
    table_rows = _e6_table_rows(run_rows)
    _write_csv(out / "tables" / "t8_fairness_threshold.csv", table_rows)
    _write_csv(out / "figures" / "f6_fairness_frontier.csv", _e6_figure_rows(table_rows))
    return {"run_count": len(run_rows), "rows": table_rows, "manifest": str(ledger.path)}


def run_e5_formal(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    source_report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Replay E5 on the E1/main-solution report and write T6/F3/F4 sources."""

    root = Path(repo_root)
    out = Path(output_dir)
    # v2026-06-12: W2 formal replay must not depend on a prior stage having
    # already created the output root.
    (out / "tables").mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    bundle_dir = _main_bundle_dir(root)
    default_source = root / "solver" / "reports" / "t0_L-main_20251113_seed1_forward_repair_real_budget.json"
    source = Path(source_report_path) if source_report_path else default_source
    if not source.exists():
        raise FileNotFoundError(
            f"E5 replay source report missing: {source}. Run E1 for L-main first and set source_report_path explicitly."
        )
    report = run_e5_charging_ablation(
        bundle_dir,
        source,
        output_json_path=out / "e5_formal_charging_ablation.json",
        output_csv_path=out / "figures" / "f4_48slot_charging.csv",
        halt_on_zero_delta=True,
    )
    table_rows = []
    cv_only = _cv_only_t6_case_from_t4(out / "tables" / "t4_solution_decomposition.csv")
    if cv_only is not None:
        table_rows.append(cv_only)
    table_rows.extend(
        [
        _t6_case("混合择时", report["carbon_aware"]),
        _t6_case("混合即充", report["naive_return_charge"]),
        ]
    )
    _write_csv(out / "tables" / "t6_two_layer_carbon.csv", table_rows)
    _write_csv(out / "figures" / "f3_two_layer_carbon.csv", _f3_from_e5(report))
    return report


def run_e7_dynamic(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seed: int = 1,
    seeds: list[int] | None = None,
    eval_budget: int = 16_000,
    max_runtime_seconds: float = 300.0,
) -> dict[str, Any]:
    root = Path(repo_root)
    out = Path(output_dir)
    bundle_dir = _main_bundle_dir(root)
    ledger = ResumeLedger(out / "formal_runner_manifest.json")
    run_seeds = seeds or [seed]
    reports: dict[int, dict[str, Any]] = {}
    for run_seed in run_seeds:
        key = RunKey("E7", FORMAL_MAIN_INSTANCE, PRIMARY_ALGORITHM, run_seed, "dynamic")
        output_json = out / ("e7_dynamic_rolling.json" if len(run_seeds) == 1 else f"e7_dynamic_rolling_seed{run_seed}.json")
        row = ledger.run(
            key,
            lambda run_seed=run_seed, output_json=output_json: run_rolling_reoptimization(
                bundle_dir,
                output_json_path=output_json,
                seed=run_seed,
                eval_budget=eval_budget,
                max_runtime_seconds=max_runtime_seconds,
                params=RollingParameters(),
            ),
            retry=1,
        )
        report = dict(row.get("result", {}))
        report["manifest"] = str(ledger.path)
        report["skipped"] = bool(row.get("skipped", False))
        report["status"] = row.get("status")
        if row.get("status") != "completed":
            report.setdefault("gate", "HALT_E7")
            report.setdefault("failure_reason", row.get("failure_reason", "E7 dynamic run failed"))
        reports[run_seed] = report
    _write_e7_t9_outputs(out, reports)
    if len(reports) == 1:
        return next(iter(reports.values()))
    return {
        "schema_version": "setp-e7-multi-stream.v1",
        "manifest": str(ledger.path),
        "run_count": len(reports),
        "reports_by_seed": reports,
        "all_assertions_pass": all(report.get("all_assertions_pass", False) for report in reports.values()),
        "gate": next((report.get("gate") for report in reports.values() if str(report.get("gate", "")).startswith("HALT")), "PASS"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run resumable SETP formal experiments.")
    parser.add_argument("stage", choices=["E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "ALNS_FIX", "ALNS_ROOT_CAUSE", "ALNS_WOUDA_STRONG", "ALNS_WANG_ROOT_CAUSE", "ALNS_WANG_STRONG"])
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[4]))
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[4] / "solver" / "reports" / "formal"))
    parser.add_argument("--eval-budget", type=int, default=16_000)
    parser.add_argument("--max-runtime-seconds", type=float, default=300.0)
    parser.add_argument("--seeds", default="1,2,3,4,5,6,7,8,9,10")
    parser.add_argument("--variants", default="")
    parser.add_argument("--carbon-price-factors", default="")
    parser.add_argument("--quota-factors", default="")
    parser.add_argument("--thetas", default="")
    parser.add_argument("--algorithms", default="")
    parser.add_argument("--exclude-algorithms", default="")
    args = parser.parse_args(argv)
    seeds = [int(item) for item in args.seeds.split(",") if item.strip()]
    variants = [item.strip() for item in args.variants.split(",") if item.strip()]
    cpf = _parse_float_list(args.carbon_price_factors)
    qf = _parse_float_list(args.quota_factors)
    thetas = _parse_float_list(args.thetas)
    algorithms = _parse_string_list(args.algorithms)
    exclude_algorithms = _parse_string_list(args.exclude_algorithms)
    out = Path(args.output_dir)
    if args.stage == "E0":
        result = run_e0_gate(args.repo_root, out / "tables" / "t1_instances.csv")
    elif args.stage == "ALNS_FIX":
        result = run_alns_fix_validation(args.repo_root, out, seeds=seeds, eval_budget=args.eval_budget, max_runtime_seconds=args.max_runtime_seconds)
    elif args.stage == "ALNS_ROOT_CAUSE":
        result = run_alns_root_cause_diagnostics(args.repo_root, out, seeds=seeds, eval_budget=args.eval_budget, max_runtime_seconds=args.max_runtime_seconds)
    elif args.stage == "ALNS_WOUDA_STRONG":
        result = run_alns_strong_validation(args.repo_root, out, target_algorithm=PRIMARY_ALGORITHM, seeds=seeds, eval_budget=args.eval_budget, max_runtime_seconds=args.max_runtime_seconds)
    elif args.stage == "ALNS_WANG_ROOT_CAUSE":
        result = run_alns_wang_root_cause(args.repo_root, out, seeds=seeds, eval_budget=args.eval_budget, max_runtime_seconds=args.max_runtime_seconds)
    elif args.stage == "ALNS_WANG_STRONG":
        result = run_alns_wang_strong_validation(args.repo_root, out, seeds=seeds, eval_budget=args.eval_budget, max_runtime_seconds=args.max_runtime_seconds)
    elif args.stage == "E1":
        result = run_e1_main_and_counterfactuals(args.repo_root, out, seed=seeds[0], seeds=seeds, eval_budget=args.eval_budget, max_runtime_seconds=args.max_runtime_seconds)
    elif args.stage == "E2":
        result = run_e2_algorithm_comparison(
            args.repo_root,
            out,
            seeds=seeds,
            eval_budget=args.eval_budget,
            max_runtime_seconds=args.max_runtime_seconds,
            algorithms=algorithms or None,
            exclude_algorithms=exclude_algorithms or None,
        )
    elif args.stage == "E3":
        result = run_e3_ablation(args.repo_root, out, seeds=seeds, variants_filter=variants or None, eval_budget=args.eval_budget, max_runtime_seconds=args.max_runtime_seconds)
    elif args.stage == "E4":
        result = run_e4_carbon_sensitivity(
            args.repo_root,
            out,
            seed=seeds[0],
            seeds=seeds,
            eval_budget=args.eval_budget,
            max_runtime_seconds=args.max_runtime_seconds,
            carbon_price_factors=cpf,
            quota_factors=qf,
        )
    elif args.stage == "E5":
        result = run_e5_formal(args.repo_root, out)
    elif args.stage == "E6":
        result = run_e6_fairness_scan(args.repo_root, out, seeds=seeds, thetas=thetas, eval_budget=args.eval_budget, max_runtime_seconds=args.max_runtime_seconds)
    else:
        result = run_e7_dynamic(args.repo_root, out, seed=seeds[0], seeds=seeds, eval_budget=args.eval_budget, max_runtime_seconds=args.max_runtime_seconds)
    gate = "PASS" if not str(result.get("gate", "")).startswith("HALT") and result.get("all_assertions_pass", True) else result.get("gate", "HALT")
    print(f"GATE {args.stage} {gate} {json.dumps(_compact_summary(result), ensure_ascii=False)}")
    return 0 if gate == "PASS" else 2


def _parse_float_list(text: str) -> list[float] | None:
    values = [float(item) for item in text.split(",") if item.strip()]
    return values or None


def _parse_string_list(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _run_algorithm_once(
    algorithm: str,
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    initial_solution: Solution | None = None,
) -> dict[str, Any]:
    bundle = load_search_bundle(bundle_dir)
    result = run_candidate(
        algorithm,
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        initial_solution=initial_solution,
    )
    best_solution = result.best_solution
    metrics = (
        evaluate(best_solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)
        if best_solution is not None
        else {}
    )
    violations = (
        check_solution(best_solution, bundle.instance, DEFAULT_PRICES)
        if best_solution is not None
        else []
    )
    solution_payload = _solution_to_dict(best_solution) if best_solution is not None else {}
    return {
        "algorithm": algorithm,
        "feasible": bool(result.feasible and not violations),
        "evals": result.evals,
        "actual_evals": result.evals,
        "actual_moves": result.actual_moves,
        "candidate_scores": result.candidate_scores,
        "repair_scores": result.repair_scores,
        "repair_delta_count": result.repair_delta_count,
        "operator_counts": result.operator_counts,
        "elapsed_seconds": result.elapsed_seconds,
        "best_cost": float(metrics["total_cost"]) if metrics else result.best_cost,
        "best_penalized_obj": result.best_penalized_obj,
        "status": result.status,
        "failure_reason": result.failure_reason,
        "metrics": metrics,
        "violation_count": len(violations),
        "best_solution": solution_payload,
        "solution": solution_payload,
        "route_count": len(best_solution.routes) if best_solution is not None else 0,
        "ev_routes": sum(1 for route in best_solution.routes if route.vehicle_type.lower() == "ev") if best_solution is not None else 0,
        "cv_routes": sum(1 for route in best_solution.routes if route.vehicle_type.lower() == "cv") if best_solution is not None else 0,
        "charging_event_count": len(best_solution.charging_actions) if best_solution is not None else 0,
        "history": result.history,
    }


def _e3_variant_specs(quota: float) -> list[dict[str, Any]]:
    """Return W2a cumulative ablation semantics in paper order."""

    no_trading_note = "paper switch p_car=0; emissions are still reported; CE=0 is finite but harmless because carbon price is zero"
    return [
        {
            "code": "M0",
            "label": "无多场协同",
            "carbon_profile_mode": "zero_gamma",
            "carbon_quota_kg": 0.0,
            "carbon_price_factor": 0.0,
            "carbon_weight": 0.0,
            "independent": True,
            "fairness_enabled": False,
            "seed_recipe": "independent_depot_concat_report_only",
            "note": f"independent depots; EV charging emissions zero; {no_trading_note}",
        },
        {
            "code": "M1",
            "label": "无碳感知",
            "carbon_profile_mode": "zero_gamma",
            "carbon_quota_kg": 0.0,
            "carbon_price_factor": 0.0,
            "carbon_weight": 0.0,
            "independent": False,
            "fairness_enabled": False,
            "seed_recipe": "concatenated_independent_seed",
            "note": f"shared vehicle pool and cross-site accounting; EV charging emissions zero; {no_trading_note}",
        },
        {
            "code": "M2",
            "label": "均值碳强度",
            "carbon_profile_mode": "mean_gamma",
            "carbon_quota_kg": 0.0,
            "carbon_price_factor": 0.0,
            "carbon_weight": 0.0,
            "independent": False,
            "fairness_enabled": False,
            "seed_recipe": "concatenated_independent_seed",
            "note": f"EV indirect emissions use daily mean gamma; {no_trading_note}",
        },
        {
            "code": "M3",
            "label": "无碳交易",
            "carbon_profile_mode": "actual_gamma",
            "carbon_quota_kg": 0.0,
            "carbon_price_factor": 0.0,
            "carbon_weight": 0.0,
            "independent": False,
            "fairness_enabled": False,
            "seed_recipe": "concatenated_independent_seed",
            "note": f"EV indirect emissions use the real 48-slot gamma; {no_trading_note}",
        },
        {
            "code": "M4",
            "label": "无收益公平",
            "carbon_profile_mode": "actual_gamma",
            "carbon_quota_kg": float(quota),
            "carbon_price_factor": 1.0,
            "carbon_weight": 1.0,
            "independent": False,
            "fairness_enabled": False,
            "seed_recipe": "concatenated_independent_seed",
            "note": "finite CE activates bidirectional carbon trading p_car*(E-CE)",
        },
        {
            "code": "M5",
            "label": "完整模型",
            "carbon_profile_mode": "actual_gamma",
            "carbon_quota_kg": float(quota),
            "carbon_price_factor": 1.0,
            "carbon_weight": 1.0,
            "independent": False,
            "fairness_enabled": True,
            "seed_recipe": "concatenated_independent_seed",
            "note": "theta=1.0 profit fairness from the concatenated independent seed",
        },
    ]


def _prices_with_carbon_price_factor(factor: float) -> PriceParameters:
    """Scale the paper carbon-trading price without changing other prices.

    v2026-06-12: W2a follows paper_main.tex line 295: no-carbon-trading
    experiments switch the trading term off with p_car=0 while retaining carbon
    emission statistics. The existing CE=inf evaluator path is still safe, but
    it is not the primary E3 switch.
    """

    return dataclass_replace(DEFAULT_PRICES, carbon_price=DEFAULT_PRICES.carbon_price * float(factor))


def _write_e3_derived_bundle(source_bundle_dir: str | Path, target_dir: str | Path, carbon_profile_mode: str) -> Path:
    source = Path(source_bundle_dir)
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name in ("instance.json", "distance_matrix.npy", "scenario_manifest.json"):
        source_path = source / name
        if source_path.exists():
            shutil.copyfile(source_path, target / name)
    bundle = load_search_bundle(source)
    profile = _derive_carbon_profile(bundle.carbon_profile, carbon_profile_mode)
    _write_carbon_profile_csv(target / "carbon_profile.csv", profile)
    return target


def _write_carbon_profile_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("carbon profile rows are required")
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _run_alns_metrics(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    policy: SearchPolicy,
    carbon_quota_kg: float = 0.0,
    carbon_weight: float = 1.0,
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    annotate_cross_site: bool = False,
    initial_solution: Solution | None = None,
    seed_recipe: str = "default_construction",
) -> dict[str, Any]:
    bundle = load_search_bundle(bundle_dir)
    started = time.perf_counter()
    result = run_alns_wouda(
        bundle.bundle_dir,
        iterations=None,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        policy=policy,
        carbon_weight=carbon_weight,
        carbon_quota_kg=carbon_quota_kg,
        initial_solution=initial_solution,
        prices=prices,
    )
    elapsed_seconds = time.perf_counter() - started
    best_solution = (
        _derive_cross_site_services(result.best_solution, bundle.instance)
        if annotate_cross_site
        else result.best_solution
    )
    metrics = evaluate(best_solution, bundle.instance, bundle.carbon_profile, prices, carbon_quota_kg=carbon_quota_kg)
    violations = check_solution(best_solution, bundle.instance, prices)
    return {
        "feasible": bool(result.feasible and not violations),
        "evals": result.evaluations,
        "actual_evals": result.evaluations,
        "elapsed_seconds": elapsed_seconds,
        "best_cost": float(metrics["total_cost"]),
        "best_penalized_obj": float(result.best_obj),
        "metrics": metrics,
        "violation_count": len(violations),
        "route_count": len(result.best_solution.routes),
        "ev_routes": sum(1 for route in result.best_solution.routes if route.vehicle_type.lower() == "ev"),
        "cv_routes": sum(1 for route in result.best_solution.routes if route.vehicle_type.lower() == "cv"),
        "charging_event_count": len(result.best_solution.charging_actions),
        "cross_site_customers": len(best_solution.cross_site_services),
        "solution": _solution_to_dict(best_solution),
        "best_solution": _solution_to_dict(best_solution),
        "seed_recipe": seed_recipe,
        "history": [{"eval": float(result.evaluations), "best_obj": float(result.best_obj)}],
    }


def _run_e4_once(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    base_emissions: float,
    price_factor: float,
    quota_factor: float,
) -> dict[str, Any]:
    prices = dataclass_replace(DEFAULT_PRICES, carbon_price=DEFAULT_PRICES.carbon_price * float(price_factor))
    result = _run_alns_metrics(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        carbon_quota_kg=float(base_emissions) * float(quota_factor),
        prices=prices,
        policy=SearchPolicy(require_charging_signal=False),
    )
    result.update(
        {
            "price_factor": float(price_factor),
            "quota_factor": float(quota_factor),
            "objective_carbon_price": float(prices.carbon_price),
        }
    )
    return result


def _derive_carbon_profile(carbon_profile: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    """Return E3 gamma-profile variants without changing evaluator code.

    v2026-06-12: W2a makes M0-M3 falsifiable: zero_gamma removes EV indirect
    carbon statistics, mean_gamma replaces all 48 slots by the daily mean, and
    actual_gamma preserves the original table for M3+.
    """

    if mode == "actual_gamma":
        return [dict(row) for row in carbon_profile]
    if mode not in {"zero_gamma", "mean_gamma"}:
        raise ValueError(f"Unsupported E3 carbon profile mode: {mode}")
    mean_gamma = 0.0
    if mode == "mean_gamma":
        values = [float(row["actual_gco2_per_kwh"]) for row in carbon_profile]
        mean_gamma = sum(values) / len(values) if values else 0.0
    out: list[dict[str, Any]] = []
    for row in carbon_profile:
        item = dict(row)
        item["actual_gco2_per_kwh"] = mean_gamma
        item["forecast_gco2_per_kwh"] = mean_gamma
        out.append(item)
    return out


def _derive_cross_site_services(
    solution: Solution,
    instance: Any,
    customer_home_depot: dict[str, str] | None = None,
) -> Solution:
    """Annotate cooperative solutions with cross-site service records.

    v2026-06-12: W2a makes M1+ cooperative service auditable; route home depot
    is the actual serving depot and nearest/home depot is the customer owner.
    """

    owners = customer_home_depot or infer_customer_home_depots(instance)
    node_lookup = {node.node_id: node for node in instance.nodes}
    services: list[CrossSiteService] = []
    for route in solution.routes:
        served_by = route.home_depot_id
        for node_id in route.node_sequence:
            node = node_lookup.get(node_id)
            if node is None or node.node_type.lower() != "c":
                continue
            if owners.get(node_id) != served_by:
                services.append(CrossSiteService(customer_id=node_id, served_by_depot_id=served_by))
    return Solution(
        routes=solution.routes,
        charging_actions=solution.charging_actions,
        cross_site_services=services,
    )


def dynamic_event_for_test(
    event_id: str,
    event_type: str,
    t_appear: float,
    customer_id: str,
    *,
    x: float = 1.0,
    y: float = 1.0,
    old_demand: float = 0.0,
    new_demand: float = 0.0,
    new_ready_time: float = 0.0,
    new_due_time: float = 86_400.0,
) -> DynamicEvent:
    return DynamicEvent(
        event_id=event_id,
        event_type=event_type,
        t_appear=t_appear,
        customer_id=customer_id,
        old_demand=old_demand,
        new_demand=new_demand,
        x=x,
        y=y,
        delta_demand=new_demand - old_demand,
        old_ready_time=new_ready_time,
        old_due_time=new_due_time,
        new_ready_time=new_ready_time,
        new_due_time=new_due_time,
    )


def dynamic_trigger_batches_for_test(events: list[DynamicEvent], params: RollingParameters) -> list[dict[str, Any]]:
    return _build_trigger_batches(events, params)


def dynamic_active_customer_ids_for_test(
    instance: Any,
    events: list[DynamicEvent],
    *,
    trigger_time: float,
    already_served: set[str],
) -> set[str]:
    return _active_customer_ids_after_events(instance, events, trigger_time, already_served)


def dynamic_read_events_for_test(path: str | Path) -> list[DynamicEvent]:
    return _read_dynamic_events(Path(path))


def _run_e3_variant(
    bundle_dir: str | Path,
    output_dir: str | Path,
    spec: dict[str, Any],
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    if bool(spec["independent"]):
        return _run_e3_independent_variant(
            bundle_dir,
            Path(output_dir),
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            carbon_quota_kg=float(spec["carbon_quota_kg"]),
            carbon_price_factor=float(spec["carbon_price_factor"]),
        )
    if bool(spec["fairness_enabled"]):
        return _run_e3_fairness_variant(
            bundle_dir,
            Path(output_dir),
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            carbon_quota_kg=float(spec["carbon_quota_kg"]),
            carbon_price_factor=float(spec["carbon_price_factor"]),
        )
    prices = _prices_with_carbon_price_factor(float(spec["carbon_price_factor"]))
    seed_payload = _build_e3_concatenated_seed(
        bundle_dir,
        Path(output_dir),
        spec,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        carbon_quota_kg=float(spec["carbon_quota_kg"]),
        carbon_price_factor=float(spec["carbon_price_factor"]),
    )
    result = _run_alns_metrics(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        policy=SearchPolicy(require_charging_signal=False),
        carbon_quota_kg=float(spec["carbon_quota_kg"]),
        carbon_weight=float(spec["carbon_weight"]),
        prices=prices,
        annotate_cross_site=True,
        initial_solution=seed_payload["initial_solution"],
        seed_recipe=str(seed_payload["seed_recipe"]),
    )
    result.setdefault("seed_recipe", str(seed_payload["seed_recipe"]))
    return result


def _run_e3_independent_variant(
    bundle_dir: str | Path,
    output_dir: Path,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    carbon_quota_kg: float,
    carbon_price_factor: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    pi_path = output_dir / f"e3_m0_pi_d0_seed{seed}.json"
    prices = _prices_with_carbon_price_factor(carbon_price_factor)
    report = run_independent_profit_baselines(
        bundle_dir,
        pi_path,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        prices=prices,
        carbon_quota_kg=carbon_quota_kg,
    )
    seed_report = build_concatenated_independent_seed(
        bundle_dir,
        pi_path,
        output_json_path=output_dir / f"e3_m0_independent_concat_seed{seed}.json",
        prices=prices,
        carbon_quota_kg=carbon_quota_kg,
    )
    bundle = load_search_bundle(bundle_dir)
    solution = _solution_from_dict(seed_report["solution"])
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices, carbon_quota_kg=carbon_quota_kg)
    violations = check_solution(solution, bundle.instance, prices)
    elapsed_seconds = time.perf_counter() - started
    evaluations = sum(int(row.get("evaluations", 0)) for row in report.get("depots", {}).values())
    return {
        "feasible": bool(seed_report.get("feasible") and not violations),
        "evals": int(evaluations),
        "actual_evals": int(evaluations),
        "elapsed_seconds": elapsed_seconds,
        "best_cost": float(metrics["total_cost"]),
        "best_penalized_obj": float(metrics["total_cost"]),
        "metrics": metrics,
        "violation_count": len(violations),
        "route_count": len(solution.routes),
        "ev_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "cv_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
        "charging_event_count": len(solution.charging_actions),
        "cross_site_customers": len(solution.cross_site_services),
        "min_profit_ratio": _min_ratio(seed_report.get("profit_ratio", {})),
        "seed_recipe": "independent_depot_concat_report_only",
        "solution": seed_report["solution"],
        "best_solution": seed_report["solution"],
        "history": [{"eval": float(evaluations), "best_obj": float(metrics["total_cost"])}],
    }


def _build_e3_concatenated_seed(
    bundle_dir: str | Path,
    output_dir: Path,
    spec: dict[str, Any],
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    carbon_quota_kg: float,
    carbon_price_factor: float,
) -> dict[str, Any]:
    code = str(spec["code"]).lower()
    prices = _prices_with_carbon_price_factor(carbon_price_factor)
    pi_path = output_dir / f"e3_{code}_pi_d0_seed{seed}.json"
    run_independent_profit_baselines(
        bundle_dir,
        pi_path,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        prices=prices,
        carbon_quota_kg=carbon_quota_kg,
    )
    seed_report = build_concatenated_independent_seed(
        bundle_dir,
        pi_path,
        output_json_path=output_dir / f"e3_{code}_independent_concat_seed{seed}.json",
        prices=prices,
        carbon_quota_kg=carbon_quota_kg,
    )
    return {
        "initial_solution": _solution_from_dict(seed_report["solution"]),
        "seed_recipe": "concatenated_independent_seed",
        "initial_seed_metrics": seed_report.get("metrics", {}),
        "seed_report": seed_report,
    }


def _run_e3_fairness_variant(
    bundle_dir: str | Path,
    output_dir: Path,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    carbon_quota_kg: float,
    carbon_price_factor: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    pi_path = output_dir / f"e3_m5_pi_d0_seed{seed}.json"
    prices = _prices_with_carbon_price_factor(carbon_price_factor)
    report = run_independent_profit_baselines(
        bundle_dir,
        pi_path,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        prices=prices,
        carbon_quota_kg=carbon_quota_kg,
    )
    seed_path = output_dir / f"e3_m5_independent_concat_seed{seed}.json"
    seed_report = build_concatenated_independent_seed(
        bundle_dir,
        pi_path,
        output_json_path=seed_path,
        prices=prices,
        carbon_quota_kg=carbon_quota_kg,
    )
    bundle = load_search_bundle(bundle_dir)
    initial_solution = _solution_from_dict(seed_report["solution"])
    owners = infer_customer_home_depots(bundle.instance)
    # v2026-06-12: W2a M5 uses the concatenated independent routes as the
    # theta=1.0 seed under the same system-level scorer and CE as the cooperative
    # run. Reusing per-depot reports with the full CE repeated once per depot
    # makes the seed falsely unfair under finite carbon trading.
    seed_profit = calculate_depot_profits(
        initial_solution,
        bundle.instance,
        bundle.carbon_profile,
        prices,
        customer_home_depot=owners,
        carbon_quota_kg=carbon_quota_kg,
    )
    independent_profit = {depot_id: float(row.profit) for depot_id, row in seed_profit.items()}
    result = run_alns_wouda(
        bundle.bundle_dir,
        iterations=None,
        seed=seed,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        policy=SearchPolicy(require_charging_signal=False),
        carbon_quota_kg=carbon_quota_kg,
        carbon_weight=carbon_price_factor,
        fairness_enabled=True,
        independent_profit=independent_profit,
        fairness_theta=prices.fairness_theta,
        customer_home_depot=owners,
        initial_solution=initial_solution,
    )
    solution = _derive_cross_site_services(result.best_solution, bundle.instance, owners)
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices, carbon_quota_kg=carbon_quota_kg)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        carbon_quota_kg=carbon_quota_kg,
        fairness_enabled=True,
        independent_profit=independent_profit,
        fairness_theta=prices.fairness_theta,
        customer_home_depot=owners,
    )
    fairness_context = fairness_context_for_solution(solution, context)
    violations = check_solution(solution, bundle.instance, prices, fairness_context=fairness_context, fairness_enabled=True)
    elapsed_seconds = time.perf_counter() - started
    ratios = {} if fairness_context is None else {
        depot_id: fairness_context.depot_profit.get(depot_id, 0.0) / baseline
        for depot_id, baseline in independent_profit.items()
    }
    return {
        "feasible": bool(result.feasible and not violations),
        "evals": int(result.evaluations),
        "actual_evals": int(result.evaluations),
        "elapsed_seconds": elapsed_seconds,
        "best_cost": float(metrics["total_cost"]),
        "best_penalized_obj": float(result.best_obj),
        "metrics": metrics,
        "violation_count": len(violations),
        "route_count": len(solution.routes),
        "ev_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "cv_routes": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
        "charging_event_count": len(solution.charging_actions),
        "cross_site_customers": len(solution.cross_site_services),
        "min_profit_ratio": _min_ratio(ratios),
        "fairness_baseline_source": "concatenated_independent_seed_same_scorer",
        "seed_recipe": "concatenated_independent_seed",
        "solution": _solution_to_dict(solution),
        "best_solution": _solution_to_dict(solution),
        "history": [{"eval": float(result.evaluations), "best_obj": float(result.best_obj)}],
    }


def _solution_to_dict(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(service) for service in solution.cross_site_services],
    }


def _solution_from_dict(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[str(node_id) for node_id in row["node_sequence"]],
            )
            for row in payload.get("routes", [])
        ],
        charging_actions=[
            charging_action_from_dict(row)
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row["customer_id"]),
                served_by_depot_id=str(row["served_by_depot_id"]),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def _load_run_rows_from_manifest(manifest_path: str | Path) -> list[dict[str, Any]]:
    path = Path(manifest_path)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in payload.get("runs", []):
        key_payload = row.get("key", {})
        if not key_payload:
            continue
        key = RunKey(
            str(key_payload["experiment"]),
            str(key_payload["instance"]),
            str(key_payload["algorithm"]),
            int(key_payload["seed"]),
            str(key_payload["variant"]),
        )
        rows.append(_flatten_run_row(key, row))
    return rows


def _load_prior_alns_wouda_rows(repo_root: Path) -> dict[tuple[str, int], dict[str, Any]]:
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for path in sorted((repo_root / "solver" / "reports" / "parallel_r2_full" / "units").glob("e2_s*/formal_runner_manifest.json")):
        for row in _load_run_rows_from_manifest(path):
            if row["algorithm"] == PRIMARY_ALGORITHM and _run_feasible_with_cost(row):
                rows[(row["instance"], int(row["seed"]))] = row
    formal_manifest = repo_root / "solver" / "reports" / "formal" / "formal_runner_manifest.json"
    for row in _load_run_rows_from_manifest(formal_manifest):
        if row["algorithm"] == PRIMARY_ALGORITHM and _run_feasible_with_cost(row):
            rows.setdefault((row["instance"], int(row["seed"])), row)
    return rows


def _alns_wouda_before_after_rows(run_rows: list[dict[str, Any]], before_rows: dict[tuple[str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    references = {
        instance: min(float(row["result"]["best_cost"]) for row in rows if _run_feasible_with_cost(row))
        for instance, rows in _group_by_instance(run_rows).items()
        if any(_run_feasible_with_cost(row) for row in rows)
    }
    out: list[dict[str, Any]] = []
    after_rows = [row for row in run_rows if row["algorithm"] == PRIMARY_ALGORITHM]
    for after in sorted(after_rows, key=lambda row: (row["instance"], int(row["seed"]))):
        key = (after["instance"], int(after["seed"]))
        before = before_rows.get(key)
        if before is not None:
            out.append(_validation_comparison_row("before", before, references.get(before["instance"], 0.0)))
        out.append(_validation_comparison_row("after", after, references.get(after["instance"], 0.0)))
    return out


def _validation_comparison_row(variant: str, row: dict[str, Any], reference: float) -> dict[str, Any]:
    result = row.get("result", {})
    cost = float(result["best_cost"]) if result.get("best_cost") not in (None, "") else 0.0
    gap = (cost - reference) / reference * 100.0 if reference else ""
    return {
        "variant": variant,
        "instance": row["instance"],
        "seed": row["seed"],
        "algorithm": row["algorithm"],
        "best_cost": round(cost, 6) if cost else "",
        "gap_to_observed_best_pct": round(gap, 3) if gap != "" else "",
        "actual_evals": row.get("actual_evals", result.get("actual_evals", "")),
        "actual_moves": result.get("actual_moves", ""),
        "candidate_scores": result.get("candidate_scores", ""),
        "repair_scores": result.get("repair_scores", ""),
        "repair_delta_count": result.get("repair_delta_count", result.get("repair_scores", "")),
        "ev_routes": result.get("ev_routes", ""),
        "charging_events": result.get("charging_event_count", ""),
        "route_count": result.get("route_count", ""),
        "elapsed_seconds": result.get("elapsed_seconds", ""),
        "feasible": result.get("feasible", False),
    }


def _group_by_instance(run_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in run_rows:
        grouped.setdefault(row["instance"], []).append(row)
    return grouped


def _alns_fix_validation_gate(finals: list[dict[str, Any]]) -> str:
    average = next((row for row in finals if row.get("instance") == "Average"), {})
    gap = average.get(f"{PRIMARY_ALGORITHM}|相对已观测最优偏差\\%")
    if gap in ("", None):
        return "HALT_ALNS_FIX_NO_AVERAGE"
    return "PASS" if float(gap) <= 5.0 else "HALT_ALNS_FIX_TARGET_MISS"


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _alns_strong_gate(output_dir: Path, target_algorithm: str) -> str:
    summary = _read_csv_rows(output_dir / "tables" / "root_cause_summary.csv")
    operators = _read_csv_rows(output_dir / "tables" / "operator_summary.csv")
    target_rows = [row for row in summary if row.get("algorithm") == target_algorithm]
    sa_rows = [row for row in summary if row.get("algorithm") == "scikit-opt-SA"]
    if not target_rows or not sa_rows:
        return "HALT_ALNS_STRONG_MISSING_ROWS"
    target_gap = mean(float(row["final_gap_pct"]) for row in target_rows)
    sa_gap = mean(float(row["final_gap_pct"]) for row in sa_rows)
    churn = mean(float(row["churn_rate"]) for row in target_rows)
    target_ops = [row for row in operators if row.get("algorithm") == target_algorithm]
    total_uses = sum(int(row["used"]) for row in target_ops)
    top_share = max((int(row["used"]) for row in target_ops), default=0) / max(1, total_uses)
    non_swap = [row for row in target_ops if row.get("destroy_op") != "vehicle_type_swap"]
    non_swap_uses = sum(int(row["used"]) for row in non_swap)
    non_swap_feasible = (
        sum(float(row["feasible_rate"]) * int(row["used"]) for row in non_swap) / max(1, non_swap_uses)
        if non_swap
        else 0.0
    )
    if non_swap_feasible <= 0.9:
        return "HALT_WOUDA_STRONG_TARGET_MISS" if target_algorithm == PRIMARY_ALGORITHM else "HALT_WANG_STRONG_TARGET_MISS"
    if churn < 0.25:
        return "HALT_WOUDA_STRONG_TARGET_MISS" if target_algorithm == PRIMARY_ALGORITHM else "HALT_WANG_STRONG_TARGET_MISS"
    if top_share >= 0.5:
        return "HALT_WOUDA_STRONG_TARGET_MISS" if target_algorithm == PRIMARY_ALGORITHM else "HALT_WANG_STRONG_TARGET_MISS"
    if target_gap > sa_gap + 1e-9:
        return "HALT_WOUDA_STRONG_TARGET_MISS" if target_algorithm == PRIMARY_ALGORITHM else "HALT_WANG_STRONG_TARGET_MISS"
    return "PASS"


def _wang_root_cause_gate(output_dir: Path) -> str:
    summary = _read_csv_rows(output_dir / "tables" / "root_cause_summary.csv")
    operators = _read_csv_rows(output_dir / "tables" / "operator_summary.csv")
    target = "ALNS@wangqianlongucas"
    target_rows = [row for row in summary if row.get("algorithm") == target]
    if not target_rows:
        return "HALT_WANG_ROOT_CAUSE_MISSING"
    churn = mean(float(row["churn_rate"]) for row in target_rows)
    target_ops = [row for row in operators if row.get("algorithm") == target]
    total_uses = sum(int(row["used"]) for row in target_ops)
    top_share = max((int(row["used"]) for row in target_ops), default=0) / max(1, total_uses)
    non_swap_uses = total_uses
    non_swap_feasible = (
        sum(float(row["feasible_rate"]) * int(row["used"]) for row in target_ops) / max(1, non_swap_uses)
        if target_ops
        else 0.0
    )
    return "PASS_WANG_SAME_ROOT_CAUSE" if (non_swap_feasible < 0.5 or top_share > 0.7 or churn < 0.1) else "HALT_WANG_DIFFERENT_ROOT_CAUSE_NEEDS_PLAN"


def _alns_strong_readme(target_algorithm: str, eval_budget: int, max_runtime_seconds: float, gate: str) -> str:
    stage = "ALNS_WOUDA_STRONG" if target_algorithm == PRIMARY_ALGORITHM else "ALNS_WANG_STRONG"
    return "\n".join(
        [
            f"# {stage} Validation",
            "",
            f"Gate: `{gate}`",
            "",
            "This directory is validation-only and does not replace formal reports or manuscript tables.",
            "",
            "```bash",
            f"PYTHONPATH=solver/src python -m setp_solver.search.formal_runner {stage} --eval-budget {int(eval_budget)} --max-runtime-seconds {float(max_runtime_seconds)} --seeds 1,2,3",
            "```",
            "",
            "Acceptance checks: non-swap repair feasibility > 0.9, churn >= 0.25, top operator-pair share < 0.5, and average gap no worse than scikit-opt-SA.",
        ]
    )


def _alns_fix_validation_readme(eval_budget: int, max_runtime_seconds: float, gate: str, result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# ALNS Fair-Budget Validation",
            "",
            f"Gate: `{gate}`",
            "",
            "Budget accounting: each full candidate solution submitted to the search selection/acceptance step counts as one `actual_evals`; repair-internal delta scoring is reported as `repair_delta_count` and mirrored in legacy `repair_scores`, but it does not consume eval budget.",
            "",
            "Suggested command:",
            "",
            "```bash",
            f"PYTHONPATH=solver/src python -m setp_solver.search.formal_runner ALNS_FIX --output-dir solver/reports/alns_fix_validation --eval-budget {int(eval_budget)} --max-runtime-seconds {float(max_runtime_seconds)}",
            "```",
            "",
            f"Run count: `{result.get('run_count', '')}`",
            f"Manifest: `{result.get('manifest', '')}`",
            "",
            "This directory is validation-only and does not replace formal paper tables or figures.",
        ]
    )


def _flatten_run_row(key: RunKey, row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row.get("result", {}))
    actual_evals = _actual_evals_from_result(result)
    actual_elapsed = _actual_elapsed_from_result(result, row.get("elapsed_seconds", ""))
    result.setdefault("actual_evals", actual_evals)
    result["elapsed_seconds"] = actual_elapsed
    return {
        "experiment": key.experiment,
        "instance": key.instance,
        "algorithm": key.algorithm,
        "seed": key.seed,
        "variant": key.variant,
        "status": row.get("status"),
        "skipped": row.get("skipped", False),
        "failure_reason": row.get("failure_reason", result.get("failure_reason", "")),
        "actual_evals": actual_evals,
        "actual_elapsed_seconds": actual_elapsed,
        "result": result,
    }


def _actual_evals_from_result(result: dict[str, Any]) -> Any:
    direct = result.get("actual_evals", result.get("evals", result.get("evaluations", "")))
    if direct not in ("", None):
        return direct
    nested_total = 0
    found_nested = False
    for key in ("fairness_on", "fairness_off"):
        nested = result.get(key)
        if isinstance(nested, dict):
            value = nested.get("actual_evals", nested.get("evals", nested.get("evaluations")))
            if value not in (None, ""):
                nested_total += int(value)
                found_nested = True
    return nested_total if found_nested else ""


def _actual_elapsed_from_result(result: dict[str, Any], row_elapsed: Any) -> Any:
    direct = result.get("elapsed_seconds", "")
    if direct not in ("", None, 0, 0.0):
        return direct
    nested_total = 0.0
    found_nested = False
    for key in ("fairness_on", "fairness_off"):
        nested = result.get(key)
        if isinstance(nested, dict):
            value = nested.get("elapsed_seconds")
            if value not in (None, ""):
                nested_total += float(value)
                found_nested = True
    if found_nested:
        return nested_total
    return row_elapsed


def _e2_final_rows(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    algorithms = _ordered_algorithms(run_rows)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in run_rows:
        grouped.setdefault(row["instance"], []).append(row)

    out: list[dict[str, Any]] = []
    best_counts = {algorithm: 0 for algorithm in algorithms}
    gap_by_algorithm: dict[str, list[float]] = {algorithm: [] for algorithm in algorithms}
    time_by_algorithm: dict[str, list[float]] = {algorithm: [] for algorithm in algorithms}
    for instance, rows in sorted(grouped.items()):
        feasible = [row for row in rows if _run_feasible_with_cost(row)]
        reference = min((float(row["result"]["best_cost"]) for row in feasible), default=0.0)
        row_out: dict[str, Any] = {"instance": instance, "n_d": _n_d_label(instance), "reference_best": round(reference, 6) if reference else ""}
        for algorithm in algorithms:
            alg_rows = [row for row in rows if row["algorithm"] == algorithm]
            costs = [float(row["result"]["best_cost"]) for row in alg_rows if _run_feasible_with_cost(row)]
            times = [float(row["result"].get("elapsed_seconds", 0.0)) for row in alg_rows if row["result"].get("elapsed_seconds") not in ("", None)]
            evals = [float(row.get("actual_evals", row["result"].get("actual_evals", 0.0))) for row in alg_rows if row.get("actual_evals", row["result"].get("actual_evals", "")) not in ("", None)]
            if costs and reference:
                avg_cost = mean(costs)
                gap = (avg_cost - reference) / reference * 100.0
                row_out[f"{algorithm}|相对已观测最优偏差\\%"] = round(gap, 3)
                gap_by_algorithm[algorithm].append(gap)
                best_counts[algorithm] += sum(1 for cost in costs if abs(cost - reference) <= 1e-6)
            else:
                row_out[f"{algorithm}|相对已观测最优偏差\\%"] = ""
            if times:
                avg_time = mean(times)
                row_out[f"{algorithm}|时间s"] = round(avg_time, 3)
                time_by_algorithm[algorithm].append(avg_time)
            else:
                row_out[f"{algorithm}|时间s"] = ""
            row_out[f"{algorithm}|实际评估次数"] = round(mean(evals), 3) if evals else ""
        out.append(row_out)

    average: dict[str, Any] = {"instance": "Average", "n_d": "", "reference_best": ""}
    best_count: dict[str, Any] = {"instance": "达优次数", "n_d": "", "reference_best": ""}
    for algorithm in algorithms:
        gaps = gap_by_algorithm[algorithm]
        times = time_by_algorithm[algorithm]
        average[f"{algorithm}|相对已观测最优偏差\\%"] = round(mean(gaps), 3) if gaps else ""
        average[f"{algorithm}|时间s"] = round(mean(times), 3) if times else ""
        average[f"{algorithm}|实际评估次数"] = ""
        best_count[f"{algorithm}|相对已观测最优偏差\\%"] = best_counts[algorithm]
        best_count[f"{algorithm}|时间s"] = ""
        best_count[f"{algorithm}|实际评估次数"] = ""
    out.extend([average, best_count])
    return out


def _ordered_algorithms(run_rows: list[dict[str, Any]]) -> list[str]:
    preferred = [PRIMARY_ALGORITHM, *Z1_CANDIDATES]
    seen = {row["algorithm"] for row in run_rows}
    ordered = [algorithm for algorithm in preferred if algorithm in seen]
    ordered.extend(sorted(seen - set(ordered)))
    return ordered


def _run_feasible_with_cost(row: dict[str, Any]) -> bool:
    result = row.get("result", {})
    return bool(
        row.get("status") == "completed"
        and result.get("feasible")
        and result.get("best_cost") not in (None, "")
    )


def _n_d_label(instance: str) -> str:
    if instance.startswith("L-main-"):
        parts = instance.split("-")
        family = parts[2] if len(parts) > 2 else ""
        depots = 1 if family == "vanilla" else 2
        for part in parts:
            if part.endswith("c") and part[:-1].isdigit():
                return f"{part[:-1]}/{depots}"
    return ""


def _e1_table_rows(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in _e1_best_rows_by_variant(run_rows):
        result = row.get("result", {})
        metrics = result.get("metrics", {})
        if not metrics:
            continue
        total_carbon = float(metrics.get("E_total", 0.0))
        charging_carbon = float(metrics.get("E_ev_indirect", 0.0))
        rows.extend(
            [
                {"metric": f"{row['variant']} total_cost", "value": round(float(metrics["total_cost"]), 3), "share_pct": ""},
                {"metric": f"{row['variant']} total_carbon_kg", "value": round(total_carbon, 3), "share_pct": ""},
                {"metric": f"{row['variant']} charging_stake", "value": round(charging_carbon, 3), "share_pct": round(charging_carbon / total_carbon * 100.0, 3) if total_carbon else 0.0},
                {"metric": f"{row['variant']} EV/CV", "value": f"{result.get('ev_routes', 0)}/{result.get('cv_routes', 0)}", "share_pct": ""},
                {"metric": f"{row['variant']} source_seed", "value": row["seed"], "share_pct": ""},
            ]
        )
    return rows


def _e1_seed_detail_rows(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in sorted(run_rows, key=lambda item: (item["variant"], int(item["seed"]))):
        result = row.get("result", {})
        metrics = result.get("metrics", {})
        total_carbon = float(metrics.get("E_total", 0.0)) if metrics else 0.0
        charging_carbon = float(metrics.get("E_ev_indirect", 0.0)) if metrics else 0.0
        rows.append(
            {
                "variant": row["variant"],
                "seed": row["seed"],
                "status": row.get("status", ""),
                "feasible": "是" if result.get("feasible") else "否",
                "violation_count": result.get("violation_count", ""),
                "total_cost": round(float(metrics["total_cost"]), 3) if metrics else "",
                "total_carbon_kg": round(total_carbon, 3) if metrics else "",
                "charging_carbon_kg": round(charging_carbon, 3) if metrics else "",
                "charging_share_pct": round(charging_carbon / total_carbon * 100.0, 3) if total_carbon else "",
                "ev_routes": result.get("ev_routes", ""),
                "cv_routes": result.get("cv_routes", ""),
                "route_count": result.get("route_count", ""),
                "actual_evals": row.get("actual_evals", result.get("actual_evals", "")),
                "elapsed_seconds": result.get("elapsed_seconds", ""),
            }
        )
    return rows


def _e1_best_rows_by_variant(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in run_rows:
        grouped.setdefault(row["variant"], []).append(row)
    best_rows = []
    for variant, rows in sorted(grouped.items()):
        feasible = [row for row in rows if _run_feasible_with_cost(row)]
        if not feasible:
            continue
        best_rows.append(min(feasible, key=lambda item: float(item["result"]["best_cost"])))
    return best_rows


def _write_e2_solution_outputs(repo_root: Path, output_dir: Path, run_rows: list[dict[str, Any]]) -> None:
    candidates = [
        row
        for row in run_rows
        if row["algorithm"] == PRIMARY_ALGORITHM
        and _run_feasible_with_cost(row)
        and _solution_payload_from_result(row.get("result", {}))
    ]
    if not candidates:
        return
    best = min(candidates, key=lambda row: float(row["result"]["best_cost"]))
    bundle_dir = repo_root / INSTANCE_DIRS[best["instance"]]
    bundle = load_search_bundle(bundle_dir)
    solution = _solution_from_dict(_solution_payload_from_result(best["result"]))
    metrics = best["result"].get("metrics") or evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)
    rows = [
        {"metric": "e2_best total_cost", "value": round(float(metrics["total_cost"]), 3), "share_pct": ""},
        {"metric": "e2_best total_carbon_kg", "value": round(float(metrics["E_total"]), 3), "share_pct": ""},
        {
            "metric": "e2_best charging_stake",
            "value": round(float(metrics.get("E_ev_indirect", 0.0)), 3),
            "share_pct": round(float(metrics.get("E_ev_indirect", 0.0)) / float(metrics["E_total"]) * 100.0, 3) if float(metrics["E_total"]) else 0.0,
        },
        {"metric": "e2_best EV/CV", "value": f"{best['result'].get('ev_routes', 0)}/{best['result'].get('cv_routes', 0)}", "share_pct": ""},
        {"metric": "e2_best source", "value": f"E2 {PRIMARY_ALGORITHM} seed={best['seed']}", "share_pct": ""},
    ]
    _write_csv(output_dir / "tables" / "t4_e2_best_solution_decomposition.csv", rows)
    _write_route_map_sources(bundle.instance, solution, output_dir / "figures")


def _solution_payload_from_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("best_solution") or result.get("solution") or {}
    return payload if isinstance(payload, dict) else {}


def _write_route_map_sources(instance: Any, solution: Solution, figures_dir: Path) -> None:
    service_depot: dict[str, str] = {}
    for route in solution.routes:
        for node_id in route.node_sequence:
            service_depot.setdefault(node_id, route.home_depot_id)
    owners = infer_customer_home_depots(instance)
    node_rows = []
    for node in instance.nodes:
        served_by = service_depot.get(node.node_id, "")
        node_rows.append(
            {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "x": float(node.x),
                "y": float(node.y),
                "service_depot": served_by,
                "cross_site": "是" if node.node_type.lower() == "c" and served_by and owners.get(node.node_id) != served_by else "否",
            }
        )
    route_rows = [
        {
            "route_id": route.vehicle_id,
            "vehicle_type": route.vehicle_type,
            "home_depot_id": route.home_depot_id,
            "node_sequence": ">".join(route.node_sequence),
        }
        for route in solution.routes
    ]
    _write_csv(figures_dir / "f1_route_nodes.csv", node_rows)
    _write_csv(figures_dir / "f1_route_lines.csv", route_rows)


def _write_e7_t9_outputs(output_dir: Path, reports: dict[int, dict[str, Any]]) -> None:
    table_rows: list[dict[str, Any]] = []
    side_rows: list[dict[str, Any]] = []
    for seed, report in sorted(reports.items()):
        if "stage_rows" not in report:
            row = {
                "stage": f"s{seed}:failed",
                "trigger_time": "",
                "trigger_reason": "failure",
                "event_counts": "",
                "frozen_routes": "",
                "stage_cost": "",
                "cumulative_cost": "",
                "cumulative_carbon_kg": "",
                "min_fairness_ratio": "",
                "feasible": "否",
                "failure_reason": report.get("failure_reason", report.get("gate", "")),
            }
            table_rows.append(row)
            side_rows.append({"event_seed": seed, **row})
            continue
        for raw in report.get("stage_rows", []):
            row = dict(raw)
            stage = str(row.get("stage", ""))
            row["stage"] = f"s{seed}:summary" if stage == "dynamic_vs_static" else f"s{seed}:{stage}"
            table_rows.append(row)
            side_rows.append({"event_seed": seed, **row})
    _write_csv(output_dir / "tables" / "t9_dynamic.csv", table_rows)
    _write_csv(output_dir / "tables" / "t9_dynamic_by_seed.csv", side_rows)


def _retained_e3_m0_rows(repo_root: Path) -> list[dict[str, Any]]:
    manifest = repo_root / "solver" / "reports" / "formal" / "formal_runner_manifest.json"
    if not manifest.exists():
        return []
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    rows = []
    for row in payload.get("runs", []):
        key = row.get("key", {})
        if key.get("experiment") == "E3" and key.get("variant") == "M0":
            flat = _flatten_run_row(key_from_payload(key), row)
            flat["label"] = "无多场协同"
            flat["retained_from"] = str(manifest)
            rows.append(flat)
    return rows


def key_from_payload(payload: dict[str, Any]) -> RunKey:
    return RunKey(
        str(payload["experiment"]),
        str(payload["instance"]),
        str(payload["algorithm"]),
        int(payload["seed"]),
        str(payload["variant"]),
    )


def _e3_table_rows(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    labels: dict[str, str] = {}
    for row in run_rows:
        grouped.setdefault(row["variant"], []).append(row)
        labels[row["variant"]] = row.get("label", row["variant"])
    full_costs = [
        float(row["result"]["best_cost"])
        for row in run_rows
        if row["variant"] == "M5" and row.get("result", {}).get("feasible") and row["result"].get("best_cost") is not None
    ]
    full_mean = mean(full_costs) if full_costs else 0.0
    rows = []
    for variant, items in sorted(grouped.items()):
        costs = [float(item["result"]["best_cost"]) for item in items if item.get("result", {}).get("feasible") and item["result"].get("best_cost") is not None]
        evs = [float(item["result"].get("ev_routes", 0)) for item in items if item.get("result", {}).get("feasible")]
        # v2026-06-13: R1-1 report-layer pickup for E3 cross-site counts already stored in manifest rows.
        crosses = [float(item["result"].get("cross_site_customers", 0)) for item in items if item.get("result", {}).get("feasible")]
        ratios = [float(item["result"].get("min_profit_ratio", 0.0)) for item in items if item.get("result", {}).get("min_profit_ratio") is not None]
        emissions = [float(item["result"].get("metrics", {}).get("E_total", 0.0)) for item in items if item.get("result", {}).get("feasible") and item.get("result", {}).get("metrics")]
        avg = mean(costs) if costs else float("nan")
        std = _std(costs)
        delta = ((avg - full_mean) / full_mean * 100.0) if full_mean and costs else float("nan")
        rows.append(
            {
                "step": f"{variant} {labels[variant]}",
                "best": round(min(costs), 3) if costs else "",
                "mean": round(avg, 3) if costs else "",
                "std": round(std, 3) if costs else "",
                "E_total_kg": round(mean(emissions), 3) if emissions else "",
                "delta_vs_full_pct": round(delta, 3) if costs and full_mean else "",
                "ev_count": round(mean(evs), 2) if evs else "",
                "cross_site_customers": round(mean(crosses), 2) if crosses else "",
                "min_profit_ratio": round(mean(ratios), 4) if ratios else "",
                "mechanism_note": labels[variant],
            }
        )
    return rows


def _e3_note_rows(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "step": spec["code"],
            "carbon_profile_mode": spec["carbon_profile_mode"],
            "carbon_quota_kg": "inf" if math.isinf(float(spec["carbon_quota_kg"])) else float(spec["carbon_quota_kg"]),
            "carbon_price_factor": float(spec["carbon_price_factor"]),
            "carbon_weight": float(spec["carbon_weight"]),
            "independent": bool(spec["independent"]),
            "fairness_enabled": bool(spec["fairness_enabled"]),
            "seed_recipe": spec.get("seed_recipe", ""),
            "official_no_trading_switch": "p_car=0 per paper_main.tex eq:objective note",
            "ce_inf_code_behavior": "cost.evaluate and depot-profit allocation special-case CE=inf as zero carbon trading cost",
            "note": spec["note"],
        }
        for spec in variants
    ]


def _e4_table_rows(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in run_rows:
        grouped.setdefault(row["variant"], []).append(row)
    rows = []
    for variant, items in sorted(grouped.items(), key=lambda item: _e4_variant_sort_key(item[0])):
        parts = dict(piece.split("=") for piece in variant.split(";"))
        metric_rows = [item.get("result", {}).get("metrics", {}) for item in items if item.get("result", {}).get("metrics")]
        feasible_items = [item for item in items if item.get("result", {}).get("feasible")]
        if not metric_rows:
            rows.append({"carbon_price": parts.get("p", ""), "quota": parts.get("ce", ""), "total_carbon_kg": "", "feasible": "否", "seed_count": len(items), "feasible_runs": 0})
            continue
        rows.append(
            {
                "carbon_price": parts.get("p", ""),
                "quota": parts.get("ce", ""),
                "total_cost": round(mean([float(row["total_cost"]) for row in metric_rows]), 3),
                "fuel_liters": round(mean([float(row["fuel_liters"]) for row in metric_rows]), 3),
                "electricity_cost": round(mean([float(row["cost_elec"]) for row in metric_rows]), 3),
                "carbon_trading_cost": round(mean([float(row["cost_carbon"]) for row in metric_rows]), 3),
                "total_carbon_kg": round(mean([float(row["E_total"]) for row in metric_rows]), 3),
                "ev_count": round(mean([float(item.get("result", {}).get("ev_routes", 0)) for item in items]), 3),
                "feasible": "是" if len(feasible_items) == len(items) else "否",
                "seed_count": len(items),
                "feasible_runs": len(feasible_items),
            }
        )
    return rows


def _e4_seed_detail_rows(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in run_rows:
        result = row.get("result", {})
        metrics = result.get("metrics", {})
        parts = dict(item.split("=") for item in row["variant"].split(";"))
        rows.append(
            {
                "seed": row["seed"],
                "carbon_price": parts.get("p", ""),
                "quota": parts.get("ce", ""),
                "total_cost": round(float(metrics["total_cost"]), 3) if metrics else "",
                "total_carbon_kg": round(float(metrics["E_total"]), 3) if metrics else "",
                "actual_evals": row.get("actual_evals", ""),
                "elapsed_seconds": result.get("elapsed_seconds", ""),
                "feasible": "是" if result.get("feasible") else "否",
            }
        )
    return rows


def _e4_diagnostic_rows(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in run_rows:
        result = row.get("result", {})
        parts = dict(item.split("=") for item in row["variant"].split(";"))
        rows.append(
            {
                "seed": row["seed"],
                "price_factor": result.get("price_factor", parts.get("p", "")),
                "quota_factor": result.get("quota_factor", parts.get("ce", "")),
                "objective_carbon_price": result.get("objective_carbon_price", ""),
                "actual_evals": row.get("actual_evals", ""),
                "feasible": "是" if result.get("feasible") else "否",
            }
        )
    return rows


def _e4_variant_sort_key(variant: str) -> tuple[float, float]:
    parts = dict(item.split("=") for item in variant.split(";"))
    return float(parts.get("p", 0.0)), float(parts.get("ce", 0.0))


def _f2_final_rows(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "instance": row["instance"],
            "algorithm": row["algorithm"],
            "seed": row["seed"],
            "final_obj": row.get("result", {}).get("best_cost", ""),
            "elapsed_seconds": row.get("result", {}).get("elapsed_seconds", ""),
            "actual_evals": row.get("actual_evals", row.get("result", {}).get("actual_evals", "")),
            "actual_moves": row.get("result", {}).get("actual_moves", ""),
            "candidate_scores": row.get("result", {}).get("candidate_scores", ""),
            "repair_scores": row.get("result", {}).get("repair_scores", ""),
            "repair_delta_count": row.get("result", {}).get("repair_delta_count", row.get("result", {}).get("repair_scores", "")),
            "feasible": row.get("result", {}).get("feasible", False),
        }
        for row in run_rows
    ]


def _f2_curve_rows(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in run_rows:
        for point in row.get("result", {}).get("history", []):
            rows.append({"instance": row["instance"], "algorithm": row["algorithm"], "seed": row["seed"], "evals": point.get("eval", 0), "best_obj": point.get("best_obj", "")})
    return rows


def _e6_table_rows(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in run_rows:
        grouped.setdefault(row["variant"], []).append(row)
    rows = []
    for variant, items in sorted(grouped.items()):
        theta = variant.split("=", 1)[-1]
        completed = [item for item in items if item.get("status") == "completed" and item.get("result", {}).get("fairness_on_feasible")]
        if not completed:
            rows.append({"theta": theta, "pi_ratio_by_depot": "", "min_ratio": "", "total_cost": "", "total_carbon_kg": "", "cross_site_customers": "", "feasible": "否"})
            continue
        ratios = [_min_ratio(item["result"]["fairness_on"]["profit_ratio"]) for item in completed]
        costs = [float(item["result"]["fairness_on"]["metrics"]["total_cost"]) for item in completed]
        carbons = [float(item["result"]["fairness_on"]["metrics"]["E_total"]) for item in completed]
        rows.append(
            {
                "theta": theta,
                "pi_ratio_by_depot": _ratio_text(completed[0]["result"]["fairness_on"]["profit_ratio"]),
                "min_ratio": round(mean(ratios), 4),
                "total_cost": round(mean(costs), 3),
                "total_carbon_kg": round(mean(carbons), 3),
                "cross_site_customers": "",
                "feasible": "是",
            }
        )
    return rows


def _e6_figure_rows(table_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "cost_ratio_to_independent": "",
        }
        for row in table_rows
    ]


def _t6_case(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "case": name,
        "total_carbon_kg": round(float(payload["cost_metrics"]["E_total"]), 3),
        "charging_carbon_kg": round(float(payload["charging_carbon_kg"]), 3),
        "mean_intensity_gco2_per_kwh": round(float(payload["mean_intensity_gco2_per_kwh"]), 3),
        "total_cost": round(float(payload["cost_metrics"]["total_cost"]), 3),
    }


def _cv_only_t6_case_from_t4(t4_csv_path: str | Path) -> dict[str, Any] | None:
    path = Path(t4_csv_path)
    if not path.exists():
        return None
    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    values = {str(row.get("metric", "")): row.get("value", "") for row in rows}
    if "cv_only total_carbon_kg" not in values or "cv_only total_cost" not in values:
        return None
    return {
        "case": "CV-only",
        "total_carbon_kg": round(float(values["cv_only total_carbon_kg"]), 3),
        "charging_carbon_kg": 0.0,
        "mean_intensity_gco2_per_kwh": 0.0,
        "total_cost": round(float(values["cv_only total_cost"]), 3),
    }


def _f3_from_e5(report: dict[str, Any]) -> list[dict[str, Any]]:
    aware = report["carbon_aware"]["cost_metrics"]
    naive = report["naive_return_charge"]["cost_metrics"]
    return [
        {"stage": "混合即充", "total_carbon_kg": float(naive["E_total"])},
        {"stage": "混合择时", "total_carbon_kg": float(aware["E_total"])},
    ]


def _prices_with_theta(theta: float) -> PriceParameters:
    from dataclasses import replace

    return replace(DEFAULT_PRICES, fairness_theta=float(theta))


def _min_ratio(ratios: dict[str, float]) -> float:
    return min((float(value) for value in ratios.values()), default=0.0)


def _std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    avg = mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _ratio_text(ratios: dict[str, float]) -> str:
    return "; ".join(f"{key}:{float(value):.3f}" for key, value in sorted(ratios.items()))


def _node_count(instance: Any, node_type: str) -> int:
    return sum(1 for node in instance.nodes if node.node_type.lower() == node_type)


def _window_width_summary(instance: Any) -> str:
    widths = [(float(node.due_time) - float(node.ready_time)) / 3600.0 for node in instance.nodes if node.node_type.lower() == "c"]
    return "" if not widths else f"{mean(widths):.2f}"


def _bundle_hash(bundle_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in ("instance.json", "distance_matrix.npy", "carbon_profile.csv"):
        path = bundle_dir / name
        digest.update(name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
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


def _compact_summary(result: dict[str, Any]) -> dict[str, Any]:
    keys = ["gate", "run_count", "manifest", "all_assertions_pass", "event_count"]
    return {key: result[key] for key in keys if key in result}


if __name__ == "__main__":
    raise SystemExit(main())
