#!/usr/bin/env python3
"""D6 corrected S3 representative-instance rerun and aggregation.

The representative instance is registered from corrected, result-blind input
features before any S3 result is read. Seeds 1--5 are reused from the corrected
81-instance D6 batch. Seeds 6--10 execute the identical frozen D6 task routine
in an isolated output directory. No historical E2/S3 artifact is overwritten.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import multiprocessing as mp
import os
import platform
import re
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
CAMPAIGN_NAME = os.environ.get(
    "RESET_D6_CAMPAIGN_NAME",
    "corrected_china81_rerun_v3_20260724",
)
if (
    not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", CAMPAIGN_NAME)
    or not CAMPAIGN_NAME.startswith("corrected_china81_rerun_")
):
    raise RuntimeError(
        f"invalid RESET_D6_CAMPAIGN_NAME: {CAMPAIGN_NAME!r}"
    )
CASE_ROLE = os.environ.get("RESET_S3_CASE_ROLE", "representative")
if CASE_ROLE not in {"representative", "mechanism_illustration"}:
    raise RuntimeError(f"invalid RESET_S3_CASE_ROLE: {CASE_ROLE!r}")
MECHANISM_INSTANCE_ID = os.environ.get(
    "RESET_S3_MECHANISM_INSTANCE_ID",
    "cn-cy-100c-01-V2-LOCATIONS",
)
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / CAMPAIGN_NAME
)
OUT = CAMPAIGN / (
    "mechanism_case_gate"
    if CASE_ROLE == "mechanism_illustration"
    else "representative_gate"
)
FULL = CAMPAIGN / "full_gate"
RESULT_STRENGTH = CAMPAIGN / "result_strength_gate"
RESULT_STRENGTH_PREREGISTRATION = (
    CAMPAIGN / "e2_result_release_preregistration_v1_20260724.json"
)
CATALOG = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723/"
    "instance_catalog.csv"
)
RUNNER_DIR = REPO / "baselines/e2_final_campaign_20260720"
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
MECHANISM_PREREGISTRATION = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "algorithm_repair_diagnostic_20260724/"
    "chen_style_mechanism_case_preregistration.json"
)
for path in (REPO / "solver/src", RUNNER_DIR, PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.cost import ev_instance_arc_energy_kwh  # noqa: E402


FEATURES = (
    "customer_count",
    "depot_count",
    "demand_dispersion",
    "time_window_tightness",
    "ev_reachability",
)
ARMS = ("HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP")
SEEDS = tuple(range(1, 11))
EXTRA_SEEDS = tuple(range(6, 11))
EPS = 1.0e-9
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def instance_ids() -> list[str]:
    with CATALOG.open(newline="", encoding="utf-8-sig") as handle:
        return sorted(row["instance_id"] for row in csv.DictReader(handle))


def instance_features(instance_id: str) -> dict[str, float]:
    bundle = load_china81_bundle(REPO, instance_id)
    customers = [
        node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    ]
    depots = [
        node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    ]
    demands = [float(node.demand) for node in customers]
    mean_demand = statistics.fmean(demands)
    horizon_seconds = 16.0 * 3600.0
    ev = bundle.instance.vehicle_profile("ev")
    if ev is None or ev.battery_kwh is None:
        raise RuntimeError(f"{instance_id}: missing EV battery authority")
    half_load = 0.5 * float(ev.payload_capacity_kg)
    reachability: list[float] = []
    for customer in customers:
        depot_id = bundle.customer_home_depot[customer.node_id]
        energy = ev_instance_arc_energy_kwh(
            bundle.instance,
            depot_id,
            customer.node_id,
            half_load,
            bundle.prices,
        )
        reachability.append(
            min(
                1.0,
                float(ev.battery_kwh)
                / max(float(energy), 1.0e-12),
            )
        )
    return {
        "customer_count": float(len(customers)),
        "depot_count": float(len(depots)),
        "demand_dispersion": (
            float(statistics.pstdev(demands) / mean_demand)
        ),
        "time_window_tightness": float(
            statistics.fmean(
                float(node.due_time - node.ready_time)
                for node in customers
            )
            / horizon_seconds
        ),
        "ev_reachability": float(statistics.fmean(reachability)),
    }


def register_representative() -> dict[str, Any]:
    if CASE_ROLE == "mechanism_illustration":
        path = OUT / "mechanism_case_registration.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        source = (
            REPO
            / "baselines/e2_final_campaign_20260720/"
            "algorithm_repair_diagnostic_20260724/"
            "chen_style_mechanism_case_preregistration.json"
        )
        source_payload = json.loads(source.read_text(encoding="utf-8"))
        if (
            source_payload.get("instance_id")
            != MECHANISM_INSTANCE_ID
        ):
            raise RuntimeError(
                "mechanism case differs from the disclosed preregistration"
            )
        if MECHANISM_INSTANCE_ID not in instance_ids():
            raise RuntimeError("mechanism case is absent from the catalog")
        payload = {
            "schema": "resetp.d6-corrected-s3-mechanism-case-registration.v1",
            "registered_at_utc": datetime.now(UTC).isoformat(),
            "case_role": CASE_ROLE,
            "selected_instance_id": MECHANISM_INSTANCE_ID,
            "result_blind": False,
            "selection_disclosure": source_payload[
                "selection_disclosure"
            ],
            "full_81_instance_matrix_remains_generality_evidence": True,
            "may_be_called_representative": False,
            "source_preregistration": str(source.relative_to(REPO)),
            "source_preregistration_sha256": file_sha256(source),
            "catalog_sha256": file_sha256(CATALOG),
        }
        write_json(path, payload)
        write_json(
            OUT / "registration_decision.json",
            {
                "schema": (
                    "resetp.d6-corrected-s3-mechanism-case-"
                    "registration-decision.v1"
                ),
                "verdict": (
                    "PASS_DISCLOSED_MECHANISM_ILLUSTRATION_REGISTRATION"
                ),
                "selected_instance_id": MECHANISM_INSTANCE_ID,
                "result_blind": False,
                "representative_claim_allowed": False,
            },
        )
        return payload
    path = OUT / "representative_registration.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    ids = instance_ids()
    raw = {instance_id: instance_features(instance_id) for instance_id in ids}
    means = {
        feature: statistics.fmean(
            raw[instance_id][feature] for instance_id in ids
        )
        for feature in FEATURES
    }
    scales = {
        feature: statistics.pstdev(
            raw[instance_id][feature] for instance_id in ids
        )
        for feature in FEATURES
    }
    z_scores = {
        instance_id: {
            feature: (
                (raw[instance_id][feature] - means[feature])
                / scales[feature]
                if scales[feature] > 0.0
                else 0.0
            )
            for feature in FEATURES
        }
        for instance_id in ids
    }
    median_vector = {
        feature: statistics.median(
            z_scores[instance_id][feature] for instance_id in ids
        )
        for feature in FEATURES
    }
    distances = {
        instance_id: math.sqrt(
            sum(
                (
                    z_scores[instance_id][feature]
                    - median_vector[feature]
                )
                ** 2
                for feature in FEATURES
            )
        )
        for instance_id in ids
    }
    selected = min(
        ids,
        key=lambda instance_id: (
            distances[instance_id],
            instance_id,
        ),
    )
    payload = {
        "schema": "resetp.d6-corrected-s3-registration.v1",
        "registered_at_utc": datetime.now(UTC).isoformat(),
        "result_blind": True,
        "corrected_input_authorities": True,
        "selection_rule": (
            "five input-only features; population z-score by feature; "
            "minimum Euclidean distance to feature-wise median; "
            "lexicographic instance_id tie-break"
        ),
        "feature_definitions": {
            "customer_count": "number of customer nodes",
            "depot_count": "number of depot nodes",
            "demand_dispersion": (
                "population standard deviation of demand divided by mean"
            ),
            "time_window_tightness": (
                "mean customer time-window width divided by the "
                "06:00--22:00 horizon"
            ),
            "ev_reachability": (
                "mean min(1, full battery energy / corrected directed "
                "home-depot-to-customer EV energy at half payload)"
            ),
        },
        "features": raw,
        "feature_means": means,
        "feature_population_scales": scales,
        "z_scores": z_scores,
        "z_score_medians": median_vector,
        "distance_to_median": distances,
        "selected_instance_id": selected,
        "tie_candidates": [
            instance_id
            for instance_id in ids
            if abs(distances[instance_id] - distances[selected])
            <= 1.0e-12
        ],
        "catalog_sha256": file_sha256(CATALOG),
    }
    write_json(path, payload)
    write_json(
        OUT / "registration_decision.json",
        {
            "schema": "resetp.d6-corrected-s3-registration-decision.v1",
            "verdict": "PASS_RESULT_BLIND_REPRESENTATIVE_REGISTRATION",
            "selected_instance_id": selected,
            "result_rows_read": 0,
        },
    )
    return payload


def _task_dir(base: Path, instance_id: str, seed: int) -> Path:
    return (
        base
        / "tasks"
        / f"D6-E2__{instance_id}__seed{int(seed)}"
    )


def _read_task_row(base: Path, instance_id: str, seed: int) -> dict[str, str]:
    path = _task_dir(base, instance_id, seed) / "raw_runs.csv"
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1 or rows[0]["status"] != "PASS":
        raise RuntimeError(f"representative source task is not PASS: {path}")
    return rows[0]


def _run_one_extra(args: tuple[str, int]) -> dict[str, Any]:
    instance_id, seed = args
    d6 = importlib.import_module("run_corrected_china81_d6")
    d6.OUT = OUT / "extra_gate"
    return d6._run_unit((instance_id, int(seed)))


def run_extra_seeds(instance_id: str, workers: int) -> None:
    full_decision = json.loads(
        (FULL / "decision.json").read_text(encoding="utf-8")
    )
    if (
        full_decision.get("verdict")
        != "PASS_D6_CORRECTED_CHINA81_E2_RAW"
    ):
        raise RuntimeError("corrected 81-instance D6 batch is not PASS")
    result_strength = json.loads(
        (RESULT_STRENGTH / "decision.json").read_text(
            encoding="utf-8"
        )
    )
    if (
        result_strength.get("verdict")
        != "PASS_E2_CORRECTED_PAPER_STRENGTH"
        or result_strength.get("paper_strength_pass") is not True
    ):
        raise RuntimeError(
            "corrected E2 did not pass the preregistered paper-strength gate"
        )
    if any(
        os.environ.get(key) != value
        for key, value in REQUIRED_THREAD_ENV.items()
    ):
        raise RuntimeError("single-thread environment is not fully locked")
    tasks = [(instance_id, seed) for seed in EXTRA_SEEDS]
    with mp.get_context("spawn").Pool(processes=workers) as pool:
        for row in pool.imap_unordered(_run_one_extra, tasks):
            print(
                f"[D6-S3] {row['instance_id']} seed={row['seed']} PASS "
                f"full={float(row['MV-HGS-SP_cost']):.6f}",
                flush=True,
            )


def _outcome(full: float, other: float) -> str:
    delta = full - other
    if delta < -EPS:
        return "win"
    if delta > EPS:
        return "loss"
    return "tie"


def mechanism_endpoint_checks(
    pairwise: dict[str, dict[str, int]],
    summary: dict[str, dict[str, float]],
) -> dict[str, bool]:
    """Evaluate the preregistered mechanism-case endpoint gate."""

    return {
        "zero_losses_vs_HGS-F": (
            pairwise["HGS-F"]["losses"] == 0
        ),
        "zero_losses_vs_HGS-E": (
            pairwise["HGS-E"]["losses"] == 0
        ),
        "zero_losses_vs_HGS-M": (
            pairwise["HGS-M"]["losses"] == 0
        ),
        "at_least_8_wins_vs_HGS-F": (
            pairwise["HGS-F"]["wins"] >= 8
        ),
        "at_least_8_wins_vs_HGS-E": (
            pairwise["HGS-E"]["wins"] >= 8
        ),
        "at_least_7_wins_vs_HGS-M": (
            pairwise["HGS-M"]["wins"] >= 7
        ),
        "mean_below_HGS-F": (
            summary["MV-HGS-SP"]["mean_cost"]
            < summary["HGS-F"]["mean_cost"] - EPS
        ),
        "mean_below_HGS-E": (
            summary["MV-HGS-SP"]["mean_cost"]
            < summary["HGS-E"]["mean_cost"] - EPS
        ),
        "mean_below_HGS-M": (
            summary["MV-HGS-SP"]["mean_cost"]
            < summary["HGS-M"]["mean_cost"] - EPS
        ),
    }


def finalize(instance_id: str) -> dict[str, Any]:
    result_strength = json.loads(
        (RESULT_STRENGTH / "decision.json").read_text(
            encoding="utf-8"
        )
    )
    if (
        result_strength.get("verdict")
        != "PASS_E2_CORRECTED_PAPER_STRENGTH"
        or result_strength.get("paper_strength_pass") is not True
    ):
        raise RuntimeError(
            "cannot finalize S3 without the E2 paper-strength PASS"
        )
    rows: list[dict[str, Any]] = []
    task_rows: list[dict[str, str]] = []
    source_hash_sets: set[str] = set()
    input_hashes: set[str] = set()
    responsibility_hashes: set[str] = set()
    for seed in SEEDS:
        base = FULL if seed <= 5 else OUT / "extra_gate"
        row = _read_task_row(base, instance_id, seed)
        task_rows.append(row)
        task_dir = _task_dir(base, instance_id, seed)
        task_decision = json.loads(
            (task_dir / "decision.json").read_text(
                encoding="utf-8"
            )
        )
        if task_decision.get("verdict") != "PASS_D6_E2_TASK":
            raise RuntimeError(
                f"representative task decision is not PASS: {task_dir}"
            )
        metadata = json.loads(
            (task_dir / "metadata.json").read_text(
                encoding="utf-8"
            )
        )
        source_hash_sets.add(
            json.dumps(
                metadata["source_hashes"],
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        manifest = json.loads(
            (task_dir / "artifact_hashes.json").read_text(
                encoding="utf-8"
            )
        )
        for name, expected in manifest["artifacts"].items():
            artifact = task_dir / name
            if (
                not artifact.is_file()
                or file_sha256(artifact) != expected
            ):
                raise RuntimeError(
                    f"representative task artifact drift: "
                    f"{task_dir.name}/{name}"
                )
        input_hashes.add(row["input_manifest_sha256"])
        responsibility_hashes.add(
            row["responsibility_map_sha256"]
        )
        if (
            int(row["complete_candidate_attempts"]) != 80
            or row["wallclock_safety_triggered"].lower()
            == "true"
        ):
            raise RuntimeError(
                f"representative task budget mismatch: {task_dir}"
            )
        witness = task_dir / "solution_witnesses.json"
        if file_sha256(witness) != row["witness_sha256"]:
            raise RuntimeError(f"witness hash mismatch: {witness}")
        for arm in ARMS:
            rows.append(
                {
                    "instance_id": instance_id,
                    "n": int(row["tier"]),
                    "seed": seed,
                    "arm": arm,
                    "status": "PASS",
                    "cost": float(row[f"{arm}_cost"]),
                    "cpu_seconds": float(
                        row[f"{arm}_cpu_seconds"]
                    ),
                    "emissions_kg": float(
                        row[f"{arm}_emissions_kg"]
                    ),
                    "joint_complete_candidate_attempts": int(
                        row["complete_candidate_attempts"]
                    ),
                    "mip_status_class": row["mip_status_class"],
                    "mip_gap": row["mip_gap"],
                    "witness_file": str(witness.relative_to(REPO)),
                    "witness_key": arm,
                    "source_scope": (
                        "corrected_full_gate"
                        if seed <= 5
                        else (
                            "corrected_mechanism_case_extra_gate"
                            if CASE_ROLE == "mechanism_illustration"
                            else "corrected_representative_extra_gate"
                        )
                    ),
                }
            )
    if (
        len(source_hash_sets) != 1
        or len(input_hashes) != 1
        or len(responsibility_hashes) != 1
    ):
        raise RuntimeError(
            "representative tasks do not share one frozen source/input/"
            "responsibility identity"
        )
    write_csv(OUT / "raw_runs.csv", rows)

    summary: dict[str, dict[str, float]] = {}
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        costs = [float(row["cost"]) for row in arm_rows]
        cpus = [float(row["cpu_seconds"]) for row in arm_rows]
        summary[arm] = {
            "best_cost": min(costs),
            "mean_cost": statistics.fmean(costs),
            "max_cost": max(costs),
            "mean_cpu_seconds": statistics.fmean(cpus),
        }
    pairwise: dict[str, dict[str, int]] = {}
    for arm in ARMS[:-1]:
        outcomes = [
            _outcome(
                float(task[f"MV-HGS-SP_cost"]),
                float(task[f"{arm}_cost"]),
            )
            for task in task_rows
        ]
        pairwise[arm] = {
            "wins": outcomes.count("win"),
            "ties": outcomes.count("tie"),
            "losses": outcomes.count("loss"),
        }
    mechanism_checks: dict[str, bool] | None = None
    mechanism_endpoint_pass: bool | None = None
    if CASE_ROLE == "mechanism_illustration":
        preregistration = json.loads(
            MECHANISM_PREREGISTRATION.read_text(encoding="utf-8")
        )
        if (
            preregistration.get("instance_id") != instance_id
            or preregistration.get("seeds") != list(SEEDS)
        ):
            raise RuntimeError(
                "mechanism endpoint gate differs from preregistration"
            )
        mechanism_checks = mechanism_endpoint_checks(
            pairwise,
            summary,
        )
        mechanism_endpoint_pass = all(
            mechanism_checks.values()
        )
    verdict = (
        (
            "PASS_D6_CORRECTED_S3_MECHANISM_CASE"
            if mechanism_endpoint_pass
            else "HALT_D6_CORRECTED_S3_MECHANISM_ENDPOINT_GATE"
        )
        if CASE_ROLE == "mechanism_illustration"
        else "PASS_D6_CORRECTED_S3_REPRESENTATIVE"
    )
    decision = {
        "schema": "resetp.d6-corrected-s3.decision.v1",
        "verdict": verdict,
        "case_role": CASE_ROLE,
        "case_instance_id": instance_id,
        "representative_instance_id": (
            instance_id if CASE_ROLE == "representative" else None
        ),
        "seed_count": len(SEEDS),
        "four_arm_rows": len(rows),
        "shared_search_task_count": len(task_rows),
        "all_full_model_feasible": True,
        "source_hash_set_count": len(source_hash_sets),
        "input_manifest_hash_set_count": len(input_hashes),
        "responsibility_map_hash_set_count": len(
            responsibility_hashes
        ),
        "all_complete_candidate_budgets_80": True,
        "wallclock_safety_trigger_count": 0,
        "summary": summary,
        "mv_hgs_sp_pairwise": pairwise,
        "mechanism_endpoint_gate": {
            "applicable": CASE_ROLE == "mechanism_illustration",
            "passed": mechanism_endpoint_pass,
            "checks": mechanism_checks,
            "preregistration": (
                str(MECHANISM_PREREGISTRATION.relative_to(REPO))
                if CASE_ROLE == "mechanism_illustration"
                else None
            ),
            "preregistration_sha256": (
                file_sha256(MECHANISM_PREREGISTRATION)
                if CASE_ROLE == "mechanism_illustration"
                else None
            ),
        },
        "claim_boundary": (
            (
                "post-audit mechanism illustration, not a statistically "
                "representative case and not a replacement for the full "
                "81-instance matrix; "
                if CASE_ROLE == "mechanism_illustration"
                else "descriptive result-blind representative comparison; "
            )
            + "the three "
            "single-view columns are exact-model-selected outputs from the "
            "same three view generations used by MV-HGS-SP, while the fusion "
            "also pays for all views and time-limited MIP recombination; no "
            "equal-compute claim is made"
        ),
        "next_gate": (
            "observation-only trajectories, S4 and S5"
            if verdict.startswith("PASS")
            else "STOP_BEFORE_TRAJECTORIES_S4_S5"
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.d6-corrected-s3.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "thread_environment": REQUIRED_THREAD_ENV,
            "case_role": CASE_ROLE,
            "registration_sha256": file_sha256(
                OUT
                / (
                    "mechanism_case_registration.json"
                    if CASE_ROLE == "mechanism_illustration"
                    else "representative_registration.json"
                )
            ),
            "full_gate_decision_sha256": file_sha256(
                FULL / "decision.json"
            ),
            "result_strength_decision_sha256": file_sha256(
                RESULT_STRENGTH / "decision.json"
            ),
            "result_strength_preregistration_sha256": file_sha256(
                RESULT_STRENGTH_PREREGISTRATION
            ),
            "d6_runner_sha256": file_sha256(
                RUNNER_DIR / "run_corrected_china81_d6.py"
            ),
            "mechanism_preregistration_sha256": (
                file_sha256(MECHANISM_PREREGISTRATION)
                if CASE_ROLE == "mechanism_illustration"
                else None
            ),
        },
    )
    report_lines = [
        (
            "# D6 corrected S3 mechanism illustration"
            if CASE_ROLE == "mechanism_illustration"
            else "# D6 corrected S3 representative comparison"
        ),
        "",
        f"Decision: `{decision['verdict']}`.",
        (
            f"Disclosed post-audit mechanism illustration: `{instance_id}`; "
            "this case is not statistically representative."
            if CASE_ROLE == "mechanism_illustration"
            else f"Result-blind representative: `{instance_id}`."
        ),
        "Seeds 1--5 are reused from the corrected full China81 batch; "
        "seeds 6--10 were run under the identical D6 task routine.",
        "",
    ]
    for arm in ARMS:
        item = summary[arm]
        report_lines.append(
            f"- {arm}: Best={item['best_cost']:.9f}; "
            f"avg={item['mean_cost']:.9f}; "
            f"CPU avg={item['mean_cpu_seconds']:.3f}s."
        )
    report_lines.append("")
    if CASE_ROLE == "mechanism_illustration":
        report_lines.extend(
            [
                (
                    "Pre-registered endpoint gate: "
                    f"{'PASS' if mechanism_endpoint_pass else 'HALT'}."
                ),
                (
                    "The trajectory and paper-artifact chain is released "
                    "only after every zero-loss, strict-win and lower-mean "
                    "check passes."
                ),
                "",
            ]
        )
    report_lines.append(
        "The comparison is descriptive and does not assert equal compute "
        "between one-view algorithms and the three-view fusion."
    )
    (OUT / "report.md").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): file_sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
            "artifacts": artifacts,
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.d6-corrected-s3-completion.v1",
            "verdict": decision["verdict"],
            "case_role": CASE_ROLE,
            "raw_runs_sha256": file_sha256(
                OUT / "raw_runs.csv"
            ),
            "decision_sha256": file_sha256(
                OUT / "decision.json"
            ),
            "artifact_hashes_sha256": file_sha256(
                OUT / "artifact_hashes.json"
            ),
        },
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--register-only", action="store_true")
    parser.add_argument("--finalize-only", action="store_true")
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    registration = register_representative()
    selected = str(registration["selected_instance_id"])
    print(
        f"[D6-S3] registered {CASE_ROLE}={selected}",
        flush=True,
    )
    if args.register_only:
        return 0
    if not args.finalize_only:
        run_extra_seeds(selected, args.workers)
    decision = finalize(selected)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if str(decision["verdict"]).startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
