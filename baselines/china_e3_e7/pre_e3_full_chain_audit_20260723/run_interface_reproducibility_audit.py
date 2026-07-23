#!/usr/bin/env python3
"""Zero-search audit of the future China E3--E7 execution boundary.

The foundation manifest is planning-only.  This script asks whether its tasks
are sufficiently bound to immutable inputs, whether the frozen E2 algorithm
has reproducible execution semantics, and whether the future E3--E7 statistics
fail closed on broken pairing.  It never invokes an optimiser.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[3]
OUT = SCRIPT.parent

CONTRACT = (
    REPO
    / "data/ChinaInstances/china_e3_e7_foundation_contract_v1_20260723.json"
)
FOUNDATION = REPO / "baselines/china_e3_e7/foundation_20260723"
MANIFEST = FOUNDATION / "task_manifest.json"
ADAPTER = REPO / "baselines/china_e3_e7/adapter.py"
STATISTICS = REPO / "baselines/china_e3_e7/statistics.py"
LEGACY_FORMAL_RUNNER = REPO / "solver/src/setp_solver/search/formal_runner.py"
E3_RUNTIME = REPO / "solver/src/setp_solver/search/e3_multitrip_runtime.py"
MULTITRIP = REPO / "solver/src/setp_solver/search/multitrip_schedule.py"
DYNAMIC = REPO / "solver/src/setp_solver/search/dynamic.py"
HGS_RUNNER = (
    REPO
    / "baselines/e2_final_campaign_20260720/mv_hgs_sp_final"
    / "run_p3_china81_formal.py"
)
SP_RUNNER = (
    REPO
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
    / "route_pool_sp.py"
)
TRAJECTORY_DECISION = (
    REPO
    / "baselines/e2_final_campaign_20260720/p2p3_threeview"
    / "representative_gate/s3_traj_v4/decision_v2.json"
)
APPROVAL_REGISTER = (
    REPO / "docs/handoff/model_change_approval_register_20260718.md"
)
PYVRP_PYTHON = (
    REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
)


@dataclass(frozen=True)
class AuditRow:
    check_id: str
    lane: str
    severity: str
    status: str
    subject: str
    observed: str
    expected: str
    evidence: str
    impact: str


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fields: list[str],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def add(
    rows: list[AuditRow],
    check_id: str,
    lane: str,
    severity: str,
    status: str,
    subject: str,
    observed: Any,
    expected: Any,
    evidence: str,
    impact: str,
) -> None:
    rows.append(
        AuditRow(
            check_id,
            lane,
            severity,
            status,
            subject,
            (
                observed
                if isinstance(observed, str)
                else json.dumps(
                    observed,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            ),
            (
                expected
                if isinstance(expected, str)
                else json.dumps(
                    expected,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            ),
            evidence,
            impact,
        )
    )


def _load_statistics_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "china_e3_e7_statistics_audit",
        STATISTICS,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load statistics module")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(STATISTICS.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _pairing_fault_probe() -> dict[str, Any]:
    """Prove whether disjoint arm seeds are rejected before aggregation."""

    module = _load_statistics_module()
    rows: list[dict[str, str]] = []
    for arm, seeds in (
        ("control", ("1", "2")),
        ("treatment", ("3", "4")),
    ):
        for map_index in range(1, 4):
            instance_id = (
                f"cn-jjj-10c-{map_index:02d}-V2-LOCATIONS"
            )
            for seed in seeds:
                rows.append(
                    {
                        "family": "AUDIT",
                        "arm": arm,
                        "status": "complete",
                        "region": "jjj",
                        "customer_size": "10",
                        # Internal alias added only so this probe can reach
                        # the cross-arm pairing logic.  The separate schema
                        # probe below uses the actual raw schema and exposes
                        # that it lacks this catalog-only field.
                        "customer_count": "10",
                        "instance_id": instance_id,
                        "seed": seed,
                        "pair_id": (
                            f"AUDIT__{instance_id}__seed{seed}"
                        ),
                        "input_manifest_sha256": "audit-input",
                        "contract_sha256": "audit-contract",
                        "total_cost": "100.0",
                    }
                )
    control, control_missing = module._cell_map_means(
        rows,
        metric="total_cost",
        family_id="AUDIT",
        arm_id="control",
    )
    treatment, treatment_missing = module._cell_map_means(
        rows,
        metric="total_cost",
        family_id="AUDIT",
        arm_id="treatment",
    )
    pairing_violations = module._pairing_violations(
        rows,
        family_id="AUDIT",
        control="control",
        treatment="treatment",
    )
    silently_accepted = not pairing_violations
    return {
        "disjoint_control_seeds": [1, 2],
        "disjoint_treatment_seeds": [3, 4],
        "control_missing": control_missing,
        "treatment_missing": treatment_missing,
        "pairing_violations": pairing_violations,
        "silently_accepted_by_arm_aggregator": silently_accepted,
    }


def _statistics_schema_probe() -> dict[str, Any]:
    """Exercise the aggregator with the documented RAW_FIELDS vocabulary."""

    module = _load_statistics_module()
    row = {
        "family": "AUDIT",
        "arm": "control",
        "status": "complete",
        "region": "jjj",
        "customer_size": "10",
        "instance_id": "cn-jjj-10c-01-V2-LOCATIONS",
        "seed": "1",
        "pair_id": "AUDIT__cn-jjj-10c-01-V2-LOCATIONS__seed1",
        "total_cost": "100.0",
    }
    error = None
    try:
        module._cell_map_means(
            [row],
            metric="total_cost",
            family_id="AUDIT",
            arm_id="control",
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "raw_field_customer_size_present": (
            "customer_size" in module.RAW_FIELDS
        ),
        "raw_field_customer_count_present": (
            "customer_count" in module.RAW_FIELDS
        ),
        "aggregation_error": error,
    }


def _infeasible_fault_probe() -> dict[str, Any]:
    """Show whether a numeric cost from an infeasible row is retained."""

    module = _load_statistics_module()
    row = {
        "family": "AUDIT",
        "arm": "control",
        "status": "complete",
        "feasible": "false",
        "region": "jjj",
        "customer_size": "10",
        "instance_id": "cn-jjj-10c-01-V2-LOCATIONS",
        "seed": "1",
        "pair_id": "AUDIT__cn-jjj-10c-01-V2-LOCATIONS__seed1",
        "total_cost": "1.0",
    }
    means, missing = module._cell_map_means(
        [row],
        metric="total_cost",
        family_id="AUDIT",
        arm_id="control",
    )
    return {
        "status": row["status"],
        "feasible": row["feasible"],
        "numeric_total_cost": row["total_cost"],
        "metric_value_retained": bool(means),
        "missing_reasons": missing,
    }


def _environment_probe(python: Path) -> dict[str, Any]:
    code = (
        "import json,platform,sys;"
        "from importlib.metadata import PackageNotFoundError,version;"
        "names=['numpy','scipy','pyvrp'];"
        "d={};"
        "\nfor n in names:\n"
        "  try:d[n]=version(n)\n"
        "  except PackageNotFoundError:d[n]=None\n"
        "print(json.dumps({'python':sys.version,'platform':platform.platform(),"
        "'packages':d},sort_keys=True))"
    )
    result = subprocess.run(
        [str(python), "-c", code],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "python_path": str(python.relative_to(REPO)),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _public_station_inventory(
    contract: dict[str, Any],
) -> dict[str, Any]:
    static_root = REPO / contract["data"]["static_root"] / "instances"
    files = sorted(static_root.glob("*/nodes.csv"))
    with_station = 0
    stations = 0
    for path in files:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        count = sum(
            str(row.get("node_type", "")).strip().lower()
            in {"f", "station"}
            for row in rows
        )
        stations += count
        with_station += int(count > 0)
    return {
        "instance_files": len(files),
        "instances_with_public_station": with_station,
        "public_station_rows": stations,
    }


def main() -> int:
    rows: list[AuditRow] = []
    contract = read_json(CONTRACT)
    manifest = read_json(MANIFEST)
    tasks = manifest["tasks"]
    family_counts = Counter(task["family"] for task in tasks)
    arm_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for task in tasks:
        arm_counts[task["family"]][task["arm"]] += 1

    expected_families = {
        family["id"]: {
            arm["id"]
            for arm in family["arms"]
        }
        for family in contract["families"]
        if family["id"] != "E7"
    }
    shape_ok = (
        len(tasks) == 3240
        and family_counts
        == Counter({"E3": 810, "E4": 810, "E5": 810, "E6": 810})
        and all(
            set(arm_counts[family_id]) == arms
            and set(arm_counts[family_id].values()) == {405}
            for family_id, arms in expected_families.items()
        )
        and manifest["e7_full_matrix_projection"]["task_count"] == 2025
        and manifest["e7_result_blind_gate_projection"]["task_count"] == 75
    )
    add(
        rows,
        "A8-01-MANIFEST",
        "A8",
        "P0",
        "PASS" if shape_ok else "FAIL",
        "planning task counts and arm definitions",
        {
            "materialized": len(tasks),
            "families": dict(family_counts),
            "arms": {
                key: dict(value)
                for key, value in arm_counts.items()
            },
            "e7_projection": manifest[
                "e7_full_matrix_projection"
            ]["task_count"],
            "e7_gate": manifest[
                "e7_result_blind_gate_projection"
            ]["task_count"],
        },
        "E3-E6 3240 planning rows; E7 2025 projection and 75-row blind gate",
        str(MANIFEST.relative_to(REPO)),
        "A wrong task shape changes the estimand or silently drops arms.",
    )

    binding_keys = {
        "input_manifest_sha256",
        "instance_bundle_sha256",
        "orders_sha256",
        "demand_time_window_sha256",
        "depot_entrances_sha256",
        "event_stream_sha256",
        "initial_solution_sha256",
        "algorithm_sha256",
        "evaluator_sha256",
    }
    missing_bindings = {
        key: sum(key not in task for task in tasks)
        for key in sorted(binding_keys)
    }
    add(
        rows,
        "A8-02-HASH-BINDING",
        "A8",
        "P0",
        (
            "PASS"
            if not any(missing_bindings.values())
            else "FAIL"
        ),
        "paired task fields bind immutable values and hashes",
        {
            "paired_field_names_only": tasks[0]["paired_fields"],
            "missing_key_counts": missing_bindings,
        },
        "every formal task stores immutable identities for all paired inputs",
        str(MANIFEST.relative_to(REPO)),
        (
            "Names of intended paired fields do not prove that two arms "
            "consumed the same bytes."
        ),
    )

    schema_probe = _statistics_schema_probe()
    add(
        rows,
        "A8-03-RAW-SCHEMA",
        "A8",
        "P0",
        "FAIL" if schema_probe["aggregation_error"] else "PASS",
        "formal raw schema is consumable by the cell aggregator",
        schema_probe,
        "customer-size field name is identical from raw schema through aggregation",
        str(STATISTICS.relative_to(REPO)),
        (
            "The current empty foundation hides a KeyError: formal rows use "
            "customer_size while primary_cell_id expects customer_count."
        ),
    )

    pairing_probe = _pairing_fault_probe()
    add(
        rows,
        "A8-02-PAIR-FAULT",
        "A8",
        "P0",
        (
            "FAIL"
            if pairing_probe[
                "silently_accepted_by_arm_aggregator"
            ]
            else "PASS"
        ),
        "disjoint-seed arms are rejected as unpaired",
        pairing_probe,
        "control and treatment must share identical pair_id and seed sets",
        str(STATISTICS.relative_to(REPO)),
        (
            "The current arm-wise aggregation can label two disjoint seed "
            "sets as a paired cell comparison."
        ),
    )

    infeasible_probe = _infeasible_fault_probe()
    infeasible_retained = bool(
        infeasible_probe["metric_value_retained"]
    )
    add(
        rows,
        "A8-05-INFEASIBLE",
        "A8",
        "P0",
        "FAIL" if infeasible_retained else "PASS",
        "infeasible numeric cost is excluded or handled by preregistered rule",
        infeasible_probe,
        "no infeasible cost enters a cost contrast without an explicit rule",
        str(STATISTICS.relative_to(REPO)),
        (
            "For E3/E4/E7, an infeasible row marked complete can currently "
            "enter a total-cost contrast as if it were feasible."
        ),
    )

    pending_budgets = Counter(
        str(task.get("evaluation_budget"))
        for task in tasks
    )
    add(
        rows,
        "A8-06-BUDGET",
        "A8",
        "P1",
        (
            "PASS"
            if set(pending_budgets) != {"PENDING_FORMAL_RELEASE"}
            else "FAIL"
        ),
        "formal evaluation and wall-clock budget contract",
        dict(pending_budgets),
        "numeric paired evaluation budget plus reporting-only wall clock",
        str(MANIFEST.relative_to(REPO)),
        (
            "No equal-compute claim or reproducible stopping rule is possible "
            "while every task budget is pending."
        ),
    )

    adapter_text = ADAPTER.read_text(encoding="utf-8")
    legacy_text = LEGACY_FORMAL_RUNNER.read_text(encoding="utf-8")
    imports_legacy_runner = any(
        token in adapter_text
        for token in (
            "from setp_solver.search.formal_runner import",
            "from .formal_runner import",
            "import setp_solver.search.formal_runner",
        )
    )
    old_runner_excluded = (
        not imports_legacy_runner
        and "MV-HGS-SP" not in legacy_text
        and "FORMAL_MAIN_INSTANCE" in legacy_text
    )
    add(
        rows,
        "A9-LEGACY-01",
        "A9",
        "P0",
        "PASS" if old_runner_excluded else "FAIL",
        "legacy UK/ALNS E0-E7 runner excluded from China mainline",
        {
            "foundation_imports_legacy_runner": (
                imports_legacy_runner
            ),
            "legacy_runner_is_mv_hgs_sp": (
                "MV-HGS-SP" in legacy_text
            ),
            "legacy_runner_uses_single_main_instance": (
                "FORMAL_MAIN_INSTANCE" in legacy_text
            ),
        },
        "China adapter does not call the legacy formal_runner",
        (
            f"{ADAPTER.relative_to(REPO)}; "
            f"{LEGACY_FORMAL_RUNNER.relative_to(REPO)}"
        ),
        "Calling the legacy runner would test a different algorithm and data lane.",
    )

    family_binding_requirements = {
        "E3": {
            "responsibility_map_sha256",
            "status_quo_witness_sha256",
        },
        "E4": {
            "fixed_route_vehicle_energy_witness_sha256",
            "calendar_panel_sha256",
        },
        "E5": {
            "linear_plan_witness_sha256",
            "nonlinear_replay_contract_sha256",
        },
        "E6": {
            "independent_profit_baseline_sha256",
            "participation_contract_sha256",
        },
    }
    for family_id, required in family_binding_requirements.items():
        family_tasks = [
            task for task in tasks if task["family"] == family_id
        ]
        missing = {
            key: sum(key not in task for task in family_tasks)
            for key in sorted(required)
        }
        add(
            rows,
            f"A9-{family_id}-BINDING",
            "A9",
            "P0",
            "PASS" if not any(missing.values()) else "FAIL",
            f"{family_id} mechanism-specific witness binding",
            missing,
            "all family-specific control/treatment artifacts are hash-bound",
            str(MANIFEST.relative_to(REPO)),
            (
                "Arm labels alone do not establish that the intended mechanism "
                "was executed or isolated."
            ),
        )

    e7_has_materialized_tasks = any(
        task.get("family") == "E7" for task in tasks
    )
    add(
        rows,
        "A9-04-E7-EVENTS",
        "A9",
        "P0",
        "PASS" if e7_has_materialized_tasks else "FAIL",
        "E7 event streams and arm tasks are materialized and hash-bound",
        {
            "materialized_e7_tasks": sum(
                task.get("family") == "E7" for task in tasks
            ),
            "projection_only": manifest[
                "e7_full_matrix_projection"
            ]["status"],
        },
        "result-blind E7 tasks include immutable event_stream_sha256",
        str(MANIFEST.relative_to(REPO)),
        (
            "A seed recipe is not a frozen event stream; dynamic arms cannot "
            "yet be paired or replayed."
        ),
    )

    runtime_text = E3_RUNTIME.read_text(encoding="utf-8")
    strict_default_off = (
        'os.environ.get("SETP_E3_STRICT_MULTITRIP", "0")'
        in runtime_text
    )
    task_flag_count = sum(
        "strict_multitrip" in task for task in tasks
    )
    add(
        rows,
        "A9-05-STRICT-CERT",
        "A9",
        "P0",
        (
            "PASS"
            if not strict_default_off and task_flag_count == len(tasks)
            else "FAIL"
        ),
        "strict multitrip certificate is mandatory on every formal task",
        {
            "runtime_default_off": strict_default_off,
            "tasks_binding_strict_mode": task_flag_count,
            "tasks": len(tasks),
        },
        "strict certificate cannot be disabled by ambient environment",
        (
            f"{E3_RUNTIME.relative_to(REPO)}; "
            f"{MANIFEST.relative_to(REPO)}"
        ),
        (
            "The generic checker does not reject all physical-vehicle, SOC "
            "and charging-session faults found by A6."
        ),
    )

    public_inventory = _public_station_inventory(contract)
    public_unsupported = (
        "public-station trips are unsupported"
        in MULTITRIP.read_text(encoding="utf-8")
    )
    add(
        rows,
        "A9-05-PUBLIC-STATION",
        "A9",
        "P0",
        (
            "FAIL"
            if public_unsupported
            and public_inventory["instances_with_public_station"] > 0
            else "PASS"
        ),
        "strict multitrip path supports public-station routes",
        {
            **public_inventory,
            "strict_runtime_rejects_public_station_routes": (
                public_unsupported
            ),
        },
        "public-station routes either execute correctly or are explicitly excluded by approved design",
        str(MULTITRIP.relative_to(REPO)),
        (
            "The China instances expose public stations, but the stronger "
            "certificate path rejects every route that visits one."
        ),
    )

    hgs_text = HGS_RUNNER.read_text(encoding="utf-8")
    sp_text = SP_RUNNER.read_text(encoding="utf-8")
    parent_protection = (
        "recombined_completion.objective"
        in sp_text
        and "parent_completion.objective"
        in sp_text
        and "completion = parent_completion"
        in sp_text
    )
    add(
        rows,
        "A7-04-PARENT",
        "A7",
        "P0",
        "PASS" if parent_protection else "FAIL",
        "complete-model parent protection after SP recombination",
        {"parent_protection_branch_present": parent_protection},
        "recombined solution replaces the parent only after exact full-model improvement",
        str(SP_RUNNER.relative_to(REPO)),
        "Without this guard, proxy/SP ranking could worsen the delivered result.",
    )

    sp_checks = all(
        token in sp_text
        for token in (
            "LinearConstraint",
            "num_cv",
            "num_ev",
            "exact_china81_score",
            "independent_violation_count",
        )
    )
    add(
        rows,
        "A7-05-SP-CHECKS",
        "A7",
        "P0",
        "PASS" if sp_checks else "FAIL",
        "SP customer coverage, fleet caps and full-model recheck",
        {"required_checks_present": sp_checks},
        "coverage equality, fleet limits and zero-violation full recheck",
        str(SP_RUNNER.relative_to(REPO)),
        "A malformed recombination must not bypass the complete-model judge.",
    )

    accepts_timed_incumbent = (
        'options={"time_limit": float(time_limit_seconds)}'
        in sp_text
        and "if result.x is None" in sp_text
        and "if not result.success" not in sp_text
        and "mip_gap" in sp_text
    )
    add(
        rows,
        "A7-05-SP-OPTIMALITY",
        "A7",
        "P1",
        "FAIL" if accepts_timed_incumbent else "PASS",
        "claim of exact SP recombination is backed by optimality certificate",
        {
            "time_limited": "time_limit" in sp_text,
            "accepts_x_without_success": accepts_timed_incumbent,
            "mip_gap_recorded_but_not_gated": (
                "mip_gap" in sp_text
            ),
        },
        "accept only proven optimum, or rename/disclose as time-limited MIP recombination",
        str(SP_RUNNER.relative_to(REPO)),
        (
            "A feasible HiGHS incumbent after timeout is not an exact optimum; "
            "the current label can overstate the mechanism and impair replay."
        ),
    )

    explicit_seed = (
        "seed=seed" in hgs_text
        and "epoch_seed = int(seed) + 1009" in hgs_text
    )
    add(
        rows,
        "A7-06-SEED",
        "A7",
        "P1",
        "PASS" if explicit_seed else "FAIL",
        "frozen E2 HGS random streams use explicit seeds",
        {
            "mother_seed_explicit": "seed=seed" in hgs_text,
            "epoch_seed_namespace": (
                "epoch_seed = int(seed) + 1009" in hgs_text
            ),
        },
        "all HGS calls use recorded deterministic seed recipes",
        str(HGS_RUNNER.relative_to(REPO)),
        "Implicit random state would make arm differences irreproducible.",
    )

    wall_clock_stop = (
        "MaxRuntime" in hgs_text
        and "NoImprovement" in hgs_text
    )
    add(
        rows,
        "A7-07-STOP",
        "A7",
        "P1",
        "FAIL" if wall_clock_stop else "PASS",
        "reproducible convergence and stopping contract",
        {
            "uses_no_improvement": "NoImprovement" in hgs_text,
            "uses_wall_clock_max_runtime": "MaxRuntime" in hgs_text,
            "future_budget": dict(pending_budgets),
        },
        "formal E3-E7 primary stop is deterministic/evaluation-count based; wall clock is a safety cap",
        str(HGS_RUNNER.relative_to(REPO)),
        (
            "With a wall-clock criterion in the primary stop, the same seed "
            "can traverse a different number of iterations across machines."
        ),
    )

    trajectory = (
        read_json(TRAJECTORY_DECISION)
        if TRAJECTORY_DECISION.is_file()
        else {}
    )
    trajectory_ok = (
        trajectory.get("decision")
        == "PASS_S3_TRAJ_CURVE_UNDER_REGISTERED_DEFINITION"
        and trajectory.get("approval_register_id")
        == "S3-TRAJ-CURVE-DEF-001"
        and "S3-TRAJ-CURVE-DEF-001"
        in APPROVAL_REGISTER.read_text(encoding="utf-8")
    )
    add(
        rows,
        "A7-08-TRAJECTORY",
        "A7",
        "P1",
        "PASS" if trajectory_ok else "FAIL",
        "trajectory observations remain isolated from sealed table scores",
        {
            "decision": trajectory.get("decision"),
            "approval_register_id": trajectory.get(
                "approval_register_id"
            ),
        },
        "registered curve-only semantics and unchanged sealed scores",
        str(TRAJECTORY_DECISION.relative_to(REPO)),
        "A trajectory-only historical observation must never replace a formal score.",
    )

    adapter_probe = subprocess.run(
        [str(PYVRP_PYTHON), str(ADAPTER), "run"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    fail_closed = (
        adapter_probe.returncode != 0
        and "FORMAL_SEARCH_HELD"
        in (adapter_probe.stdout + adapter_probe.stderr)
    )
    add(
        rows,
        "A10-03-FAILCLOSE",
        "A10",
        "P0",
        "PASS" if fail_closed else "FAIL",
        "current adapter run command fails closed",
        {
            "returncode": adapter_probe.returncode,
            "message": (
                adapter_probe.stdout + adapter_probe.stderr
            ).strip(),
        },
        "nonzero exit containing FORMAL_SEARCH_HELD",
        str(ADAPTER.relative_to(REPO)),
        "The audit itself must not accidentally release formal search.",
    )

    formal_runner_exists = any(
        path.name not in {"adapter.py", "formal_runner.py"}
        and "formal" in path.name
        for path in (REPO / "baselines/china_e3_e7").glob("*.py")
    )
    add(
        rows,
        "A10-03-FORMAL-RUNNER",
        "A10",
        "P0",
        "PASS" if formal_runner_exists else "FAIL",
        "China E3-E7 formal runner exists with resumable atomic unit evidence",
        {
            "formal_runner_exists": formal_runner_exists,
            "adapter_run_is_intentionally_disabled": fail_closed,
        },
        "versioned China formal runner plus per-task atomic witness and resume ledger",
        str(ADAPTER.relative_to(REPO)),
        (
            "Planning rows cannot be executed, resumed, independently checked "
            "or attributed to the frozen MV-HGS-SP implementation."
        ),
    )

    certificate_binding_count = sum(
        "certificate_sha256" in task for task in tasks
    )
    add(
        rows,
        "A10-02-CERTIFICATE",
        "A10",
        "P0",
        (
            "PASS"
            if certificate_binding_count == len(tasks)
            else "FAIL"
        ),
        "formal task schema requires an independent recomputation certificate",
        {
            "tasks_with_certificate_sha256": (
                certificate_binding_count
            ),
            "tasks": len(tasks),
        },
        "every completed formal task binds solution, certificate and independent recomputation hashes",
        str(MANIFEST.relative_to(REPO)),
        "The aggregate-level certificate cannot substitute for per-run witness integrity.",
    )

    env_probe = {
        "current": _environment_probe(Path(sys.executable)),
        "pyvrp": _environment_probe(PYVRP_PYTHON),
        "thread_environment": {
            name: os.environ.get(name)
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
    }
    metadata = read_json(FOUNDATION / "metadata.json")
    environment_bound = all(
        key in metadata
        for key in (
            "python_version",
            "pyvrp_version",
            "scipy_version",
            "numpy_version",
            "thread_environment",
        )
    )
    add(
        rows,
        "A10-05-ENVIRONMENT",
        "A10",
        "P1",
        "PASS" if environment_bound else "FAIL",
        "runtime dependencies and thread settings are bound in formal metadata",
        {
            "environment_probe_file": (
                "execution_environment_probe.json"
            ),
            "foundation_metadata_keys": sorted(metadata),
            "required_environment_keys_present": environment_bound,
        },
        "Python, PyVRP, SciPy/HiGHS, NumPy and thread controls recorded",
        str((FOUNDATION / "metadata.json").relative_to(REPO)),
        "Unbound solver/library/thread versions can change iteration counts and MIP incumbents.",
    )

    write_json(OUT / "execution_environment_probe.json", env_probe)
    write_csv(
        OUT / "interface_reproducibility_audit.csv",
        (asdict(row) for row in rows),
        list(asdict(rows[0])),
    )
    open_high = [
        row
        for row in rows
        if row.status == "FAIL" and row.severity in {"P0", "P1"}
    ]
    summary = {
        "schema": "resetp.pre-e3-interface-reproducibility-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "search_evaluations": 0,
        "formal_search_allowed": False,
        "checks": len(rows),
        "status_counts": dict(Counter(row.status for row in rows)),
        "open_p0_p1": len(open_high),
        "open_findings": [asdict(row) for row in open_high],
        "verdict": (
            "HOLD_E3_INTERFACE_REPRODUCIBILITY_FINDINGS_OPEN"
            if open_high
            else "PASS_E3_INTERFACE_REPRODUCIBILITY_AUDIT"
        ),
    }
    write_json(OUT / "interface_reproducibility_findings.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if open_high else 0


if __name__ == "__main__":
    raise SystemExit(main())
