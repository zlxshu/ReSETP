#!/usr/bin/env python3
# ruff: noqa: E402
"""Additive E6 profit-guarantee frontier runner.

The sealed E6 participation experiment remains untouched.  This runner reads
its independently operated solutions only as frozen starts and profit
baselines.  For each network, responsibility structure, and seed it first runs
unrestricted cooperation, measures the lower of the two depot profit ratios
(``mu``), and then evaluates the pre-registered guarantee levels

    mu + alpha * (1 - mu), alpha in {0, .25, .5, .75, 1}.

Alpha zero is the unrestricted run itself.  If that run already leaves both
depots no worse off (mu >= 1), the remaining four displayed levels reuse the
same solution and certificate instead of wasting four identical searches.
Otherwise, all four constrained searches start byte-identically from the same
frozen independent solution and differ only in the active profit lower bound.

The formal default is 4,000 complete candidate evaluations per executed
search.  ``--max-specs`` and ``--eval-budget`` provide a bounded wiring probe;
their outputs must use a separate directory and are never formal evidence.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from baselines.e3_ablation.e3_paired_cost_formal_20260713 import (
    load_envelopes,
    load_owners,
)
from baselines.e6_fairness import e6_participation_formal_20260714 as sealed
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_tvci_alns
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations
from setp_solver.solution import Solution


E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
SEALED_E6 = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
DEFAULT_OUT = ROOT / "baselines/e6_fairness/e6_profit_guarantee_frontier_20260715"
CONDITIONS = ("geographic", "mixed")
SEEDS = (1, 2, 3)
ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)
FORMAL_BUDGET = 4_000
NATURAL_TOLERANCE = 1e-9
CONTRACT_SCHEMA = "setp.e6.profit_guarantee_frontier.v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]], fallback_fields: Iterable[str]) -> None:
    fields = sorted({key for row in rows for key in row}) if rows else list(fallback_fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def evidence_path(path: Path) -> str:
    """Prefer a repository-relative path, while keeping external probes usable."""

    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def alpha_label(alpha: float) -> str:
    return f"alpha_{int(round(alpha * 100)):03d}"


def guarantee_levels(mu: float) -> list[dict[str, Any]]:
    """Return the frozen five-level design for one unrestricted result."""

    if not math.isfinite(mu):
        raise ValueError(f"unrestricted minimum profit ratio is not finite: {mu!r}")
    natural = mu >= 1.0 - NATURAL_TOLERANCE
    rows: list[dict[str, Any]] = []
    for alpha in ALPHAS:
        formula_theta = float(mu + alpha * (1.0 - mu))
        rows.append(
            {
                "alpha": alpha,
                "alpha_label": alpha_label(alpha),
                "formula_theta": formula_theta,
                "effective_theta": None if alpha == 0.0 else (1.0 if natural else formula_theta),
                "fairness_enabled": alpha != 0.0 and not natural,
                "natural_satisfaction": natural,
                "execution_rule": (
                    "run_unrestricted"
                    if alpha == 0.0
                    else ("reuse_alpha0" if natural else "run_constrained")
                ),
            }
        )
    return rows


def solution_payload(solution: Solution) -> dict[str, Any]:
    return legacy.solution_to_dict(solution)


def solution_copy(solution: Solution) -> Solution:
    return legacy.solution_from_dict(json.loads(canonical_bytes(solution_payload(solution))))


def _context(
    bundle: Any,
    prices: Any,
    owners: dict[str, str],
    *,
    fairness_enabled: bool,
    independent_profit: dict[str, float] | None,
    theta: float | None,
    allow_cross: bool = True,
) -> EvaluationContext:
    return EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        carbon_weight=0.0,
        carbon_quota_kg=0.0,
        fairness_enabled=fairness_enabled,
        independent_profit=independent_profit if fairness_enabled else None,
        fairness_theta=theta if fairness_enabled else None,
        customer_home_depot=owners,
        allow_cross_depot=allow_cross,
    )


def validate_solution(
    solution: Solution,
    bundle: Any,
    prices: Any,
    owners: dict[str, str],
    *,
    fairness_enabled: bool,
    independent_profit: dict[str, float] | None,
    theta: float | None,
    caps: dict[str, dict[str, int]] | None = None,
    allow_cross: bool = True,
) -> tuple[Solution, Any, list[Any], dict[str, Any], float]:
    context = _context(
        bundle,
        prices,
        owners,
        fairness_enabled=fairness_enabled,
        independent_profit=independent_profit,
        theta=theta,
        allow_cross=allow_cross,
    )
    with legacy.strict_mode(caps):
        prepared, certificate = prepare_solution(solution, context)
        violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    if certificate is None:
        raise ValueError("strict validation emitted no physical-vehicle certificate")
    metrics, closure_error = legacy._metric_row(prepared, bundle, prices)
    return prepared, certificate, violations, metrics, float(closure_error)


def profit_report(
    solution: Solution,
    bundle: Any,
    prices: Any,
    owners: dict[str, str],
    independent_profit: dict[str, float],
) -> tuple[dict[str, Any], dict[str, float], dict[str, float], float]:
    breakdowns = calculate_depot_profits(
        solution,
        bundle.instance,
        bundle.carbon_profile,
        prices,
        customer_home_depot=owners,
        carbon_quota_kg=0.0,
    )
    profits = {depot: float(row.profit) for depot, row in breakdowns.items()}
    if set(profits) != set(independent_profit):
        raise ValueError(
            f"profit depot set drifted: observed={sorted(profits)}, baseline={sorted(independent_profit)}"
        )
    ratios = {
        depot: profits[depot] / float(independent_profit[depot])
        for depot in sorted(independent_profit)
    }
    allocated_cost = sum(float(row.cost_total) for row in breakdowns.values())
    return (
        {depot: row.to_dict() for depot, row in breakdowns.items()},
        profits,
        ratios,
        allocated_cost,
    )


def frozen_input_spec(instance: str, condition: str, seed: int) -> dict[str, Any]:
    spec_id = f"{instance}__{condition}__seed{seed}"
    pair_path = SEALED_E6 / "pairs" / f"{spec_id}.json"
    if not pair_path.exists():
        raise FileNotFoundError(f"sealed E6 pair is missing: {pair_path}")
    pair = read_json(pair_path)
    if pair.get("pair_status") != "PASS":
        raise ValueError(f"sealed E6 pair did not pass: {spec_id}")
    independent_rows = [row for row in pair.get("rows", []) if row.get("arm") == "independent"]
    if len(independent_rows) != 1:
        raise ValueError(f"expected one sealed independent row for {spec_id}")
    independent = independent_rows[0]
    solution_path = ROOT / str(independent["solution_path"])
    certificate_path = ROOT / str(independent["certificate_path"])
    owners, owner_path = load_owners(instance, condition)
    _ = owners
    bundle_dir = E3 / "assets" / instance / "bundle"
    inputs = {
        "sealed_pair": sha256(pair_path),
        "independent_solution": sha256(solution_path),
        "independent_certificate": sha256(certificate_path),
        "ownership": sha256(owner_path),
        "bundle_instance": sha256(bundle_dir / "instance.json"),
        "bundle_distance_matrix": sha256(bundle_dir / "distance_matrix.npy"),
        "bundle_carbon_profile": sha256(bundle_dir / "carbon_profile.csv"),
    }
    if inputs["independent_solution"] != str(independent["solution_sha256"]):
        raise ValueError(f"sealed independent solution hash drifted for {spec_id}")
    if inputs["independent_certificate"] != str(independent["certificate_sha256"]):
        raise ValueError(f"sealed independent certificate hash drifted for {spec_id}")
    independent_profit = {str(key): float(value) for key, value in pair["independent_profit"].items()}
    if any(value <= 1e-9 for value in independent_profit.values()):
        raise ValueError(f"independent profit is not positive for {spec_id}: {independent_profit}")
    return {
        "spec_id": spec_id,
        "instance": instance,
        "condition": condition,
        "seed": int(seed),
        "sealed_pair_path": str(pair_path.relative_to(ROOT)),
        "independent_solution_path": str(solution_path.relative_to(ROOT)),
        "independent_certificate_path": str(certificate_path.relative_to(ROOT)),
        "independent_profit": independent_profit,
        "input_hashes": inputs,
        "input_fingerprint": canonical_hash(inputs),
    }


def build_specs() -> list[dict[str, Any]]:
    return [
        frozen_input_spec(str(item["instance"]), condition, seed)
        for item in load_envelopes()
        for condition in CONDITIONS
        for seed in SEEDS
    ]


def source_hashes() -> dict[str, str]:
    paths = (
        Path(__file__).resolve(),
        ROOT / "baselines/e6_fairness/e6_participation_formal_20260714.py",
        ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
        ROOT / "solver/src/setp_solver/algorithms/resetp_alns/operators/feasible_repair.py",
        ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
        ROOT / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
        ROOT / "solver/src/setp_solver/profit.py",
        ROOT / "solver/src/setp_solver/check.py",
        ROOT / "solver/src/setp_solver/search/evaluation.py",
    )
    return {str(path.relative_to(ROOT)): sha256(path) for path in paths}


def build_contract(
    out_dir: Path,
    *,
    eval_budget: int,
    formal_intent: bool,
) -> tuple[list[dict[str, Any]], str]:
    if eval_budget <= 0:
        raise ValueError("eval_budget must be positive")
    if formal_intent and eval_budget != FORMAL_BUDGET:
        raise ValueError("formal output requires exactly 4000 evaluations per executed search")
    specs = build_specs()
    sources = source_hashes()
    contract_core = {
        "schema": CONTRACT_SCHEMA,
        "question": "How does system cost change as the weaker depot is progressively protected from its unrestricted cooperation outcome to its independent-operation profit?",
        "instances": [spec["instance"] for spec in specs[:: len(CONDITIONS) * len(SEEDS)]],
        "conditions": list(CONDITIONS),
        "seeds": list(SEEDS),
        "alphas": list(ALPHAS),
        "level_rule": "theta(alpha)=mu+alpha*(1-mu), where mu is the lower depot profit ratio in the paired unrestricted run",
        "alpha_zero_rule": "alpha=0 is the unrestricted run itself and does not enable the fairness checker",
        "natural_satisfaction_rule": "if unrestricted mu>=1, alpha>0 rows reuse alpha=0 solution and certificate; no redundant search is run and displayed cost increments are exactly zero",
        "nested_reporting_rule": "the displayed curve is an observed frontier over one fixed pool containing the frozen independent start and every level outcome computed for that spec; each point selects the cheapest pool member satisfying its requirement",
        "reporting_cost_guard": "a selected-frontier point is not described as an isolated 4000-evaluation search; every row records the complete search evaluations exposed through its fixed candidate pool",
        "common_start_rule": "all executed levels start byte-identically from the paired sealed independent-operation solution",
        "common_search_rule": "same source, seed, evaluation budget, reciprocal cross-depot policy, immediate feasible charging, prices, and candidate-generation rules; only the active profit lower bound differs",
        "candidate_pool_guard": "the generation rule is common; realized trajectories may diverge after the fairness filter changes acceptance and are not claimed to be byte-identical candidate streams",
        "eval_budget_per_executed_search": int(eval_budget),
        "maximum_planned_level_rows": len(specs) * len(ALPHAS),
        "maximum_executed_searches": len(specs) * len(ALPHAS),
        "conditional_reuse": True,
        "cross_site_fee": 0.0,
        "carbon_weight": 0.0,
        "carbon_quota_kg": 0.0,
        "charging_strategy": "immediate feasible",
        "statistical_unit": "base network; seeds remain repeated algorithm runs within network-condition",
        "result_direction_does_not_gate_execution": True,
        "sealed_e6_metadata_sha256": sha256(SEALED_E6 / "metadata.json"),
        "sealed_e6_decision_sha256": sha256(SEALED_E6 / "decision.json"),
        "spec_input_fingerprints": {spec["spec_id"]: spec["input_fingerprint"] for spec in specs},
        "source_hashes": sources,
    }
    contract_sha = canonical_hash(contract_core)
    metadata = {
        **contract_core,
        "contract_sha256": contract_sha,
        "formal_intent": formal_intent,
        "source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.strip(),
        "output_dir": str(out_dir),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = out_dir / "metadata.json"
    if metadata_path.exists():
        previous = read_json(metadata_path)
        if previous.get("contract_sha256") != contract_sha:
            raise ValueError(
                "output directory already contains a different contract; use a new --output-dir"
            )
    write_json_atomic(metadata_path, metadata)
    manifest_rows = []
    for spec in specs:
        for alpha in ALPHAS:
            manifest_rows.append(
                {
                    "task_id": f"{spec['spec_id']}__{alpha_label(alpha)}",
                    "spec_id": spec["spec_id"],
                    "instance": spec["instance"],
                    "condition": spec["condition"],
                    "seed": spec["seed"],
                    "alpha": alpha,
                    "dependency": "" if alpha == 0.0 else f"{spec['spec_id']}__alpha_000",
                    "execution": "run_or_conditional_reuse" if alpha > 0.0 else "run_unrestricted",
                    "eval_budget": eval_budget,
                    "input_fingerprint": spec["input_fingerprint"],
                    "contract_sha256": contract_sha,
                }
            )
    if len(manifest_rows) != 270:
        raise ValueError(f"expected 270 level rows, got {len(manifest_rows)}")
    write_csv(out_dir / "task_manifest.csv", manifest_rows, ("task_id",))
    return specs, contract_sha


def load_and_validate_start(spec: dict[str, Any]) -> tuple[Any, Any, Any, Any, Any]:
    instance = str(spec["instance"])
    condition = str(spec["condition"])
    bundle = load_search_bundle(E3 / "assets" / instance / "bundle")
    owners, _ = load_owners(instance, condition)
    prices = legacy.prices_for("M1", 0.0)
    start_path = ROOT / str(spec["independent_solution_path"])
    start = legacy.solution_from_dict(read_json(start_path))
    caps = sealed.depot_caps(instance, condition)
    prepared, certificate, violations, metrics, closure_error = validate_solution(
        start,
        bundle,
        prices,
        owners,
        fairness_enabled=False,
        independent_profit=None,
        theta=None,
        caps=caps,
        allow_cross=False,
    )
    if violations or closure_error > 1e-6:
        raise ValueError(
            f"frozen independent start failed validation: violations={violations}, closure={closure_error}"
        )
    profit_rows, profits, ratios, allocated_cost = profit_report(
        prepared, bundle, prices, owners, spec["independent_profit"]
    )
    baseline_error = max(
        abs(float(profits[depot]) - float(spec["independent_profit"][depot]))
        for depot in profits
    )
    if baseline_error > 1e-6:
        raise ValueError(f"frozen independent profit drifted by {baseline_error}")
    if max(abs(value - 1.0) for value in ratios.values()) > 1e-9:
        raise ValueError(f"frozen independent ratios are not one: {ratios}")
    if abs(float(metrics["total_cost"]) - allocated_cost) > 1e-6:
        raise ValueError("frozen independent system cost does not close to depot allocation")
    independent_reference = {
        "candidate_id": "frozen_independent_start",
        "source_alpha": None,
        "total_cost": float(metrics["total_cost"]),
        "profit_json": json.dumps(profit_rows, ensure_ascii=False, sort_keys=True),
        "depot_profit_json": json.dumps(profits, ensure_ascii=False, sort_keys=True),
        "profit_ratio_json": json.dumps(ratios, ensure_ascii=False, sort_keys=True),
        "minimum_profit_ratio": min(ratios.values()),
        "solution_path": spec["independent_solution_path"],
        "solution_sha256": spec["input_hashes"]["independent_solution"],
        "solution_canonical_sha256": canonical_hash(solution_payload(prepared)),
        "certificate_path": spec["independent_certificate_path"],
        "certificate_sha256": spec["input_hashes"]["independent_certificate"],
        "cost_component_error": closure_error,
        "profit_cost_allocation_error": abs(float(metrics["total_cost"]) - allocated_cost),
        **metrics,
    }
    return bundle, owners, prices, prepared, independent_reference


def save_result_artifacts(
    out_dir: Path,
    task_id: str,
    solution: Solution,
    certificate: Any,
) -> tuple[Path, Path]:
    solution_path = out_dir / "solutions" / f"{task_id}.json"
    certificate_path = out_dir / "certificates" / f"{task_id}.json"
    write_json_atomic(solution_path, solution_payload(solution))
    write_json_atomic(certificate_path, certificate.as_dict())
    return solution_path, certificate_path


def run_level(
    spec: dict[str, Any],
    level: dict[str, Any],
    *,
    out_dir: Path,
    contract_sha: str,
    eval_budget: int,
    bundle: Any,
    owners: dict[str, str],
    prices: Any,
    start: Solution,
    common_start_hash: str,
) -> dict[str, Any]:
    task_id = f"{spec['spec_id']}__{level['alpha_label']}"
    task_path = out_dir / "tasks" / f"{task_id}.json"
    if task_path.exists():
        cached = read_json(task_path)
        if (
            cached.get("contract_sha256") == contract_sha
            and cached.get("status") == "PASS"
            and int(cached.get("evaluations", -1)) == eval_budget
        ):
            return cached
    fairness_enabled = bool(level["fairness_enabled"])
    theta = float(level["effective_theta"]) if fairness_enabled else None
    started = time.perf_counter()
    with legacy.strict_mode():
        result = run_tvci_alns(
            E3 / "assets" / str(spec["instance"]) / "bundle",
            config=WinnerKernelConfig(
                seed=int(spec["seed"]),
                eval_budget=eval_budget,
                max_runtime_seconds=max(600.0, eval_budget * 0.5),
                require_charging_signal=False,
            ),
            initial_solution=solution_copy(start),
            prices=prices,
            charging_strategy="naive",
            policy=SearchPolicy(
                require_charging_signal=False,
                max_cv=int(bundle.instance.num_cv or 0),
                max_ev=int(bundle.instance.num_ev or 0),
                allow_cross_depot=True,
                reciprocal_cross_depot=True,
            ),
            carbon_weight=0.0,
            fairness_enabled=fairness_enabled,
            independent_profit=spec["independent_profit"] if fairness_enabled else None,
            fairness_theta=theta,
            customer_home_depot=owners,
        )
    best = legacy.annotate_cross_site(result["best_solution"], owners)
    prepared, certificate, violations, metrics, closure_error = validate_solution(
        best,
        bundle,
        prices,
        owners,
        fairness_enabled=fairness_enabled,
        independent_profit=spec["independent_profit"] if fairness_enabled else None,
        theta=theta,
        caps=None,
        allow_cross=True,
    )
    profit_rows, profits, ratios, allocated_cost = profit_report(
        prepared, bundle, prices, owners, spec["independent_profit"]
    )
    solution_path, certificate_path = save_result_artifacts(out_dir, task_id, prepared, certificate)
    evaluations = int(result.get("evaluations", -1))
    min_ratio = min(ratios.values())
    fairness_ok = not fairness_enabled or min_ratio >= float(theta) - NATURAL_TOLERANCE
    status = (
        "PASS"
        if evaluations == eval_budget
        and not violations
        and closure_error <= 1e-6
        and abs(float(metrics["total_cost"]) - allocated_cost) <= 1e-6
        and fairness_ok
        else "HALT"
    )
    payload = {
        "task_id": task_id,
        "spec_id": spec["spec_id"],
        "instance": spec["instance"],
        "condition": spec["condition"],
        "seed": spec["seed"],
        "alpha": level["alpha"],
        "alpha_label": level["alpha_label"],
        "formula_theta": level["formula_theta"],
        "effective_theta": theta,
        "fairness_enabled": fairness_enabled,
        "natural_satisfaction": level["natural_satisfaction"],
        "execution_rule": level["execution_rule"],
        "executed_search": True,
        "reused_from_alpha0": False,
        "source_alpha": level["alpha"],
        "planned_budget": eval_budget,
        "budget": eval_budget,
        "evaluations": evaluations,
        "elapsed_seconds": time.perf_counter() - started,
        "status": status,
        "contract_sha256": contract_sha,
        "input_fingerprint": spec["input_fingerprint"],
        "common_start_sha256": common_start_hash,
        "solution_path": evidence_path(solution_path),
        "solution_sha256": sha256(solution_path),
        "solution_canonical_sha256": canonical_hash(solution_payload(prepared)),
        "certificate_path": evidence_path(certificate_path),
        "certificate_sha256": sha256(certificate_path),
        "violation_count": len(violations),
        "violations_json": json.dumps(
            [asdict(item) if hasattr(item, "__dataclass_fields__") else str(item) for item in violations],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "fairness_satisfied": fairness_ok,
        "independent_profit_json": json.dumps(
            spec["independent_profit"], ensure_ascii=False, sort_keys=True
        ),
        "profit_json": json.dumps(profit_rows, ensure_ascii=False, sort_keys=True),
        "depot_profit_json": json.dumps(profits, ensure_ascii=False, sort_keys=True),
        "profit_ratio_json": json.dumps(ratios, ensure_ascii=False, sort_keys=True),
        "minimum_profit_ratio": min_ratio,
        "lower_bound_slack_json": json.dumps(
            {
                depot: ratios[depot] - float(theta)
                for depot in ratios
            }
            if fairness_enabled
            else {},
            ensure_ascii=False,
            sort_keys=True,
        ),
        "minimum_lower_bound_slack": (
            min(ratio - float(theta) for ratio in ratios.values())
            if fairness_enabled
            else math.nan
        ),
        "profit_cost_allocation_error": abs(float(metrics["total_cost"]) - allocated_cost),
        "cost_component_error": closure_error,
        "cross_site_customer_count": len(prepared.cross_site_services),
        "search_score_counts_json": json.dumps(legacy.score_counts(result), sort_keys=True),
        **legacy._certificate_stats(certificate),
        **metrics,
    }
    write_json_atomic(task_path, payload)
    return payload


def reuse_alpha0(
    alpha0: dict[str, Any],
    level: dict[str, Any],
    *,
    out_dir: Path,
    contract_sha: str,
) -> dict[str, Any]:
    task_id = f"{alpha0['spec_id']}__{level['alpha_label']}"
    payload = {
        **alpha0,
        "task_id": task_id,
        "alpha": level["alpha"],
        "alpha_label": level["alpha_label"],
        "formula_theta": level["formula_theta"],
        "effective_theta": 1.0,
        "fairness_enabled": False,
        "natural_satisfaction": True,
        "execution_rule": "reuse_alpha0",
        "executed_search": False,
        "reused_from_alpha0": True,
        "source_alpha": 0.0,
        "planned_budget": int(alpha0["planned_budget"]),
        "budget": 0,
        "evaluations": 0,
        "elapsed_seconds": 0.0,
        "fairness_satisfied": True,
        "lower_bound_slack_json": json.dumps(
            {
                depot: float(ratio) - 1.0
                for depot, ratio in json.loads(alpha0["profit_ratio_json"]).items()
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "minimum_lower_bound_slack": float(alpha0["minimum_profit_ratio"]) - 1.0,
        "contract_sha256": contract_sha,
    }
    # Reuse means exact evidence identity, not a copied solution under a new name.
    for key in (
        "solution_path",
        "solution_sha256",
        "solution_canonical_sha256",
        "certificate_path",
        "certificate_sha256",
        "total_cost",
    ):
        if payload[key] != alpha0[key]:
            raise AssertionError(f"alpha0 reuse drifted field {key}")
    write_json_atomic(out_dir / "tasks" / f"{task_id}.json", payload)
    return payload


def lock_level_contract(
    spec: dict[str, Any],
    alpha0: dict[str, Any],
    levels: list[dict[str, Any]],
    *,
    out_dir: Path,
    contract_sha: str,
) -> dict[str, Any]:
    """Persist mu and all later lower bounds before any constrained search."""

    payload = {
        "spec_id": spec["spec_id"],
        "contract_sha256": contract_sha,
        "input_fingerprint": spec["input_fingerprint"],
        "alpha0_task_id": alpha0["task_id"],
        "alpha0_solution_sha256": alpha0["solution_sha256"],
        "alpha0_minimum_profit_ratio_mu": float(alpha0["minimum_profit_ratio"]),
        "levels": levels,
        "status": "LOCKED_BEFORE_CONSTRAINED_SEARCH",
    }
    path = out_dir / "level_contracts" / f"{spec['spec_id']}.json"
    if path.exists():
        previous = read_json(path)
        if canonical_hash(previous) != canonical_hash(payload):
            raise ValueError(f"pre-run level contract drifted for {spec['spec_id']}")
    else:
        write_json_atomic(path, payload)
    return payload


def run_spec(
    spec: dict[str, Any],
    *,
    out_dir: Path,
    contract_sha: str,
    eval_budget: int,
) -> dict[str, Any]:
    group_path = out_dir / "groups" / f"{spec['spec_id']}.json"
    if group_path.exists():
        cached = read_json(group_path)
        if cached.get("contract_sha256") == contract_sha and cached.get("status") == "PASS":
            return cached
    try:
        bundle, owners, prices, start, independent_reference = load_and_validate_start(spec)
        common_start_hash = canonical_hash(solution_payload(start))
        alpha0_seed_level = {
            "alpha": 0.0,
            "alpha_label": alpha_label(0.0),
            "formula_theta": math.nan,
            "effective_theta": None,
            "fairness_enabled": False,
            "natural_satisfaction": False,
            "execution_rule": "run_unrestricted",
        }
        alpha0 = run_level(
            spec,
            alpha0_seed_level,
            out_dir=out_dir,
            contract_sha=contract_sha,
            eval_budget=eval_budget,
            bundle=bundle,
            owners=owners,
            prices=prices,
            start=start,
            common_start_hash=common_start_hash,
        )
        if alpha0["status"] != "PASS":
            raise ValueError(f"alpha0 unrestricted run failed: {alpha0.get('violations_json', '')}")
        mu = float(alpha0["minimum_profit_ratio"])
        levels = guarantee_levels(mu)
        alpha0.update(
            {
                "formula_theta": levels[0]["formula_theta"],
                "natural_satisfaction": levels[0]["natural_satisfaction"],
            }
        )
        write_json_atomic(out_dir / "tasks" / f"{alpha0['task_id']}.json", alpha0)
        level_contract = lock_level_contract(
            spec,
            alpha0,
            levels,
            out_dir=out_dir,
            contract_sha=contract_sha,
        )
        rows = [alpha0]
        for level in levels[1:]:
            if level["execution_rule"] == "reuse_alpha0":
                rows.append(reuse_alpha0(alpha0, level, out_dir=out_dir, contract_sha=contract_sha))
            else:
                rows.append(
                    run_level(
                        spec,
                        level,
                        out_dir=out_dir,
                        contract_sha=contract_sha,
                        eval_budget=eval_budget,
                        bundle=bundle,
                        owners=owners,
                        prices=prices,
                        start=start,
                        common_start_hash=common_start_hash,
                    )
                )
        status = "PASS" if len(rows) == 5 and all(row["status"] == "PASS" for row in rows) else "HALT"
        payload = {
            "spec_id": spec["spec_id"],
            "instance": spec["instance"],
            "condition": spec["condition"],
            "seed": spec["seed"],
            "status": status,
            "contract_sha256": contract_sha,
            "input_fingerprint": spec["input_fingerprint"],
            "common_start_sha256": common_start_hash,
            "unrestricted_mu": mu,
            "natural_satisfaction": bool(levels[0]["natural_satisfaction"]),
            "level_contract_sha256": canonical_hash(level_contract),
            "independent_reference": independent_reference,
            "rows": rows,
        }
    except Exception as exc:
        payload = {
            "spec_id": spec["spec_id"],
            "instance": spec["instance"],
            "condition": spec["condition"],
            "seed": spec["seed"],
            "status": "HALT",
            "contract_sha256": contract_sha,
            "reason": f"{type(exc).__name__}: {exc}",
            "rows": [],
        }
    write_json_atomic(group_path, payload)
    return payload


def frontier_rows(group: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply one fixed nested-feasible-set selection rule to a complete group."""

    if group.get("status") != "PASS" or len(group.get("rows", [])) != 5:
        return []
    raw_rows = list(group["rows"])
    independent = dict(group["independent_reference"])
    candidates = [independent, *raw_rows]
    candidate_pool_size = len(candidates)
    unique_candidate_solution_count = len(
        {str(row["solution_sha256"]) for row in candidates}
    )
    total_search_evaluations = sum(
        int(row["evaluations"])
        for row in raw_rows
        if bool(row.get("executed_search"))
    )
    natural = bool(group["natural_satisfaction"])
    alpha0_candidates = candidates
    alpha0_selected = min(alpha0_candidates, key=lambda row: float(row["total_cost"]))
    base_cost = float(alpha0_selected["total_cost"])
    rows: list[dict[str, Any]] = []
    previous_cost = -math.inf
    for raw in raw_rows:
        alpha = float(raw["alpha"])
        theta = float(raw["formula_theta"])
        if natural:
            selected = alpha0_selected
            eligible_count = len(candidates)
        elif alpha == 0.0:
            selected = alpha0_selected
            eligible_count = len(candidates)
        else:
            eligible = [
                row
                for row in candidates
                if float(row["minimum_profit_ratio"]) >= theta - NATURAL_TOLERANCE
            ]
            if not eligible:
                raise ValueError(f"no eligible candidate at theta={theta} for {group['spec_id']}")
            selected = min(eligible, key=lambda row: float(row["total_cost"]))
            eligible_count = len(eligible)
        selected_cost = float(selected["total_cost"])
        if selected_cost + 1e-8 < previous_cost:
            raise ValueError(f"nested frontier cost decreased for {group['spec_id']}")
        previous_cost = selected_cost
        selected_ratios = {
            str(key): float(value)
            for key, value in json.loads(selected["profit_ratio_json"]).items()
        }
        displayed_theta = 1.0 if natural and alpha > 0.0 else theta
        premium = 0.0 if natural else 100.0 * (selected_cost - base_cost) / max(1e-12, base_cost)
        rows.append(
            {
                "spec_id": group["spec_id"],
                "instance": group["instance"],
                "condition": group["condition"],
                "seed": group["seed"],
                "alpha": alpha,
                "unrestricted_mu": group["unrestricted_mu"],
                "formula_theta": theta,
                "displayed_theta": displayed_theta,
                "natural_satisfaction": natural,
                "raw_task_id": raw["task_id"],
                "raw_executed_search": raw["executed_search"],
                "raw_reused_from_alpha0": raw["reused_from_alpha0"],
                "selected_candidate_id": selected.get("task_id", selected.get("candidate_id")),
                "selected_source_alpha": selected.get("source_alpha"),
                "selected_source_kind": (
                    "independent_start" if selected.get("candidate_id") else "level_search"
                ),
                "candidate_pool_size": candidate_pool_size,
                "unique_candidate_solution_count": unique_candidate_solution_count,
                "total_search_evaluations_exposed": total_search_evaluations,
                "selected_solution_path": selected["solution_path"],
                "selected_solution_sha256": selected["solution_sha256"],
                "selected_certificate_path": selected["certificate_path"],
                "selected_certificate_sha256": selected["certificate_sha256"],
                "selected_total_cost": selected_cost,
                "cost_increment_pct": premium,
                "selected_minimum_profit_ratio": min(selected_ratios.values()),
                "independent_profit_json": group["independent_reference"]["depot_profit_json"],
                "selected_depot_profit_json": selected["depot_profit_json"],
                "selected_profit_ratio_json": json.dumps(selected_ratios, ensure_ascii=False, sort_keys=True),
                "lower_bound_slack_json": json.dumps(
                    {depot: ratio - displayed_theta for depot, ratio in selected_ratios.items()},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "minimum_lower_bound_slack": min(
                    ratio - displayed_theta for ratio in selected_ratios.values()
                ),
                "eligible_candidate_count": eligible_count,
                "selected_cross_site_customer_count": selected.get("cross_site_customer_count", 0),
                "selected_cost_fix": selected["cost_fix"],
                "selected_cost_km": selected["cost_km"],
                "selected_cost_fuel": selected["cost_fuel"],
                "selected_cost_elec": selected["cost_elec"],
                "selected_cost_occ": selected["cost_occ"],
                "selected_cost_transship": selected["cost_transship"],
                "selected_cost_carbon": selected["cost_carbon"],
            }
        )
    return rows


def raw_frontier_rows(group: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep the unpooled per-level search outcomes as secondary evidence."""

    if group.get("status") != "PASS" or len(group.get("rows", [])) != 5:
        return []
    rows = list(group["rows"])
    alpha0_cost = float(rows[0]["total_cost"])
    return [
        {
            "spec_id": group["spec_id"],
            "instance": group["instance"],
            "condition": group["condition"],
            "seed": group["seed"],
            "alpha": row["alpha"],
            "unrestricted_mu": group["unrestricted_mu"],
            "formula_theta": row["formula_theta"],
            "effective_theta": row["effective_theta"],
            "executed_search": row["executed_search"],
            "reused_from_alpha0": row["reused_from_alpha0"],
            "source_alpha": row["source_alpha"],
            "raw_total_cost": row["total_cost"],
            "raw_cost_increment_pct": 100.0
            * (float(row["total_cost"]) - alpha0_cost)
            / max(1e-12, alpha0_cost),
            "raw_minimum_profit_ratio": row["minimum_profit_ratio"],
            "raw_profit_ratio_json": row["profit_ratio_json"],
            "raw_solution_sha256": row["solution_sha256"],
            "raw_certificate_sha256": row["certificate_sha256"],
            "evaluations": row["evaluations"],
        }
        for row in rows
    ]


def aggregate(specs: list[dict[str, Any]], out_dir: Path, contract_sha: str) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    for spec in specs:
        path = out_dir / "groups" / f"{spec['spec_id']}.json"
        if not path.exists():
            continue
        group = read_json(path)
        if group.get("contract_sha256") == contract_sha:
            groups.append(group)
    raw_rows = [row for group in groups for row in group.get("rows", [])]
    displayed: list[dict[str, Any]] = []
    raw_curve: list[dict[str, Any]] = []
    frontier_errors: list[str] = []
    for group in groups:
        try:
            displayed.extend(frontier_rows(group))
            raw_curve.extend(raw_frontier_rows(group))
        except Exception as exc:
            frontier_errors.append(f"{group['spec_id']}: {type(exc).__name__}: {exc}")
    write_csv(out_dir / "raw_runs.csv", raw_rows, ("task_id",))
    write_csv(out_dir / "raw_frontier.csv", raw_curve, ("spec_id",))
    write_csv(out_dir / "selected_frontier.csv", displayed, ("spec_id",))
    passed_groups = sum(group.get("status") == "PASS" for group in groups)
    executed_searches = sum(bool(row.get("executed_search")) for row in raw_rows)
    reused_rows = sum(bool(row.get("reused_from_alpha0")) for row in raw_rows)
    complete = passed_groups == len(specs) and len(raw_rows) == len(specs) * 5 and not frontier_errors
    status = "PASS_E6_PROFIT_GUARANTEE_FRONTIER" if complete else (
        "PARTIAL_E6_PROFIT_GUARANTEE_FRONTIER" if groups else "PREPARED"
    )
    decision = {
        "schema": CONTRACT_SCHEMA,
        "status": status,
        "contract_sha256": contract_sha,
        "expected_specs": len(specs),
        "completed_specs": len(groups),
        "passed_specs": passed_groups,
        "expected_level_rows": len(specs) * 5,
        "completed_level_rows": len(raw_rows),
        "executed_searches": executed_searches,
        "reused_level_rows": reused_rows,
        "natural_satisfaction_specs": sum(
            bool(group.get("natural_satisfaction")) for group in groups if group.get("status") == "PASS"
        ),
        "frontier_rows": len(displayed),
        "raw_frontier_rows": len(raw_curve),
        "frontier_errors": frontier_errors,
        "formal_complete": complete,
        "result_direction_used_as_gate": False,
    }
    write_json_atomic(out_dir / "decision.json", decision)
    return decision


def report(decision: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# E6收益保障曲线",
            "",
            f"状态：`{decision['status']}`。完成 {decision['passed_specs']}/{decision['expected_specs']} 组，形成 {decision['completed_level_rows']}/{decision['expected_level_rows']} 档记录。",
            "",
            "每组先从同一份封存的各自经营方案出发，计算一次不限制单方收益的合作方案，并以两家车场中较低的收益比作为曲线起点。随后把较弱一方的收益要求按四个等距幅度提高到各自经营水平。所有实际搜索使用同一起点、同一随机种子、同一调整办法和同一完整方案比较次数，只有收益下界不同。",
            "",
            f"实际执行搜索 {decision['executed_searches']} 次；另有 {decision['reused_level_rows']} 档因无约束方案已使双方均不吃亏，直接复用起点档的同一方案和排班证明，未重复消耗算力。",
            "",
            "每档原始搜索、原始曲线和固定候选池筛选后的已观测前沿分别保存在 raw_runs.csv、raw_frontier.csv 和 selected_frontier.csv。主曲线的每个点都记录候选池大小、方案来源及该候选池背后的完整比较次数，不把它写成单档独立花费4000次比较的结果。运行方向不参与继续或停止判断。",
        ]
    ) + "\n"


def artifact_hashes(out_dir: Path) -> dict[str, str]:
    return {
        str(path.relative_to(out_dir)): sha256(path)
        for path in sorted(out_dir.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    }


def select_specs(
    specs: list[dict[str, Any]],
    *,
    instances: set[str],
    conditions: set[str],
    seeds: set[int],
    max_specs: int | None,
) -> list[dict[str, Any]]:
    selected = [
        spec
        for spec in specs
        if (not instances or spec["instance"] in instances)
        and (not conditions or spec["condition"] in conditions)
        and (not seeds or int(spec["seed"]) in seeds)
    ]
    def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        match = re.search(r"-(\d+)c(?:-|$)", str(row["instance"]))
        scale = int(match.group(1)) if match else math.inf
        return (scale, str(row["instance"]), str(row["condition"]), int(row["seed"]))

    selected.sort(key=sort_key)
    if max_specs is not None:
        if max_specs <= 0:
            raise ValueError("max_specs must be positive")
        selected = selected[:max_specs]
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("prepare", "run", "aggregate"), default="prepare")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--eval-budget", type=int, default=FORMAL_BUDGET)
    parser.add_argument("--max-specs", type=int)
    parser.add_argument("--instance", action="append", default=[])
    parser.add_argument("--condition", action="append", choices=CONDITIONS, default=[])
    parser.add_argument("--seed", action="append", type=int, default=[])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--probe",
        action="store_true",
        help="mark this output as a bounded wiring probe; formal output requires 4000 evaluations",
    )
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        raise SystemExit("workers must be between 1 and 8")
    formal_intent = not args.probe
    if args.probe and args.output_dir.resolve() == DEFAULT_OUT.resolve():
        raise SystemExit("a probe must use a separate --output-dir")
    specs, contract_sha = build_contract(
        args.output_dir,
        eval_budget=args.eval_budget,
        formal_intent=formal_intent,
    )
    if args.stage == "run":
        selected = select_specs(
            specs,
            instances=set(args.instance),
            conditions=set(args.condition),
            seeds=set(args.seed),
            max_specs=args.max_specs,
        )
        if not selected:
            raise SystemExit("no specs selected")
        with ProcessPoolExecutor(max_workers=min(args.workers, len(selected))) as pool:
            futures = {
                pool.submit(
                    run_spec,
                    spec,
                    out_dir=args.output_dir,
                    contract_sha=contract_sha,
                    eval_budget=args.eval_budget,
                ): spec
                for spec in selected
            }
            for future in as_completed(futures):
                payload = future.result()
                print(
                    json.dumps(
                        {
                            "spec_id": payload["spec_id"],
                            "status": payload["status"],
                            "reason": payload.get("reason", ""),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    decision = aggregate(specs, args.output_dir, contract_sha)
    (args.output_dir / "report.md").write_text(report(decision), encoding="utf-8")
    write_json_atomic(args.output_dir / "artifact_hashes.json", artifact_hashes(args.output_dir))
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    if args.stage in {"prepare", "aggregate"}:
        return 0
    if args.probe:
        selected_count = len(
            select_specs(
                specs,
                instances=set(args.instance),
                conditions=set(args.condition),
                seeds=set(args.seed),
                max_specs=args.max_specs,
            )
        )
        return 0 if decision["passed_specs"] >= selected_count else 2
    return 0 if decision["formal_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
